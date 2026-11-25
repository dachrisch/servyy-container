# LeagueSphere — Environments & Deployment Reference

> One-stop reference for the **prod**, **stage**, **demo**, and **test** deployments of
> LeagueSphere, how to set each one up, where their logs/metrics live, and the two everyday
> playbooks: **investigate an error on prod** and **reproduce it with real data**.
>
> Deployment is driven from this repo's Ansible (`ansible/plays/leaguesphere.yml` and the
> `ls_*` roles). The application code lives in the separate `leaguesphere` repo
> (`github.com/dachrisch/league-manager`).

---

## TL;DR — the everyday workflows

```bash
# ── Investigate an error on PROD ────────────────────────────────────────────
ssh lehel.xyz "docker logs leaguesphere.app --tail 100"      # Django backend
ssh lehel.xyz "docker logs leaguesphere.www --tail 100"      # static frontend / nginx
# then open Grafana → https://monitor.lehel.xyz  (dashboard: "leaguesphere")
#   and/or query Loki for {container="leaguesphere.app"} — see "Logs & metrics" below

# ── Reproduce it with REAL prod data ────────────────────────────────────────
# The ls_db_sync role clones prod into the STAGE stack. Deploy that stack on whichever
# host you want, then sync:
cd ansible
./servyy.sh      --tags ls.db.sync --limit lehel.xyz   # → public stage on lehel.xyz
#   ── or, into the isolated TEST box ──
./servyy-test.sh --tags ls.db.sync                     # → stage stack on servyy-test.lxd
```

> 💡 **What `ls_db_sync` actually does:** it clones the **production database into the _stage_
> stack** (`leaguesphere_stage.mysql`). Because the playbook is `hosts: all` with no host
> gating, that stage stack — and the sync — runs against **whatever inventory you target**:
> `./servyy.sh` puts it on `lehel.xyz` (public `stage.leaguesphere.app`); `./servyy-test.sh`
> puts it on `servyy-test.lxd` (a fully isolated copy with prod data). Either way you get a
> real-data reproduction; pick the host by how isolated you need to be.
>
> **Source toggle (`ls_db_sync_source`):** since the local mariadb migration, `ls_db_sync` can
> pull from either the legacy external host (`external`) or the new local prod container
> `leaguesphere.db` (`local`). **Prod cutover completed 2026-07-08**, so `local` is now the
> correct source; the code default is still `external` (a follow-up flips it to `local`).
> Override on the command line:
> `./servyy.sh --tags ls.db.sync -e ls_db_sync_source=local`
>
> This is **separate** from `spinup_test_db.sh`, which seeds a lighter `mysql` container on
> `servyy-test.lxd` with **synthetic** fixtures for the pytest suite (see
> [Test](#4-test--servyy-testlxd)). Use `ls_db_sync` for real-data repro, `spinup_test_db.sh`
> for running the test suite.

---

## Environment matrix

| | **Prod** | **Stage** | **Demo** | **Test** |
|---|---|---|---|---|
| URL | `leaguesphere.app` | `stage.leaguesphere.app` | `demo.leaguesphere.app` | — (no public app) |
| Host | `lehel.xyz` | `lehel.xyz` (same host) | `lehel.xyz` | `servyy-test.lxd` (LXD) |
| Compose project | `leaguesphere` | `leaguesphere_stage` | `leaguesphere-demo` | `mysql` (DB only) |
| App container | `leaguesphere.app` | `leaguesphere_stage.staging-app` | `leaguesphere-demo.demo-app` | n/a |
| DB container | `leaguesphere.db` ¹ | `leaguesphere_stage.mysql` | `leaguesphere-demo.mysql` | `mysql` |
| Web container | `leaguesphere.www` | `leaguesphere_stage.www` | `leaguesphere-demo.www` | n/a |
| Database | container `leaguesphere.db` (db `web35_db8`) — **internal-only, no published port** ¹ | container `leaguesphere_stage.mysql` (db `leaguesphere_stage`) | container `leaguesphere-demo.mysql` | container `mysql` (db `test_db`) |
| DB backup | `mariadb-backup` → prepared set + **binlog (2-day PITR window)** + hourly restic repo `restic-ls-db` (Hetzner Storage Box) | n/a | n/a | n/a |
| Data | live production data | **clone of prod** (via `ls_db_sync`) | synthetic, **auto-resets nightly** | synthetic fixtures (`test_db_dump.sql`) |
| Git branch | `master` | `master` | `master` | working tree (pytest) |
| Compose file | `deployed/docker-compose.yaml` | `deployed/docker-compose.staging.yaml` | `deployed/docker-compose.demo.yaml` | n/a |
| Deployed under | SSH chroot jail: `…/home/leaguesphere/container/` | jail: `…/container-stage/` | jail: `…/container-demo/` | n/a |

> ¹ **Prod database:** the prod stack runs its own MariaDB container (`leaguesphere.db`) on an
> internal-only Docker `backend` network with **no published host ports**. Data and backups are
> bind-mounted under `/var/jail/home/leaguesphere/container/` (not named volumes) so they fall
> within restic's covered paths. The container is initialised with the same `db_name` / `db_user`
> / `db_password` the app already uses; cutover required changing only `app.db_host`.
>
> > STATUS: **DONE — prod cutover completed 2026-07-08.** The prod app now runs on the local
> > `leaguesphere.db` container (`MYSQL_HOST=leaguesphere.db`, db `web35_db8`); `app.db_host` is
> > flipped. The legacy external host (`s207.goserver.host`) is retained as a rollback net until
> > **2026-07-22** (cutover + 14 days), then decommissioned. This table reflects the live
> > architecture.

Container names follow this repo's convention `{project}.{compose-service}`, which is also the
**Loki `container` label** — see [Logs & metrics](#logs--metrics).

> **Stage is a stack, not a fixed host.** The "Stage" column above is the *public* stage on
> `lehel.xyz`, but the same stage stack (and its prod-data sync) can be deployed on
> `servyy-test.lxd` via `./servyy-test.sh` — an isolated, prod-data reproduction environment.
> See [Test › mode (b)](#4-test--servyy-testlxd).

---

## How it's wired (Ansible)

Everything runs from `ansible/plays/leaguesphere.yml`, imported by `ansible/servyy.yml`.

- **Inventories** (`ansible/`):
  - `production` → `lehel.xyz` (prod + stage + demo all live here)
  - `testing` → `servyy-test.lxd`
- **Run scripts** (`ansible/`):
  - `./servyy.sh` → `ansible-playbook servyy.yml -i production`
  - `./servyy-test.sh` → `ansible-playbook servyy.yml -i testing …`
- **Roles** (`ansible/plays/roles/`):
  - `ls_setup`, `ls_access` — shared host/user/jail setup (run once)
  - `ls_app` — deploys prod **and** stage (same role, different vars: `secret_main.yaml` vs `secret_stage.yaml`)
  - `ls_demo` — deploys the nightly-reset demo
  - `ls_db_sync` — clones prod DB → stage DB (details below)
- **Secrets / config** (git-crypt encrypted; appear as plaintext when the repo is unlocked):
  - `ansible/plays/roles/ls_app/vars/secret_main.yaml` — prod (DB host/name/user, secret key, Moodle, etc.)
  - `ansible/plays/roles/ls_app/vars/secret_stage.yaml` — stage
  - non-secret env is rendered from `templates/docker.env.j2` and `templates/ls.env.j2`

### Useful Ansible tags

`leaguesphere.yml` exposes granular tags so you don't redeploy everything:

| Tag | Scope |
|---|---|
| `ls` | everything LeagueSphere |
| `ls.app` | prod **and** stage app |
| `ls.app.prod` | prod only (includes `leaguesphere.db` container) |
| `ls.app.stage` | stage only (also triggers `ls.db.sync`) |
| `ls.demo` | demo only |
| `ls.db.sync` | clone prod DB → stage (no redeploy); source toggleable via `ls_db_sync_source` |
| `ls.app.pull` / `ls.app.env` / `ls.app.deploy` | sub-steps of an app deploy |

---

## Setup / deploy each environment

> **Deployment policy (this repo): test-first, no manual prod edits.** Validate on
> `servyy-test.lxd` first, never `scp`/`ssh`-edit prod files, and **ask for explicit approval
> before any production deploy.** See the repo `AGENTS.md` › "CRITICAL DEPLOYMENT RULES."

### 1. Prod — `leaguesphere.app`

```bash
cd ansible
./servyy.sh --syntax-check                       # sanity check first
./servyy.sh --tags ls.app.prod --limit lehel.xyz # deploy prod app + db (after approval)
ssh lehel.xyz "docker ps | grep leaguesphere"    # verify
ssh lehel.xyz "docker inspect -f '{{.State.Health.Status}}' leaguesphere.db"  # db healthy?
```
Backend pulls the `master` branch via sparse checkout and runs `deployed/docker-compose.yaml`.
The prod stack now includes a `db` service (`leaguesphere.db`) — a MariaDB container on the
internal `backend` network with no published ports. The `app` service `depends_on` the `db`
service being healthy before it starts.

**Prod DB backup design:**
- `mariadb-backup` runs inside the container (`docker exec leaguesphere.db mariadb-backup …`)
  so its version always matches the server. It writes a *prepared* physical backup set to
  `container/deployed/mysql-backup/current/` (bind-mounted from the jail).
- A systemd user timer (`mariadb-backup-ls`, fires at `:40`) refreshes the prepared set.
- A second timer (`restic-backup-ls-db`, hourly) snapshots `current/` into the dedicated
  restic repo `restic-ls-db` on the Hetzner Storage Box.
- Environment file: `/etc/restic/env.db`; snapshots are tagged `db`.
- **Since 2026-10-26 the set also carries the binlogs** (`binlog.00000N` +
  `xtrabackup_binlog_info`, the coordinates the replay starts from) because
  `mariadb-backup` runs without `--skip-binlog`. That is what makes
  point-in-time recovery work; see below.

### Reading the DB audit trail (who changed what)

Two records, neither of them reachable from the web app:

| Question | Where | Command |
|---|---|---|
| who ran what, when, from where | `/var/lib/mysql/server_audit.log` inside `leaguesphere.db` | `ssh lehel.xyz "docker exec leaguesphere.db sh -c 'grep dbeaver_prod_nn /var/lib/mysql/server_audit.log'"` |
| which rows changed, before → after | the binlog files in the datadir | `ssh lehel.xyz "docker exec leaguesphere.db mariadb-binlog --base64-output=DECODE-ROWS -v --start-datetime='2026-10-26 14:00:00' --stop-datetime='2026-10-26 14:40:00' /var/lib/mysql/binlog.000004"` |

Row events carry no user column, so the audit line answers *who* and the binlog answers *what*;
join them on the statement text and the timestamp window.

The application account (`web35_8`) is **excluded** from the audit log on purpose — otherwise
constant Django traffic buries the person being investigated. Reads are not logged
(`QUERY_DML_NO_SELECT`); adding them is a one-line change in the config for a session where
"what did they look at" matters.

Both files are enabled by `deployed/mysql-conf/zz-binlog-audit.cnf` in the leaguesphere repo
(PR #2092), mounted read-only into `/etc/mysql/conf.d`. **mysqld reads it only at startup**, and
a deploy does not recreate `db` when only the file's content changes — after editing it, restart
deliberately (`docker compose … up -d --force-recreate db`). Rollback is removing the mount.

> Both the audit log and the binlog contain literal values from the database, so the restic
> repos now carry user data: the audit file on the daily root snapshot, the binlogs inside every
> hourly `restic-ls-db` snapshot. Treat Storage Box access as data access.

**Prod DB is self-contained.** Since the 2026-07-08 cutover the app talks directly to
`leaguesphere.db`; there is no external seeding step. The former external migration role
and its dedicated Ansible tag were removed: its external credentials were stale and, because
it was included in the playbook without a guard, it could have dropped and recreated the live
prod DB on an ordinary deploy. Restore and re-seed from the binlog-backed
`mariadb-backup` set and its restic snapshots described above, not from an external host.

### 2. Stage — `stage.leaguesphere.app`

Stage **always deploys alongside prod** when you run `ls.app`, and the prod→stage DB sync runs
with it. To deploy stage on its own:

```bash
cd ansible
./servyy.sh --tags ls.app.stage --limit lehel.xyz
```
Stage runs `docker-compose.staging.yaml` and has **no database container of its own** since
WP-4: it reaches `db-nonprod.mariadb` on the host's nonprod DB tier (`db_nonprod_backend`,
internal). The app-owned `leaguesphere_stage.mysql` is retired (kept stopped for one week as
the cutover rollback); `ls_db_sync` now refuses to run while it is running again.

Prerequisite on any host that should run stage (including `servyy-test.lxd`): the nonprod tier
must be enabled (`db_tiers` in the inventory) and deployed before the stage stack:

```bash
cd ansible
./servyy.sh --tags user.docker.db-nonprod --limit lehel.xyz   # server + stage/demo users
```

### 3. Demo — `demo.leaguesphere.app`

```bash
cd ansible
./servyy.sh --tags ls.demo --limit lehel.xyz
```
Demo uses pre-built images and **auto-resets nightly** — never put data you care about here.

### 4. Test — `servyy-test.lxd`

`servyy-test.lxd` is the LXD box used for testing. It serves **two distinct purposes** — don't
confuse them:

**(a) Run the pytest / molecule suites** against a light, synthetic-data MariaDB. This is a
single bare `mysql` container seeded from `test_db_dump.sql` — *not* the app stack.

**(b) Stand up a full prod-data reproduction.** Post-WP-4 this is a three-step sequence: the
test box has no prod container, so `ls_db_sync` dumps prod **on `lehel.xyz`** (read-only,
`--single-transaction`, views ignored), fetches the dump through the Ansible controller and
imports it into the test box's own nonprod tier.

```bash
cd ansible
# 1. nonprod DB tier: db-nonprod.mariadb + the stage/demo users (idempotent)
./servyy-test.sh --tags user.docker.db-nonprod
# 2. stage stack; its ls.db.sync step pulls the read-only prod dump
./servyy-test.sh --tags ls.app.stage
# 3. later: refresh the data only
./servyy-test.sh --tags ls.db.sync
```
This gives you the stage stack on `servyy-test.lxd` (`leaguesphere_stage.*` app containers plus
`db-nonprod.mariadb`) holding a clone of prod - fully isolated, nothing exposed publicly. (Stage
host name derives from `inventory_hostname`, i.e. `stage.leaguesphere.servyy-test.lxd`.) See
[Reproduce a prod issue with real data](#reproduce-a-prod-issue-with-real-data-ls_db_sync).

**Spin up / reset the pytest test DB** — purpose (a), run from the `leaguesphere` repo:
```bash
cd <leaguesphere-repo>
./container/spinup_test_db.sh --fresh   # recreates `mysql` container, imports test_db_dump.sql

# point pytest at it
export MYSQL_HOST=$(lxc list servyy-test --format json \
  | jq -r '.[0].state.network.eth0.addresses[] | select(.family=="inet") | .address' | head -n1)
pytest
```
The fresh import includes the **placeholder teams** that schedule JSON files reference (P1/P2/P3
groups, "Gewinner/Verlierer HF…", etc.). If you see `Team.DoesNotExist`, re-run with `--fresh`.

> This DB holds **synthetic fixtures, not production data.** To reproduce an issue against a
> real prod data shape, use **stage** + `ls.db.sync` (next section).

---

## Reproduce a prod issue with real data (`ls_db_sync`)

`ansible/plays/roles/ls_db_sync/tasks/main.yml` does, in order:

1. Dump the **prod** DB (single-transaction, `--lock-tables=false`, **all views ignored**) into
   `/tmp/leaguesphere_prod_<epoch>.sql`. The dump source is controlled by `ls_db_sync_source`:
   - `local` (default post-cutover): `mariadb-dump` from the `leaguesphere.db` container on this
     host (prod, public stage on lehel.xyz).
   - `external` (recovery only): `mysqldump` from `s207.goserver.host`.
   - `remote_prod` (default on test hosts): the dump runs **on `lehel.xyz`** (read-only,
     same flags/views), is fetched to the Ansible controller, copied to the target and imported.
     `ls_db_sync_remote_prod_host` defaults to the `lehel.xyz` SSH alias; nothing is written to
     prod except the dump file in `/tmp`, which is removed in an `always` block.
2. Refuse to continue when no dump landed (never drop the DB without data).
3. Wait for `db-nonprod.mariadb` to be healthy.
4. **Drop & recreate** the `leaguesphere_stage` database (utf8mb4) as the stage app user.
5. Import the dump, restart `leaguesphere_stage.staging-app`, then clean up the dump (also when
   the import fails).

**Privacy:** in `remote_prod` mode a prod dump crosses three hosts. It is written 0600 on prod,
fetched into a 0700 controller directory as 0600, copied 0600 to the target, and every copy is
deleted in an `always` block — including on failure. Never move it to a world-readable path.

Run it against either host (the playbook is `hosts: all`, so the target is just the inventory):

```bash
cd ansible

# Public stage on lehel.xyz (using default source):
./servyy.sh --tags ls.db.sync --limit lehel.xyz

# Force a specific source regardless of the default:
./servyy.sh --tags ls.db.sync --limit lehel.xyz -e ls_db_sync_source=local
./servyy.sh --tags ls.db.sync --limit lehel.xyz -e ls_db_sync_source=external

# Isolated copy on the test box (source defaults to remote_prod there):
./servyy-test.sh --tags ls.db.sync
# Explicit override if needed:
./servyy-test.sh --tags ls.db.sync -e ls_db_sync_source=remote_prod
./servyy-test.sh --tags ls.db.sync -e ls_db_sync_remote_prod_host=lehel.xyz
```

The stage **stack must already exist** on the target host. Deploying the stack runs the sync
for you, so a clean first run on the test box is:

```bash
./servyy-test.sh --tags ls.app.stage   # deploys stage stack on servyy-test + runs ls.db.sync
./servyy-test.sh --tags ls.db.sync     # later: just re-pull fresh prod data
```

`ls.db.sync` also runs automatically as part of any `ls.app.stage` / `ls.app` deploy.

> **Destructive on the target stage DB:** step 3 wipes that host's staging DB every run. That's
> intended — stage is a disposable mirror of prod. Prod is read-only here (dump only); nothing
> is written back.

---

## Prod DB restore procedure

If `leaguesphere.db` data is lost or corrupt — or you are **rebuilding a host from scratch
after a disaster** — the last prepared `mariadb-backup` set is restored from restic and then
**copied back manually**.

> ### ⚠️ The restore is TWO steps. restic alone does NOT bring the data back.
> The restic restore (Step 1, also run automatically during a fresh `./servyy.sh`) only
> repopulates the backup **files** in `…/deployed/mysql-backup/current/`. It does **not** load
> them into the running database. After a fresh reprovision, `leaguesphere.db` comes up on an
> **empty data dir** serving an **empty schema** — the data is recovered only once you run the
> **copy-back** (Step 2). This is deliberate: an automated re-provision must never overwrite a
> healthy live DB. When the integrated restore fires on a fresh host, Ansible prints a loud
> `LEAGUESPHERE DB RESTORE` notice with the exact copy-back commands below — do not consider the
> host recovered until you have run them.

> ### ⚠️ The set now also contains binlogs
> Since 2026-10-26 `current/` holds `binlog.00000N` and `xtrabackup_binlog_info` (the replay
> coordinates). A copy-back therefore copies the *old* binlog timeline into the restored datadir.
> That is harmless on its own — mysqld continues from the highest number present — but those
> files must never be mistaken for a PITR replay: they end at the moment the backup was taken.

### Fresh-container / full-disaster rebuild

A from-scratch `./servyy.sh` (or `./servyy-test.sh`) provisions the host and, via the integrated
restic restore, repopulates `…/mysql-backup/current/` — then brings `leaguesphere.db` up **empty**.
To finish recovery, run **Step 2 (copy-back)** and **Step 3 (verify)** below. (Step 1 already ran
as part of the reprovision; run it standalone only when recovering an already-provisioned host.)

**Step 1 — Restore the prepared set from restic:**
```bash
cd ansible
./servyy.sh --tags restic.restore --limit lehel.xyz
# Restic repopulates /var/jail/home/leaguesphere/container/deployed/mysql-backup/current/
# NOTE: this restores FILES only — the live DB is still empty until Step 2.
```

**Step 2 — Copy-back to MariaDB data directory (run on the host):**
```bash
ssh lehel.xyz "
  cd /var/jail/home/leaguesphere/container
  docker compose -p leaguesphere stop db
  sudo rm -rf mysql-data/*
  docker run --rm \
    -v \$(pwd)/mysql-data:/var/lib/mysql \
    -v \$(pwd)/mysql-backup/current:/backup \
    mariadb:latest mariadb-backup --copy-back --target-dir=/backup
  sudo chown -R 999:999 mysql-data   # mariadb uid inside the image
"
```

**Step 3 — Start the DB and verify:**
```bash
ssh lehel.xyz "
  cd /var/jail/home/leaguesphere/container
  docker compose -p leaguesphere start db
  docker inspect -f '{{.State.Health.Status}}' leaguesphere.db
"
```

### Point-in-time recovery (binlog replay)

A restore gets you to the **backup**, not to "just before the bad statement". For that, replay the
binlog into a **scratch** container — never into the live datadir.

```bash
# 1. what the backup knows: the coordinates to start from
ssh lehel.xyz "sudo cat /var/jail/home/leaguesphere/container/deployed/mysql-backup/current/xtrabackup_binlog_info"

# 2. copy the set aside and start a throwaway server on it (no network, no grants)
ssh lehel.xyz "sudo cp -a /var/jail/home/leaguesphere/container/deployed/mysql-backup/current /tmp/pitr && \
  docker run -d --name pitr --network none -v /tmp/pitr:/var/lib/mysql \
    mariadb:latest --skip-grant-tables --skip-networking"

# 3. replay up to the moment before the statement
ssh lehel.xyz "docker exec pitr mariadb-binlog --start-position=<pos from step 1> \
  --stop-datetime='2026-10-26 14:30:59' /var/lib/mysql/binlog.000004 | docker exec -i pitr mariadb"

# 4. read the rows out, then destroy the container
ssh lehel.xyz "docker exec pitr mariadb -e 'SELECT * FROM web35_db8.divisions'"
ssh lehel.xyz "docker rm -f pitr && sudo rm -rf /tmp/pitr"
```

Lift the rows you need out of the scratch instance with `mysqldump --where` and import them into
prod. **Never** copy-back a replayed datadir over the live one. The full drill, including how to
verify the position arithmetic on the test host first, is in
`history/2026-10-26_mariadb-binlog-and-audit.md`.

---

## Cutover runbook (external → local DB) — two phases

> 📋 **Cutover day → use the [Phase B cutover checklist](leaguesphere-cutover-checklist.md).**
> That is the tickable pre-flight → execute → verify → post sheet. The block below is the
> condensed reference the checklist links back to.

> STATUS: **Phase A DONE (2026-06-25)** and **Phase B DONE (2026-07-08)** — cutover complete.
> Prod app now runs on the local `leaguesphere.db` (`web35_db8`), `RUN_MIGRATIONS=true`
> (migrate-on-start). External `s207.goserver.host` retained as rollback net until 2026-07-22.
> Full write-up: `history/2026-07-08_leaguesphere-phase-b-cutover.md`.
>
> **Phase B plan (as executed): full-downtime window.** App taken fully offline, the final seed
> ran against the quiet local DB, then a single `ls.app.prod` deploy brought app/www back up on
> the local DB. Deviation from the original plan: the final seed was sourced from the **stage
> copy** (`leaguesphere_stage`, which already held a fresh external dump) rather than re-pulling
> `s207` — same data, no dependency on the flaky external host. The `database`→`egress` network
> rename (old cutover PR #34) was **not** applied; the app reaches the local DB over `backend`.
>
> **Why two phases:** standing up `leaguesphere.db` (Phase A) does not move the app off the
> external DB — the app keeps `MYSQL_HOST=external`. The app moves to the local DB only at
> cutover (Phase B), via the single `db_host` flip + the `database`→`egress` rename.

> ⚠️ **Two things actually happen in Phase A on prod (observed 2026-06-25), so it is _not_
> strictly zero-touch:**
>
> 1. **app/www are recreated once.** The `git pull` updates the on-host `deployed/` checkout to
>    `master`; if prod was behind (it was), `docker compose up` recreates `app`/`www` to match —
>    a few seconds' blip. (On `servyy-test` the checkout already matched, so IDs were unchanged
>    there — that test did **not** exercise the stale-checkout case.) Schedule Phase A in a quiet
>    window even though it needs no formal maintenance.
> 2. **The seed competes for the external DB's `max_user_connections`.** `mysqldump` opens
>    connections to the shared external host (`web35_8@s207`) **on top of** the live app's pool.
>    **Any other consumer of the same user pushes it over the limit** and the live app starts
>    returning HTTP 500 (`OperationalError 1203`). In the 2026-06-25 run a still-running
>    `servyy-test` app shared that user and caused a transient prod login outage until it was
>    stopped. **Before seeding prod, stop every non-prod stack that points at the external DB**
>    (`servyy-test`, stage-on-external, local dev) — see the warning under "Reproduce a prod
>    issue" / `ls_db_sync`.

### Phase A — DB stand-up + validation (no maintenance window; brief app/www restart + external-DB contention — see warning above)

```bash
cd ansible
# Pre-flight: stop any non-prod stack still connected to the external DB (web35_8@s207)
#   so the seed's mysqldump doesn't exhaust max_user_connections and 500 the live app.
./servyy.sh --tags ls.app.prod --limit lehel.xyz      # pulls master; adds leaguesphere.db (recreates app/www once if checkout was stale)
./servyy.sh --tags restic.init,restic.backup --limit lehel.xyz
ssh lehel.xyz "docker inspect -f '{{.State.Health.Status}}' leaguesphere.db"   # → healthy
# External seed step (formerly a dedicated Ansible tag) was retired with the migration role:
# prod runs on its own leaguesphere.db and is no longer seeded from an external host.
```

### Phase B — cutover (full-downtime maintenance window, approval-gated)

> Day-of: follow the [cutover checklist](leaguesphere-cutover-checklist.md). Condensed here:

```bash
# 0. Pre-flight: verify backups (timers active, set log-applied & fresh, restic snapshot < 1h)
#    AND stop every NON-prod stack still on the external DB (servyy-test, stage-on-external, dev).
# 1. Take the app OFFLINE — full downtime, no in-flight writes, no external-DB contention:
ssh lehel.xyz "cd /var/jail/home/leaguesphere/container && docker compose -p leaguesphere stop app www"
# 2. (Removed) Final delta seed — the external migration role/tag was retired; live prod
#    is not re-seeded from an external host. Confirm leaguesphere.db is healthy instead.
# 3. In ONE deploy: flip app.db_host to 'leaguesphere.db' in secret_main.yaml
#    AND rename database->egress in leaguesphere/deployed/docker-compose.yaml, then:
./servyy.sh --tags ls.app.prod --limit lehel.xyz      # recreates app/www → back ONLINE on local DB
ssh lehel.xyz "docker exec leaguesphere.app sh -c 'env | grep MYSQL_HOST'"   # → leaguesphere.db
# 4. Smoke test (login, read, write); the app is already back up. Then end the window.
# 5. Set ls_db_sync_source: "local" default in ls_db_sync/defaults/main.yml and commit
```

---

## Rollback runbook (local → external DB)

If the cutover must be reversed within the 14-day retention window:

1. Revert `app.db_host` back to `s207.goserver.host` in
   `ansible/plays/roles/ls_app/vars/secret_main.yaml`.
2. Redeploy the prod app:
   ```bash
   cd ansible
   ./servyy.sh --tags ls.app.prod --limit lehel.xyz
   ssh lehel.xyz "docker exec leaguesphere.app sh -c 'env | grep MYSQL_HOST'"
   # → s207.goserver.host
   ```
3. The `leaguesphere.db` container can be left running (it keeps accumulating backups) or
   stopped — it does not affect the rolled-back app.

> **Decommission deadline:** the external DB (`s207.goserver.host`) is retained for **14 days**
> after cutover as a rollback safety net. After that window it can be dropped.
> Cutover date + 14 days = **decommission on/after 2026-07-06** (adjust to actual cutover date).
>
> > STATUS: PENDING — decommission date depends on the actual cutover date from Task 11.

---

## Logs & metrics

All container logs flow **stdout/stderr → Promtail → Loki**, explorable in Grafana.

- **Grafana:** https://monitor.lehel.xyz — dashboard **"leaguesphere"** (Traefik/Prometheus
  metrics: request rate, 5xx error rate, p50/p95 response time).
- **Loki datasource** inside Grafana is `loki` (`http://loki:3100`); Prometheus is `prometheus`.
- **Loki `container` labels** to query (use `query_range`, and the **container** name, not the
  compose-service name):

  | Environment | Backend | Web |
  |---|---|---|
  | Prod | `leaguesphere.app` | `leaguesphere.www` |
  | Stage | `leaguesphere_stage.staging-app` | `leaguesphere_stage.www` |
  | Demo | `leaguesphere-demo.demo-app` | `leaguesphere-demo.www` |

Example LogQL (last hour of prod backend errors):
```logql
{job="docker", container="leaguesphere.app"} | json | level=~"ERROR|CRITICAL"
```

Quick log access without Grafana:
```bash
ssh lehel.xyz "docker logs leaguesphere.app --tail 100 -f"            # prod backend
ssh lehel.xyz "docker logs leaguesphere_stage.staging-app --tail 100" # stage backend
```

See `monitor/AGENTS.md` › "Querying logs and checking bans" for the raw `curl`/`X-Scope-OrgID` recipe.

---

## Quick reference card

```text
PROD    leaguesphere.app          host lehel.xyz   db leaguesphere.db (internal container) [¹]
        containers: leaguesphere.app / leaguesphere.www / leaguesphere.db
        deploy:  ./servyy.sh --tags ls.app.prod --limit lehel.xyz
        db seed: none — self-contained since cutover (external migration removed)
        backup:  mariadb-backup-ls timer → restic repo restic-ls-db (hourly)
        logs:    docker logs leaguesphere.app   | Grafana "leaguesphere"
        [¹] Prod DB is the local leaguesphere.db container since the 2026-07-08 cutover

STAGE   stage.leaguesphere.app    host lehel.xyz   db db-nonprod.mariadb (nonprod tier)
        containers: leaguesphere_stage.staging-app / .www (no db container since WP-4)
        deploy:  ./servyy.sh --tags ls.app.stage --limit lehel.xyz
        prod-data clone: ./servyy.sh --tags ls.db.sync --limit lehel.xyz

DEMO    demo.leaguesphere.app     host lehel.xyz   resets nightly
        deploy:  ./servyy.sh --tags ls.demo --limit lehel.xyz

TEST    servyy-test.lxd           two modes:
        (a) pytest DB — bare MariaDB `mysql`, synthetic fixtures
            setup:   ./container/spinup_test_db.sh --fresh   (from leaguesphere repo)
        (b) prod-data repro — STAGE stack + nonprod tier here, prod dump over SSH
            setup:   ./servyy-test.sh --tags user.docker.db-nonprod
                     ./servyy-test.sh --tags ls.app.stage      (runs ls.db.sync)
                     later: ./servyy-test.sh --tags ls.db.sync
```

---

## Agent stage (Phase 0c, leaguesphere#2536)

A long-lived comparison stage on **servyy-test.lxd only**. Two app containers
share the stage database:

| container | image | updates |
|---|---|---|
| `ls_agent_stage.ref` | `leaguesphere/backend:agent-ref` (pinned in `ls_agent_stage/defaults/main.yml`) | never automatically — rebuilt per phase from the stack's **base commit**, then `ls.agent.stage` is re-applied |
| `ls_agent_stage.cand` | `leaguesphere/backend:agent-candidate` | `ls-agent-cand-update.timer` (system timer as `leaguesphere`, 5 min, health-gated) |

Both sit behind one nginx basic-auth proxy (`ls_agent_stage.proxy`, loopback
ports 18081/18082) and read/write **the same** stage database. The equivalence
harness (`scripts/equivalence/` in the leaguesphere repo) diffs ref against
cand.

### Initial setup (once per phase, in this exact order)

The test box has **no LeagueSphere containers by default**, and a fresh host needs more than
one pass: the stage app cannot become healthy before its database exists, and `www` starts only
after the database is imported. Each step is idempotent; only the sync (step 4) is destructive
to the stage data.

```bash
cd ansible

# 1. Nonprod DB tier: db-nonprod.mariadb + the stage/demo users. Creates the
#    db_nonprod_backend network the stage stack and the agent stage attach to.
#    The role now waits for a just-created datadir to finish initialising before
#    its root-password guard; before that fix the very first run could fail in
#    that guard, and a plain re-run passed.
./servyy-test.sh --limit servyy-test.lxd --tags user.docker.db-nonprod

# 2. dba.env for the stage compose. `deploy/docker-compose.staging.yaml` has
#    `env_file: dba.env`, which only ls_dbeaver_access writes; `up` fails
#    without it. The `provision` tag writes the files only - it skips the SSH
#    tunnel accounts, the sshd restart and the Vaultwarden push.
./servyy-test.sh --limit servyy-test.lxd --tags ls.dbeaver.provision

# 3. Stage stack WITHOUT the sync. On a fresh tier leaguesphere_stage does not
#    exist yet, so staging-app starts unhealthy and www waits; that is expected.
#    This pass creates the `leaguesphere_stage_media` volume the agent stage
#    mounts as external.
./servyy-test.sh --limit servyy-test.lxd --tags ls.app.stage --skip-tags ls.db.sync

# 4. Sync: creates the database, imports the read-only prod dump from lehel.xyz
#    (see the sync section) and restarts staging-app.
./servyy-test.sh --limit servyy-test.lxd --tags ls.db.sync

# 5. Stage again WITHOUT the sync: now that the DB exists, www comes up too.
./servyy-test.sh --limit servyy-test.lxd --tags ls.app.stage --skip-tags ls.db.sync

# 5b. PRE-APPLY SCHEMA CHECK. ref and cand share the stage database, and neither
#     runs migrations, so the phase BASE must not carry migrations the stage
#     deploy has not applied. Compare the stage stack's release with the base
#     (replace the tag with the release the stage stack was deployed from):
cd <leaguesphere-checkout>
git fetch origin
BASE=$(git rev-parse origin/phase0-docs)        # the stack's base commit
git diff --name-only <stage-release-tag>..$BASE | grep migrations && {
  echo "base adds migrations the stage DB lacks - deploy stage from a newer release first"; exit 1; }
cd -   # back to ansible/
#     `ls.agent.stage` enforces the authoritative version after the containers
#     are up: `python manage.py migrate --check` in both ref and cand against
#     the shared DB (ls_agent_stage_schema_check).

# 6. Build BOTH agent images BEFORE the agent stage (the role pulls them with
#    `pull: always`). `agent-ref` is the phase baseline: build it from the stack
#    BASE commit, not from a release tag (a tag always lags a moving master).
#    `agent-candidate` is the stack HEAD. Environment is not needed for either:
cd <leaguesphere-checkout>
gh workflow run deploy.yaml --ref phase0c-equivalence \
  -f agent_candidate_ref=$BASE -f agent_tag=agent-ref
gh workflow run deploy.yaml --ref phase0c-equivalence \
  -f agent_candidate_ref=phase0c-equivalence -f agent_tag=agent-candidate
cd -   # back to ansible/
#    Wait for both workflow runs to finish before step 7.

# 7. Agent stage (ref/cand/proxy + harness users + candidate timer + tunnel).
#    Harvest the credentials first, they live in git-crypt:
#      ansible/plays/roles/ls_agent_stage/vars/secret_agent_stage.yaml
./servyy-test.sh --limit servyy-test.lxd --tags ls.agent.stage
```

During a phase, never re-run step 4, and never run `ls.app.stage` **without**
`--skip-tags ls.db.sync`: the sync drops and recreates the stage DB and deletes the harness
accounts. After a deliberate refresh, re-run step 7.

Verify each step:

```bash
# 1. tier
ssh servyy-test.lxd 'docker ps --filter name=db-nonprod --format "{{.Names}} {{.Status}}"'
#    (if the first run stopped in the root-password guard, it was the fresh
#     datadir: the role now waits; just re-run step 1)
# 3-5. stage (containers healthy + the prod clone actually landed)
ssh servyy-test.lxd 'docker ps --filter name=leaguesphere_stage --format "{{.Names}} {{.Status}}"'
ssh servyy-test.lxd 'docker inspect -f "{{.State.Health.Status}}" leaguesphere_stage.staging-app'
ssh servyy-test.lxd 'docker exec leaguesphere_stage.staging-app python manage.py shell \
  -c "from gamedays.models import Gameday; print(Gameday.objects.count())"'
#    The stage UI on the test box is a plain-HTTP local router
#    (leaguesphere_stage.<hostname>) without a public certificate; the harness
#    does not depend on it - it compares ref/cand through the opentunnel proxy.
# 5b. no migrations between the stage release and the stack base
# 7. agent stage; then verify both sides pass the authoritative check:
ssh servyy-test.lxd 'docker exec ls_agent_stage.ref python manage.py migrate --check && echo ref-ok'
ssh servyy-test.lxd 'docker exec ls_agent_stage.cand python manage.py migrate --check && echo cand-ok'
#    `agent-ref` predates /health/version/, so verify the baked commit from the
#    image label instead:
ssh servyy-test.lxd 'docker image inspect leaguesphere/backend:agent-ref \
  --format "{{index .Config.Labels \"org.opencontainers.image.revision\"}}"'
ssh servyy-test.lxd 'docker ps --filter name=ls_agent_stage --format "{{.Names}} {{.Status}}"'
ssh servyy-test.lxd 'systemctl status ls-agent-cand-update.timer'
```

The role creates/updates the harness users (`agent_staff`,
`agent_team_manager`, `agent_official`) in the stage database. Passwords are
throwaway and live only in that git-crypt file — never real prod accounts.

**Harness role limits:** `agent_team_manager` and `agent_official` are plain
logged-in users — they are not linked to a team (teammanager) or an
`Official` row (officials) in the clone yet, so their probes exercise the
logged-in baseline, not team-manager/official-specific pages. TODO(Phase 1):
link them to a small test team/official in the clone if a phase's probes need
that surface.

### Per phase: moving `ref` to the new base

Renovate keeps master moving, so the phase baseline is a **commit-pinned build**,
not a release tag. When a phase starts (or the agreed base changes):

```bash
cd <leaguesphere-checkout>
git fetch origin
BASE=$(git rev-parse origin/phase0-docs)                 # the stack's base commit
gh workflow run deploy.yaml --ref <stack branch> \
  -f agent_candidate_ref=$BASE -f agent_tag=agent-ref     # rebuild the baseline
# wait for the run, then, in ansible/:
./servyy-test.sh --limit servyy-test.lxd --tags ls.agent.stage
```

Before rebuilding, confirm the base adds no migrations the stage DB lacks
(`git diff --name-only <stage-release-tag>..$BASE | grep migrations`); the role
also runs `manage.py migrate --check` in both containers after starting them.
`ref` has no update timer or watchtower label: it only changes on this
deliberate rebuild + re-apply.

### Credentials

`secret_agent_stage.yaml` (git-crypt) holds the basic-auth credential and the
role passwords. Rotate the basic-auth password by editing
`basic_auth_password` and regenerating the hash:

```bash
htpasswd -nbB ls-agent-stage '<new password>'   # nginx accepts $2y$ and $apr1$
```

then replace `basic_auth_htpasswd` and re-run `--tags ls.agent.stage`.

### Nightly sync guard (verify once)

`ls_db_sync` installs `ls-db-sync-nightly.timer` at 02:00 on hosts where the
role runs, and `servyy-test.lxd` runs LeagueSphere, so historically it would
have re-cloned prod nightly and wiped the harness accounts. The role now
skips the timer on `is_test_host` and stops/masks a leftover unit:

```bash
ssh servyy-test.lxd 'sudo -u cda systemctl --user status ls-db-sync-nightly.timer'
# expect: Unit ... could not be found.  (or "masked")
```

### Rolling out a candidate

`servyy-test` runs no watchtower, so `ls_agent_stage` installs the
`ls-agent-cand-update.timer` **system** timer, running as the stack user (the
compose directory is in the 0750 ssh jail; a `create_user` timer cannot enter
it). Interval: `ls_agent_stage_cand_update_interval`, default 5 min. It pulls
`leaguesphere/backend:agent-candidate` and restarts **only** `cand`, only when
the image id changed, then waits up to 3 minutes for the container healthcheck.
`ref` is never touched.

```bash
# from the leaguesphere checkout (the stack head branch)
gh workflow run deploy.yaml --ref <branch> -f agent_candidate_ref=<branch-or-sha>

# watch the timer pick it up
ssh servyy-test.lxd 'systemctl list-timers ls-agent-cand-update.timer'
ssh servyy-test.lxd 'journalctl -u ls-agent-cand-update.service -n 20'

# then wait until cand reports the new SHA:
curl -u "$LS_AGENT_BASIC_USER:$LS_AGENT_BASIC_PASSWORD" https://<cand-route>/health/version/
```

The helper `container/deploy.sh` still drives the version-bump deploy; the
agent candidate uses the `agent_candidate_ref` input above.

A failed health gate exits non-zero in the journal and leaves `cand` on the new
image; the next timer run retries. Roll back by dispatching a known-good ref.

### opentunnel

Route names are **not** authentication (the hostname appears in Certificate
Transparency logs), hence the basic-auth proxy.

The role installs the CLI idempotently (official installer,
`~/.local/bin/opentunnel` as the deploy user) and registers the two routes:

```text
ref  -> 127.0.0.1:18081
cand -> 127.0.0.1:18082
```

`opentunnel route add <port>` creates the tunnel on the first route, prints
`added route <id> → 127.0.0.1:<port>` and the public
`https://<id>.<tunnel>.opentunnel.xyz` URL, and leaves the encrypted bridge
running as its own service (no systemd unit from this role). The role only
adds a route when `opentunnel route list` does not already contain the port.

Read the current URLs with:

```bash
ssh servyy-test.lxd 'sudo -u cda ~/.local/bin/opentunnel route list'
```

If the installed CLI's `--help` does not advertise `route list`, the role
installs the CLI but skips the routes (to avoid duplicates) and prints the two
manual `route add` commands; run them once and record the URLs. The two HTTPS
tunnel URLs and the basic-auth credential are what the equivalence session
needs.

### What not to do

- Do **not** re-run `ls.app.stage` or `ls.db.sync` on servyy-test during a
  phase; both reset the stage DB.
- Do **not** point watchtower at `ref`; a moving baseline makes every report
  meaningless.
- Do **not** expose the ports beyond loopback; opentunnel is the only ingress.
