# 2026-07-08 — LeagueSphere Phase B cutover: prod DB external → local MariaDB

## Status

**DONE on prod (`lehel.xyz`) 2026-07-08.** Prod LeagueSphere now runs on the self-hosted local
`leaguesphere.db` MariaDB container (db `web35_db8`), off the legacy external managed MySQL
(`s207.goserver.host`). App healthy, fresh data, `RUN_MIGRATIONS=true` (migrate-on-start) live.
External host retained as a rollback net until **2026-07-22** (cutover + 14 days).

## Problem

Phase A (2026-06-25) stood up `leaguesphere.db` beside the live app and seeded it, but the app
stayed on the external DB. Phase B — the actual cutover — remained pending. Two blockers had to
clear first:

1. **A latent landmine in `ls_db_migrate`.** The cutover flips `secret_main.yaml` `app.db_host`
   → `leaguesphere.db`. `ls_db_migrate` (the "seed local prod DB **from external**" role) used
   `app.db_host` as its dump *source*, so post-flip it would dump the local container into itself
   instead of pulling from `s207` — and if that self-dump were empty/partial, its
   `DROP DATABASE` + import could wipe the local prod DB. `ls_db_sync` had already been decoupled
   via `ls_db_sync_external_host`; `ls_db_migrate` never got the equivalent fix.
2. **The external host had been flaky** (DDoS-era connection resets, stalled dumps), so a fresh
   external pull at cutover time was a risk. A good fresh dump had already been landed into the
   **stage** DB (`leaguesphere_stage`) via `ls_db_sync` (external source), giving a trustworthy
   local copy of current prod data.

## Solution / method

**Fix first (PR #37 → master):** added `ls_migrate_external_host` (default `s207.goserver.host`)
to `ls_db_migrate` and pointed the export at it, independent of the cutover-mutated `app.db_host`
— mirroring `ls_db_sync_external_host`. Syntax-checked; merged.

**Cutover (full-downtime window), seeding from the stage copy** to avoid another external pull:

1. **Offline:** `docker compose -p leaguesphere stop app www` (in `…/container/deployed`).
2. **Seed** `web35_db8` ← stage `leaguesphere_stage`, safe-ordered: `mariadb-dump` stage (ignore
   views) → verify complete (size + `-- Dump completed` marker) **before** any DROP → DROP/recreate
   `web35_db8` → import.
3. **Verify parity** against the fresh source.
4. **Deploy:** `./servyy.sh --syntax-check && ./servyy.sh --tags ls.app.prod --limit lehel.xyz` —
   regenerated env (now `RUN_MIGRATIONS=true`), recreated app/www online on the local DB,
   migrate-on-start.
5. **Verify** maintenance off + smoke tests.
6. **Baseline backup:** triggered `mariadb-backup-ls.service` then `restic-backup-ls-db.service`.

## Results

| Step | Outcome |
|------|---------|
| `ls_db_migrate` fix (PR #37) | ✅ merged to master (`ab7552b`); syntax-check PASS |
| Stage dump (source) | ✅ 30.5 MB, complete marker present |
| Reseed `web35_db8` | ✅ DROP/create OK, import rc=0 |
| Parity (target after seed) | ✅ **104 tables, 342 users, migration head 139**, `gamedays_resourceurl` present (was 103/341/138 stale, 2026-06-25) |
| `ls.app.prod` deploy | ✅ RECAP `ok=36 changed=5 failed=0` |
| App state | ✅ `leaguesphere.app` healthy, `MYSQL_HOST=leaguesphere.db`, `RUN_MIGRATIONS=true` |
| Migrate-on-start | ✅ "No migrations to apply" (seed matched image head) |
| Maintenance mode | ✅ `SiteConfiguration.maintenance_mode=0` (site live) |
| Reads | ✅ home `200`, `/api/gamedays/` `200` |
| Writes | ✅ `web35_8@%` has `ALL PRIVILEGES ON web35_db8` (grants survive DROP/recreate) |
| App error log | ✅ clean |
| Baseline backup | ✅ `mariadb-backup` + restic `success`; new snapshot `bb4542a9` @ 13:23 (178.4 MiB) |

## Files changed

- `ansible/plays/roles/ls_db_migrate/defaults/main.yml` — add `ls_migrate_external_host`.
- `ansible/plays/roles/ls_db_migrate/tasks/main.yml` — export sources from `ls_migrate_external_host`.
- `docs/leaguesphere-environments.md`, `docs/leaguesphere-cutover-checklist.md` — status → DONE.
- (No app-DB config change here beyond what was already on master: `app.db_host=leaguesphere.db`,
  `RUN_MIGRATIONS=true` from #35.)

## Verification commands

```bash
# App on local DB + migrations flag
ssh lehel.xyz "docker exec leaguesphere.app sh -c 'env | grep -E \"MYSQL_HOST|RUN_MIGRATIONS\"'"
# Data parity
ssh lehel.xyz 'docker exec leaguesphere.db sh -c '\''mariadb -h127.0.0.1 -uroot -p"$MYSQL_ROOT_PASSWORD" -N web35_db8 -e "SELECT COUNT(*) FROM auth_user; SELECT MAX(id) FROM django_migrations;"'\'''
# Site serves
ssh lehel.xyz "curl -sS -o /dev/null -w '%{http_code}\n' https://leaguesphere.app/api/gamedays/"
# Baseline snapshot
ssh lehel.xyz "sudo bash -c 'source /etc/restic/env.db && restic snapshots --tag db --no-lock | tail -3'"
```

## Known issues / gotchas

- The `leaguesphere.db` container env still carries `MYSQL_HOST=s207…`, so ad-hoc
  `docker exec leaguesphere.db mariadb …` must pass `-h 127.0.0.1` or it chases the dead host.
- Maintenance mode is a **DB-backed** flag (`league_manager_siteconfiguration.maintenance_mode`,
  cached `site_maintenance_config`) — reseeding overwrites it with the source's value; the
  container restart clears the in-process cache. Post-seed value here was `0` (live).
- Retained safety dump on host: `/tmp/ls_fresh_seed_1783509389.sql` — clean up once confident.

## Follow-ups

- Flip `ls_db_sync_source` default → `local` in `ls_db_sync/defaults/main.yml`.
- Decide old cutover PR #34 (`database`→`egress` net rename) — still OPEN; app healthy over
  `backend`, so optional hardening.
- Optional authenticated write smoke (login → create/edit) — needs real creds.
- Decommission external `s207.goserver.host` on/after **2026-07-22**.
