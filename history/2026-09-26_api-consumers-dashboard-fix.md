# 2026-09-26 — API Consumers dashboard query repairs (dashboard v2)

The dashboard shipped in #149 rendered "No data" on the totals and endpoint
panels (only the req/min panel showed data). Live diagnosis against Loki
(Loki 3.7.8) found three independent query bugs; all 35 panel queries now
verified green through the Grafana API before redeploy.

1. **`regexReplaceAll` in `label_format` does not parse** (`unexpected
   IDENTIFIER` at the function name — nested quotes terminate the LogQL
   string, and sprig regex funcs are absent from Loki's template func map
   anyway; even arg-free `regexReplaceAll "a" "b" "c"` fails). Endpoint
   grouping is now by `/api/<area>` (first two path segments via `regexp`),
   which returns ~29 series over 24h. Per-ID grouping is unworkable regardless:
   the snapshot bot alone crawls ~900 gameday IDs/day, exceeding Loki's
   500-series limit.
2. **Bare `| json` explodes cardinality.** Full extraction includes
   per-line-unique fields (`RequestCount` counter, nanosecond `Duration`s),
   so any 24h aggregation instantly hits the 500-series limit. All extractions
   are now field-limited (`| json <field>`) with `| __error__=""` guards.
   The guards also fix abort-on-truncated-line: Docker `local`-driver rotation
   cuts mid-JSON-line writes, and one malformed line aborted whole queries.
   Raw-`user_agent` grouping has the same disease (148 distinct UAs in a few
   minutes of traffic; >500/day with scanner/bot churn), so client totals are
   fixed UA classes (node / Sideline / browsers / scrapers&probes / other).
3. **Unscoped stream mixes vhosts.** `/api/*` matches Grafana's own UI polling
   (`/api/ds`, `/api/account`, … on `monitor.lehel.xyz`) and subdomain-scan
   noise (`api.`/`admin.`/`account.`…). All consumer panels are now
   host-scoped to `leaguesphere.app` (node bot and Sideline verified 100%
   there). Also fixed: `\?` is an invalid LogQL string escape (catalog
   latency/bytes panels) — use `[?]` instead.

- Changed: `monitor/provisioning/dashboards/leaguesphere/api-consumers.json`
  (queries, 3 panel titles, About/runbook notes),
  `docs/leaguesphere-api-consumers-dashboard.md` (conventions section).
- Deploy: repo sync + `docker restart monitor.grafana` (provisioning needs
  the restart); verified via API (dashboard version bump + live panel data).
- Note: `user_agent="node"` matched only 2 lines in one probe — the bot runs
  ~08:0x UTC daily; verify burst panels at the next run if aged out.
