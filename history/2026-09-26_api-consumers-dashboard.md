# 2026-09-26 — LeagueSphere API Consumers dashboard

Built a Grafana "API Consumers" dashboard for third-party client observability on
`leaguesphere.app` (renegades-scores snapshot bot UA `node`, Sideline/1.0 client, browsers).

- New: `monitor/provisioning/dashboards/leaguesphere/api-consumers.json`
  (UID `leaguesphere-api-consumers`, default `now-24h`, 7 panel groups + runbook text).
- New: `docs/leaguesphere-api-consumers-dashboard.md` (UI/API import steps, proof procedure
  for the 2026-09-26 08:06–08:08 UTC burst, runbook, 3 alert proposals).
- Loki patterns copied from the Security dashboard: `{job="docker", container="traefik.traefik"}`
  + structured-metadata filters (`path`, `user_agent`, `status`); `| json` only for
  `ClientHost`/`Duration` (ns→ms)/`DownstreamContentSize`; endpoint templating
  (`/{id}`, query stripped) via chained `label_format` + `regexReplaceAll`.
- Effective window (~24h, Docker rotation vs 31d Loki retention) is noted on the dashboard itself.
- No prod changes: dashboard goes in via Grafana UI/API import; the provisioning-path file
  makes it automatic on the next monitor redeploy. Alerts explicitly out of scope (proposals only).
- Validation: JSON lint OK, unique panel IDs, no grid overlaps, LogQL cross-checked against
  Security/http-errors/leaguesphere dashboards. Live proof against the 2026-09-26 burst
  (or next daily run) is a manual Grafana step — see the docs proof section.
