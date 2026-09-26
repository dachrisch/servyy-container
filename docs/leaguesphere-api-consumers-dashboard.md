# LeagueSphere — API Consumers dashboard

Grafana dashboard for observability on third-party API clients hitting `leaguesphere.app`
(via `traefik.traefik` JSON access logs → promtail → Loki).

- Dashboard file (source of truth, also provisioned on next monitor redeploy):
  `monitor/provisioning/dashboards/leaguesphere/api-consumers.json`
- Dashboard UID: `leaguesphere-api-consumers`, title `LeagueSphere — API Consumers`
- Default time range: `now-24h` (daily bot burst must be visible without changing the picker)
- No prod server edits were made for this; import goes through the Grafana UI/API.

## Import steps (reproducible, no SSH file edits)

### Option A — Grafana UI (recommended)
1. Open Grafana on `servy.lehel.xyz` → Dashboards → New → Import.
2. Upload `monitor/provisioning/dashboards/leaguesphere/api-consumers.json`
   (or paste its contents).
3. Select the existing **Loki** datasource when prompted (UID `loki`), click Import.

### Option B — Grafana HTTP API
```bash
export GRAFANA_URL="https://monitor.lehel.xyz"  # adjust to the real Grafana host
export GRAFANA_TOKEN="<service-account-token-with-dashboards-write>"
curl -s -H "Authorization: Bearer $GRAFANA_TOKEN" \
     -H "Content-Type: application/json" \
     "$GRAFANA_URL/api/dashboards/db" \
     -d @monitor/provisioning/dashboards/leaguesphere/api-consumers.json
```

### Option C — provisioning (automatic on next deploy)
The file already lives in the `leaguesphere` dashboard provider path
(`monitor/provisioning/dashboards/dashboards.yml`), so the next normal monitor
stack redeploy picks it up into the LeagueSphere folder with no manual step.

## Proof — snapshot-bot burst of 2026-09-26
1. Import the dashboard, set the time picker to `2026-09-26 08:00 – 08:15 UTC`
   (retention permitting — see effective-window note below).
2. Row 7 §7 must read: **catalog hits ≈ 1**, **/games/ hits ≈ 900** for UA `node`.
3. The "Snapshot-bot raw lines" logs panel must show 1×
   `/api/gamedays/?format=json&page_size=1000` then ~900×
   `/api/gamedays/<id>/games/?format=json` from a single ClientHost
   (on 2026-09-26: `20.161.69.33`), and the red "Snapshot-bot catalog hit"
   annotation must mark the window.
4. If the 2026-09-26 window has aged out (Docker rotation ≈ current day),
   use the **next daily run** (~08:0x UTC): same signature, fresh Azure/GH-Actions IP.
5. Sanity: row 3 burst view spikes to ~300 req/min during the run and returns to ~0.

## Effective window
Docker `local` log-driver rotation keeps roughly the **current day**; Loki retention is
31d but cannot show what Docker already rotated. Treat the dashboard as a **~24h window**.
Longer retention / recording rules are a follow-up proposal, not this task.

## Runbook — normal vs deserves a look
**Normal:** daily ~08:0x UTC burst (UA `node`, 1× catalog + ~900× `/games/` in ~3 min);
steady low-rate Sideline/1.0 polling (`search=season:2026&page_size=500` + `/games/`);
`Mozilla/*` browsers spread over many IPs, 2xx-dominated.
**Look closer:** a new UA/ClientHost bursting >100 req/min (row 3 red line);
429 spikes (rate limiting engaging — known bot vs unknown client?);
5xx spikes (upstream nginx/gunicorn/Django problem — check LeagueSphere logs);
p95 regression on `/api/gamedays*/games/` (row 5) or payload jump (row 6).

## Alert proposals (OUT OF SCOPE — candidates only)
1. Unknown-UA burst: Loki metric query — per-(user_agent) req/min > 100 for 5m,
   excluding `node` and `Sideline`.
2. Upstream errors: `sum(rate(traefik_service_requests_total{service=~".*leaguesphere.*",code=~"5.."}[5m])) > threshold`
   (matches the existing Prometheus-side alert style in `monitor/provisioning/alerting/`).
3. Latency SLO: p95 of `/api/gamedays*/games/` > 2× baseline for 15m
   (needs a recording rule + longer retention first).

## Query conventions used
Copied from the Security dashboard: stream `{job="docker", container="traefik.traefik"}`,
structured-metadata filters (`| path =~`, `| user_agent =~`, `| status =~`),
`| json` only for `ClientHost`/`Duration`/`DownstreamContentSize`/`RouterName`.
Endpoint templating via
`| label_format path_nq=… | label_format endpoint=…` (`regexReplaceAll`, query stripped, IDs → `{id}`).

> 2026-09-26 fix (dashboard v2): three corrections after live verification.
> (1) Go-template `regexReplaceAll` inside `label_format` does **not** parse on
> Loki 3.7.8 — endpoint grouping is now by `/api/<area>` (first two path
> segments via `regexp`, no templates). (2) Bare `| json` extracts every field
> (incl. per-line-unique `RequestCount`/nanosecond timings) and blows Loki's
> 500-series limit — all extractions are field-limited (`| json <field>`) with
> `| __error__=""` guards (Docker rotation truncates lines mid-write, which
> otherwise aborts whole queries). Same guard needed because raw-`user_agent`
> grouping exceeds 500 distinct values/day: client totals are fixed UA classes
> (node / Sideline / browsers / scrapers&probes / other). (3) All consumer
> panels are host-scoped to `leaguesphere.app` (the unscoped stream mixes in
> Grafana's own `/api/*` polling and subdomain-scan noise).
