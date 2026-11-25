# ADR: Keep resolve mails and add a two-server overview dashboard

**Date:** 2026-11-25
**Status:** Proposed (code complete; test deploy pending)
**Relates to:** [`2026-11-25_monitor-codey-coverage.md`](2026-11-25_monitor-codey-coverage.md)

## Context

The 2026-11-25 alert-tuning change suppressed resolve messages to halve the mail
volume. The admin wants the "resolved" mail back. Separately, codey's metrics
were added to Grafana as a second datasource, but every provisioned dashboard
still used the default `prometheus` datasource (servy), so codey was visible in
alerts but not on a dashboard.

## Decision

1. Set `disableResolveMessage: false` on both contact points. Severity grouping
   and the relaxed repeat intervals stay — they are what bound the volume; a
   flapping rule now produces one grouped firing mail and one grouped resolve
   mail rather than one per rule.
2. Add `monitor/provisioning/dashboards/infrastructure/fleet-overview.json`: a
   paired `servy — …` / `codey — …` stat panel for CPU busy, load per core,
   memory used, root disk used, containers running/unhealthy, containers near
   their memory limit and OOM kills. Each panel names its datasource explicitly
   (`prometheus` vs `prometheus-codey`); Loki panels are untouched. No new
   route, no new datasource, no dashboard template variable — the user asked for
   a combined overview, not a switcher.

## Consequences

### Positive
- Recovery is visible in the inbox again, without returning to one-mail-per-rule.
- One dashboard answers "how is each host doing?" with both columns visible.
- Adding new paired metrics is mechanical; the contract test enforces the pairing
  and explicit datasources.

### Negative / Tradeoffs
- Two mails per firing cycle again (still grouped by severity).
- The overview has fixed hosts; a third server means another pair of columns.
- Grafana polls dashboards but not alerting provisioning, so the dashboard is
  picked up on the next poll while the contact-point change needs the Grafana
  restart that `monitor_reload` already performs.

## Implementation Details

**Files modified/created:**
- `monitor/provisioning/alerting/contact-points.yml` — resolve mail back on.
- `monitor/provisioning/dashboards/infrastructure/fleet-overview.json` — NEW.
- `ansible/tests/monitor_alerts/test_notification_tuning.py`,
  `ansible/tests/monitor_codey/test_fleet_dashboard.py` — tests.
- `monitor/AGENTS.md` — documents the paired-datasource invariant.

**Testing & Verification:** pending — CI, test-host deploy and production rollout
will be recorded here before this ADR is Accepted.
