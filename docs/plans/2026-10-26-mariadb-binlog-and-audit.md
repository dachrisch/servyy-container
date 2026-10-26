# MariaDB binlog + audit — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn on binary logging and the MariaDB audit plugin on the prod database, so that (a) a bad `UPDATE` can be recovered to the second instead of the hour, and (b) "who ran which statement, when" is recorded somewhere the web app cannot rewrite. One config file, **one** `db` container restart, no schema change.

**Architecture:** A single extra config file mounted into `/etc/mysql/conf.d`, enabling `log_bin` (ROW format, already the default here) and `plugin_load_add=server_audit` with the **app user excluded** so the log holds humans, not Django. Binlogs stay in the datadir and are swept into the existing hourly `mariadb-backup` prepared set by `--binlog`, which MariaDB already enables by default. Audit lines land in the datadir and reach the off-host restic repo on the daily `root` snapshot.

**Tech Stack:** MariaDB 13.0.2 (`mariadb:latest` container `leaguesphere.db`), `mariadb-backup`, `mariadb-binlog`, `server_audit` plugin (present in the image), Docker Compose (leaguesphere repo), restic (`root` + `ls-db` repos), systemd user timers.

---

## Verified baseline (2026-10-26, read from the running host)

| Fact | Value | Why it matters |
|---|---|---|
| `log_bin` | `OFF` | no PITR today; `mariadb-backup --binlog` is currently a no-op |
| `SET GLOBAL log_bin=ON` | **`ERROR 1238 — Variable 'log_bin' is a read only variable`** | it cannot be switched on at runtime; a restart is unavoidable |
| `binlog_format` | **`ROW`** (already) | row images, no statement replay ambiguity |
| `binlog_row_image` / `binlog_annotate_row_events` | **`FULL`** / **`ON`** (already) | before/after values *and* the statement text annotated onto row events |
| `expire_logs_days` / `max_binlog_size` / `sync_binlog` | `10` / `1 GB` / `0` | retention is too long for this disk; durability needs `sync_binlog=1` |
| `server_audit.so` | **present**, not installed | `SELECT … FROM information_schema.PLUGINS` returns no audit row |
| Audit plugin options in this build | `server_audit_incl_users`, **`server_audit_excl_users`**, `…file_rotate_size`, `…file_rotations`, `…timestamp_format`, `…last_error`, `…writes_failed` | the exclusion filter is what keeps the log usable |
| Audit event types | `CONNECT`, `QUERY`, `TABLE`, `QUERY_DDL`, `QUERY_DML`, `QUERY_DML_NO_SELECT` | writes-only vs everything is a one-word choice |
| `mariadb-binlog` | present (`/usr/bin/mariadb-binlog`) | the restore side of PITR needs it in the container |
| Container mounts | `mysql-init` (ro), `mysql-data` (rw), `mysql-backup` (rw) — **no `/etc/mysql/conf.d`** | adding one means a compose change → `db` is recreated |
| `/etc/mysql/conf.d` in the image | **empty** | a *directory* bind-mount hides nothing |
| Data / write volume | prepared set **251 MB**; **160 queries/min**, ~2 KB/s out, 0 writes in a sampled minute | binlog volume will be small and bursty (gameday weekends) |
| Disk | **11 GB free of 75 GB — 86 % used** | the retention choice is a disk decision, not just a policy one |
| Existing backup | user timer `mariadb-backup-ls` at `:40` → `mariadb-backup --backup --target-dir=/backup/new` (no `--skip-binlog`) → `--prepare` → swap to `current/`; restic `ls-db` repo, hourly, `source_path=…/mysql-backup/current` | PITR coverage comes for free once binlogs exist |
| restic `root` repo | daily, `source_path=/`, includes `/var`, excludes `/var/log` | the datadir (and therefore the audit file) gets a **daily** off-host copy |
| Cross-env restore rule | copy-back carries the source's `mysql` system DB; the repo uses temp-container → `mysqldump` → import | the drill must not copy-back into anything that matters |

**Environment note:** `ansible-playbook` is not on `PATH` in this checkout; every `./servyy.sh` / `./servyy-test.sh` line must run on the machine that has the toolchain. The read-only `ssh servy.lehel.xyz "docker exec …"` probes do work from here.

---

## What this buys, and what it deliberately does not

| Question | Answer after this plan |
|---|---|
| "A wrong `UPDATE` was committed at 14:31 — can we get the rows back from 14:30?" | **yes** — restore the prepared set, replay binlog to `14:30:59`, lift the rows out |
| "Who ran that `UPDATE`?" | **yes** — `server_audit.log`, `user@host` + timestamp + statement |
| "Which rows did it change, before and after?" | **yes** — `mariadb-binlog --base64-output=DECODE-ROWS -v`, joined to the audit line by statement + time |
| "Can I query that history in SQL?" | **no** — not without triggers or system-versioned tables (explicitly out of scope, see non-goals) |
| "Did the web app write this row?" | **by design no** — `web35_8` is excluded; Django traffic would drown the log |

**Non-goals:** replication or a second server, a CDC pipeline (Debezium/Kafka), per-table triggers, system-versioned tables, logging the app user's DML, and any change to the application.

---

## Design decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **One restart, both features** | `log_bin` cannot be set at runtime (`ERROR 1238`); the audit plugin's persistence needs the same config file. Splitting them means two outages for one change |
| D2 | **Leave `binlog_format=ROW`, `binlog_row_image=FULL`, `binlog_annotate_row_events=ON` alone** | they are already the values PITR and forensics want — the plan adds nothing here, and says so rather than "setting" defaults |
| D3 | **`sync_binlog=1`** | an audit trail that can lose the last second of commits is not an audit trail. At 160 queries/min the fsync cost is invisible; revisit only if commit latency shows up in the app |
| D4 | **`expire_logs_days=2`, not 10** | the PITR window *is* the retention window, and every binlog file is copied into **every** hourly prepared set. Two days keeps both the datadir and each restic snapshot bounded; older recovery falls back to snapshot-only, which is what we have today anyway |
| D5 | **Binlogs stay in the datadir**, never in `/backup` | the backup script does `rm -rf /backup/new` on every run; binlogs there would be deleted mid-flight |
| D6 | **Audit excludes the app user**, writes only (`QUERY_DML_NO_SELECT`) | otherwise the log is 99 % Django and the one contractor session is unfindable. Reads can be added per session by changing one line |
| D7 | **Audit file in the datadir** | it inherits the daily `root` restic snapshot, so the record survives the host, and the web app has no path to it. Hourly coverage is a documented upgrade, not a prerequisite |
| D8 | **`plugin_load_add` only after a verified runtime `INSTALL SONAME`** | a bad `plugin_load_add` aborts `mysqld` startup — that is a total DB outage from a typo. Prove the load on the test host first |
| D9 | **Mount the config as a *directory*** | `git pull` replaces files by rename; a single-file bind-mount goes stale while the container runs. `conf.d` is empty in this image, so a directory mount hides nothing |

---

## Task 1: Rehearse the whole config on `servyy-test.lxd`

Nothing here touches prod. The point is to answer two questions before the window: *does the plugin load this way*, and *does a second start actually produce binlogs*.

**Files:**
- Create: `/root/dev/dachrisch/leaguesphere/deployed/mysql-conf/zz-binlog-audit.cnf`
- Modify: `/root/dev/dachrisch/leaguesphere/deployed/docker-compose.staging.yaml` (service `mysql`)

**Step 1: Write the config file** (one file serves both stacks; the exclusion list names both app accounts so the same file is valid on each host)

```ini
# Managed by Ansible? No - by hand in the leaguesphere repo, next to the compose
# file it belongs to. Mounted read-only into /etc/mysql/conf.d.
#
# Two features, one file, deliberately: log_bin cannot be set at runtime
# (ERROR 1238: read only variable), so turning it on costs a db restart - the
# audit plugin costs nothing extra once we are paying that.

[mysqld]
# --- point-in-time recovery ------------------------------------------------
server_id                  = 1
log_bin                    = /var/lib/mysql/binlog
binlog_format              = ROW
binlog_row_image           = FULL
binlog_annotate_row_events = ON
sync_binlog                = 1
max_binlog_size            = 256M
# 2 days: this is the PITR window AND the bound on how much every hourly
# prepared set carries around. Raise only together with the disk check.
expire_logs_days           = 2

# --- who did what ----------------------------------------------------------
plugin_load_add               = server_audit
server_audit_events           = CONNECT,QUERY_DML_NO_SELECT
# The app writes constantly; logging it hides the humans we care about.
# Stage's admin user is included so this file is valid on both hosts.
server_audit_excl_users       = web35_8,leaguesphere_stage
server_audit_output_type      = file
server_audit_file_path        = /var/lib/mysql/server_audit.log
server_audit_file_rotate_size = 50M
server_audit_file_rotations   = 9
server_audit_timestamp_format = %Y-%m-%d %H:%M:%S
```

**Step 2: Mount it in the staging compose** (`mysql:` service, next to the existing `mysql-init` mount)

```yaml
    volumes:
      - "./mysql-data:/var/lib/mysql"
      - "./mysql-init:/docker-entrypoint-initdb.d:ro"
      # Directory mount, not a file: `git pull` replaces files by rename, which
      # leaves a single-file bind-mount pointing at a dead inode.
      - "./mysql-conf:/etc/mysql/conf.d:ro"
```

**Step 3: Deploy to the test host and prove it starts**

```bash
cd /root/dev/dachrisch/leaguesphere && git add deployed/mysql-conf deployed/docker-compose.staging.yaml
cd /root/dev/dachrisch/servyy-container/ansible
./servyy-test.sh --tags ls.app.pull,ls.app.deploy --limit servyy-test.lxd
ssh servyy-test.lxd "docker ps --format '{{.Names}} {{.Status}}' | grep leaguesphere_stage"
ssh servyy-test.lxd "docker logs --tail 30 leaguesphere_stage.mysql | grep -iE 'binlog|audit|error'"
```

Expected: the container is `Up`, the log mentions server audit being loaded, and no `[ERROR]` line. If `mysqld` refuses to start, D8 is the reason this was tested here and not on prod — remove the file and read the container log.

**Step 4: Verify both features answer**

```bash
ssh servyy-test.lxd "docker exec leaguesphere_stage.mysql mariadb -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -t -e \"
  SHOW VARIABLES LIKE 'log_bin';
  SHOW VARIABLES LIKE 'sync_binlog';
  SHOW BINARY LOGS;
  SELECT PLUGIN_NAME, PLUGIN_STATUS FROM information_schema.PLUGINS WHERE PLUGIN_NAME LIKE '%audit%';\""
```

Expected: `log_bin=ON`, `sync_binlog=1`, at least one `binlog.000001`, `server_audit=ACTIVE`.

**Step 5: Prove the audit filter and the annotation, as a human-shaped user**

```bash
ssh servyy-test.lxd "docker exec leaguesphere_stage.mysql mariadb -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"
  CREATE USER auditprobe@'127.0.0.1' IDENTIFIED BY 'Probe12345xyz';
  GRANT SELECT, UPDATE ON leaguesphere_stage.divisions TO auditprobe@'127.0.0.1';\""
ssh servyy-test.lxd "docker exec leaguesphere_stage.mysql mariadb -uauditprobe -pProbe12345xyz \
  -e \"UPDATE leaguesphere_stage.divisions SET id=id LIMIT 1;\""
ssh servyy-test.lxd "docker exec leaguesphere_stage.mysql sh -c 'tail -3 /var/lib/mysql/server_audit.log'"
```

Expected: a `QUERY` line naming `auditprobe@127.0.0.1` with the statement. Then prove exclusion and clean up:

```bash
ssh servyy-test.lxd "docker exec leaguesphere_stage.mysql mariadb -uleaguesphere_stage -p\"\$MYSQL_PWD\" \
  -e 'SELECT 1' 2>/dev/null; docker exec leaguesphere_stage.mysql sh -c 'grep -c leaguesphere_stage /var/lib/mysql/server_audit.log || true'"
ssh servyy-test.lxd "docker exec leaguesphere_stage.mysql mariadb -uroot -p\"\$MYSQL_ROOT_PASSWORD\" \
  -e \"DROP USER auditprobe@'127.0.0.1';\""
```

Expected: the app account's statements are **absent** from the log.

**Step 6: Commit**

```bash
git add deployed/mysql-conf deployed/docker-compose.staging.yaml
git commit -m "feat(db): enable binlog and statement audit on the staging stack"
```

---

## Task 2: The prod compose change

**Files:**
- Modify: `/root/dev/dachrisch/leaguesphere/deployed/docker-compose.yaml` (`db:` service)

**Step 1: Add the mount** — same line, same directory, next to `mysql-init`:

```yaml
    volumes:
      - "./mysql-data:/var/lib/mysql"
      - "./mysql-backup:/backup"
      - "./mysql-init:/docker-entrypoint-initdb.d:ro"
      - "./mysql-conf:/etc/mysql/conf.d:ro"
```

**Step 2: Validate and commit**

```bash
cd /root/dev/dachrisch/leaguesphere/deployed && docker compose -f docker-compose.yaml config --quiet
cd /root/dev/dachrisch/leaguesphere
git add deployed/docker-compose.yaml
git commit -m "feat(db): enable binlog and statement audit on prod"
git push origin HEAD && gh pr create --fill
```

Merged before the window — the host pulls `master`.

---

## Task 3: The maintenance window

**Timing:** any quiet hour; avoid gameday weekends (`Com_*` write bursts are what makes the restart long).

**Step 1: Record the "before" state**

```bash
ssh servy.lehel.xyz "docker inspect -f '{{.State.StartedAt}}' leaguesphere.db"
ssh servy.lehel.xyz "docker exec leaguesphere.db mariadb -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -N -B -e \
  'SELECT COUNT(*) FROM web35_db8.divisions'"
```

**Step 2: Make sure a *fresh* prepared set exists before restarting**

```bash
ssh servy.lehel.xyz "systemctl --user start mariadb-backup-ls.service" # or wait for :40
ssh servy.lehel.xyz "sudo ls -la /var/jail/home/leaguesphere/container/deployed/mysql-backup/current | head -5"
```

This is the rollback: if the new config misbehaves, you restore this set, and it was taken under the old (binlog-free) configuration.

**Step 3: Deploy**

```bash
cd /root/dev/dachrisch/servyy-container/ansible
./servyy.sh --tags ls.app.pull,ls.app.deploy --limit servy.lehel.xyz
```

Expected: **only `leaguesphere.db` is recreated** (its config changed). `app`, `www`, `db-tunnel`, `db-access` report no recreation. The app will return 5xx for the restart plus the DB healthcheck's `start_period` — expect ~90 s of degraded writes, not a clean instant.

> If `app` or `www` are recreated too, stop and check the compose diff: the change belongs on `db` only.

**Step 4: Verify immediately**

```bash
ssh servy.lehel.xyz "docker logs --tail 40 leaguesphere.db | grep -iE 'binlog|audit|ready for connections|ERROR'"
ssh servy.lehel.xyz "docker exec leaguesphere.db mariadb -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -t -e \"
  SHOW VARIABLES WHERE Variable_name IN ('log_bin','log_bin_basename','sync_binlog','expire_logs_days','max_binlog_size');
  SHOW MASTER STATUS;
  SHOW BINARY LOGS;
  SELECT PLUGIN_NAME, PLUGIN_STATUS FROM information_schema.PLUGINS WHERE PLUGIN_NAME LIKE '%audit%';\""
```

Expected: `log_bin=ON`, `log_bin_basename=/var/lib/mysql/binlog`, `sync_binlog=1`, `expire_logs_days=2`, a position row from `SHOW MASTER STATUS`, one binlog file, `server_audit=ACTIVE`.

**Step 5: Prove the app still works and the app is *not* in the audit log**

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://leaguesphere.app/          # expect 200
ssh servy.lehel.xyz "docker exec leaguesphere.db sh -c 'wc -l /var/lib/mysql/server_audit.log; grep -c web35_8 /var/lib/mysql/server_audit.log || true'"
```

Expected: `200`, a small non-zero line count (startup CONNECTs from other accounts), and **zero** `web35_8` lines.

---

## Task 4: Prove the backup now carries the binlog

This is the step that turns "binlog is on" into "PITR actually works", and the one most likely to be skipped.

**Step 1: Let the next `:40` run happen, then look inside the set**

```bash
ssh servy.lehel.xyz "sudo ls -la /var/jail/home/leaguesphere/container/deployed/mysql-backup/current | grep -E 'binlog|xtrabackup_binlog_info'"
ssh servy.lehel.xyz "sudo cat /var/jail/home/leaguesphere/container/deployed/mysql-backup/current/xtrabackup_binlog_info"
```

Expected: the `binlog.00000N` files present **and** an `xtrabackup_binlog_info` line holding the file + position at which the backup started. That pair is the entire PITR handle.

**Step 2: Check what it cost**

```bash
ssh servy.lehel.xyz "sudo du -sh /var/jail/home/leaguesphere/container/deployed/mysql-backup/current"
ssh servy.lehel.xyz "df -h / | tail -1"
ssh servy.lehel.xyz "systemctl --user list-timers | grep -E 'restic|mariadb'"
```

Expected: the set grew by roughly the binlog size (a few MB at this write volume, not the 251 MB × N that `max_binlog_size=1G` would have allowed). Confirm the next hourly restic snapshot completed.

**Step 3: Add the disk guard** — the one number that can quietly break this:

```bash
ssh servy.lehel.xyz "df -h / | tail -1"
```

Record it in the history entry, and add an alert if the existing `system_probe`/Pushgateway setup has a disk threshold below 90 %. If it does not, note in the runbook: **check `df` after a gameday weekend** — binlog grows in bursts, and this disk is at 86 %.

---

## Task 5: PITR drill on `servyy-test.lxd`

Do this once, with a deliberately wrong `UPDATE`, so that the real incident is not the first time. **Never copy-back into a running app's datadir** — the repo's rule (a copy-back carries the source's `mysql` system DB) applies here too, which is why the drill uses a throwaway container with no published port.

**Step 1: Make a known-bad change on the stage stack, and note the time**

```bash
ssh servyy-test.lxd "docker exec leaguesphere_stage.mysql mariadb -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"
  SELECT id, name FROM leaguesphere_stage.divisions LIMIT 3;\""
# note T0 = now
ssh servyy-test.lxd "docker exec leaguesphere_stage.mysql mariadb -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"
  UPDATE leaguesphere_stage.divisions SET name='PITR-DRILL-WRONG' WHERE id=1;\""
```

**Step 2: Find it in the binlog**

```bash
ssh servyy-test.lxd "docker exec leaguesphere_stage.mysql sh -c 'ls /var/lib/mysql/binlog.*'"
ssh servyy-test.lxd "docker exec leaguesphere_stage.mysql mariadb-binlog \
  --base64-output=DECODE-ROWS -v --start-datetime='<T0 minus 1 minute>' \
  /var/lib/mysql/binlog.000001 | grep -A 12 -B 4 'PITR-DRILL-WRONG'"
```

Expected: the annotated statement, then the row image with the **old** and **new** `name` values. That output is the answer to "what did they change" — verify you can read it without help.

**Step 3: Replay to before the change, into a scratch server**

```bash
ssh servyy-test.lxd "mkdir -p /tmp/pitr && sudo cp -a /var/jail/home/leaguesphere/container/deployed/mysql-backup/current /tmp/pitr/set"
ssh servyy-test.lxd "docker run -d --name pitr-drill --network none \
  -v /tmp/pitr/set:/var/lib/mysql mariadb:latest --skip-grant-tables --skip-networking"
ssh servyy-test.lxd "docker exec pitr-drill mariadb-binlog --start-position=<from xtrabackup_binlog_info> \
  --stop-datetime='<T0>' /var/lib/mysql/binlog.000001 | docker exec -i pitr-drill mariadb"
ssh servyy-test.lxd "docker exec pitr-drill mariadb -e \"SELECT id,name FROM leaguesphere_stage.divisions WHERE id=1\""
```

Expected: the **pre-incident** value. Then re-run with `--stop-datetime` after T0 and confirm the wrong value appears — that proves the position arithmetic rather than assuming it.

**Step 4: Tear down, and clean the drill artefact off the stage stack**

```bash
ssh servyy-test.lxd "docker rm -f pitr-drill && sudo rm -rf /tmp/pitr"
```

**Step 5: Record the drill** in the history entry: the timestamps used, how long the restore + replay took, and the exact command that worked. A runbook nobody has executed is a guess.

---

## Task 6: The reading runbook

**Files:**
- Modify: `docs/leaguesphere-environments.md` (new subsection under the DB notes)

**Step 1: Add the section**

```markdown
### Reading the DB audit trail (who changed what)

Two records, both off the app's reach:

| Question | Where | Command |
|---|---|---|
| who ran what, when, from where | `/var/lib/mysql/server_audit.log` in `leaguesphere.db` | `docker exec leaguesphere.db sh -c "grep dbeaver_prod_nn /var/lib/mysql/server_audit.log"` |
| which rows changed, before → after | binlog files in the datadir | `docker exec leaguesphere.db mariadb-binlog --base64-output=DECODE-ROWS -v --start-datetime='…' --stop-datetime='…' /var/lib/mysql/binlog.00000N` |

The app account (`web35_8`) is **excluded** from the audit log on purpose — otherwise Django
drowns the person you are looking for. PITR window: `expire_logs_days=2`; the hourly prepared
set carries the binlogs it needs, so restoring to a second is one replay away.
The audit file reaches restic on the **daily** root snapshot; the binlogs ride along inside
every hourly db snapshot.
```

**Step 2: Amend the DR notes** — `current/` now contains `binlog.00000N` files and `xtrabackup_binlog_info`. A `--copy-back` restore must **not** try to reuse them (delete them before starting the restored instance, or restore to a point first), and the restore runbook should say which of the two it is doing.

**Step 3: Note the PII** — the audit file and the binlog both contain literal values from the database. They live in the datadir, so `restic root` now carries user data it did not carry before. Say so in the environments doc's backup section, so the Storage Box is treated as holding user data.

**Step 4: Commit**

```bash
git add docs/leaguesphere-environments.md
git commit -m "docs: reading the DB audit trail and PITR window"
```

---

## Task 7: History + the cross-reference from the access plan

**Files:**
- Create: `history/2026-10-26_mariadb-binlog-and-audit.md`
- Modify: `docs/plans/2026-10-25-prod-db-temp-credentials.md` (baseline rows)

**Step 1: Write the history entry** — the two facts that forced a restart (`ERROR 1238`, no `conf.d` mount), why the defaults were already right (`ROW`/`FULL`/annotate), the exclusion decision, the retention/disk arithmetic, the drill result, and what is still not covered (no user column in row events, no app-write attribution).

**Step 2: Fix the access plan's baseline** — these two rows are no longer true and both documents must agree:

```markdown
| `@@log_bin` / `@@general_log` | `1` / `0` — binlog ROW/FULL, 2-day PITR window; general log still off | SQL audit + PITR exist since 2026-10-26 (see `docs/plans/2026-10-26-mariadb-binlog-and-audit.md`) |
```

and in that plan's "what is recorded" section, replace "with no binlog, the `.sql` file is the only record" with a pointer to the audit log, keeping the honest gap: the binlog proves *what* changed, the audit log proves *who*, and neither is queryable as a table.

**Step 3: Commit**

```bash
git add history/2026-10-26_mariadb-binlog-and-audit.md docs/plans/2026-10-25-prod-db-temp-credentials.md
git commit -m "docs: record binlog + audit enablement, update the access plan baseline"
```

---

## Verification matrix

| # | Check | Command | Expected |
|---|---|---|---|
| 1 | Only `db` was recreated | `docker inspect -f '{{.State.StartedAt}}' leaguesphere.{app,www,db-tunnel}` | unchanged; `db` new |
| 2 | Binlog is on with the intended settings | `SHOW VARIABLES WHERE Variable_name IN ('log_bin','sync_binlog','expire_logs_days','max_binlog_size')` | `ON`, `1`, `2`, `268435456` |
| 3 | A write produces a binlog event | do one `UPDATE`, then `SHOW MASTER STATUS` | position advanced |
| 4 | Old and new values are recoverable | `mariadb-binlog --base64-output=DECODE-ROWS -v` | row image with both values + annotated statement |
| 5 | The audit plugin is active and excludes the app | `SELECT PLUGIN_NAME,PLUGIN_STATUS FROM information_schema.PLUGINS` + `grep -c web35_8 server_audit.log` | `ACTIVE`, `0` |
| 6 | A temp account appears in the log | connect as `dbeaver_prod_<p>` and run one `UPDATE` | one `QUERY` line naming that user and host |
| 7 | The hourly set carries binlogs | `ls …/mysql-backup/current \| grep binlog` + `cat …/xtrabackup_binlog_info` | files present, coordinates present |
| 8 | Restore-to-a-second works | PITR drill (Task 5) | pre-incident row state reproduced |
| 9 | The app is unaffected | `curl https://leaguesphere.app/` + a gameday page | `200`, no error in `docker logs leaguesphere.app` |
| 10 | Disk is still sane after a week | `df -h /` | ≥ 15 % free |
| 11 | `sshd`/unrelated units untouched | `systemctl --user list-timers` | `mariadb-backup-ls`, restic timers unchanged |

## Rollback

| Component | Rollback |
|---|---|
| The whole change | remove `./mysql-conf` from the compose volume list, `./servyy.sh --tags ls.app.pull,ls.app.deploy` → `db` restarts without the file |
| Binlogs left behind | harmless; `PURGE BINARY LOGS BEFORE NOW()` or delete after the next prepared set is archived |
| Audit plugin misbehaving | `UNINSTALL SONAME 'server_audit'` at runtime, or drop `plugin_load_add` from the file and restart once |
| Bad recovery attempt | the set is read-only in the drill; prod is never restored over, only replayed into a scratch container |

## Effort

| Task | Estimate |
|---|---|
| 1 — rehearsal on the test host | 45 min |
| 2 — prod compose + PR | 20 min |
| 3 — maintenance window | 45 min |
| 4 — backup + size verification | 30 min |
| 5 — PITR drill | 1 h |
| 6 — runbook + DR notes | 40 min |
| 7 — history + cross-reference | 20 min |
| **Total** | **≈ 4 h 20** |

## Open decisions

1. **Reads in the audit log?** `QUERY_DML_NO_SELECT` captures writes. Switching to `QUERY_DML` also records what the contractor *looked at* — better oversight, more volume, more PII in the file. Decide per session or once for all.
2. **Is 2 days the right PITR window?** Every extra day multiplies the size of each hourly restic snapshot, on a disk that is already 86 % full. The alternative — `--skip-binlog` on the backup and a separate binlog archive — is more work, not less.
3. **`sync_binlog=1` or 0?** 1 costs an fsync per commit and is the right default for an audit trail. If a gameday shows commit latency, 0 gives back ~1 s of loss window.
4. **Daily or hourly coverage for the audit file?** It rides the daily `root` snapshot today. Hourly means teaching the `ls-db` repo a second path — worth doing only if "audit lines from the last 24 h" turns out to matter.
5. **Does the app's own write traffic need to be attributable one day?** If yes, that is triggers or system versioning, which this plan deliberately avoids. Say so now rather than discovering it during an incident.
