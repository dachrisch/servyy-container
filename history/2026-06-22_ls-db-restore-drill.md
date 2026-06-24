# LeagueSphere Prod DB — Restore Drill (servyy-test.lxd)

**Date executed:** 2026-06-23 (plan dated 2026-06-22)
**Environment:** `servyy-test.lxd` (isolated LXD test box — test only, no production touched)
**Plan:** `docs/superpowers/plans/2026-06-22-leaguesphere-local-mariadb-migration.md` (Task 10)

## Scope

Full end-to-end validation of the local-MariaDB migration on the test box: stand up the
prod-config stack, seed external→local, take a `mariadb-backup` prepared set, snapshot it to
the dedicated restic repo, confirm restore-skips-on-healthy, then simulate data loss and
restore from restic.

## Result: ✅ DRILL PASSED

| Step | Action | Result |
|------|--------|--------|
| Task 4 S5 | `./servyy-test.sh --tags ls.app.prod` | `leaguesphere.db` healthy, **no published ports**, `SHOW DATABASES` lists the prod db |
| Task 5 S5 | `./servyy-test.sh --tags ls.db.migrate` | seed OK — **103 base tables** (pre-loss baseline) |
| Task 6 S3 | `./servyy-test.sh --tags restic.backup` + run unit | `mysql-backup/current/` holds prepared set (`ibdata1`, `mariadb_backup_checkpoints`, db dir) |
| Task 7 S5 | `./servyy-test.sh --tags restic.init,restic.backup` + run unit | snapshot `fb13731d` (176 MiB) in repo `db` for `servyy-test.lxd` |
| Task 8 S3 | `./servyy-test.sh --tags restic.restore` | ⏭️ correctly SKIPS on healthy host (target dir non-empty) |
| Task 10 | simulate loss → `restic.restore` → `mariadb-backup --copy-back` → start | db healthy, **103 tables** restored |

**Decisive numbers:** pre-loss **103** tables == post-restore **103** tables. ✅

## Bugs found & fixed during the drill (container repo)

The drill surfaced four real defects that would have broken the prod cutover; all fixed and
re-validated by completing the drill:

1. **`ls_db_migrate/tasks/main.yml`** — the in-container `mariadb` calls lacked `-h localhost`.
   The container's `MYSQL_HOST` env still points at the external host, so the client dialed
   the wrong server. Added `-h localhost` to the drop/recreate and import tasks.
2. **`restic/tasks/backup.yml`** — `ls_backup_host_dir` missing the `deployed/` path component.
3. **`vars/restic.yml`** — `restic.db.source_path` missing `deployed/`.
4. **`restic/tasks/main.yml`** — DB `restore_path` (and the recovery comment block) missing
   `deployed/`.

The real host path is `/var/jail/home/leaguesphere/container/**deployed**/mysql-backup` (the
compose bind mounts resolve relative to the `deployed/` directory). The plan's Global
Constraints stated the path without `deployed/`, which propagated into the code.

## Operational notes for the prod cutover (Task 11)

- **External DB connection limit:** the external shared MySQL (`s207.goserver.host`) enforces a
  tight `max_user_connections`. Running `ls.db.migrate` while `leaguesphere.app` is connected to
  the external DB can exhaust it. The cutover's maintenance window (read-only, app stopped)
  before the final delta seed naturally frees these connections. On the test box, stop
  `leaguesphere.app` before `ls.db.migrate`.
- **`restic.restore` on the test box** requires the test restic repo to be initialized with at
  least one snapshot (`./servyy-test.sh --tags restic.test` + a test backup) first, otherwise an
  earlier service's restore task fails before the DB restore is reached. Test-bootstrap only —
  not a production concern.

## Verification commands

```bash
# table count (baseline + post-restore)
ssh servyy-test.lxd "docker exec leaguesphere.db mariadb -h localhost -u root -p<root> -N -e \
  'SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=\"<db_name>\" AND table_type=\"BASE TABLE\";'"
# snapshot list
ssh servyy-test.lxd "sudo bash -c 'source /etc/restic/env.db && restic snapshots'"
```
