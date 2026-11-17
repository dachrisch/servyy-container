# 2026-11-17 — the shared data layer enters the container-health probe

## Problem

`shared` (mongo / valkey / postgres) is the data layer for leagues-finance,
queen and — since 2026-11-17 — dontforget
(`history/2026-11-17_dontforget-shared-mongo.md`). It was in no probe list and
in no alert. The container-health probe is built from `docker.services`
(`ansible/plays/vars/secrets.yml`), which has never held a `shared` entry, and
the deployed script (`~/.system-probes/system-container-health.sh`) had **34
`check_container` calls, none of them a shared container**. All three
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
`{dir}.{domain}` endpoint. `shared` has no Traefik router and no name.

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

The molecule asserts pin the emission path itself (both `printf` format
strings, the running-branch discriminator, the `--format` health field, the
`else}}none` fallback, the tiered `check_container` calls, the backend compose
resolution). Each of the 8 needles was proven to fail a specific silent-failure
mutant — a broken `--format`, for instance, renders green everywhere else and
only shows up in production as `containers_all_down` or an unhealthy alert for
every healthcheck-less container. Molecule asserts on the script's text, never
executes it, and cannot run on this laptop, so CI is the runner.

### Alert rules — `container-health-alerts` (7 rules)

| uid | severity | for | expr |
|---|---|---|---|
| `container_not_running` (existing, narrowed) | medium | 2m | `system_container_running{tier!="backend"}` |
| `backend_container_not_running` (new) | critical | 10m | `system_container_running{tier="backend"}` |
| `container_unhealthy` (new, narrowed) | medium | 10m | `system_container_healthy{tier!="backend"}` |
| `backend_container_unhealthy` (new) | critical | 10m | `system_container_healthy{tier="backend"}` |
| `containers_all_down` | critical | 5m | `avg(system_container_running)` — unchanged |
| `container_health_probe_failure` | medium | 10m | unchanged |
| `container_health_probe_stale` | medium | — | unchanged |

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
  `300`, the file's norm.
- **Backend "up but not answering" is CRITICAL, like "down".** The shared
  healthchecks are protocol-level (`mongosh ping`, `valkey-cli ping`,
  `pg_isready`), so one dead or unanswering container takes leagues-finance,
  queen and dontforget down. A single app container that is up but degraded
  stays MEDIUM.
- **`for: 10m` on both criticals, not 1m.** Consecutive pushes are 0–10 min
  apart and Pushgateway keeps serving the last value until the next PUT, so a
  shorter window lets ONE bad push page. Cost: a real stop pages 11–20 min
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

- The template was rendered and the result exercised against a stub `docker`
  binary (running / stopped / unhealthy / healthcheck-less branches), which is
  the only check that exercises behaviour rather than the needles' strings.
- `ansible-playbook plays/system.yml --syntax-check` and
  `ansible-playbook servyy.yml --syntax-check` pass.
- `yamllint` on `monitor/provisioning/alerting/alert-rules.yml`: **34 → 37**
  line-length warnings, all by design (each rule carries one long description;
  CI does not lint `monitor/`).

PENDING — filled in after the 2026-11-17 deploy:

- PENDING — probe deployed at commit `<sha>` via
  `./servyy.sh --tags "user.docker.repo,system.probe" --limit servy.lehel.xyz`;
  changed tasks and anything unexpected.
- PENDING — `~/.system-probes/system-container-health.sh` run by hand:
  `all_running=1 probe_success=1 pushed=1`.
- PENDING — `curl http://localhost:9091/metrics/job/system_container_health`
  shows the 3 `shared.*` series (`shared.mongo`, `shared.redis`, `shared.db`)
  with `tier="backend"` and `running=1` plus `system_container_healthy 1`, and
  no series left without a `tier` (the PUT replaced the group).
- PENDING — 7 rules loaded in `container-health-alerts` via
  `/api/v1/provisioning/alert-rules` (must not be empty; if it is, Grafana
  rejected the file — check `docker logs monitor.grafana --since 5m`).
- PENDING — `shared.redis` stop/start drill: `running 0` and no healthy series
  while stopped, back to `1` after the restart.
- PENDING — Grafana afterwards: `backend_container_not_running` Normal, no
  leftover `system_container_healthy 0`, `container_not_running` instances
  re-keyed and Normal.

## Rollback

```bash
git revert 6b60005 65399b2
cd ansible && ./servyy.sh --tags "user.docker.repo,system.probe" --limit servy.lehel.xyz
ssh lehel.xyz "docker restart monitor.grafana"
```

`--limit` takes the inventory name (`servy.lehel.xyz`), not the SSH alias
`lehel.xyz` — the alias matches no host and the run silently does nothing.
Revert the follow-up commits too (`2254b61` hardening, `41bc6e6` and `fd3cd88`
alert corrections) if the goal is the exact pre-change files.

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
