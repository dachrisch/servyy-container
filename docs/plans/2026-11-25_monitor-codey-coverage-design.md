# Design: quiet the alert emails and bring codey into monitoring

**Date:** 2026-11-25
**Status:** Approved by user (2026-11-25)

## Context

Inspection of `monitor/` found two independent problems.

1. **Notification noise is in the routing layer, not the thresholds.** The load and
   CPU rules were deliberately retuned in `history/2026-10-30_load-alert-tuning.md`.
   But `notification-policies.yml` groups by `alertname, severity` — with 65 uniquely
   named rules that is 65 separate notification groups — and both contact points
   send resolve messages. Seven days of Grafana state history showed 36 firings,
   33 resolves, and 39 Error + 39 Error-resolved events, all 39 errors naming the
   single cross-host `prometheus` datasource. They arrive in five synchronized
   bursts of 43–53 rules, i.e. one flaky route becomes ~100 emails.
2. **Codey is only the alerting plane.** It runs Grafana + Loki (`ui` profile) but
   no collector: Prometheus, node-exporter, cadvisor, promtail and the Pushgateway
   all live on servy. Prometheus has no codey target; codey's containers and logs
   are invisible to the alerts. `system_probe_push_enabled` is false there because
   there is no local sink.

## Decision

**A. Notification tuning.** Group notifications by `severity` only (one email per
severity per interval instead of one per rule), suppress resolve messages on both
contact points, and lengthen repeat intervals (critical 1h, high 4h, medium 12h).

**B. Codey gets its own local collector stack.** Add distinct `ui`-profile services
to the same compose project: `prometheus-codey`, `node-exporter-codey`,
`cadvisor-codey`, `pushgateway-codey` + bridge on `127.0.0.1:9092` (9091 is taken on
servyy-test, which runs both profiles), and `promtail-codey`. A second Grafana
datasource `prometheus-codey` points at the internal `backend` network. A focused
`alert-rules-codey.yml` carries codey-specific host and container rules. No new
public route, no change to servy's Prometheus, no remote write.

**C. Container-health probe on codey.** Add a per-probe gate
`system_probe_container_push_enabled` (true where `ui` is active) so only the
container-health timer runs on codey; point it at the local bridge on 9092. The
all-probes cleanup must not delete that one timer. Codey's Prometheus scrapes the
local Pushgateway, so `container_not_running` / `unhealthy` cover codey.

**D. Log shipping.** `promtail-codey` pushes to the existing authenticated
`loki.lehel.xyz` route. The Loki-password render (currently gated on `collect`)
must also run for `ui`.

## Alternatives rejected

- **Remote-write into servy's Prometheus:** one datasource/rule set, but needs the
  remote-write receiver enabled on servy and makes every shared rule host-aware.
  Rejected: keeps codey's alerts dependent on the fragile cross-host route.
- **Third Traefik route for codey exporters:** explicitly forbidden by the
  "only two cross-host routes" invariant in `monitor/AGENTS.md`.
- **Firewalled :9100 host node-exporter (runny pattern):** host metrics only, no
  container metrics or logs; second stack still needed later.

## Data flow after the change

```
codey: node-exporter-codey/cadvisor-codey -> prometheus-codey (local backend net)
codey: container-health timer -> localhost:9092 -> bridge -> pushgateway-codey
codey: promtail-codey -> loki.lehel.xyz (existing authenticated route)
codey: Grafana -> prometheus-codey (local) AND prometheus (servy, via existing route)
servy: unchanged collectors; its rules keep using the servy datasource
```

## Constraints / invariants

- Compose container names must stay distinct across profiles because servyy-test
  runs both; a second bridge must not collide on `127.0.0.1:9091`.
- Prometheus and Grafana read startup config only; `monitor_reload` must fingerprint
  the new `prometheus-codey.yml` and restart `monitor.prometheus-codey` on change.
- Files bind-mounted into containers as non-root must be in
  `world_readable_paths_by_service.monitor` (add `prometheus-codey.yml`).
- The architecture map (`architecture/landscape.yaml`) must gain the new containers
  and edges, and `render.py --verify` must stay silent.
- Molecule tests first: extend `monitor_reload/default` and `system_probe/no-sink`
  rather than adding new scenarios (matrix stays valid).
- Production deploy requires explicit user approval after test verification.
