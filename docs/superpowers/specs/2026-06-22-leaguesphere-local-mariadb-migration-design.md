# Design: Migrate LeagueSphere prod DB → local MariaDB

- **Date:** 2026-06-22
- **Status:** Approved (brainstorming) — pending implementation plan
- **Repos affected:** `container` (Ansible, compose, restic), `leaguesphere` (prod compose, mysql-init)
- **Owner:** christian.daehn@bumbleflies.de

## Problem

LeagueSphere **prod** currently runs its database on an **external** MySQL at
`s207.goserver.host` (`web35_db8`). We are bringing that database in-house: prod will run its
own **local MariaDB** container, like stage already does, but **production-grade** —
consistent backups, tested restore, and **no public exposure** (the DB is reachable only over
the internal Docker network). This is a **one-time switch**, not a permanent dual-run.

The transition must be **smooth, not a big-bang cut-over**: all risky setup happens with zero
prod impact first, the new instance is **live-validated through the real app on stage**, and the
external DB is kept **untouched as a hot rollback** for a retention window.

## Constraints & assumptions

- **External DB access = normal DB user only.** `s207.goserver.host` is a shared hoster; we
  have a `mysqldump`-capable user (as `ls_db_sync` already uses) but **no `SUPER`/`REPLICATION`
  privileges and no shell** on the box. → Live MySQL→MariaDB replication is **out of scope**;
  the migration is **dump-based**. (Can be confirmed with a single read-only `SHOW GRANTS`, but
  the design does not depend on it.)
- **No public exposure.** The new DB must have **no published host port** and live on an
  `internal: true` Docker network — reachable only by the LeagueSphere containers.
- **Test-first, no manual prod edits** (repo policy): everything validated on
  `servyy-test.lxd` first, prod only after explicit approval, all via Ansible automation.
- **Rollback retention:** external DB kept untouched for **14 days** post-cutover (override on
  request), then references decommissioned.

## Tooling decision: `mariadb-backup` vs `mysqldump`

The two tools are **complementary**, used for different jobs:

| | `mariadb-backup` (physical) | `mysqldump` (logical) |
|---|---|---|
| Granularity | **Whole instance** (all DBs + `mysql` system tables: users, grants) | Per-database, portable SQL |
| Restore | Stop server, **wipe datadir**, `--copy-back`, `chown`, start | Import into **any DB name** on a **running** server |
| Used for here | **Prod's own backup & disaster recovery** (instance identity preserved) | **External→local seed** *and* **local-prod→stage sync** (cross-instance, cross-DB-name) |

- **`mariadb-backup`** is the right tool for prod backing up and restoring **itself** — same
  instance identity. It produces a **consistent, non-blocking physical** backup of the running
  server (`--backup` → `--prepare`), which restic then captures.
- **`mysqldump`** is the right tool for **cross-instance / cross-DB-name** copies. Using
  `mariadb-backup` for the stage sync would be wrong: a `--copy-back` onto stage makes stage a
  byte-for-byte clone of prod's instance (prod DB name `leaguesphere`, prod app user, prod
  grants/passwords) and **wipes stage's datadir** — fighting the prod/stage separation that
  `ls_db_sync` maintains. `mysqldump --single-transaction` gives a consistent InnoDB snapshot
  and imports cleanly into the differently-named `leaguesphere_stage`; the dataset is small.

## Target architecture

Add a `db` service to the **prod** compose (`leaguesphere/deployed/docker-compose.yaml`),
mirroring the proven staging setup:

- `image: mariadb:latest`, container **`leaguesphere.db`** (compose service `db`, following the
  deck's `{project}.{service}` convention), `utf8mb4` server defaults, healthcheck copied from
  staging.
- Bind mounts:
  - `./mysql-data:/var/lib/mysql` — data directory.
  - `./mysql-backup:/backup` — **new**; `mariadb-backup` output (host-visible for restic).
- Init: reuse `mysql-init/01-create-staging-db.sh` to create the prod database + app user, and
  **add a dedicated `mariadb-backup` user** with `RELOAD, PROCESS, LOCK TABLES, REPLICATION
  CLIENT` (and `INSERT/CREATE/ALTER` on the history table if `--history` is used).
- **Networking — not exposed:** `db` joins **only** `backend` (`internal: true`). **No
  published ports.** The `app` service moves off the external-facing `database` network onto
  `backend`; the prod `database` network (`internal: false`) is **removed**. Net result: the DB
  is reachable only over the internal Docker network — no host port, no public surface.
- App config: prod Django `DATABASES['default']['HOST']` → `leaguesphere.db`, via the existing
  `ls.env` / `secret_main.yaml` mechanism.

> **Stage naming:** the new prod service is `db`; stage keeps its existing `mysql` service to
> avoid scope creep (renaming it would touch `ls_app/tasks/deploy.yaml`'s hardcoded `.mysql`
> references). Aligning stage to `db` later is optional.

## Backup & restore (`mariadb-backup` + restic)

**Backup** — a systemd timer (existing `restic/tasks/oneshot_include.yml` pattern) runs a
script that operates **inside the container** so the `mariadb-backup` version always matches the
server version:

1. `docker exec leaguesphere.db mariadb-backup --backup --target-dir=/backup/new --user=<backup-user> --password=<…>`
2. `docker exec leaguesphere.db mariadb-backup --prepare --target-dir=/backup/new`
3. Atomically swap `/backup/new` → `/backup/current` (keep the previous prepared set until the
   new one is complete).

**Restic capture — the jail changes where this data lands (verified).** Prod deploys to
`container_dir = /var/jail/home/leaguesphere/container/` (the SSH chroot jail,
`ssh_chroot_jail_path = /var/jail`, owned by the `leaguesphere` user). So the bind mounts
resolve to `/var/jail/home/leaguesphere/container/mysql-data` and `.../mysql-backup`. Against
`restic.yml`:

- `restic.home` (`source_path = /home/{{ create_user }}`, **hourly**) — **does NOT cover** the
  jail tree. (PhotoPrism rides the home repo because it lives in the admin user's home;
  LeagueSphere does not.)
- `restic.root` (`source_path = /`, **daily**, excludes `/var/lib/docker`, `/var/cache`,
  `/var/tmp`, logs) — **does cover** `/var/jail/...` (under `/var`, matches no exclude).

> **Load-bearing design choice:** the DB uses a **bind mount** to `/var/jail/...`, *not* a named
> Docker volume — a named volume would fall under the `/var/lib/docker` exclude and be **silently
> not backed up**.

**Cadence decision:** prod DB is backed up **hourly** via a **dedicated restic entry + systemd
timer** for the `mysql-backup` path (matching the home cadence), rather than relying on the daily
root repo. This minimizes the data-loss window and gives the DB its own repo/restore target.

**Restore** — add a new env-aware `restore.yml` include to `restic/tasks/main.yml` for the DB
backup path, reusing the existing decision matrix (fail on test if no snapshot, skip on healthy
prod when the dir is non-empty / containers running). **The restore block must reference the new
dedicated DB repo** (`backup_name`), not `home` (which the existing Gitea/PhotoPrism/Vaultwarden
blocks use). Recovery procedure:

1. Restore the backup path from restic.
2. Stop `leaguesphere.db`.
3. `mariadb-backup --copy-back` the prepared set into `mysql-data` (empty datadir first).
4. `chown -R mysql:mysql` the datadir.
5. Start `leaguesphere.db`; verify healthcheck.

## Transition: pre-seed + brief delta cutover

### Phase A — Build (zero prod impact)
- New Ansible role/tags (working name `ls_db_migrate`) stand up `leaguesphere.db` in prod
  **alongside** the still-live external DB. The app **stays on external**.
- Seed local from a `mysqldump` of the external prod DB (reuse `ls_db_sync` export logic,
  ignoring all views).

### Phase B — Validate live via stage (zero prod impact)
- **Repoint `ls_db_sync`'s source** from the external host to the **local prod container**:
  `docker exec leaguesphere.db mysqldump …` (runs on the host; no network exposure needed).
- Stage then pulls from `leaguesphere.db`, so the **real LeagueSphere app runs end-to-end
  against data that round-tripped through the new MariaDB**. If stage behaves, the new instance
  + dump/restore path are validated *with the actual application*, not just row counts.
- **Shadow freshness = on-demand re-seed:** while prod still writes to external, re-run the
  (zero-impact) external→local seed whenever a refresh is wanted, then re-sync stage from local.
  Row-count parity (local vs external) is most meaningful immediately after a fresh seed.
- Validate `mariadb-backup` + restic with a **full restore drill on `servyy-test.lxd`**.

### Phase C — Cutover (short read-only window)
1. Put the prod app in read-only / maintenance (no in-flight writes).
2. Final `mysqldump` delta from external → import into `leaguesphere.db` (guarantees identical
   state).
3. Flip prod `DATABASES['default']['HOST']` env → `leaguesphere.db`; redeploy the app.
4. Verify app health; lift maintenance.

### Phase D — Rollback safety
- The external DB is **never modified** and stays live as a **one-env-flip rollback** for
  **14 days**. Rolling back = revert the host env and redeploy.
- After the retention window: retire the external-host dump path in `ls_db_sync` (its source is
  now permanently `leaguesphere.db`), remove external DB credentials/references, decommission.

> **`ls_db_sync` evolves, not duplicated.** The source swap (external host → `leaguesphere.db`)
> is correct **both** during validation **and permanently after cutover**, since post-cutover
> the local container *is* prod. The external-host export path is retired with the external DB.

## Test-first validation (repo policy)

All changes validated on `servyy-test.lxd` before prod, with explicit approval before any prod
deploy:

1. Stand up a prod-like stack (incl. `leaguesphere.db`) on `servyy-test.lxd`.
2. Seed it via `mysqldump`.
3. Run the `mariadb-backup` timer → confirm restic captures the path.
4. **Full restore drill**: restore from restic → `--copy-back` → start → verify data + health.
5. Confirm stage-from-local sync works.

## Affected components

- **`container` repo**
  - `ansible/plays/roles/ls_db_migrate/` (new) — seed + delta orchestration.
  - `ansible/plays/roles/ls_db_sync/` — source swap (external host → `leaguesphere.db`).
  - `ansible/plays/roles/ls_app/` — prod app DB host env, network change, `db` service deploy
    handling.
  - `ansible/plays/roles/restic/tasks/main.yml` — new DB `restore.yml` include block.
  - backup timer wiring (`oneshot_include.yml` pattern) + backup script template.
  - secrets: `secret_main.yaml` (prod DB host → `leaguesphere.db`, backup-user creds).
  - `docs/leaguesphere-environments.md` — update the matrix (prod DB now local).
- **`leaguesphere` repo**
  - `deployed/docker-compose.yaml` — add `db` service, `./mysql-backup` mount, network change.
  - `deployed/mysql-init/` — backup-user grant (and prod DB/user creation for prod).

## Open items to resolve in the implementation plan

1. ~~Restic coverage of the backup path inside the chroot jail~~ **RESOLVED:** prod lives in
   `/var/jail` (covered only by the daily root repo), so the DB gets a **dedicated hourly restic
   entry + timer** for `/var/jail/home/leaguesphere/container/mysql-backup`, with its own
   restore repo. The plan must wire this new entry (repo URL, password, schedule) and point the
   `restore.yml` block at it.
2. Exact `mariadb-backup` user grants and whether to use `--history`/incremental backups (start
   with full backups; incremental is a later optimization).
3. Backup timer ordering — the `mariadb-backup` step must complete (produce a fresh
   `mysql-backup/current`) **before** the dedicated hourly restic run captures it.
4. Confirm prod Django settings module reads DB host from env cleanly for the cutover flip.
5. Read-only/maintenance mechanism for the prod app during Phase C.

## Out of scope

- Live replication from the external DB (no privileges).
- App-level dual-write (evaluated and rejected: real Django changes + silent-divergence risk
  for marginal benefit on a low-write app).
- Renaming stage's `mysql` service to `db` (optional future alignment).
- Incremental `mariadb-backup` (full backups first; revisit later).
