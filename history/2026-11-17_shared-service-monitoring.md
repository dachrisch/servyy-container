# 2026-11-17 — the shared data layer enters the container-health probe

## Problem

`shared` (mongo / valkey / postgres) is the data layer for four services:
leagues-finance (mongo + redis), finance/Firefly (postgres), queen (mongo +
redis) and — since 2026-11-17 — dontforget (mongo,
`history/2026-11-17_dontforget-shared-mongo.md`). It was in no probe list and
in no alert. The container-health probe is built from `docker.services`
(`ansible/plays/vars/secrets.yml`), which has never held a `shared` entry, and
the deployed script (`~/.system-probes/system-container-health.sh`) has **32
`check_container` calls, none of them a shared container**. All four
consumers could be erroring against a dead database while every signal on the
host stayed green, and even if `shared` had been listed, `container_not_running`
would have treated it like any single app container — medium severity, no hint
of the blast radius.

The probe also read only `.State.Running`. A container whose own healthcheck
fails stays `running=1`, so `shared.mongo` can stop answering `mongosh ping`
and nothing notices. There was no `system_container_healthy` series at all.

`shared` cannot simply be added to `docker.services`: that list also creates
Pi-hole DNS records (`roles/user/tasks/dns.yml`), `test_host.sh` URLs
(`roles/user/tasks/host_ping.yml`) and servyy-test `/etc/hosts` entries
(`roles/testing/tasks/resolve.yml`), all of which assume a public
`{dir}.{domain}` endpoint. `shared` has no Traefik router, so a
`shared.lehel.xyz` record would resolve and every request to it would get
Traefik's 404.

## Solution

### Probe — `system_container_health.sh.j2`

| File | Change |
|---|---|
| `ansible/plays/roles/system_probe/templates/system_container_health.sh.j2` | one `docker container inspect` per container returning running + health, retried once; two metrics with a `tier` label |
| `ansible/plays/vars/default.yml` | new top-level `docker_backend_services: [{dir: shared}]` |
| `ansible/plays/roles/system_probe/molecule/default/` | `files/backendtest/docker-compose.yml` fixture, converge var, 8 assert needles |
| `monitor/provisioning/alerting/alert-rules.yml` | `container-health-alerts` group: 4 → 7 rules |

Metric schema:

- `system_container_running{name,service,tier}` — always emitted, for every
  container of both lists.
- `system_container_healthy{name,service,tier}` — emitted **only while the
  container runs**: `healthy`, or no healthcheck declared → `1`;
  `unhealthy` / `starting` → `0`. A stopped container therefore drops out of
  the healthy series entirely, so one failure can never page both rules.
- `tier` is `app` for `docker.services` and `backend` for
  `docker_backend_services`. The alert rules select on it, so a future backend
  service (a second db, a queue) is covered without touching PromQL.

`docker_backend_services` is top-level in `plays/vars/default.yml`, not under
`docker:`: `secrets.yml` owns the `docker:` key and `vars_files` do not
deep-merge, so a `docker:` block in `default.yml` would be clobbered.

One inspect per container, not two: the host was explicitly tuned to reduce
`docker exec` churn (`history/2026-10-30_load-alert-tuning.md`). The `--format`
is hoisted into one variable and the inspect is retried once, because pushes
are 5 min apart with up to 5 min of `RandomizedDelaySec` — without the retry a
single dockerd hiccup would read as "down" for up to 10 min.

The molecule asserts pin the emission path itself (the `# TYPE` line, both
`printf` format strings, the running-branch discriminator, the `--format`
health field and the `else}}none` fallback among the eight needles). Each
needle was proven to fail a specific silent-failure mutant — a broken
`--format`, for instance, renders green everywhere else and only shows up in
production as `containers_all_down` or an unhealthy alert for every
healthcheck-less container. Separate asserts cover the `tier` value on both
`check_container` call sites and the backend compose-name resolution; those
were not part of the mutation round. Molecule asserts on the rendered text
only, never executes the script, and cannot run on this laptop, so CI is the
runner.

### Alert rules — `container-health-alerts` (7 rules)

| uid | severity | for | expr |
|---|---|---|---|
| `container_not_running` (existing, narrowed) | medium | 2m | `system_container_running{tier!="backend"}` |
| `backend_container_not_running` (new) | critical | 10m | `system_container_running{tier="backend"}` |
| `container_unhealthy` (new, narrowed) | medium | 10m | `system_container_healthy{tier!="backend"}` |
| `backend_container_unhealthy` (new) | critical | 10m | `system_container_healthy{tier="backend"}` |
| `containers_all_down` | critical | 5m | `avg(system_container_running)` — unchanged |
| `container_health_probe_failure` | medium | 10m | unchanged |
| `container_health_probe_stale` | medium | 1m | unchanged |

Review-driven decisions worth keeping:

- **The narrowing is backward compatible.** PromQL negative matchers also
  select series where the label is absent, so deploying the alert file before
  the probe keeps full coverage — `tier!="backend"` still matches the old
  untiered series. The reverse order leaves the two new rules inert until the
  first tiered push: silence, never a false page.
- **`container_unhealthy` used `relativeTimeRange.from: 900` and that was a
  bug.** A range query keeps returning the last sample for the whole window, so
  a container seen unhealthy and then stopped would still read unhealthy for 15
  minutes — a guaranteed duplicate page next to the not-running rule. Fixed to
  `300`, the value 42 of the 46 rules that set a range use.
- **Backend "up but not answering" is CRITICAL, like "down".** The shared
  healthchecks are protocol-level (`mongosh ping`, `valkey-cli ping`,
  `pg_isready`), so one dead or unanswering container takes leagues-finance,
  finance/Firefly, queen and dontforget down. A single app container that is up
  but degraded stays MEDIUM.
- **`for: 10m` on both criticals, not 1m.** Consecutive pushes are 0–10 min
  apart and Pushgateway keeps serving the last value until the next PUT, so a
  shorter window lets ONE bad push page. Cost: a real stop pages 10–20 min
  later (plus ~2.5 min for the healthcheck to report unhealthy in the health
  case).
- **The down rule is `backend_container_not_running`, not
  `backend_container_down`.** The file already has an unrelated `container_down`
  (cAdvisor *target* check), and a rule's title becomes the `alertname`
  notification label.
- **Adding `tier` re-keys every Grafana alert instance** (instances are keyed by
  labels): existing `container_not_running` instances resolve and re-appear as
  Normal. Expected, not a regression.

## Verification

Local, before the deploy:

- Molecule asserts on the **rendered text** only; it does not execute the
  script. The behavioural matrix (healthy / none / unhealthy / starting /
  stopped / inspect-fail / daemon-unreachable) was run ad hoc during review
  against a stub `docker` binary and is **not committed** — the deploy drill
  further down is the real behavioural check.
- `ansible-playbook plays/system.yml --syntax-check` and
  `ansible-playbook servyy.yml --syntax-check` pass.
- `yamllint` on `monitor/provisioning/alerting/alert-rules.yml`: **34 → 37**
  line-length warnings, all by design (each rule carries one long description;
  CI does not lint `monitor/`).

Deployed 2026-11-17 on servy, merged as `9b01e57` (PR #303).

- `./servyy.sh --tags "user.docker.repo,system.probe" --limit servy.lehel.xyz`
  finished `ok=61 changed=3 failed=0`. The probe script itself reported `ok` on
  that run because a previous attempt had already written it (see the two
  incidents below).
- `~/.system-probes/system-container-health.sh` run by hand:
  `container-health all_running=1 probe_success=1 pushed=1`.
- `curl -s http://localhost:9091/metrics | grep '^system_container_running'`:
  32 `tier="app"` series and 6 `tier="backend"` (3 `running` + 3 `healthy` for
  `shared.mongo`, `shared.redis`, `shared.db`), every one at `1`, **zero**
  series left without a `tier` (the PUT replaced the group). A GET of a job path
  (`/metrics/job/...`) answers 405 — read the aggregate metrics page.
- 7 rules in `container-health-alerts` via `/api/v1/provisioning/alert-rules`
  (46 rules file-wide), correct `for` values and severities; 0 firing/pending
  instances afterwards, i.e. all Normal.
- The `shared.redis` stop/start drill was **deliberately skipped** on user
  decision: the state matrix above is the argument, and valkey is a live
  dependency of leagues-finance/queen.

### Two incidents during the deploy (read before the next one)

1. **A worktree has no gitignored seed files → the deploy key gets replaced.**
   The first attempt died at the repo clone with
   `git@github.com: Permission denied (publickey)`. Cause: the run happened from
   `.worktrees/shared-service-monitoring`, which does not carry
   `ansible/plays/vars/.servyy_container_deploy_key` (gitignored, so never in a
   fresh worktree). `github_deploy_key.yml` therefore *generated* a new key and
   wrote it to servy, invalidating the registered one. Fix: copy the seed from
   the main checkout (`cp .../ansible/plays/vars/.servyy_container_deploy_key`),
   re-run; nothing had to change on GitHub. Copying that file (and any other
   `plays/vars/.*` seed) into a worktree before deploying from it is mandatory.
2. **`--tags user.docker.repo` alone leaves the monitor provisioning files
   unrendered.** `monitor/promtail.yml`,
   `monitor/provisioning/datasources/datasources.yml` and
   `provisioning/alerting/contact-points.yml` are Jinja **in git** and are
   rendered over the checkout by the task tagged `user.docker.monitor` /
   `user.docker.env.monitor`. A sync without that task leaves literal
   `{{ monitor.loki_tenant }}` in place, which YAML reads as a nested mapping:
   Grafana crash-looped on `Datasource provisioning error: yaml: unmarshal
   errors: line 23: cannot unmarshal !!map into string`. Fix:
   `./servyy.sh --tags "user.docker.env.monitor"` (+ `docker restart
   monitor.grafana`). Any deploy that includes `user.docker.repo` must include
   that render task — the two tags are not independent.

## Rollback

```bash
git revert --no-commit fd3cd88 41bc6e6 2254b61 65399b2 6b60005
git commit -m "revert: shared-service monitoring"
cd ansible && ./servyy.sh --tags "user.docker.repo,system.probe" --limit servy.lehel.xyz
ssh lehel.xyz "docker restart monitor.grafana"
```

The reverts must go in reverse-chronological order (latest first): reverting
only `6b60005 65399b2` conflicts in `verify.yml` and the template, because
`2254b61` and the alert corrections touch the same lines. `2254b61` is the
probe hardening, `41bc6e6`/`fd3cd88` the alert corrections.

`--limit` takes the inventory name (`servy.lehel.xyz`), not the SSH alias
`lehel.xyz` — the alias matches no host and the run silently does nothing.

No manual series cleanup: every probe run PUTs the whole
`system_container_health` job group (a POST would merge, a PUT replaces), so
the next push after the revert drops the `tier` label and the
`system_container_healthy` series, and the old
`system_container_running{name,service}` series come back.

## Follow-ups

Deferred on purpose, none of them in code:

- **`container_health_probe_stale` threshold 90 min → ~30 min.** The probe is
  now the only critical path for the data layer, and if the timer dies while a
  `0` sits in Pushgateway, `backend_container_not_running` fires forever and
  can never resolve.
- **Crash-looping backend container evades both rules.** `noDataState: OK`
  resets the `for` clock as the healthy series blinks, and `running`
  alternates 0/1, so neither rule reaches 10 min while every consumer is down.
  A cAdvisor
  `changes(container_start_time_seconds{name=~"shared\\..*"}[30m])` rule would
  close it with no probe cost. A *paused* container (`running=1`, health
  frozen) is invisible for the same reason.
- **`container_not_running` still uses `for: 2m`**, shorter than a full push
  gap; aligning it to `10m` like the new rules is the obvious next step.
- **`containers_all_down` now averages over 35 series instead of 32** (the 3
  `shared.*` series join it), so its "majority down" threshold shifts slightly
  — intended, but worth knowing. It also still lacks
  `missingSeriesEvalsToResolve`, unlike `container_not_running`.
- **No `absent()`-based staleness rule for the probe job itself.**
  `container_health_probe_failure` reads a series that disappears with the job.
- **A dockerd-down run PUTs only `probe_success=0`**, wiping every other series
  for that job (pre-existing behaviour).
