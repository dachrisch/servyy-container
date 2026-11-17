# 2026-11-17 — dontforget: own mongo container retired, db moved into shared.mongo

## Problem

dontforget was the last service still running its own database container. When
the data layer was consolidated (`c82b387`, 2026-10-06) leagues-finance and
finance/queen moved onto `shared.mongo`, but dontforget kept
`dontforget.mongo` in its own compose project — a second mongod on a 4-core box
that is queue-bound rather than CPU-bound, for a database that holds 1.1 MB
(14 collections, ~700 documents, mostly `model_metrics`/`search_metrics`).
Its mongo 9 migration (`3c308db`) had already duplicated the effort of the
shared one, volume by volume.

## Solution

`dontforget.mongo` is gone. The `dontforget` db lives in `shared_mongo_data`,
reached cross-project as `shared.mongo` on the `shared_backend` network — the
same pattern leagues-finance and queen use.

Files:

| File | Change |
|---|---|
| `dontforget/docker-compose.yml` | `mongo` service, `depends_on`, the `internal` network and the `mongo_data` volume block removed; `web` joins `shared_backend` (`external: true`) |
| `templates/dontforget/web.env.j2` | `DATABASE_URL` → `shared.mongo:27017/dontforget?authSource=dontforget`; `MONGO_INITDB_ROOT_*` dropped (they only ever existed for the local entrypoint) |
| `plays/tasks/dontforget_mongo_migrate.yml` | new one-time dump/restore + orphan-container removal (see below) |
| `plays/roles/shared_mongo_users/` | new role: provisions dedicated db-scoped users in shared.mongo |
| `plays/user.yml` | DBS-1820 root-user pre-task and the dontforget `mongo9_migrate` import removed; the new migrate task imported; `shared_mongo_users` invoked right after the `shared` role |
| `plays/vars/secrets.yml` | `vault_dontforget_mongo_username` / `_password` (dedicated user); the old root pair kept only for the one-time dump |

### Dedicated user, not shared's root

league-finance and queen authenticate as shared's root (`lf_admin`), so a
compromised app can read the other's data. dontforget gets `dontforget_app`,
created in — and scoped to — the `dontforget` db with `readWrite` + `dbAdmin`
(the latter for `collMod`/index work in its schema migrations). Nothing else is
granted; there is no cross-database or `admin` role.

The credential cannot live in `/docker-entrypoint-initdb.d` because init scripts
only run on a FRESH volume and `shared_mongo_data` already exists. The
`shared_mongo_users` role therefore does it with one idempotent `mongosh` call
per deploy: it prints a JSON array of the users it created or repaired, and
`changed` is decided by that output — a re-run with an unchanged user touches
nothing. Password rotation is opt-in (`shared_mongo_rotate_passwords: true`)
because the stored SCRAM hash cannot be compared to the vault value, so
re-applying it every deploy would report `changed` forever.

### One-time data move

`plays/tasks/dontforget_mongo_migrate.yml` runs in `pre_tasks` (before any
service role starts the app) and triggers only while all three hold:

1. `dontforget.mongo` still runs,
2. `shared.mongo` is running,
3. `shared.mongo` does not have a `dontforget` db yet.

It then stops `dontforget.web`, counts documents per collection, `mongodump
--db dontforget --gzip --archive` inside the retired container, copies the
archive to `<remote>/dontforget/.backup/dontforget-db-<ts>.archive.gz` and into
`shared.mongo`, restores with `--nsExclude=admin.* --nsExclude=config.*`,
asserts the per-collection counts are identical, and removes the orphan
container — which is no longer in the compose file, hence no longer covered by
the container-health probe and would otherwise keep running unmonitored.

If the retired container holds the data but `shared.mongo` is not running, the
task fails loudly instead of retiring anything.

Kept as rollback copies: the volume `dontforget_mongo9_data` (pre-9 volume
`dontforget_mongo_data` was already kept by the 2026-11-03 migration) and the
dump in `.backup/` (gitignored, covered by the restic `/` backup).

## Verification (before the production deploy)

dontforget is prod-only (`ansible/testing` does not enable it, only its TLS vars
are left over), so there is no test-host rehearsal; the two riskier halves were
rehearsed on production without touching the live db instead.

- The user-provisioning JS was run against the live `shared.mongo` with a
  throwaway user — first the hand-checked script, then the exact artifact Ansible
  renders (`lookup('ansible.builtin.template', …)`, verified with a throwaway
  role): first run `["rendercheck_user:created"]`, second `[]` (no change), a
  roles change was also exercised (`["selftest_user:roles"]`), then unchanged;
  user dropped and `listDatabases` back to its original set.
- The dump/restore was rehearsed on production without touching the live db:
  `mongodump` from `dontforget.mongo`, `mongorestore` into `shared.mongo` as
  `dontforget_rehearsal` with `--nsFrom/--nsTo`. All 14 collections matched
  document-for-document (716 documents, 0 failures) and the 39 indexes came
  back; the rehearsal db and every temp file were dropped afterwards.
- `yamllint`, `ansible-lint` and `ansible-playbook servyy.yml --syntax-check` pass.

## Deploy

```bash
cd ansible
./servyy.sh --tags "user.docker.repo,user.docker.shared,user.docker.dontforget" --limit servy.lehel.xyz
```

`--limit` takes the INVENTORY name (`servy.lehel.xyz`), not the SSH alias
`lehel.xyz`: the alias matches no host, so the run silently does nothing.

Each tag is load-bearing (Ansible tag matching is exact, not hierarchical):

- `user.docker.repo` — syncs the server checkout from this repo. Without it the
  server still runs the OLD `dontforget/docker-compose.yml` (mongo service, web
  on its own `internal` network) while the freshly rendered `web.env` already
  points at `shared.mongo` — the app comes up unable to reach its database.
  `docker_service` does no repo sync itself.
- `user.docker.shared` — deploys the shared project, so `shared_backend` and
  `shared.mongo` are current before the app moves onto them.
- `user.docker.dontforget` — the migration pre_tasks, the dedicated user, and
  the app itself.

`--tags user.docker` also works (it selects everything in the docker play,
~283 tasks) but redeploys every service on the host for a single-service change.

Expected order on servy: pre_tasks move the db and remove `dontforget.mongo`,
then `shared` (mongo healthy), then `shared_mongo_users` (creates
`dontforget_app`), then `dontforget` (app starts on the new `DATABASE_URL`).
Downtime is the app stop in pre_tasks plus the ~2 s restore of 716 documents.

Verify afterwards: `dontforget.web` healthy and serving,
`docker ps` has no `dontforget.mongo`, `docker exec dontforget.web` can reach
`shared.mongo`, and the Grafana `container_not_running` alert has no
`dontforget.mongo` series.

## Rollback

Restore the `mongo` service block in `dontforget/docker-compose.yml` and the
pre-2026-11-17 `DATABASE_URL` in `web.env.j2`, redeploy, then restore
`dontforget/.backup/dontforget-db-<ts>.archive.gz` (or the untouched volume)
into the recreated container.

## Follow-ups

- `shared` is not listed in `docker.services` (`plays/vars/secrets.yml`), so
  `container_not_running` does not cover `shared.mongo`/`shared.redis`/
  `shared.db` — already true for leagues-finance and queen before this change,
  but now a single mongo serves three apps.
- Once `dontforget_mongo9_data` is deleted, remove
  `vault_dontforget_mongo_root_username` / `_password` and the migrate task file.
