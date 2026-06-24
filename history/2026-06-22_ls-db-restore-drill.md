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

**Re-run 2026-06-24:** repeated end-to-end against merged `master` (PR #24, `e38cafc`) — passed clean with **zero manual file edits**, 103 == 103, snapshot `1e7ed1f2`; confirms the fixes below are fully landed.

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

---

## Destructive full-rebuild re-run (2026-06-24)

Hardest variant of the drill: instead of simulating data loss on a live box, the **entire
`servyy-test` LXD container was destroyed and rebuilt from scratch** (`scripts/setup_test_container.sh -x`
→ fresh Ubuntu 26.04), then the LeagueSphere DB was recovered **from the offsite Storage Box
restic repo** — proving the backup survives total host loss, not just a wiped data dir.

### Result: ✅ PASSED — 0 → 103 tables, ~379k rows

| Step | Action | Result |
|------|--------|--------|
| Pre-wipe gate | confirm offsite `db` snapshots + baseline | 8 snapshots; baseline **103** base tables |
| Wipe | `setup_test_container.sh -x` | fresh blank Ubuntu 26.04 container |
| Reprovision | base + complete `ls` role | `leaguesphere.db` healthy, schema **empty (0 tables)** |
| Offsite reachability | `source /etc/restic/env.db && restic snapshots` on the rebuilt box | reachable (key + `env.db` redeployed by `restic.init`) |
| Restore | `--tags restic.restore` | `✅ RESTORED` `…/mysql-backup/current`; **operator notice fired** (DB only) |
| Copy-back | `mariadb-backup --copy-back` per the notice | `completed OK!` |
| Verify | base tables + rows | **103 tables / ~379,402 rows** (`gamedays_teamlog`=204,574) |

**Decisive numbers:** pre-restore **0** tables → post-restore **103** tables with real data. ✅

### Bugs found & fixed during this drill

Only a from-scratch host exposes these (a re-provision over existing state hides them):

1. **`restic/tasks/test_setup.yml`** — wrote `restic-test-backup.sh` into `~/.backup-scripts`
   before that dir existed (it is created later in `backup.yml`). Added a dir-create task to
   `test_setup.yml` so it is self-sufficient on a fresh host.
2. **`ls_app/templates/ls.env.j2`** — emitted `MYSQL_BACKUP_USER`/`MYSQL_BACKUP_PWD` for any app
   with `db_root_password` defined, but **stage** (`secret_stage.yaml`) has no `db_backup_user` →
   `ls.env` render failed, breaking the stage deploy. Guarded the backup-user lines with
   `{% if app.db_backup_user is defined %}`.

### Operational notes

- The notice now printed by `restore.yml` makes the **manual copy-back** unmissable: a full
  reprovision restores the backup *files* into `current/` but intentionally does NOT load them
  into the live DB (no auto-clobber). Operator must run the copy-back shown in the notice.
- `ls_db_sync` still fails on a full `ls` run while `leaguesphere.app` holds external
  `max_user_connections` (documented, environmental — not a code defect). Irrelevant to DB DR.
- Fresh LXD containers need ~1–2 min for IPv6 RA routing to settle; pulls/fetches that run too
  early (Docker Hub, prod Gitea) can transiently time out — retry, not a fault.
