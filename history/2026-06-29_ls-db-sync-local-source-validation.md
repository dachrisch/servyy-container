# 2026-06-29 — Validate `ls_db_sync` local-source path on prod (full cycle)

## Status

**Done on prod (`lehel.xyz`) 2026-06-29.** Proved end-to-end that `ls_db_sync` with
`ls_db_sync_source=local` clones the **stage** DB from the new self-hosted prod container
`leaguesphere.db` (not the legacy external host `s207.goserver.host`). Non-disruptive: prod app
untouched, still on external DB. Phase B cutover remains pending/approval-gated.

## Problem

Since the local MariaDB migration, `ls_db_sync` gained a source toggle (`ls_db_sync_source`:
`external` | `local`, default `external`). The `local` path
(`ansible/plays/roles/ls_db_sync/tasks/main.yml:34-44`) had never been exercised end-to-end
against a real prod target. We wanted to confirm the stage actually pulls from the new
`leaguesphere.db` container — and that the data genuinely originates there, not from external.

## Solution / method

A marker-based full cycle that makes the data source unambiguous:

1. **Update the prod DB** — write a unique sentinel into `leaguesphere.db` only:
   table `web35_db8._sync_test_marker`, token `fullcycle-20260628T231225Z-3827`.
2. **Sync the stage** — `./servyy.sh --tags ls.db.sync -e ls_db_sync_source=local --limit lehel.xyz`.
3. **Verify** — the marker (which exists nowhere but the local container) appears in
   `leaguesphere_stage._sync_test_marker` ⟹ stage was sourced from local.
4. **Cleanup** — drop the marker table from both prod and stage.

## Results

| Step | Outcome |
|------|---------|
| Marker write into `leaguesphere.db` (`web35_db8`) | ✅ row present |
| `ls_db_sync` run (`ls_db_sync_source=local`) | ✅ `EXIT 0`, `ok=22 changed=7`; **LOCAL** export task `changed`, **EXTERNAL** task `skipping` |
| Marker present in stage (`leaguesphere_stage`) | ✅ exact token + timestamp (`2026-06-28 23:13:25`) |
| Cleanup (drop from prod + stage) | ✅ both gone |
| Prod app DB target after run | `MYSQL_HOST=s207.goserver.host` (unchanged — cutover not triggered) |
| Container health | all `leaguesphere*` healthy; only `leaguesphere_stage.staging-app` restarted (role does this) |

## Known issue / gotcha (role is fine; ad-hoc is not)

The `leaguesphere.db` container's env sets `MYSQL_HOST=s207.goserver.host`, which the in-container
mysql/mariadb **client** inherits as its default host. An ad-hoc
`docker exec leaguesphere.db mariadb -u <user> ...` therefore tries to reach **external** s207
(fails from inside the container: `ERROR 2005 Unknown server host 's207.goserver.host'`).
The `ls_db_sync` role's `local` tasks were **not** affected — the run resolved to the local
server and the marker proves local origin. Rule of thumb for manual queries against the local
prod DB: **always pass `-h 127.0.0.1`** (and read the password from the container env, e.g.
`sh -c 'mariadb -h 127.0.0.1 -u root -p"$MYSQL_ROOT_PASSWORD" ...'`).

## No files changed

Validation only — no code or config modified. `ls_db_sync_source` default stays `external`
until Phase B cutover.

## Verification commands

```bash
# 1. marker into local prod db (connect to LOCAL server explicitly)
ssh lehel.xyz "docker exec leaguesphere.db sh -c 'mariadb -h 127.0.0.1 -u root \
  -p\"\$MYSQL_ROOT_PASSWORD\" web35_db8 -e \"CREATE TABLE IF NOT EXISTS _sync_test_marker \
  (id INT PRIMARY KEY, note VARCHAR(255), created_at DATETIME); \
  REPLACE INTO _sync_test_marker VALUES (1, \\\"<token>\\\", NOW());\"'"

# 2. sync stage from local source
cd container/ansible && ./servyy.sh --tags ls.db.sync -e ls_db_sync_source=local --limit lehel.xyz

# 3. confirm marker reached stage
ssh lehel.xyz "docker exec leaguesphere_stage.mysql sh -c 'mariadb -h 127.0.0.1 -u root \
  -p\"\$MYSQL_ROOT_PASSWORD\" leaguesphere_stage -e \"SELECT * FROM _sync_test_marker;\"'"

# 4. cleanup (both DBs)
# DROP TABLE IF EXISTS _sync_test_marker;  in web35_db8 and leaguesphere_stage
```

## Success criteria (all met)

- [x] `local` export task runs, `external` skips
- [x] Stage contains the local-only marker after sync
- [x] Prod app stays on external DB; no prod app/db recreation
- [x] Marker removed from both DBs afterward

## Next

- Real Phase B cutover (migration plan Task 11 Phase B) — flip `app.db_host` →
  `leaguesphere.db` + `database`→`egress` net rename, in a maintenance window, approval-gated.
  Once cut over, `ls_db_sync_source=local` becomes the natural default.

See also: `history/2026-06-25_leaguesphere-phase-a-prod.md`,
`history/2026-06-25_decouple-db-standup-validation.md`,
`docs/leaguesphere-environments.md`.
