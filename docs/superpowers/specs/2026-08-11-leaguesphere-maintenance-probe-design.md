# LeagueSphere Maintenance/Games Probe — Design

## Problem

There's no automated check that the production LeagueSphere app is actually usable during a
live game. `SiteConfiguration.maintenance_mode` can be left on (or turned on by mistake) while
real games are in progress, silently locking out officials, scorekeepers, and spectators — the
existing container-health check (`container/healthcheck.sh`) deliberately treats maintenance
mode as "healthy" (see its comment), so it will never catch this.

## Goal

An hourly, automated check on production: **fail loudly if maintenance mode is active while
games are happening.** Loosely modeled on the existing CircleCI `auto_approve_hold_production`
job, which already knows how to ask "are games happening right now" — but that job only runs at
deploy time. This needs to run continuously, independent of deploys, and page someone.

## Roadmap context: this is step 1 of a larger Monit → Grafana migration

While scoping this, we identified that Monit (`container/ansible/plays/roles/system/tasks/monit.yml`)
currently does several distinct jobs, most of which are pure alerting and could move to the
Prometheus/Grafana stack that already exists and already delivers email
(`container/monitor/provisioning/alerting/`):

| Monit check today | Fate |
|---|---|
| SSHD process monitor + auto-restart | **Stays on Monit** — it's server-side process supervision (active remediation), a different job than alerting, and out of scope for this migration |
| System resources (load/mem/swap/CPU, root + extension volume disk) | Follow-on sub-project — mostly redundant with node-exporter metrics already scraped |
| Backup/cleanup log-freshness (restic, docker/kernel cleanup logs) | Follow-on sub-project — needs the same "probe → Pushgateway → Grafana alert" pattern this design introduces |
| Storagebox mount presence + space | Follow-on sub-project — same pattern again |
| Per-service container running-state (bespoke script per docker-compose service) | Follow-on sub-project — likely derivable from cAdvisor metrics already scraped, avoiding new scripts entirely |

This design covers **only** the LeagueSphere maintenance/games probe. It deliberately
establishes a reusable pattern (host-level probe script → Pushgateway → Grafana alert rule) that
the three follow-on sub-projects above will each reuse in their own future spec. Each gets
brainstormed and planned separately when picked up.

## Architecture

```
systemd user timer (hourly, lehel.xyz)
   -> ls-maintenance-probe.sh
        -> GET https://leaguesphere.app/health/            (maintenance-mode check)
        -> GET https://www.leaguesphere.app/api/game-progress/?page_size=100  (games check)
        -> POST http://localhost:9091/metrics/job/leaguesphere_maintenance_probe  (Pushgateway)
   -> Prometheus scrapes Pushgateway (already configured, job "pushgateway")
   -> Grafana alert rule evaluates the pushed gauges
   -> email via existing "email-critical" / "email-admin" contact points
```

**Revision note (caught during Task 7's validation on stage):** the design originally proposed
detecting maintenance mode via `GET /login/`, on the assumption — copied from
`container/healthcheck.sh`'s comment — that maintenance mode blocks broad site access, so any
gated path would 302 to `/maintenance/`. That assumption is wrong in practice: inspecting
stage's live `SiteConfiguration.maintenance_pages` (which mirrors prod's, since `ls_db_sync`
clones the full prod DB into stage) showed it's scoped to specific *write* endpoints
(`/gamedays/gameday/new/`, passcheck transfers, officials sign-up, gameday design/update, …) —
`/login/` is never in that list, so `healthcheck.sh`'s redirect-handling branch is effectively
dead code today. Since maintenance is meant to block writes while leaving the site browsable,
checking a redirect on some gated write path was also the wrong shape of signal generally (it
depends on an admin-editable list never dropping the one path this probe happens to poll).
Instead, `/health/` now reports `maintenance_mode` directly as a JSON boolean — see
`league_manager/urls.py`'s `HealthCheckView` in the `leaguesphere` repo, added in
[dachrisch/leaguesphere#1821](https://github.com/dachrisch/leaguesphere/pull/1821). This
probe now depends on that PR merging and deploying to whichever environment it targets before
maintenance-mode detection actually works; the games-detection half is unaffected.

- **Maintenance-mode detection** — `GET /health/`, parse the `maintenance_mode` boolean from the
  JSON response. Sourced from the same cache-then-DB-fallback `MaintenanceModeMiddleware` already
  uses, so it can never disagree with the middleware's own behavior. No auth needed.
- **Games-happening detection** — identical to `.circleci/config.yml`'s
  `auto_approve_hold_production` job: `GET /api/game-progress/?page_size=100` (documented as an
  "unrestricted public API"), filtered to today's date (`Europe/Berlin`) with
  `status != "beendet" and status != "Geplant"`.
- **Metrics delivery** — the `pushgateway-bridge` container (`container/monitor/docker-compose.yml`)
  exposes Pushgateway on `localhost:9091` on the host specifically for host-level scripts to
  push to (the same path the k6 load-test tooling uses). See the revision note below — making
  that publish actually reach the container required new networking.

**Revision note (found while validating the alert pipeline):** exercising the synthetic-payload
half of the testing strategy below (pushing to production's Pushgateway) surfaced that
`pushgateway-bridge`'s `ports: ["9091:9091"]` never actually worked — the port was never
listening on the host at all. Confirmed by direct reproduction on `servyy-test.lxd`:
`HostConfig.PortBindings` shows the requested mapping, but `NetworkSettings.Ports` stays `null`
and nothing accepts connections on 9091. Root cause: Docker silently no-ops `ports:` publishing
for a container whose *only* network is `internal: true` (`backend`, here). Fixed by giving
`pushgateway-bridge` a second, non-internal network (`pushgateway_publish`, added in
`monitor/docker-compose.yml`) purely so its port publish takes effect — `backend` stays
`internal: true` for every other service in this stack, unchanged. The host binding was also
tightened to `127.0.0.1:9091:9091` once the publish started working for real, since the only
intended consumer is host-local scripts and an unauthenticated Pushgateway (accepts POST and
DELETE) has no business listening on every interface.

## Metrics pushed

Job name: `leaguesphere_maintenance_probe`. All gauges, overwritten on every push:

| Metric | Meaning |
|---|---|
| `leaguesphere_maintenance_mode_active` | 0/1 — the `maintenance_mode` field from `GET /health/` |
| `leaguesphere_active_games` | integer — count of today's non-finished, non-scheduled games |
| `leaguesphere_maintenance_blocking_games` | 0/1 — precomputed `maintenance_active AND active_games>0`. Computed in the script (not in the Grafana rule) so the alert stays a plain single-query threshold, matching every existing rule's shape in `alert-rules.yml` |
| `leaguesphere_probe_success` | 0/1 — whether both HTTP calls completed (distinguishes "prod is fine" from "the probe itself is broken") |

Reference script (`ls_maintenance_probe.sh.j2`, parameterized by `{{ ls_maintenance_probe_url }}`):

```bash
#!/bin/bash
set -uo pipefail
# Deliberately no `set -e`: each step below handles its own failure explicitly so a
# problem in one check (e.g. non-JSON response) can't abort the script before it pushes
# anything — see the assumption/fail-safe note below.

BASE_URL="{{ ls_maintenance_probe_url }}"
PUSHGATEWAY_URL="http://localhost:9091"
JOB_NAME="leaguesphere_maintenance_probe"

probe_success=1

# 1. Maintenance-mode detection via the health endpoint (leaguesphere#1821)
maintenance_active=0
health_response=$(curl -A ls-maintenance-probe -s --max-time 15 --connect-timeout 5 "${BASE_URL}/health/")
if [ -z "$health_response" ] || ! echo "$health_response" | jq -e 'has("maintenance_mode")' >/dev/null 2>&1; then
  probe_success=0
else
  maintenance_active=$(echo "$health_response" | jq -r 'if .maintenance_mode then 1 else 0 end')
fi

# 2. Active-games detection (mirrors .circleci/config.yml auto_approve_hold_production).
# Assumption: /api/game-progress/ is never itself gated by maintenance_pages — CircleCI's
# own auto_approve job already depends on that being true today. If maintenance_pages is
# ever reconfigured to include /api/, exclude game-progress from it explicitly rather than
# relying on this script to route around it.
active_games=0
games_known=1
response=$(curl -A ls-maintenance-probe -sf --max-time 15 --connect-timeout 5 "${BASE_URL}/api/game-progress/?page_size=100")
if [ -z "$response" ] || ! echo "$response" | jq -e '.results | type == "array"' >/dev/null 2>&1; then
  probe_success=0
  games_known=0
else
  today_date=$(TZ=Europe/Berlin date +%Y-%m-%d)
  active_games=$(echo "$response" | jq --arg today "$today_date" \
    '[.results[] | select(.date == $today) | .games[] | select(.status != "beendet" and .status != "Geplant")] | length')
fi

# Fail-safe: if maintenance is active and the game state can't be confirmed (e.g. the API
# call above failed), treat it as blocking rather than silently assuming zero active games
# — an unverifiable state is exactly the case where suppressing the alert would be worst.
blocking=0
if [ "$maintenance_active" = "1" ] && { [ "$games_known" = "0" ] || [ "$active_games" -gt 0 ]; }; then
  blocking=1
fi

cat <<EOF | curl -sf --max-time 15 --connect-timeout 5 --data-binary @- "${PUSHGATEWAY_URL}/metrics/job/${JOB_NAME}"
# TYPE leaguesphere_maintenance_mode_active gauge
leaguesphere_maintenance_mode_active ${maintenance_active}
# TYPE leaguesphere_active_games gauge
leaguesphere_active_games ${active_games}
# TYPE leaguesphere_maintenance_blocking_games gauge
leaguesphere_maintenance_blocking_games ${blocking}
# TYPE leaguesphere_probe_success gauge
leaguesphere_probe_success ${probe_success}
EOF
```

## Alerting

New rule group in `container/monitor/provisioning/alerting/alert-rules.yml`, `folder:
LeagueSphere`, `name: leaguesphere-alerts`, `interval: 1m` — same shape (query → reduce last →
threshold) as every existing rule:

1. **`leaguesphere_maintenance_blocking_games`** — `leaguesphere_maintenance_blocking_games ==
   1`, `for: 5m` (avoids alerting on a single mid-transition sample), `severity: critical` →
   routes to `email-critical` (10s group_wait, 30m repeat, per existing notification-policies.yml).
   Title: "Maintenance Mode Blocking Live Games."
2. **`leaguesphere_probe_success`** — `leaguesphere_probe_success == 0`, `for: 10m`, `severity:
   medium` → routes to `email-admin`. Catches the timer firing but the HTTP calls failing (prod
   unreachable, API shape changed, DNS issue).
3. **`leaguesphere_maintenance_probe_stale`** — `time() -
   push_time_seconds{job="leaguesphere_maintenance_probe"} > 5400` (90 min, giving headroom over
   the hourly cadence + `RandomizedDelaySec`), `severity: medium` → routes to `email-admin`.
   `push_time_seconds` is a metric Pushgateway automatically maintains per job (generic metric
   name, distinguished by the `job` label — not prefixed per-job); this catches the timer
   stopping entirely (disabled unit, host down, script crashing before it can push), which rule
   2 alone would miss since a dead timer just leaves the last-pushed values in place. This
   mirrors Monit's own two-tier approach (its container check alerts on a bad exit status; its
   log checks separately alert on file staleness).

## Deployment

New Ansible role `container/ansible/plays/roles/ls_maintenance_probe/`, mirroring
`ls_db_sync`'s existing oneshot-timer structure exactly (`tasks/oneshot_include.yml` +
`templates/oneshot.service.j2` + `templates/oneshot.timer.j2`, copied verbatim from that role):

```
ls_maintenance_probe/
├── defaults/main.yml           # ls_maintenance_probe_url: "https://leaguesphere.app"
├── tasks/
│   ├── main.yml                 # deploy the script, import oneshot_include.yml
│   └── oneshot_include.yml
└── templates/
    ├── ls_maintenance_probe.sh.j2
    ├── oneshot.service.j2
    └── oneshot.timer.j2
```

- Schedule: `OnCalendar=*-*-* *:00:00` (hourly, on the hour); `RandomizedDelaySec=5m` (already
  baked into the shared `oneshot.timer.j2` template) staggers it slightly.
- No secrets: both endpoints are public and unauthenticated. `curl`/`jq` are already in
  `sys_packages` on every host — no new package installs.
- Wired into `ansible/plays/leaguesphere.yml` as its own role entry, tag `ls.maintenance.probe`
  only — not bundled into `ls.app`/`ls.app.prod`, matching how `ls_db_migrate` is deliberately
  kept "tag-only, not in default ls run." Correction (caught in task review): the play itself
  *does* carry a play-level `tags: [ls]` at the bottom of `leaguesphere.yml`, which Ansible's
  tag-inheritance rule applies to every task in the play — including this role's, and every
  other "tag-only" role's. In practice this is dormant: nothing in this repo (scripts, docs, or
  runbooks) ever runs bare `--tags ls`, every real deploy path uses granular tags
  (`ls.app.prod`, `ls.db.sync`, etc.), and it predates this change. A full untagged run still
  includes this role too, same as every other role.
- The Grafana alert-rules.yml change ships through the normal `monitor` service sync. Because
  "Monitor" is a `manual: true` service (`container/ansible/plays/user.yml`), applying it
  requires an explicit deploy: `./servyy.sh --tags user.docker.monitor -e manual=false`
  (overriding the role default so `deploy.yml` actually runs `docker compose up` and Grafana
  picks up the new provisioning file).

## Testing strategy (test-first policy)

The "Monitor" stack (Grafana/Prometheus/Pushgateway) only exists on production — it's a
`manual` service, not part of the set auto-provisioned onto `servyy-test.lxd`. So validation
splits into two independent, both-safe halves instead of one end-to-end run on the test box:

1. **Script logic** (maintenance detection + game-progress parsing + metric math) — validated
   against **stage** (`stage.leaguesphere.app`). Point `ls_maintenance_probe_url` at stage,
   toggle stage's own `SiteConfiguration.maintenance_mode` via the documented admin toggle
   (`/admin/league_manager/siteconfiguration/toggle-maintenance/`), and confirm the script
   produces the right gauge values in both states. Stage is safe to flip — it's not seen by real
   users. **Blocked on leaguesphere#1821 deploying to stage** — until `/health/` reports
   `maintenance_mode`, this half of validation can't run for real; the games-detection half is
   independent and already validated.
2. **Alert pipeline** (Pushgateway → Prometheus → Grafana rule → email) — validated by pushing a
   **synthetic** test payload directly to production's Pushgateway under a distinct job name
   (e.g. `leaguesphere_maintenance_probe_test`), confirming the rule fires and the email lands,
   then deleting it (`DELETE /metrics/job/leaguesphere_maintenance_probe_test`). This never
   touches real prod maintenance-mode state or real game data — only exercises the same public
   push endpoint the real script will use, with throwaway data.

Only once both halves check out does the role get pointed at prod
(`ls_maintenance_probe_url=https://leaguesphere.app`) and deployed for real, with explicit
approval before that final production run — per this repo's standing test-first policy.

## Non-goals

- No remediation (the probe never toggles maintenance mode itself).
- No change to `MaintenanceModeMiddleware`'s redirect behavior or `SiteConfiguration`'s schema —
  the one app-side change (leaguesphere#1821) only adds a read-only field to an existing,
  already-public health endpoint; it doesn't alter what maintenance mode actually does.
- The 4 follow-on Monit-replacement sub-projects (system resources, log-freshness, storagebox,
  container health) are out of scope here — each gets its own spec later, reusing the probe →
  Pushgateway → Grafana pattern this design introduces.
- SSHD monitoring/remediation stays on Monit permanently — not part of this migration.
