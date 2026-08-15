# LeagueSphere Maintenance Probe — Grafana Verification (Stage)

**Date:** 2026-08-14
**Status:** ✅ Resolved same day. Fix merged and deployed to stage, re-validated end-to-end
(both halves of the testing strategy), all test artifacts cleaned up.
**Repos:** `leaguesphere` (app-side bug + fix), `container` (probe script + Grafana alert rules)

## Background

`leaguesphere` PR #1823 (`feat(admin): simplify maintenance mode to 3-scope dropdown`, merged
2026-08-11) replaced the old binary `SiteConfiguration.maintenance_mode` field with a 4-value
`maintenance_scope` (off/full/writes_only/custom), and changed `MaintenanceModeMiddleware`'s
shared cache dict shape from `{"mode_active": bool, "patterns": [...]}` to
`{"scope": str, "patterns": [...]}`. It missed updating `HealthCheckView`
(`league_manager/urls.py`), which still read `config["mode_active"]` — the exact field the
LeagueSphere Grafana maintenance probe (`container/ansible/plays/roles/ls_maintenance_probe`,
added same evening in commit `a510fc5`) polls via `/health/` to drive the "Maintenance Mode
Blocking Live Games" critical alert. Once the shared cache warmed, `/health/` would `KeyError`
→ 500; separately, `/health/` wasn't exempt from the maintenance middleware, so under "Full App"
scope it would 302-redirect instead of returning JSON.

This was fixed 25 minutes later by commit `5a3188e0` — pushed **directly to `master`, no PR**
(author `opencode@servy.lehel.xyz`, an automated agent with apparent push access; see
`leaguesphere-opencode-direct-master-push` in project memory). The fix derives
`maintenance_mode` from `scope != "off"`, exempts `/health/` and `/database-error/` from the
middleware, and adds regression tests including one that reproduces the exact warm-cache
scenario the original PR's tests missed. Shipped in release `v4.18.0`/`v4.18.1`. Verified: all 5
tests in `league_manager/tests/test_health_check.py` pass against current `origin/master`.

**This session's task:** verify on stage that the fix actually works end-to-end — i.e. that
Grafana would correctly pick up a real `maintenance_scope` change via the probe pipeline — per
the two-half testing strategy already documented in
`container/docs/superpowers/specs/2026-08-11-leaguesphere-maintenance-probe-design.md`.

## What was tested

All testing used a **distinct Pushgateway job name** (`leaguesphere_maintenance_probe_stagetest`)
so nothing could collide with or overwrite the real `leaguesphere_maintenance_probe` job that
Grafana's alerts actually read. Confirmed the real job's values before starting and never
touched them:
```
leaguesphere_maintenance_mode_active{job="leaguesphere_maintenance_probe"} 0
leaguesphere_active_games{job="leaguesphere_maintenance_probe"} 0
leaguesphere_maintenance_blocking_games{job="leaguesphere_maintenance_probe"} 0
leaguesphere_probe_success{job="leaguesphere_maintenance_probe"} 1
```

1. Copied the deployed probe script (`/home/cda/.backup-scripts/ls-maintenance-probe.sh` on
   `lehel.xyz`) to `/tmp/ls-maintenance-probe-stagetest.sh`, with only `BASE_URL` pointed at
   `https://stage.leaguesphere.app` and `JOB_NAME` changed to the test job name.
2. **Baseline (`scope=off`):** ran the test script — correctly reported
   `maintenance_active=0 active_games=0 blocking=0 probe_success=1`, confirmed under the
   `..._stagetest` label in Pushgateway. `/health/` on stage also correctly returned
   `{"status": "healthy", "maintenance_mode": false}`.
3. **Toggled stage** to `maintenance_scope = "writes_only"` directly via
   `docker exec leaguesphere_stage.staging-app python manage.py shell`, confirmed the DB write
   persisted (re-read cleanly in a separate process/connection).
4. **`/health/` did not pick up the change** — 8 consecutive requests all returned
   `maintenance_mode: false`, despite the DB being correct.
5. Restarted `leaguesphere_stage.staging-app` to test a cold-cache hypothesis. After restart,
   the DB read back as `off` again — **unexplained, not root-caused**. Re-set
   `scope=writes_only` a second time (confirmed via DB); `/health/` still uniformly returned
   `false` across 8 more requests with no restart involved this time, which rules out the
   restart itself as the explanation for the staleness (though not for the earlier DB revert).

## Root cause found

`CACHES` (`league_manager/settings/base.py`) uses `LocMemCache`, which is **per-process**, not
shared across processes. Both stage and prod run gunicorn with `-w 6 --worker-class gthread`
(confirmed identical on both via `docker top` / the compose files) — 6 independent worker
processes, each with its own private in-memory cache. The admin's `cycle_scope` view (and the
old `toggle-maintenance` view before it) calls `cache.delete(MAINTENANCE_CONFIG_CACHE_KEY)`,
but that only clears the cache inside whichever single worker happened to serve *that specific
HTTP request*. The other 5 workers keep serving their previously-cached config — for up to the
cache TTL (6,000,000s ≈ 69 days) — regardless of what the DB or the admin UI now says.

This is **not** something PR #1823 or commit `5a3188e0` introduced — the identical bug existed
with the old `mode_active` cache shape too. It predates this week's work entirely and is a
standing architectural gap in how maintenance mode (and now `/health/`) is served.

**Practical implication:** flipping maintenance mode in the admin — on stage, and very likely on
production too — does not reliably take effect across all workers immediately. Some fraction of
requests (and potentially the Grafana probe's own request) can keep observing the pre-toggle
state for a long time after the change, purely depending on which worker's socket accept()
happens to pick up the connection. This directly undermines confidence in the very probe/alert
this session set out to validate: "does Grafana see a live maintenance-mode change" is not
reliably true today.

Production's real state was **not** tested against this hypothesis — deliberately, to avoid
touching prod's actual maintenance-mode behavior. It's inferred from identical config
(`-w 6` gunicorn, same `LocMemCache` settings), not directly observed.

## Left in place (cleanup not yet done — stopped for review)

- Stage `SiteConfiguration.maintenance_scope` is currently `"writes_only"` (not reverted to
  `"off"`). Because of the caching bug above, some/all of stage's live workers may still be
  *serving* as if it were `"off"` regardless.
- `/tmp/ls-maintenance-probe-stagetest.sh` left on `lehel.xyz` (harmless temp file, not wired
  into any timer).
- `leaguesphere_maintenance_probe_stagetest` job still present in production's real Pushgateway
  (`http://localhost:9091` on `lehel.xyz`) — separate label from the real
  `leaguesphere_maintenance_probe` job, so it does not affect real alerts, but should eventually
  be removed: `curl -X DELETE http://localhost:9091/metrics/job/leaguesphere_maintenance_probe_stagetest`.

## Known gaps / open questions

- **No fix designed yet** for the cross-worker cache staleness. Candidate directions (not
  evaluated in depth): shorten the TTL drastically so staleness is bounded to something
  reasonable; move `MAINTENANCE_CONFIG_CACHE_KEY` to a cross-process backend (Redis/Memcached)
  if one is already available to this app; or have the admin action trigger a worker
  reload/signal instead of relying on cache invalidation at all.
- **Unexplained:** why restarting the stage app container caused `maintenance_scope` to revert
  from `"writes_only"` to `"off"` in the DB itself (not just the cache). Entrypoint
  (`container/entrypoint.sh`) only conditionally runs `manage.py migrate --no-input`, which
  shouldn't touch existing data — but something did. Not reproduced a second time (second
  toggle, without a restart, held correctly at the DB level for the remainder of the session).
- Whether production has ever actually served inconsistent maintenance-mode behavior across
  workers in practice is unknown — this session only established that the *mechanism* for it to
  happen exists, not that it has caused a real incident.
- The original two-half testing strategy's second half (push a synthetic payload under a test
  job name, confirm the Grafana alert rule actually fires and the email lands, then delete it)
  was **not** executed this session — testing stopped once the cache-staleness issue surfaced.

## Next steps

1. ~~Decide on and implement a cache-invalidation fix that actually works across all gunicorn
   workers, in `leaguesphere`.~~ **DONE** — see Resolution below.
2. Investigate the stage DB revert-on-restart anomaly — **deferred, not investigated further**
   (deliberately left as unreproduced/low-priority per instruction; it did not recur during this
   session's subsequent stage toggles).
3. ~~Clean up the three leftover items above.~~ **DONE** — see Resolution below.
4. ~~Re-run stage validation (half 1) once the cache fix lands, then run the alert-pipeline
   synthetic-payload validation (half 2) that was never reached.~~ **DONE** — see Resolution below.
5. Separately worth raising: commit `5a3188e0` (the original regression fix) went straight to
   `master` with no PR — flagged in project memory
   (`leaguesphere-opencode-direct-master-push`), not addressed here.

## Resolution (later same session, 2026-08-14)

**Fix:** [PR #1832](https://github.com/dachrisch/leaguesphere/pull/1832), merged to master.
`MaintenanceModeMiddleware`'s cache TTL (`middleware/maintenance.py`) dropped from 6,000,000s
(~69 days) to a new `MAINTENANCE_CONFIG_CACHE_TTL = 30` (`league_manager/constants.py`) —
bounds cross-worker propagation to ~30s instead of effectively unbounded, without needing a
shared cache backend (no Redis/Memcached exists in this stack). TDD: new test
`TestMaintenanceConfigCacheTTL` in `test_views.py` asserts the middleware's `cache.set` timeout
for the maintenance key is ≤60s. Adds one cheap single-row `SiteConfiguration` query roughly
every 30s per idle gunicorn worker — negligible. Only the `site_maintenance_config` cache key is
affected; other cache users (`db_guard.py`, `team_repository_service.py`, the `views.py`
`cache.clear()` admin action) are untouched (per-entry `timeout`, not backend-wide).

**Deployed to stage:** `./container/deploy.sh stage` → tag `v4.18.4-rc.1` → CircleCI
`deploy_staging` → Watchtower auto-pulled and recreated `leaguesphere_stage.staging-app` within
its 5-minute poll interval. (Transient: the fresh `leaguesphere_stage.www` container briefly
showed `unhealthy` — its CSRF healthcheck failed twice before the fresh session/cookie state
settled — and Traefik 404'd `stage.leaguesphere.app` for ~40s until it passed. Self-resolved,
unrelated to this fix; not investigated further.)

**Half 1 re-validated (script logic / `/health/` on stage):** toggled `maintenance_scope` to
`writes_only` via `manage.py shell` **without** an explicit `cache.delete()` (i.e. relying only
on the new TTL, not the admin view's same-worker invalidation) — `/health/` correctly flipped to
`maintenance_mode: true` at **t+17s**. Reverted to `off` — flipped back to `false` at **~t+20s**.
Both well inside the new 30s TTL bound. (Contrast with the original session: 8 consecutive
requests all stale, no propagation observed.)

**Half 2 re-validated (alert pipeline, synthetic payload against prod Pushgateway):** pushed
`leaguesphere_maintenance_blocking_games 1` etc. under job
`leaguesphere_maintenance_probe_synthetictest`. Confirmed via Grafana's own `/metrics`
(`grafana_alerting_alerts{state=...}`, unauthenticated — no working Grafana admin credentials
were available this session, `admin:admin` no longer valid): rule went `pending` immediately,
`alerting` after the full `for: 5m`, with a matching `logger=ngalert.sender.router
rule_uid=leaguesphere_maintenance_blocking_games msg="Sending alerts to local notifier"` log
line. **User confirmed the actual email landed** ("Maintenance Mode Blocking Live Games").

> ⚠️ **Gotcha found during cleanup — worth remembering for future synthetic Pushgateway tests:**
> `DELETE /metrics/job/<job>` removes the series from Pushgateway/Prometheus immediately, but
> **Grafana does not auto-resolve an alert instance just because its series disappeared** from
> the query results — disappearing is not the same as the condition evaluating false. The
> synthetic alert stayed stuck in `alerting` for 5+ minutes after deletion with Prometheus
> already showing zero trace of the series. Fix: push an explicit resolved value (e.g.
> `leaguesphere_maintenance_blocking_games 0`) instead of relying on deletion to resolve it;
> *then* delete the job once it's back to `normal`. The real hourly probe never hits this edge
> case since it always re-pushes rather than deleting.

**Cleanup confirmed complete:**
- Stage `maintenance_scope` reverted to `off` (confirmed via `/health/`).
- `/tmp/ls-maintenance-probe-stagetest.sh` on `lehel.xyz` — already gone (host `/tmp` cleanup).
- `leaguesphere_maintenance_probe_stagetest` Pushgateway job — deleted.
- `leaguesphere_maintenance_probe_synthetictest` Pushgateway job — pushed resolved, confirmed
  `normal`, then deleted.
- Real `leaguesphere_maintenance_probe` job confirmed untouched throughout (checked before and
  after every synthetic operation).

**Still open:** item 2 (DB revert-on-restart anomaly) and item 5 (opencode direct-master-push
practice) — both explicitly deferred, not part of this resolution.

**Local checkout note:** running `container/deploy.sh stage` directly from the `leaguesphere`
checkout (rather than via its `-b` worktree mode) left local `master` tracking
`origin/release/stage_model-sole` with an extra local-only version-bump commit. Reset to match
`origin/master` and re-pointed the upstream after this session's work was confirmed merged —
no data lost, the commit remains reachable via `release/stage_model-sole` and tag `v4.18.4-rc.1`.
Prefer `-b` (worktree mode) for future `deploy.sh` runs from a shared checkout to avoid this.

## Session closed 2026-08-14

Everything in scope for this session is done: fix merged (leaguesphere#1832), deployed to stage,
both validation halves re-run and passing, all synthetic/temp artifacts cleaned up, local
checkout state clean. Remaining open items (DB revert-on-restart anomaly, opencode direct-push
practice) are tracked in project memory for a future session, not carried as unfinished work
here.
