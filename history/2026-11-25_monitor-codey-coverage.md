# ADR: Quiet the alert emails and give codey its own monitoring

**Date:** 2026-11-25
**Status:** Accepted — merged as PR #368 (`2bb8f5ad`), verified on
`servyy-test.lxd`, and rolled out from `master` to `codey.lehel.xyz` and
`servy.lehel.xyz` on 2026-11-25.
**Relates to:** [`2026-11-20_grafana-loki-to-codey.md`](2026-11-20_grafana-loki-to-codey.md),
[`2026-10-30_load-alert-tuning.md`](2026-10-30_load-alert-tuning.md),
[`2026-11-18_db-tier-r2b-alert-truth.md`](2026-11-18_db-tier-r2b-alert-truth.md)

## Context

Inspection of the live monitor stack found two independent problems.

**1. The email volume comes from routing, not from bad thresholds.** The load and
CPU rules were deliberately retuned on 2026-10-30 and still look right. What the
live config showed on 2026-11-25:

| Setting | Was | Meaning |
|---|---|---|
| `group_by` | `alertname, severity` | 65 uniquely named rules = 65 separate mail groups |
| `disableResolveMessage` | `false` (both contact points) | a second mail per firing |
| `repeat_interval` | critical 30m / high 2h / medium 4h | long-lived criticals mail twice an hour |

Seven days of Grafana state history: 36 firings, 33 resolved-from-firing, 39
Error + 39 Error-resolved (≈147 notification events, ~21/day, before repeats).
All 39 Error events named `datasource_uid=prometheus`, arriving in five
synchronized bursts of 43–53 rules (11-20 09:14, 11-21 04:30, 11-24 12:36, 15:03,
20:53): one flaky cross-host Grafana→Prometheus route produced ~50 error mails
plus ~50 resolves. A separate sample showed `container_not_running` (finance.queen)
and `high_load_average_15m` dispatched every minute while active.

**2. Codey was only the alerting plane.** Grafana + Loki ran there, but
Prometheus, node-exporter, cadvisor, promtail and the Pushgateway all ran on
servy. `up{job=...}` proved there was no codey target; codey's containers, host
metrics and logs were invisible to every alert. `system_probe_push_enabled` was
false there because it had no local Pushgateway sink. The 2026-11-20 split had
explicitly deferred this.

## Decision

A. **Notification tuning.** Group by `severity` only; suppress resolve messages
on both contact points; repeats critical 1h / high 4h / medium 12h.

B. **Codey gets its own local collector stack in the `ui` profile.** Distinct
container names (`*-codey`) because servyy-test runs both profiles; codey's
bridge binds `127.0.0.1:9092` (9091 is taken there). A second Grafana datasource
`prometheus-codey` and `alert-rules-codey.yml` (19 rules) carry codey's own host
and container alerts. No third public route, no remote write, no change to
servy's Prometheus.

C. **Container-health probe on codey.** A separate gate
`system_probe_container_push_enabled` (true where `ui` is active) runs ONLY that
probe on codey, pushing to the local bridge; the generic no-sink cleanup exempts
its timer. All other probes keep reading servy-only state.

D. **Log shipping from codey.** `promtail-codey` pushes to the existing
authenticated `loki.lehel.xyz` route; the Loki-password render now runs for both
profiles.

E. **Reload coverage.** `monitor_reload` gains a third, independent half that
fingerprints `prometheus-codey.yml` and restarts only
`monitor.prometheus-codey`; Grafana's existing glob already covered the new rule
file.

## Consequences

### Positive
- A datasource blip now yields at most three grouped mails (one per severity)
  instead of ~50 + 50 resolves; long-lived alerts repeat much less often.
- Codey's own host, containers and logs are covered, and its alerts no longer
  fail when servy or `prometheus.lehel.xyz` is down — which was the point of
  putting Grafana there.
- No new public network surface; the two authenticated cross-host routes stay
  the only ones.

### Negative / Tradeoffs
- Two Prometheus TSDBs, two datasources and two rule files to maintain; shared
  threshold changes must be made in both files.
- No resolve mails means you must look at Grafana to confirm recovery.
- Codey's PSI rules may be `NoData` if that kernel does not expose PSI;
  `noDataState: OK` keeps them quiet by design.
- `servyy-test` now runs two bridges; 9091 and 9092 must stay distinct.

## Implementation Details

**Files modified/created (all on branch `claude/monitor-codey`):**
- `monitor/provisioning/alerting/{notification-policies,contact-points}.yml` — routing.
- `monitor/docker-compose.yml`, `monitor/prometheus-codey.yml` — codey collectors.
- `monitor/provisioning/datasources/datasources.yml`,
  `monitor/provisioning/alerting/alert-rules-codey.yml` — datasource + rules.
- `ansible/plays/user.yml`, `ansible/plays/vars/default.yml` — rendering and permissions.
- `ansible/plays/roles/monitor_reload/` (defaults, main, new `prometheus-codey.yml`,
  Molecule default scenario) — third reload half.
- `ansible/plays/roles/system_probe/` (defaults, tasks, template, `no-sink`
  Molecule scenario) — codey's container probe.
- `architecture/landscape.yaml`, `monitor/AGENTS.md`, root `AGENTS.md`,
  `check-server-status/SKILL.md` — map and docs.
- `.github/workflows/ci.yml` — runs the new config tests.
- Tests: `ansible/tests/{monitor_alerts,monitor_codey,monitor_reload,system_probe}/`.

**Commits:** design/plan `12174567`; notifications `561d3a6f`; compose `2c060905`;
datasource/rules `a4d6094f`; password render `90d8fd6d`; reload `4d7a1ffb`;
probe `f2d5bcbd`; docs/map `4c6f1e52`; skip-missing `c7b8d99d`; ui-only gate
`74754c47`; Molecule assertion `4b9137a2`; PR #368 merge `2bb8f5ad`.

**Testing & verification (done on the branch):**
- All new unit tests written first, watched RED, then GREEN; 18 tests pass.
- `ansible-playbook servyy.yml --syntax-check -i testing` and `-i production` clean.
- `architecture/render.py --verify` → 31 services, 51 edges agree; `--selftest` ok.
- `yamllint` clean on the new rule file; `ansible-lint` shows only pre-existing
  categories (the new reload task file has the same 8 `var-naming` findings as its
  existing sibling).
- Molecule could not run locally (no Docker daemon); both changed scenarios were
  extended and syntax-checked, and CI will run them.

### servyy-test.lxd (verified 2026-11-25)

- `./servyy-test.sh -e docker_branch=claude/monitor-codey` first failed on the
  unrelated Moodle test-host image (`config.php` missing); the monitor half had
  already deployed. A targeted rerun with `--tags user.docker.repo,user.docker.monitor,user.docker.env.monitor,system.probe`
  finished `failed=0`.
- All eight new `monitor.*-codey` containers Up; `up{job=...}` for
  `prometheus-codey`, `node-exporter-codey`, `cadvisor-codey` and
  `pushgateway-codey` all 1.
- Grafana: **84 rules** (65 fleet + 19 codey), all `health=ok`; datasources
  `prometheus`, `prometheus-codey`, `loki`; `group_by: ['severity']`, repeats
  `1h/4h/12h`; both rendered contact points `disableResolveMessage: true`.
- The first test run exposed two real problems, both fixed before the final run:
  1. Render tasks (`datasources.yml`, `contact-points.yml`) read `docker.local_dir`,
     i.e. the **controller's main checkout**, not the branch in the remote dir.
     Running from a worktree therefore rendered the master templates. Fixed by
     temporarily checking the branch out in the controller checkout (then
     restoring master) and re-running the tagged deploy. This is a trap for every
     future template change deployed from a worktree.
  2. The global `docker.services` list describes the whole fleet, so the new
     container-health probe would have paged codey for servy's containers. The
     rendered script now skips containers that do not exist on the host (a
     STOPPED container still exists and is reported down), and the probe gate is
     **ui-only** so the both-profiles test host keeps the old behaviour. A stale
     Pushgateway job group from the earlier run was deleted on test; after the
     rule lookback expired the only remaining alert was the pre-existing
     LeagueSphere maintenance-probe failure.
- Molecule scenarios were extended but could not run locally (no Docker daemon);
  CI runs them, and the test-host deploy exercised the same role changes.

### Production (2026-11-25, from `master` after PR #368 merged)

- `codey.lehel.xyz`: `--tags user.docker.repo,user.docker.monitor,user.docker.env.monitor,system.probe` → `failed=0`, 14 changes. All eight new `monitor.*-codey` containers Up; `prometheus-codey` scrapes cadvisor/node-exporter/pushgateway/itself with `health=up`; rendered datasources contain `prometheus-codey`; contact points `disableResolveMessage: true`; Grafana has 84 rules (19 codey) all `health=ok`, `group_by ['severity']`, repeats `1h/4h/12h`, **0 firing / 0 pending alerts**; the rendered probe has `SKIP_MISSING_CONTAINERS=1` and pushes to `localhost:9092`.
- `servy.lehel.xyz`: `--tags user.docker.repo,system.probe` → `failed=0`, 3 changes; remote checkout at merge commit `2bb8f5ad`; collect containers unchanged and Up; probe still pushes to `localhost:9091` with `SKIP_MISSING_CONTAINERS=0`.
- CI on the PR: all 40 checks pass including `CI Gate`, both changed Molecule scenarios, git-crypt validation and YAML lint. The first CI run failed on a bad Molecule assertion (hyphenated unit name in a script that uses the underscore job name); fixed in `4b9137a2`.

### Key learnings
1. A branch deploy from a worktree syncs the **remote** checkout from the branch,
   but rendered monitor files come from `docker.local_dir` on the **controller**.
   A template change needs the controller checkout on the same ref, or it renders
   master's template while the remote dir has the branch's rules.
2. Any probe driven by the fleet-wide `docker.services` list must skip containers
   that were never created on the host; "inspect failed" does not distinguish
   "never existed" from "down" unless you check existence first.
3. `servyy-test` enables both compose profiles. A gate phrased as `'ui' in
   monitor_profiles` is also true there; per-host gates must exclude the other
   profile explicitly.

## Alternatives Considered

- **Remote-write codey metrics into servy's Prometheus:** one datasource/rule set,
  but needs the remote-write receiver enabled on servy and makes every shared rule
  host-aware. Rejected — codey's alerts would still depend on servy.
- **Third Traefik route / firewalled :9100:** rejected for widening the network
  surface (the "only two routes" invariant in `monitor/AGENTS.md`).

## Known issues
- Molecule scenarios were not executed locally (no Docker); CI/test-host proves them.
- The rule file was generated from a template, so descriptions are repetitive;
  this is cosmetic.
- The worktree branch was merged and removed; `master` is the only branch left.
