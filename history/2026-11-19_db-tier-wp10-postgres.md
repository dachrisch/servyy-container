# WP-10 — Firefly off PostgreSQL, `shared.db` retired

**Date:** 2026-11-19
**Branch:** `db-tier/wp10-postgres-retirement` (from `4b43c190`)
**Packages:** `docs/plans/2026-11-18_db-tier-work-packages.md` §WP-10,
`docs/plans/2026-11-17_db-tier-topology.md` Phase 9 / D7.
**State:** implemented and proven live on `servy.lehel.xyz`; **not merged** — the
coordinator merges and re-deploys from `master` (the branch was deployed only to
run the copy/cutover proof, exactly like WP-9).

## Context

Firefly III was the last PostgreSQL tenant. `shared.db` (`postgres:15`) held the
`firefly` database (81 tables, 6 530 rows) and was the only reason the host still
ran a third database engine. Firefly is a Laravel application whose own migrations
are the schema source of truth, so the move is a connection change plus a
data-only copy, not a schema translation. The private tier already existed
(`db-private.mariadb`, `mariadb:13.0`) with PhotoPrism and dontforget on it.

Measured before the move (2026-11-19, `shared.db` running):

| fact | value |
|---|---|
| tables | **81** |
| rows (sum of per-table counts) | **6 530** |
| database size | ~13 MB logical; datadir **69 MB** |
| Firefly image | `fireflyiii/core:latest`, label **v6.7.9** (digest `1cb7e7bc…`) |
| transactions | **1 126**, all EUR, absolute sum **243 029.32**, signed sum **0.000000000000** (double-entry) |
| transaction journals | **563** |
| journal_meta | **2 160** |
| accounts | **56** |
| accounts' api balances | 56/56 captured before the cutover |

## Decision

**Let Firefly build the MariaDB schema itself, then copy DATA ONLY table by
table.** A scratch `mariadb:13.0` + the same Firefly image built the schema by
migrations (81 tables, 62 migrations) and the same converter was exercised
against it before the tier was touched. The converter is committed as
`plays/scripts/pg_to_mariadb_copy.py`, driven by
`plays/postgres_to_mariadb_copy.yml`.

The copy is deliberately not `pg_dump | mysql`: each source row is read as JSON
(`row_to_json`), converted against the **target's** `information_schema`, and
written as an explicit multi-row `INSERT`. That preserves `NULL` vs `''`,
decimal scale, timestamps and UUID text without the CSV/backslash ambiguities of
a text pipeline.

## What the schema actually contained, and what had to be transformed

| PostgreSQL | MariaDB (from Firefly's own migrations) | count | transform |
|---|---|---|---|
| `bigint` | `bigint(20) unsigned` | 47 | integer text; **no negative values measured in any unsigned target column** (233 checked) |
| `integer` | `int(10) unsigned` / `int(11)` / `mediumint(8) unsigned` | 172 | same |
| `smallint` | `smallint(5) unsigned` / `tinyint(3) unsigned` | 18 | same |
| `boolean` | `tinyint(1)` | 41 | `true/false` → `1/0` |
| `numeric(32,12)` | `decimal(32,12)` | 31 | `Decimal`, never `float`; exact scale kept |
| `numeric(12,8)` | `decimal(12,8)` | 4 | same |
| `timestamp without time zone` | `timestamp` (157) / `datetime` (11) | 168 | verbatim; `row_to_json` writes `T`, MariaDB stores a space; **0 rows had fractional seconds**; min/max `2026-06-03 08:55:28`…`2026-11-19 08:35:41`, inside TIMESTAMP's 1970–2038 window |
| `uuid` | `char(36)` | 6 | canonical lowercase text |
| `character(8)` / `character(80)` | `char(8)` / `char(80)` | 6 | blank-padded; compared unpadded |
| `text` | `text` / `longtext` | 32 | verbatim |
| `character varying(n)` | `varchar(n)` | 123 | lengths identical |
| `json/jsonb/bytea/ARRAY/domain` | — | **0** | nothing to transform |

Also measured: **0 nullability differences** across all 669 columns; the only
structural difference was **column order** in `account_balances` (same set,
values matched by name). No `zero dates` (PostgreSQL cannot store them), no
negative unsigned values, no case-only duplicate unique keys.

Session settings for the load: `FOREIGN_KEY_CHECKS=0` and `UNIQUE_CHECKS=0`
per batch, re-enabled after each batch; `NO_BACKSLASH_ESCAPES` **added** to the
existing strict `sql_mode` (not replacing it), so the only string escaping is
`'` → `''`; `time_zone='+00:00'`; `NAMES utf8mb4 COLLATE utf8mb4_unicode_ci`.

**Order.** PostgreSQL's 114 foreign keys were topologically sorted (Kahn), so
parents load before children; the printed order starts
`account_types, audit_log_entries, configuration, failed_jobs, jobs, link_types,
locations, migrations, notes, notifications, oauth_*, … user_groups, user_roles,
webhook_*, … transaction_currencies, transaction_types …`. FK checks were
disabled anyway, so a cycle or an order mistake cannot abort a load half way.

**Sequences.** There are 62 `*_id_seq` in PostgreSQL. After each table the
converter sets `AUTO_INCREMENT = max(id)+1` (the WP-10 requirement), e.g.
`transactions` 1148 → **1149** (PG sequence was 1151), `journal_meta` 2182 →
**2183** (PG 2185), `users` 1 → **2** (PG 29, because deleted users had advanced
the sequence). Deleted rows have no surviving references (FKs), so reusing those
numbers is safe; the deliberate cost is that the next ids are lower than
PostgreSQL's.

## Scratch rehearsal (before touching production)

- scratch `mariadb:13.0` with the private tier's exact flags
  (`utf8mb4_unicode_ci`, `READ-COMMITTED`, 512 connections, 128M pool);
- scratch Firefly from the **same image digest**, entrypoint ran
  `firefly-iii:create-database` + `upgrade-database` → **81 tables, 62
  migrations**, migration names identical to the source;
- copy: **6 530 rows / 81 tables in 37.4 s**;
- verify: **81/81 tables row-identical**, per-currency sums identical,
  **56/56 account balances identical**;
- the Firefly API on the scratch copy returned **56/56 identical
  `current_balance` values** to the live instance;
- OAuth/PAT finding: a JWT-signed PAT returned **401** on the scratch container
  until the live `oauth-private.key`/`oauth-public.key` were copied in, then
  **200**. The production recreate came up with the same pair (see below), but
  the pair must be treated as part of the app's state, not as data in the DB.

## Cutover (measured)

The app was stopped so the final copy had a quiescent source:

1. `docker stop finance.importer`, `docker stop finance.firefly` (13:0xZ).
2. Final copy with `--truncate`: **81/81 tables row-identical**,
   **6 530 rows**, per-currency sums and 56 account balances identical.
3. Deploy `user.docker.finance` from the branch: `finance.firefly`,
   `finance.importer` and `finance.queen` were **recreated at
   13:14:34–35Z** (queen was a project-wide `up` side effect; no config change).
   `db-private.mariadb` was **not** recreated (created 2026-11-18T16:58:14Z).
4. New container env: `DB_CONNECTION=mysql`, `DB_HOST=db-private.mariadb`,
   `DB_PORT=3306`, `DB_DATABASE=firefly`, `DB_USERNAME=firefly`; networks
   `proxy`, `finance_backend`, `db_private_backend`; `shared_backend` gone.
5. `firefly-iii:upgrade-database` logged **“Nothing to migrate.”** — the copied
   `migrations` table is authoritative.
6. Post-cutover: `/login` **200**, API accounts **200** and **56/56**
   `current_balance` values identical to the pre-cutover capture; the importer's
   authenticated call to Firefly **200**, and a full `/import/run-import.sh`
   ran **13:31:34–13:32:46Z, exit 0** (no new transactions: 563/1126/2160
   unchanged).
7. **No query reaches Postgres**: `pg_stat_activity` had **0** firefly client
   backends (only the inspecting `psql` itself).
8. The OAuth key pair in the recreated container has the **same SHA-256** as the
   pair saved before the recreate (`4a08…` / `936f…`), which is why the
   importer's PAT kept working. A standalone scratch container generated a
   different pair and the same PAT got 401 — so `oauth-*.key` is app state:
   never delete it, and copy it back if a future recreate regenerates it.

## Financial invariant

The gate is not row counts. On both engines, with the **same SQL expressions**:

- per currency: `EUR` **1 126** rows, `SUM(amount)` **0.000000000000**,
  `SUM(ABS(amount))` **243 029.32**;
- per account: `SUM(transactions.amount)` + `COALESCE(virtual_balance,0)` for
  **56/56** accounts identical; ledger total **0.000000000000** (double-entry);
- the UI's own source, `app/Support/Steam.php::accountsBalancesOptimized()`, is
  exactly that per-(account,currency) sum plus the virtual balance — all virtual
  balances are NULL/0, so the API comparison above is the UI balance
  comparison: **56/56 identical before and after**.
- row-level: every table compared as a multiset of canonical column tuples
  (not just counts) — **0 differences**.

## Retirement: stopped, not deleted

`docker stop shared.db` at **2026-11-19T13:16:20Z**. The container, its image
(`postgres:15`) and its bind-mounted datadir
(`/mnt/servy-docker-data/docker/finance/db`, **69 MB**, untouched) are the
rollback. `shared/docker-compose.yml` no longer defines the `db:` service; a
`shared` deploy was run after the stop and `docker compose config --services`
reports **only `redis`**, while `shared.db` stayed `Exited (0)` and `shared.mongo`
stayed `Exited (0)` (no `--remove-orphans`). `shared.redis` itself was recreated
by that deploy (13:18:22Z, same image, healthy) — the only unrelated restart.

**Rollback (valid until 2026-12-19):**
```bash
docker start shared.db
# revert this package's inventory row (engine/server) + finance compose +
# shared compose, then deploy user.docker.finance. The datadir is untouched.
```

**Delete on/after 2026-12-19** (one month; only after the tenant has a green
month of MariaDB dumps and at least one green drill):

1. Prove the newest `db-private-firefly` snapshots are MariaDB dumps and that
   the last drill was `ok` (`~/.restore-drills/state/firefly`).
2. `docker rm shared.db` (already stopped).
3. `sudo rm -rf /mnt/servy-docker-data/docker/finance/db` — **irreversible**,
   the 69 MB datadir.
4. Remove the `shared.db` entry from `db_retired_servers` in
   `plays/vars/db_tenants.yml`.
5. Remove the commented `db:` block from `shared/docker-compose.yml` and the
   `POSTGRES_PASSWORD` line from `finance/.env.j2`; then remove
   `shared/.env.j2` + its `env_templates` entry in `plays/user.yml` if nothing
   else reads `shared.env` (redis does not).
6. Delete `roles/restic/templates/firefly_dump.sh.j2` and the
   `tenant_row.engine == 'postgres'` branch in `roles/restic/tasks/backup.yml`.
7. Delete the postgres recipe from
   `roles/restore_drill/templates/restore_drill.sh.j2` (`wait_postgres`,
   `pg_counts`, `drill_postgres`, the `postgres)` case) and `postgres` from the
   guard's allowed-engine assert if it is no longer a legal engine.
8. Old postgres-format snapshots in `db-private-firefly` age out under
   `db_daily_short` (14 dailies + 4 weekly); no manual prune needed.

Do **not** delete `shared_mongo_data` in the same change — that is WP-9's own
checklist (`history/2026-11-19_db-tier-wp9-mongo-tiers.md`, on/after
2026-11-26).

## Inventory, guard and drift

`db_tenants.yml` `firefly` row: `engine: mariadb`, `server:
db-private.mariadb`, `compose_dir: db-private`, `compose_service: mariadb`.
`dump_dir`, `restic_repo` (`db-private-firefly`), `size_floor_bytes`, `probe_minutes`,
`severity` and `drill: monthly` are **unchanged** — the repo belongs to the
tenant, not to the engine.

`db_retired_servers` gained `shared.db` (`compose_dir: ''`, `retiring: false`)
for the rollback month. The guard now compares **8** servers:
`leaguesphere.db`, `db-nonprod.mariadb`, `db-business.mariadb`,
`db-business.mongo`, `db-private.mariadb`, `db-private.mongo`, `shared.mongo`,
`shared.db`; four MariaDB 13.0, three mongo 9.0, **one** postgres 15. The D8
minor-line check passes for every engine.

Drift pushed after the stop: **`db_version_drift{mariadb}=0`,
`{mongo}=0`, `{postgres}=0`**. Postgres is a single *stopped* server, so its
drift is honestly 0 (one image ID); it is not a claim that Postgres is in
service. The entry is removed with the container on 2026-12-19.

## Dump, snapshot and drill after the move (same repo, same directory)

- `~/.backup-scripts/dump-firefly.sh` now renders `dbops_dump.sh.j2` (selected
  by **engine**, not tenant name) and ran by hand:
  **13:25:37Z, `firefly-20261119T132537Z.sql.gz`, 179 035 B, 81 `CREATE TABLE`,
  `gzip -t` OK**, in `/home/cda/db-dumps/firefly/current` (unchanged path).
- `restic-backup-db-private-firefly.sh`: snapshot **`37587d55`** at
  **13:25:46Z**, **174.839 KiB**, same repo
  `sftp://storagebox/backup/servy.lehel.xyz/restic-db-private-firefly`.
- `plays/restore_drill.yml -e restore_drill_run_now=true
  -e drill_limit_tenant=firefly`: **ok, 57.5 s**, snapshot `37587d55`,
  scratch `drill-firefly-20261119T132659Z` (`mariadb:13.0`, network none,
  removed), **81 tables, 6 530 / 6 530 rows, 0 drift, checksum-identical**.
  Evidence appended to `history/2026-11-19_db-restore-drills.md`.
- Probes after the move: `db_dump_age_seconds{tenant="firefly"} = 297 s`
  (threshold 93 600), `restic_snapshot_age_seconds{repo="db-private-firefly"} =
  316 s` (threshold 93 600). Same tenant/repo labels, no alert-file change.

## Credentials touched (names only)

- **Reused, not invented:** `finance.db_password` is now also the `firefly`
  MariaDB account's password (the same key `finance/.env.j2` renders as
  `DB_PASSWORD`). No rotation, no new secret, no value in this entry.
- `dbops_backup_private` gained `SELECT, LOCK TABLES, SHOW VIEW, EVENT, TRIGGER
  ON firefly.*` (the dump identity; still no write grant).
- The OAuth JWT key pair `storage/oauth-private.key` / `oauth-public.key` is
  app state. Saved before the recreate and verified identical after; never
  deleted or printed.

## Checks run

- `ansible-playbook --syntax-check` for `servyy.yml`, `plays/user.yml`,
  `plays/restore_drill.yml`, `plays/postgres_to_mariadb_copy.yml`,
  `plays/leaguesphere.yml`, `plays/mongo_tier_copy.yml`.
- `yamllint` on every changed YAML (clean; the pre-existing noise is in
  `secrets.yml`, `ls_db_migrate`, `ls_demo`, `db_tier/tasks/server.yml`).
- `ansible-lint --profile production` over the whole `ansible/` tree:
  **passed, 0 failures / 0 warnings**.
- `bash -n` on the rendered `~/.backup-scripts/dump-firefly.sh` and
  `~/.dbops/dbops`.
- `python3 -m py_compile` on the converter.
- `db_tier` molecule scenario: the private play now supplies
  `finance.db_password`; CI runs it (no Docker socket on this controller).
- The branch deploy needed one new knob: `docker_branch` (commit `482dceba`),
  because a global `-e branch=<feature>` also hit the zprezto clone and failed
  the run. The normal controller-HEAD default is unchanged.

## Do not disable / do not change

- **Do not start `shared.db` while Firefly points at MariaDB** — that is a split
  brain, not a rollback. The rollback is `docker start shared.db` **and** revert
  the row/compose in the same sitting.
- **Do not delete `db-private-firefly`'s repo, timer, dump dir or floor** before
  the 2026-12-19 checklist; it is the tenant's only off-host copy, and its
  identity is deliberately unchanged across the engine move.
- **Do not rotate `finance.db_password` on one side only.** It is both the
  app's `DB_PASSWORD` and the MariaDB user's password; `db_tier` re-applies it
  from `secrets.yml`.
- **Do not add the `db:` service back to `shared/docker-compose.yml`** and do
  not add `--remove-orphans` to the shared deploy: the stopped container is the
  rollback.
- **Do not drop the OAuth key pair.** The importer authenticates with a
  JWT-signed PAT; a new key pair invalidates it (measured 401 on the scratch
  container).
- **Do not change the private tier's `utf8mb4_unicode_ci`** or its server flags:
  the schema was created with them and joins/collation are part of the data.
- **Do not read `db_version_drift{engine="postgres"} = 0` as “postgres is
  healthy”** — it means one stopped server, no drift. The engine is retired.
- **Do not run the full `./servyy.sh`** for the deployment; use
  `--tags user.repo.clone,user.docker.finance` (plus
  `user.docker.env.finance` when the Enable Banking PEM fact is needed — a
  known non-self-contained tag, recorded as a follow-up below).

## Known follow-ups

- `--tags user.docker.finance` still fails without
  `user.docker.env.finance` (the PEM fact). It failed safely before any compose
  action and is unchanged from the pre-existing follow-up list.
- Firefly's retention stays `db_daily_short` (14 dailies + 4 weekly) because
  WP-10's contract was an unchanged dump path. Revisit as its own change now
  that it is a permanent MariaDB tenant.
- The shared project's `shared.env`/`.env.j2` still renders `POSTGRES_PASSWORD`
  for the stopped container; remove it in the 2026-12-19 cleanup.
- `finance.queen` and `shared.redis` were recreated as side effects of the
  project-wide `compose up` (13:14:34Z and 13:18:22Z, same images); both
  healthy, no config change.
