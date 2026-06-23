# 2026-06-22 — LeagueSphere Local MariaDB Migration

## Problem

LeagueSphere prod was backed by an external managed MySQL instance (`s207.goserver.host`).
This created several risks:

- **No backup ownership:** database backups depended entirely on the hosting provider; no
  tested restore procedure existed within the self-hosted infrastructure.
- **Uncontrolled exposure:** the prod app reached the external host over the public internet
  via a `database`-network entry in docker-compose with no port isolation.
- **Restic coverage gap:** the external DB data fell completely outside the restic backup
  regime already in place for the server jail.
- **Stage sync latency:** `ls_db_sync` had to go out to the external host on every run;
  post-cutover it can pull from the local container directly.

## Solution

Add a self-hosted MariaDB container (`leaguesphere.db`) to the prod compose stack on an
**internal-only** Docker `backend` network (no published ports). Seed it from the external DB,
back it up with `mariadb-backup` + a dedicated hourly restic repo (`restic-ls-db`), validate
restore on `servyy-test.lxd`, then cut over by flipping a single env var (`app.db_host`).

Key design decisions:

| Decision | Rationale |
|----------|-----------|
| Internal-only `backend` network, no published ports | DB never reachable from outside the Docker stack |
| Bind mounts (not named volumes) under the jail | Named volumes fall under restic's `/var/lib/docker` exclude; bind mounts are covered |
| `mariadb-backup` (physical, prepared) | Crash-consistent; version-matched because it runs inside the container |
| Dedicated restic repo `restic-ls-db` | Separate encryption key; independent retention from filesystem backups |
| `mysqldump` for seed and stage sync, `mariadb-backup` for DR | `mysqldump` is logical/portable; `mariadb-backup` is fast/safe for physical restore |
| Single-var cutover (`app.db_host`) | Local DB reuses same `db_name`/`db_user`/`db_password`; minimal blast radius |
| 14-day external-DB retention post-cutover | Rollback window without immediate decommission pressure |

## Files Changed

### `leaguesphere` repo (branch `feature/local-mariadb-prod-db`)

| File | Change |
|------|--------|
| `deployed/docker-compose.yaml` | Added `db` service (MariaDB, internal `backend` network, bind mounts `mysql-data` + `mysql-backup`); moved `app` onto `backend`; added `depends_on: db: condition: service_healthy`; removed `database` network |
| `deployed/mysql-init/01-create-staging-db.sh` | Optionally creates a dedicated `mariadb-backup` user when `MYSQL_BACKUP_USER` env var is set (guarded so stage, which doesn't set it, is unaffected) |

Commits (leaguesphere repo):
- `2291cb1d` — feat(prod): add internal-only mariadb db service, drop external db network
- `359c29d6` — feat(db-init): optionally create mariadb-backup user

### `container` repo (branch `feature/leaguesphere-local-mariadb-migration`)

| File | Change |
|------|--------|
| `ansible/plays/roles/ls_app/vars/secret_main.yaml` | Added `db_root_password`, `db_backup_user`, `db_backup_password` for prod (git-crypt encrypted) |
| `ansible/plays/roles/ls_app/templates/ls.env.j2` | Emit `MYSQL_BACKUP_USER` / `MYSQL_BACKUP_PWD` when `db_root_password` is defined |
| `ansible/plays/roles/ls_app/tasks/deploy.yaml` | Generalised DB-init dance from stage-only to any app with its own DB container; prod DB container is `leaguesphere.db`, stage keeps `.mysql` |
| `ansible/plays/roles/ls_db_migrate/` (new role) | Seeds local prod container from external DB via `mysqldump`; re-runnable; tag `ls.db.migrate` |
| `ansible/plays/leaguesphere.yml` | Wired `ls_db_migrate` role under tag `ls.db.migrate` |
| `ansible/plays/roles/restic/templates/mariadb_backup.sh.j2` (new) | In-container `mariadb-backup` → prepared `current/` set script |
| `ansible/plays/roles/restic/tasks/backup.yml` | Deploy `mariadb-backup-ls.sh` + systemd timer; deploy `restic-backup-ls-db.sh` + timer |
| `ansible/plays/vars/restic.yml` | Added `restic.db` block (repository, password, source path, schedules) |
| `ansible/plays/roles/restic/tasks/init.yml` | Extended loops for `db` repo: env file, sftp mkdir, repo init |
| `ansible/plays/roles/restic/tasks/main.yml` | Added restore include for `db` repo path (env-aware, skips on healthy/populated) |
| `ansible/plays/roles/ls_db_sync/defaults/main.yml` | Added `ls_db_sync_source` toggle (`external` | `local`) and `ls_db_sync_local_container` |
| `ansible/plays/roles/ls_db_sync/tasks/main.yml` | Branched export task: external path uses `mysqldump` against remote host; local path uses `mariadb-dump` via `docker exec` |

Commits (container repo):
- `c496c80` — feat(ls): prod db container creds + backup-user env
- `271d275` — feat(ls_app): run own DB container for prod, not just stage
- `c18c95d` — feat(ls_db_migrate): seed local prod db from external via mysqldump
- `8f8c488` — fix(ls_db_migrate): run as root like ls_db_sync (drop become_user so apt works)
- `de23353` — feat(restic): mariadb-backup prepared-set timer for prod db
- `44d929a` — fix(restic): no_log on mariadb-backup script deploy to avoid leaking db backup password
- `0363c49` — feat(restic): dedicated hourly repo for leaguesphere prod db backup
- `b98d58c` — fix(restic): use lookup('password') for restic_password_ls_db like sibling repos
- `eea3dd1` — feat(restic): env-aware restore wiring for leaguesphere prod db
- `94c979c` — feat(ls_db_sync): source toggle external|local for shadow validation

## Test-First Deployment Approach

All code changes were validated on `servyy-test.lxd` before any prod deployment:

1. Compose syntax validated locally (`docker compose config -q`).
2. Prod stack (`ls.app.prod`) deployed to `servyy-test.lxd` — verified `leaguesphere.db`
   healthy and no published ports.
3. `ls_db_migrate` run on test — verified table count matches external DB.
4. `mariadb-backup` timer deployed and run once on test — verified prepared set at
   `mysql-backup/current/` contains `xtrabackup_checkpoints`.
5. Restic repo initialised and first snapshot taken on test.
6. `ls_db_sync` validated with `ls_db_sync_source=local` on test (stage pulled from local
   prod container rather than external).
7. Restore drill (Task 10) — see below.

## Restore Drill (Task 10)

> STATUS: PENDING — restore drill on `servyy-test.lxd` has not been executed yet.
> Complete Task 10 and record the outcome here before proceeding to Task 11 (prod cutover).
>
> Record: snapshot ID used, pre-loss and post-restore table counts, pass/fail.

## Production Cutover (Task 11)

> STATUS: PENDING — prod cutover requires explicit user approval and has not run yet.
> Once complete, record: cutover date/time, final delta row counts, smoke-test results,
> maintenance window duration.

## Verification Commands

```bash
# Verify db container is healthy and has no published ports
ssh lehel.xyz "docker inspect -f '{{.State.Health.Status}}' leaguesphere.db"
ssh lehel.xyz "docker port leaguesphere.db || echo NO_PORTS"

# Verify app is pointing at the local container post-cutover
ssh lehel.xyz "docker exec leaguesphere.app sh -c 'env | grep MYSQL_HOST'"
# Expected post-cutover: MYSQL_HOST=leaguesphere.db

# Check restic snapshots for the db repo
ssh lehel.xyz "sudo bash -c 'source /etc/restic/env.db && restic snapshots --latest 3'"

# Run a manual mariadb-backup
ssh lehel.xyz "systemctl --user start mariadb-backup-ls.service"
ssh lehel.xyz "ls -la /var/jail/home/leaguesphere/container/mysql-backup/current/ | head"
```

## Rollback Procedure

If the cutover must be reversed (within the 14-day retention window):

1. Revert `app.db_host` to `s207.goserver.host` in
   `container/ansible/plays/roles/ls_app/vars/secret_main.yaml`.
2. Redeploy the prod app stack:
   ```bash
   cd container/ansible
   ./servyy.sh --tags ls.app.prod --limit lehel.xyz
   ```
3. Verify the app is back on the external host:
   ```bash
   ssh lehel.xyz "docker exec leaguesphere.app sh -c 'env | grep MYSQL_HOST'"
   # Expected: MYSQL_HOST=s207.goserver.host
   ```

The `leaguesphere.db` container can be left running (it will continue accumulating backups)
or stopped with `docker compose -p leaguesphere stop db` — it does not affect the rolled-back
app since `app.db_host` now points away from it.

## Decommission (14-day retention)

The external DB (`s207.goserver.host` / `web35_db8`) is retained for **14 days** post-cutover
as a rollback safety net. After that window it may be dropped.

Decommission on/after **actual cutover date + 14 days** (e.g. if cutover lands 2026-06-23 → decommission 2026-07-07). STATUS: PENDING — set the concrete date once Task 11 cutover completes.

Decommission checklist (separate change, out of scope for this PR):
- [ ] Remove `external` branch of `ls_db_sync` (the `when: ls_db_sync_source == 'external'` task).
- [ ] Remove external DB creds (`db_host`, `db_user`, `db_password` pointing at `s207.goserver.host`) from `secret_main.yaml`.
- [ ] Drop the external DB via the hosting provider control panel.
- [ ] Update `leaguesphere-environments.md` to remove all references to the external host.

## Known Issues / Follow-ups

- The `ls_db_migrate` role runs `apt install default-mysql-client` on every invocation
  (idempotent, but noisy). Consider caching or pre-installing in the base image.
- `mariadb-backup` timer fires at `:40` (20 min before the hourly restic run at `:00`).
  Adjust `restic.schedules.backup_ls_db_dump` if the backup window needs tuning.
- Stage DB sync (`ls_db_sync`) defaults to `external` until the cutover commit flips the
  default. The `ls_db_sync_source` override flag (`-e ls_db_sync_source=local`) can be used
  in the interim to validate the local-source path.
