# WP-9 — Mongo into the two tiers, `shared.mongo` retired

**Date:** 2026-11-19
**Branch:** `db-tier/wp9-mongo-tiers` (from `6c00f10f`)
**Packages:** `docs/plans/2026-11-18_db-tier-work-packages.md` §WP-9,
`docs/plans/2026-11-17_db-tier-topology.md` Phase 8.
**State:** implemented and proven live on `servy.lehel.xyz`; **not merged** — the
coordinator merges and re-deploys from `master` (the branch was deployed only to
run the copy/cutover proof).

## What was true before (measured, not assumed)

`shared.mongo` — `mongo:9.0`, 512m, volume `shared_mongo_data`
(`/mnt/servy-docker-data/docker/volumes/shared_mongo_data/_data`), network
`shared_backend`, watchtower scope `db`. Three tenants, three consumers reaching
it cross-project:

| tenant | db size | collections | documents | indexes | consumer container |
|---|---|---|---|---|---|
| `leagues_finance` | 794 624 B | 11 | **186** | 30 | `leagues-finance.finance-api` (192.168.64.5) |
| `queen` | 1 126 400 B | 14 | **366** | 33 | `finance.queen` (192.168.64.6) |
| `dontforget` | 1 261 568 B | 14 | **717** | 41 | `dontforget.web` (192.168.64.8) |

Per-collection counts (before, 2026-11-19T09:45Z):

```
leagues_finance {"_migrations":4,"associations":24,"contacts":24,"discounts":0,
  "financialconfigs":40,"financialsettings":1,"invoicelineitems":20,"invoices":8,
  "offers":20,"trackedleagues":42,"users":3}
queen {"accounts":40,"banktransactions":79,"bills":4,"clients":15,"counters":23,
  "emailbills":0,"fiscalyears":2,"invoicelines":39,"invoices":25,
  "journalentries":71,"reconcileruns":58,"settings":1,"suppliers":6,"users":3}
dontforget {"events":48,"feed_tokens":6,"magic_links":18,"model_metrics":398,
  "models":3,"ping_collection":1,"queries":11,"review_tokens":62,
  "schema_migrations":10,"search_metrics":125,"series":22,"sessions":6,
  "stripe_events":0,"users":7}
```

Empty collections were `leagues_finance.discounts`, `queen.emailbills` and
`dontforget.stripe_events` — they exist and were copied (with their indexes);
`mongorestore --drop --nsInclude` recreates an empty collection. Nothing else
was empty.

Users and scopes on `shared.mongo` (all app users were already db-scoped since
WP-2; the server root was the remaining admin identity):

| user | defined in | roles |
|---|---|---|
| `lf_admin` | `admin` | `root@admin` (server admin; used by `dbops`/drills through the container env) |
| `leagues_finance` | `leagues_finance` | `readWrite@leagues_finance`, `dbAdmin@leagues_finance` |
| `queen` | `queen` | `readWrite@queen`, `dbAdmin@queen` |
| `dontforget_app` | `dontforget` | `readWrite@dontforget`, `dbAdmin@dontforget` |

## The two servers

Both are committed compose services, not rendered ones (`db-<tier>/docker-compose.yml`):

| | `db-business.mongo` | `db-private.mongo` |
|---|---|---|
| image | `mongo:9.0` (minor pinned, patch floats; `db` watchtower scope) | same |
| project/network | `db-business`, `db_business_backend` (internal) | `db-private`, `db_private_backend` (internal) |
| memory / cache | 384m, `--wiredTigerCacheSizeGB 0.25` | same |
| datadir | bind `db-business/data/mongo` (D13, on `/`) | bind `db-private/data/mongo` |
| root identity | `business_admin` (own password) | `private_admin` (own password) |
| tenants | `leagues_finance`, `queen` | `dontforget` |
| healthcheck | `mongosh --eval db.adminCommand('ping')`, 30s, start 2s/30s | same |

**No replica set** — both apps run with `MONGODB_DISABLE_TRANSACTIONS=true`, so
there is no keyfile, oplog or election to operate (the reason the plan chose
business over high).

`roles/db_tier` now owns the mongo side the way it already owned MariaDB:
- `tasks/render.yml` renders `db-<tier>/mongo.env` (0600, gitignored) from the
  two new secrets, only for a tier whose inventory has a `mongo` row;
- `tasks/mongo.yml` creates/repairs each tenant's db-scoped user from
  `db_tenants.yml` + the app's existing credential (`tasks/tenant_passwords.yml`),
  after waiting for the mongod's healthcheck. It is gated on the rows of **this
  tier** — a `set_fact` survives across the tier role invocations inside one
  play, and the first run created `leagues_finance`/`queen` on `db-private.mongo`
  for exactly that reason (measured and cleaned up; the gate is now the
  inventory row, not the accumulated map).
- `tasks/configure.yml` splits tenants by engine, so a MariaDB tenant never
  reaches a mongod and vice versa (db-business now has both engines).

The old `shared_mongo_users` role is no longer invoked by `plays/user.yml`; the
three invocations were removed. Its role directory is kept for the rollback week
only (nothing references it).

## The copy, proven before the cutover

New committed play: `ansible/plays/mongo_tier_copy.yml` +
`tasks/mongo_tier_copy_tenant.yml`. Per tenant it dumps from the SOURCE with
`DBOPS_SERVER=<source> dbops dump`, restores into the target with
`DBOPS_SERVER=<target> dbops restore <file> --force`, then proves it with
`DBOPS_SERVER=<source> dbops verify <tenant> --against <target>` (per-collection
document counts) and compares the **index names** of every collection on both
sides. `mongo_copy_require_exact=false` uses `--drill` for a rehearsal, where the
apps are still writing and a lag is expected but a lost/empty collection is not.

Two passes were run:

1. **Rehearsal (apps live)** — `leagues_finance` 186/186, `queen` 366/366,
   `dontforget` 717/717, index sets identical.
2. **Cutover (apps stopped)** — same three tenants, `dbops: ok per-collection
   document counts identical`, index sets identical. Dumps:
   `leagues_finance-20261119T095405Z.archive.gz`,
   `queen-20261119T095423Z.archive.gz`,
   `dontforget-20261119T095456Z.archive.gz` (in the tenants' normal dump dirs,
   so restic carried them; see the drill evidence below).

No collection had a different count; the only "difference" is the natural
document growth of live apps between the two passes (`magic_links` went 17→18
when the write probe ran later).

## Cutover (measured)

`plays/user.yml` change, deployed from the branch on servy:
`leagues-finance` and `queen` now join `db_business_backend` and their
`MONGO_URI` names `db-business.mongo`; `dontforget` joins
`db_private_backend` and its `DATABASE_URL` names `db-private.mongo`. Queen and
leagues-finance **keep** `shared_backend`: that is where `shared.redis` lives
and it is not a database of record. Firefly/importer were untouched.

| app | before (shared.mongo) | after (tier) |
|---|---|---|
| `leagues-finance.finance-api` | 7 pooled connections from 192.168.64.5 | 8 connections from 192.168.48.6 on `db-business.mongo` |
| `finance.queen` | 7 pooled connections from 192.168.64.6 | 8 connections from 192.168.48.7 on `db-business.mongo` |
| `dontforget.web` | 2 pooled connections from 192.168.64.8 | 3 connections from 192.168.112.5 on `db-private.mongo` |
| `shared.mongo` | 20 current / 389 available / totalCreated 20 254 | container **stopped**, 0 connections |

Read/write paths (Mongo profiler at level 2 on the tenant db, then switched off
and `system.profile` dropped):

* **queen** — opening `https://queen.bumbleflies.de/dashboard` produced **16
  operations as `queen@queen`** across `queen.users`, `fiscalyears`, `invoices`,
  `banktransactions`, `reconcileruns`, `clients`, `journalentries`, `bills`,
  `settings`. A write through the app's own `MONGO_URI` (mongoose, inside the app
  container: one insert into a throwaway `__wp9_probe`, counted 1, then dropped)
  succeeded.
* **leagues_finance** — the app was restarted after cutover and its startup
  migration probe issued **4 `find` operations as `leagues_finance@leagues_finance`
  on `leagues_finance._migrations`**; the same in-container write probe inserted
  1 and dropped the collection. (`/login` is the SPA entry point and issues no
  DB query before authentication, so the startup path is the honest read proof.)
* **dontforget** — `POST /api/auth/magic-link` for an existing user returned
  **202** and the profiler recorded the app's real write path as
  `dontforget_app@dontforget`: `findAndModify` on `dontforget.users` and
  `insert` on `dontforget.magic_links` (the test row was removed afterwards;
  `magic_links` is back to 18).

All three public URLs returned 200 before and after the cutover.

## Isolation, shown with the actual errors

Both directions, using the other tier's real application credential (URI host
rewritten to `127.0.0.1` inside the target container so this is an auth test and
not a network test):

```
leagues_finance user -> db-private.mongo : MongoServerError: Authentication failed.
dontforget_app user -> db-business.mongo : MongoServerError: Authentication failed.
```

And on the business server, same-tier isolation still holds:

```
queen user (authSource=queen) reading leagues_finance:
  MongoServerError: not authorized on leagues_finance to execute command
  { aggregate: "invoices", ... }
```

The two server roots are distinct credentials, so neither tier's admin account
works on the other either.

## Inventory, guard and the metric

`db_tenants.yml` rows: `leagues_finance` and `queen` → `server:
db-business.mongo`, `compose_dir: db-business`, `compose_service: mongo`;
`dontforget` → `server: db-private.mongo`, `compose_dir: db-private`,
`compose_service: mongo`. Dump dirs, repos, floors and drill cadence are
unchanged — the repo belongs to the tenant, not the server.

New `db_retired_servers` entry for `shared.mongo` (guard-only; `compose_dir: ''`
because the service left the compose). The guard now compares **eight** servers:
`leaguesphere.db`, `db-nonprod.mariadb`, `db-business.mariadb`,
`db-business.mongo`, `db-private.mariadb`, `db-private.mongo`, `shared.db`,
`shared.mongo` — active mongo servers **3** while the rollback lives (two tiers +
the stopped shared), all `mongo:9.0`. `db_version_drift{engine="mongo"} = 0`;
the guard's D8 mongo equality check passes.

Two guard defects were exposed and fixed on the way: its derived server list
accumulated across guard invocations inside one run (every server printed twice),
and the reset task did not clear it.

## Dumps, probes and one drill after the move

* `db-dump-leagues_finance`, `db-dump-queen`, `db-dump-dontforget` started by
  hand: all `success`; archives 11 580 B / 29 198 B / 24 706 B at 10:05Z (the
  same order of size as before — the growth is app data, not a scope change).
* `db_dump_age_seconds` **6 / 6 / 7 s** for the three tenants (threshold 93 600);
  the probe still reads the inventory dump dirs, unchanged.
* `restic-backup-db-lf` `success`; `restic_snapshot_age_seconds{repo="db-lf"}`
  went from 34 786 s to **3 s** after the snapshot probe ran.
* One real drill from the committed playbook:
  `restore_drill_run_now=true drill_limit_tenant=leagues_finance` →
  **ok, 19.6 s**, scratch `drill-leagues_finance-20261119T100729Z`
  (`mongo:9.0`, network none) removed, `dbops verify leagues_finance --against
  <scratch> --drill` compared **11 collections, 186 / 186 documents, 0 drift**.
  The evidence section (including `live(db-business.mongo)`) is in
  `history/2026-11-19_db-restore-drills.md`.

## `shared.mongo` is retired, not deleted

`docker stop shared.mongo` at 2026-11-19T10:03Z. The container and
`shared_mongo_data` (which still holds all three databases exactly as of the
cutover) are **the rollback**. `shared/docker-compose.yml` no longer defines a
`mongo:` service — a `shared` deploy now configures only `db` and `redis`
(verified with `docker compose config --services` on the host), and there is no
`--remove-orphans`, so a deploy cannot delete the stopped container.

**Rollback (valid for one week):**
```bash
docker start shared.mongo
# revert the three URIs + the app networks and the inventory rows to shared,
# then deploy the app roles. The volume is untouched; the dumps are in
# /home/cda/db-dumps/<tenant>/ (also in restic).
```

**Delete on/after 2026-11-26** (one week, and only after the tenant dumps are
verified restorable from restic):
1. `docker rm shared.mongo` (it is already stopped).
2. `docker volume rm shared_mongo_data`.
3. Remove the `mongo_data` volume declaration from `shared/docker-compose.yml`.
4. Remove the `db_retired_servers` entry from `plays/vars/db_tenants.yml` (then
   the guard's mongo set is the two tier servers and nothing else).
5. Delete the now-unimported `plays/roles/shared_mongo_users/`,
   `plays/tasks/mongo9_migrate.yml` and `plays/tasks/dontforget_mongo_migrate.yml`,
   and the `leagues_finance.mongo_root_username/password` vars + the `shared.env`
   note that references them.
6. WP-10 then removes `shared.db`, at which point the `shared` project is redis
   only. Until WP-10 lands, `shared` holds redis **and** postgres; this page does
   not claim otherwise.

## Do not disable / do not change

* the `db` watchtower scope and healthcheck on both tier mongos (patch window and
  rollback);
* `db_version_guard` / `db_version_drift` — mongo must stay on one line; the
  `shared.mongo` entry is deliberate until step 4 above;
* the `dbops` mongo credential path: it reads `MONGO_INITDB_ROOT_*` from the
  **server container's env**. The restore drill reads the same pair and starts a
  scratch mongod with it. Moving mongo credentials to a tier env file without
  changing both would break every dump and drill;
* the `db_dump_*` / restic timers — the inventory rows still point at the same
  dump dirs and repos, and that is why they kept working unchanged.

## Checks run

* `ansible-playbook --syntax-check` for `plays/user.yml`,
  `plays/mongo_tier_copy.yml`, `plays/restore_drill.yml`, `plays/leaguesphere.yml`.
* `yamllint` on every changed YAML (clean except pre-existing line-length
  warnings in `roles/db_tier/tasks/server.yml`).
* `ansible-lint --profile production` over the whole `ansible/` tree: **passed,
  0 failures / 0 warnings**.
* `bash -n` on the rendered `~/.dbops/dbops` and `~/.restore-drills/restore-drill.sh`.
* `db_tier` molecule scenario extended (mongo tier: two db-scoped users, cross-db
  reads refused, no admin/root roles, MariaDB-only play creates no mongo user)
  and **added to the CI matrix**. This workspace has no Docker socket, so the
  scenario must be proven by CI — it had never run there before (WP-3b recorded
  molecule as blocked), which is why the scenario now also supplies the vars
  `tasks/tenant_passwords.yml` reads from `secrets.yml` on a real host.

## Credentials touched (names only)

* **New:** `db_tier_mongo_root_password_business`,
  `db_tier_mongo_root_password_private` (literal values in the encrypted
  `plays/vars/secrets.yml`; **not** `lookup('password')` seeds — mongo applies
  `MONGO_INITDB_ROOT_*` only when it initialises a datadir, so a seed regenerated
  in a fresh checkout would diverge from the running server). Usernames
  `business_admin` / `private_admin` (templates, not secrets).
* **Reused unchanged:** `vault_leagues_finance_mongo_username/password`,
  `vault_queen_mongo_username/password`, `vault_dontforget_mongo_username/password`
  (the apps' existing credentials, now provisioned on the tiers).
* **Kept for the rollback only:** `leagues_finance.mongo_root_username/password`
  (shared.mongo's root). No app, role or play reads it any more; the stopped
  container's env is the only consumer.
* Nothing was rotated, and no secret value appears in this entry.
