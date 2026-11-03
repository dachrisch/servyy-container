# 2026-11-03 — shared.mongo 8 → 9.0.4 (kernel ≥ 6.19 incompatibility)

## Problem

Since servy booted kernel `7.0.0-42-generic` (2026-10-29 05:30 unattended
reboot), watchtower rolled `shared.mongo` back to the July `mongo:8` image
(`e0ce8c35`) every ~2 h: **50 rollbacks** since 2026-10-30 11:00, each about 30 s
of mongo downtime for leagues-finance and queen.

The newer `mongo:8` image did not become unhealthy. It exited with code 1 before the
healthcheck ever ran:

```
MongoDB cannot start: Linux kernel versions 6.19 and newer has a known
incompatibility with this version of MongoDB. See SERVER-121912
```

This is the TCMalloc ↔ rseq regression introduced in Linux 6.19 (LWN 1092555). The
July image only runs because it predates that guard. It is exactly the build that
MongoDB says must not run on this kernel.

Investigation was done by the codey opencode worker (session
`ses_e5f606b25ffeZMeTwgCaawIC5R`). Tested on servy with fresh volumes:

| image | result |
|---|---|
| `mongo:8` (Oct 26 rebuild) | refuses to start (guard) |
| `mongo:8.3.13` | refuses to start (guard) |
| `mongo:9.0.4` | starts |

`mongo:9.0` cannot open the existing data (`Invalid featureCompatibilityVersion
value '8.2'`), and no 8.x binary runs on this kernel to lower the FCV first. An
in-place upgrade is therefore impossible, and the data has to be moved by dump and restore.

## Solution

- `shared/docker-compose.yml`: `image: mongo:9.0.4` (exact pin, no floating tag
  for a database), new volume `shared_mongo_data`, and `command: ["--auth"]`
  dropped. When the first argument is a flag, the official entrypoint skips initdb and never
  creates `MONGO_INITDB_ROOT_*`. It adds `--auth` itself when the credentials are set.
- `ansible/plays/tasks/shared_mongo9_migrate.yml`, imported as the **last
  pre_task** of `plays/user.yml`, so it finishes before any shared or consumer role runs.
  It triggers only when `shared.mongo` is running on `leagues-finance_mongo_data`
  and `shared_mongo_data` does not exist. Steps:
  1. stop `leagues-finance.finance-api` and `finance.queen`
  2. per-collection document counts (app dbs)
  3. `mongodump --gzip --archive` → `shared/.backup/mongo8-<ts>.archive.gz`
  4. `compose up mongo`, which recreates it on the empty new volume (entrypoint creates root)
  5. `mongorestore --nsExclude admin.* --nsExclude config.*` (both apps use root)
  6. assert that the counts are identical, and fail with the consumers still stopped if not
  7. the consumer roles later in the play start the apps again
- post_tasks "Remove corrupted mongo volume": it now targets `shared_mongo_data`
  (the mounted volume) and is skipped on the migration run. Before this change it pointed at
  `leagues-finance_mongo_data`, which is now the rollback copy.

## Rollback

The legacy volume `leagues-finance_mongo_data` is never touched. Revert
`shared/docker-compose.yml`, run `docker volume rm shared_mongo_data`, then redeploy
`--tags user.docker.shared`. The July image then runs again on the old data, with the same
kernel caveat as before.

## Test (servyy-test.lxd, kernel 7.0.0-34, same July image)

```bash
./servyy-test.sh -e branch=claude/shared-mongo9-kernel7 \
  --tags user.docker.repo,user.docker.shared,user.docker.finance,user.docker.env.finance
```

- Run 1: migration ran and counts verified (`queen`: 12 collections, 40 docs).
  The play then failed in the finance env template because the PEM fact is
  tagged only `user.docker.env.finance`. This quirk predates the change.
- Run 2 (with that tag): `failed=0`, all migration tasks skipped (idempotent),
  `finance.queen` healthy and logging `MongoDB connected: shared.mongo:27017`.
- `db.version()` 9.0.4, FCV 9.0, unauthenticated query rejected, legacy volume
  and dump present.

## Production deploy (pending approval)

After the PR is merged, deploy from master so the prod checkout stays on master:

```bash
cd ansible && ./servyy.sh --limit servy.lehel.xyz \
  --tags user.docker.repo,user.docker.shared,user.docker.leagues-finance,user.docker.finance,user.docker.env.finance
```

Expected downtime is about 1–2 min for leagues-finance and queen. The data is small: the rehearsal
on servy measured 37 KB compressed and identical counts (`leagues_finance` 11 collections / 186
docs, `queen` 14 / 342).

## Known follow-ups

- `dontforget.mongo` on servy runs the same July image (not watchtower-scoped).
  It runs today, but any pull breaks it the same way. It needs the same migration.
- The post_task that wipes the mongo volume when it is unhealthy within about 30 s is a
  data-loss hazard in general. It should be removed or replaced with a loud failure.
