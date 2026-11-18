# 2026-11-18 — a routine deploy can no longer wipe shared.mongo

WP-1 of `docs/plans/2026-11-18_db-tier-work-packages.md` (plan: Phase 1 step 0). No data,
config or topology moved; the point of the change is that one post_task stops being able to
delete all three mongo tenants.

## The hazard

`ansible/plays/user.yml` ran this after every `--tags user.docker` deploy:

1. "Wait for shared mongo to become healthy" — 15 retries × 2 s = **30 s**, `failed_when:
   false`, so the result was only recorded;
2. "Remove corrupted mongo volume and restart if unhealthy" — if that wait had not seen
   `healthy`: `docker_compose_v2 state: absent` on the whole `shared` project (mongo, redis,
   **postgres/Firefly**), `docker_volume state: absent` on **`shared_mongo_data`**, then
   compose `state: present` and another 30 s wait.

`shared.mongo`'s healthcheck was `interval: 30s` with no `start_interval`, so a container the
same play had just recreated had **no** health record yet and sat in `starting` for up to
~30 s. The wait could therefore expire on a perfectly healthy mongo and the play would delete
`shared_mongo_data` — `leagues_finance`, `queen` and `dontforget` in one volume — then start
an empty database. The recreated container was itself produced by ordinary work (a compose
edit, an image tag, a watchtower label), which is why the plan puts WP-1 before every package
that recreates `shared.mongo`.

## What replaced it

| File | Change |
|---|---|
| `ansible/plays/user.yml` | the whole destructive block (compose `absent` → `docker_volume absent` → compose `present` → retry wait) replaced by one `ansible.builtin.fail` that names the container and the observed `State.Health.Status` and points at `docker logs shared.mongo`; the wait task above it is unchanged, tags unchanged |
| `shared/docker-compose.yml` | `shared.mongo` healthcheck gains `start_interval: 2s` and `start_period: 30s` |

`fail` is the whole failure path now: the volume is not touched by any play. The message
states that explicitly ("NOTHING WAS DELETED") so an operator who sees it at 07:00 does not
reach for the old remedy. The task keeps the two `when` guards from the wipe era —
`lf_mongo_upgrading` and `shared_mongo9_migrating` — because those runs bring mongo up
themselves with their own longer waits further down the file; they no longer guard anything
destructive, they only stop this check from second-guessing an in-flight migration.

`grep -n "shared_mongo_data" ansible/plays/user.yml` now matches only
`mongo9_new_volume: shared_mongo_data` in the migration pre_tasks (line 280) and comments —
no removal path is left. The mongo-9 migration pre_tasks are deliberately untouched: they
create/rename that volume legitimately.

**Healthcheck semantics.** `start_interval: 2s` makes Docker probe every 2 s while the
container is starting, so a recreated mongo reports `healthy` in seconds instead of
"whenever the next 30 s tick lands"; `start_period: 30s` gives mongod 30 s of grace before
failures count. Requires Docker Engine ≥ 25 (`start_interval`); servy runs 29.1.3. The
30 s `interval` is kept for steady state, for the load reason recorded in
`history/2026-10-30_load-alert-tuning.md`.

## Backup taken first

All three tenants, dumped inside the running container so no credential is printed or
templated:

```bash
ssh servy.lehel.xyz 'docker exec shared.mongo sh -c '"'"'mongodump --archive --gzip \
  --uri "mongodb://$MONGO_INITDB_ROOT_USERNAME:$MONGO_INITDB_ROOT_PASSWORD@localhost:27017/?authSource=admin"'"'"'' \
  > /home/cda/servyy-container/shared/.backup/mongo-all-pre-wp1-20261118T081534Z.archive.gz
```

**Path** `/home/cda/servyy-container/shared/.backup/mongo-all-pre-wp1-20261118T081534Z.archive.gz`
**Size** 65 609 bytes (64 KiB) — the same convention and directory as the 2026-11-03 mongo 8
dump, covered by the hourly `restic` **home** repo (`/home/cda`, `service/.backup/` is
gitignored).

Restore proof, into a throwaway `mongo:9.0.8` container on servy (dry run *and* a real
restore, then the container removed):

```
dryRun exit=0                      # parses the archive, writes nothing
restore exit=0                     # 1263 document(s) restored successfully. 0 failed
admin,config,dontforget,leagues_finance,local,queen
leagues_finance: collections=11 docs=186
queen:           collections=14 docs=360
dontforget:      collections=14 docs=717
```

Those three lines are byte-for-byte the counts read from the live `shared.mongo` in the same
session, so the archive is a complete, restorable copy of the volume it protects.

## Verification (static — hosts not touched)

This branch was **not** deployed: the owner's rule from 2026-11-18 is that everything is
merged to master before it is deployed. What was verified here:

- `ansible-playbook plays/user.yml --syntax-check -i production` — pass;
  `ansible-playbook servyy.yml --syntax-check -i testing` — pass;
  `yamllint -c ../.yamllint.yml plays/user.yml ../shared/docker-compose.yml` — pass.
  (A full `yamllint .` still exits 1 on 26 pre-existing errors in files this change does not
  touch, `secrets.yml` among them — identical set on master.)
- The new `fail` task was evaluated offline with fake `docker_container_info` registers
  (localhost only): `Status=starting` → fails with the status in the message; `Status=healthy`
  → skipped; `container: null` → fails with "container absent". No host involved.
- No removal path: `grep -n "shared_mongo_data" ansible/plays/user.yml` shows only the
  migration variable and comments.

**Pending, to be appended once the merged commit is deployed** (test host first, then
production):

1. recreate the test `shared.mongo` so it enters `starting`, run the play with tag
   `user.docker` — the wait must pass at `start_interval` speed and
   `docker volume ls` must still show `shared_mongo_data`;
2. stop `shared.mongo` and run the play again — it must FAIL with the new message and the
   volume must still exist;
3. production `./servyy.sh --limit servy.lehel.xyz`: volume present, all three databases
   listable, no destructive task in the run.

## Deploy (after merge only)

```bash
cd ansible
./servyy-test.sh                       # -i testing; recreate + stop-mongo cases above
./servyy.sh --limit servy.lehel.xyz --tags user.docker
```

Rendering the changed healthcheck recreates `shared.mongo` on each host — expected, and now
harmless: it is the exact event that used to be able to wipe the volume.

## Rollback

Revert this commit. The volume was never touched, so there is nothing to restore; the
healthcheck keys and the fail task simply disappear. The dump in
`shared/.backup/mongo-all-pre-wp1-20261118T081534Z.archive.gz` stays as a bonus.

## Follow-ups

- WP-0 owns the next recreate of `shared.mongo` (image tag → `mongo:9.0`, watchtower label →
  `db`) and is explicitly ordered after this package for that reason.
- WP-2 replaces the root credential the apps use; WP-9 retires `shared.mongo` entirely.
