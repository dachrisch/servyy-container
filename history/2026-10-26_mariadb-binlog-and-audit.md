# MariaDB binlog + statement audit (LeagueSphere prod DB)

**Date:** 2026-10-26
**Status:** ⚠️ **PREPARED — NOT YET DEPLOYED.** The changes below are opened as PRs and verified
read-only against the running host. The `db` container has **not** been restarted, so prod still
runs with `log_bin = OFF` and no audit plugin. Update this entry (status, timings, drill result)
after the maintenance window.

| Repo | Change | PR |
|---|---|---|
| `leaguesphere` | `deployed/mysql-conf/zz-binlog-audit.cnf` + mounts in both compose files + CI scope entry | #2092 |
| `servyy-container` | this entry, the plan, the environments doc (audit/PITR runbook) | (this PR) |

## Summary

Prod's MariaDB gains two capabilities, from one config file and **one** container restart:

1. **Binary logging** — `ROW` format, `FULL` row images, annotated row events, `sync_binlog=1`,
   256 M rotation, **2-day** retention. Gives point-in-time recovery to the second instead of the
   hour.
2. **The MariaDB audit plugin** (`server_audit.so`, already present in the image) — `CONNECT` +
   `QUERY_DML_NO_SELECT` events, with the application account excluded, so the log records the
   humans who connect rather than constant Django traffic.

No Ansible change. The config belongs beside the compose file it is mounted from, following the
existing `mysql-init/` precedent.

## Reason

Two questions had no answer before this change:

| Question | Before | After |
|---|---|---|
| "A wrong `UPDATE` landed at 14:31 — get the rows back from 14:30" | hourly prepared set only, up to 1 h lost, full-DB restore | restore + replay binlog to `14:30:59`, lift the rows out |
| "Who ran it?" | nothing — no binlog, no audit, no general log | `server_audit.log`: user, host, timestamp, statement |

It also matters for the rev. 3 temporary-access design
(`docs/plans/2026-10-25-prod-db-temp-credentials.md`), where the web app's `dbaccess_event` table
was the *only* record of who held access. A record the app can rewrite is a weak control; a
binlog that has already been snapshotted is not.

## Evidence gathered before writing any config (read-only, 2026-10-26)

| Probe | Result | Consequence |
|---|---|---|
| `SET GLOBAL log_bin=ON` | **`ERROR 1238 — Variable 'log_bin' is a read only variable`** | restart is unavoidable; do both features in one window |
| `/etc/mysql/conf.d` mount | none (`mysql-init`, `mysql-data`, `mysql-backup` only) | needs a compose change → `db` is recreated |
| `/etc/mysql/conf.d` content | **empty**, and included by `/etc/mysql/my.cnf` | a directory mount hides nothing |
| `docker-entrypoint.sh` writes into `conf.d`? | no | safe to mount read-only |
| `mariadb.conf.d/50-server.cnf` | `log_bin` commented out | no conflict; our file also loads later and wins |
| `binlog_format` / `binlog_row_image` / `binlog_annotate_row_events` | **`ROW` / `FULL` / `ON`** (already) | the image's defaults were already what PITR and forensics want |
| `mariadb-backup --binlog` | present, **defaults to on** | the hourly set starts carrying binlogs with no backup-script change |
| restic `ls-db` scope | `…/mysql-backup/current` only | binlogs reach the Storage Box *through* the set, not from the datadir |
| restic `root` scope | daily, `/var` included, `/var/log` excluded | the audit file in the datadir gets a daily off-host copy |
| write volume (60 s sample) | 160 queries, 0 writes, ~2 KB/s | binlog growth is small and bursty (gameday weekends) |
| disk | **11 GB free, 86 % used** | retention is a disk decision: 2 days, not the default 10 |
| data size | prepared set **251 MB** | every hourly snapshot grows by the binlog it carries |

## Detailed changes

### `leaguesphere` — `deployed/mysql-conf/zz-binlog-audit.cnf` (new)

```ini
[mysqld]
server_id                  = 1
log_bin                    = /var/lib/mysql/binlog
binlog_format              = ROW
binlog_row_image           = FULL
binlog_annotate_row_events = ON
sync_binlog                = 1
max_binlog_size            = 256M
expire_logs_days           = 2

plugin_load_add               = server_audit
server_audit_events           = CONNECT,QUERY_DML_NO_SELECT
server_audit_excl_users       = web35_8,leaguesphere_stage
server_audit_output_type      = file
server_audit_file_path        = /var/lib/mysql/server_audit.log
server_audit_file_rotate_size = 50M
server_audit_file_rotations   = 9
server_audit_timestamp_format = %Y-%m-%d %H:%M:%S
```

Design notes worth keeping:

- **`zz-` prefix** — `my.cnf` includes `mariadb.conf.d/` before `conf.d/`; a later file wins.
- **Directory mount, not a single file** — `git pull` replaces files by rename, which leaves a
  file bind-mount reading a dead inode.
- **Restart semantics are *not* obvious**: mysqld reads the file only at startup, and a deploy
  does **not** recreate `db` when only the file content changes (the service definition is
  unchanged, so `recreate: auto` sees no diff). After editing: `up -d --force-recreate db`.
- **Two application accounts excluded** so the same file is valid on prod (`web35_8`) and on
  stage/test (`leaguesphere_stage`).

### `leaguesphere` — compose mounts

`deployed/docker-compose.yaml` (`db`) and `deployed/docker-compose.staging.yaml` (`mysql`) each
gain one read-only directory mount:

```yaml
      - "./mysql-conf:/etc/mysql/conf.d:ro"
```

### `leaguesphere` — `.circleci/scope-exclude.txt`

`deployed/mysql-conf/.*`, next to the existing `deployed/mysql-init/.*`. A `.cnf` runs no test
suite; without the entry the always-on `scope-coverage` job fails the PR.

### `servyy-container` — documentation

- `docs/plans/2026-10-26-mariadb-binlog-and-audit.md` — the plan, the PITR drill, the rollout.
- `docs/leaguesphere-environments.md` — "Reading the DB audit trail", "Point-in-time recovery",
  the backup-design bullet, the DR warning that `current/` now contains binlogs, and the note
  that both restic repos now carry user data.
- `docs/plans/2026-10-25-prod-db-temp-credentials.md` — baseline row corrected: the "no SQL
  audit / no PITR" fact is now annotated as being closed by this work.

## Verification performed (no prod change)

- `python3 scripts/check_scope_coverage.py` → `OK: 1746 tracked files covered by 74 job rules + 40 ignore rules`.
- `docker compose -f docker-compose.yaml config --quiet` and the staging file → exit 0.
- CI's `run-compose` job brings the stack up **including `db`**, so a config that stops `mysqld`
  from starting fails the PR rather than prod.
- All host probes above were read-only (`SHOW VARIABLES`, `docker inspect`, `docker exec ls/grep`).

**Not yet verified (belongs to the window):** that `mysqld` starts with `plugin_load_add`, that a
write produces a binlog event, that the next `:40` prepared set carries the binlogs, and the PITR
drill itself. The plan rehearses the first on `servyy-test.lxd` (Task 1) and the last on the test
host (Task 5) before prod is touched.

## Impact assessment

| | |
|---|---|
| **App behaviour** | unchanged; no code, no query, no schema |
| **Downtime** | one `db` recreate in the window; app returns 5xx for the restart plus the healthcheck `start_period` (~90 s) |
| **Disk** | binlogs in the datadir (2-day retention, 256 M rotation) **and** inside every hourly prepared set → restic snapshots grow. The host is at 86 %; re-check after a gameday weekend |
| **Commit latency** | `sync_binlog=1` adds one fsync per commit. At ~160 queries/min this is invisible; revisit only if commit latency shows up |
| **Backups** | the prepared set now contains `binlog.00000N` + `xtrabackup_binlog_info`. A copy-back copies that timeline into the datadir — harmless, but end-of-timeline, not a replay |
| **Data handling** | both new files contain literal values from the DB → the Storage Box now holds user data |
| **Timers** | untouched (`mariadb-backup-ls`, `restic-backup-ls-db`) |

## Rollback

| Component | How |
|---|---|
| The whole change | remove the `./mysql-conf` mount from the compose file, deploy → `db` restarts without it |
| Audit plugin only | `UNINSTALL SONAME 'server_audit'` at runtime, or drop `plugin_load_add` and restart once |
| Leftover binlogs | harmless; `PURGE BINARY LOGS BEFORE NOW()` or delete once a prepared set has been archived |
| Bad PITR attempt | rehearsed only in a scratch container; prod is never restored over, only replayed into |

## Next steps

1. Merge PR #2092 → the host pulls `master` on the next deploy (no behaviour change until the restart).
2. Rehearse on `servyy-test.lxd` (plan Task 1) — this is the `plugin_load_add` safety check.
3. Maintenance window: fresh prepared set → deploy → verify (plan Tasks 3–4).
4. Run the PITR drill and record the timings here (plan Task 5).
5. Decide: log reads too (`QUERY_DML` instead of `_NO_SELECT`)? hourly restic coverage for the
   audit file? both are open decisions in the plan.
6. Add or confirm a disk alert below 90 % — this change is the first thing on this host that grows
   with write volume.
