# ADR: Quiet the alert emails and give codey its own monitoring

**Date:** 2026-11-25
**Status:** Proposed (code complete and statically verified; test/production deploy pending)
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
probe `f2d5bcbd`.

**Testing & verification (done on the branch):**
- All new unit tests written first, watched RED, then GREEN; 18 tests pass.
- `ansible-playbook servyy.yml --syntax-check -i testing` and `-i production` clean.
- `architecture/render.py --verify` → 31 services, 51 edges agree; `--selftest` ok.
- `yamllint` clean on the new rule file; `ansible-lint` shows only pre-existing
  categories (the new reload task file has the same 8 `var-naming` findings as its
  existing sibling).
- Molecule could not run locally (no Docker daemon); both changed scenarios were
  extended and syntax-checked, and CI will run them.

**Deploy verification and final status:** pending — see the update at the end.

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
