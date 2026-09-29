# 2026-09-29 — Mongo 8 + Valkey migration (leagues-finance, job-search)

## Problem
PR #162 moved leagues-finance and job-search from `redis:7-alpine`/`mongo:7` to
`valkey:9-alpine`/`mongo:8` to consolidate images (~1.3 GB). CI green, but
untested on a real host. Prod wrinkle: job-search had zero containers, only
orphaned volumes, so the PR's backup/FCV safety tasks (gated on a live
container) would silently skip.

## Test-first validation (servyy-test.lxd) — initial NO-GO
- Scenario A (running mongo:7 → 8): pre-tasks passed, then 3 blockers:
  1. `Set FCV 8.0` ran even on mongo:7 → `Invalid featureCompatibilityVersion`.
  2. Fresh `mongo:8` crash-looped: `SERVER-121912` (TCMalloc/rseq vs kernel
     6.19–7.0.13). Test kernel was 7.0.0-30.
  3. `valkey:9` can't read old redis RDB v12 (`job-search_redis_data`).
- Scenario B (stranded volumes, no container): backup + FCV check all skip —
  fails loudly, no wipe, but zero safety net. Confirmed unsafe as-is.
- Full flow re-tested later on kernel 7.0.0-34: `ok=31 failed=0`, all 8
  containers healthy, FCV already 8.0 on fresh volumes (set-tasks skip cleanly).

## Key research
No fixed mongo:8 build exists — the fix is kernel-side (7.0.14+ upstream).
Ubuntu freezes the reported version at 7.0.0-x, but 7.0.0-34 contains the
backported rseq fix: pinned `mongo:8` (8.2.12) starts and stays up 100 s+.

## Fix (PR #163, merged, 23/23 CI green)
- `ansible/plays/user.yml`: gate both `Set FCV 8.0` tasks on mongo:8 image
  (`lf/js_mongo_is_v8` facts).
- Pin prod-proven digests: `mongo:8@sha256:e0ce8c35…`, `valkey:9-alpine@sha256:ee91f7a1…`.
- Note: `-e prune_legacy_datastore_images=true` (string) breaks the `when`
  conditional — must pass JSON boolean `-e '{"prune_legacy_datastore_images": true}'`.

## Prod deploy (servy.lehel.xyz)
1. Rebooted host 7.0.0-31 → 7.0.0-34 (34 was already installed). All containers
   restarted healthy, incl. `dontforget.mongo mongo:8`.
2. `user.docker.repo` sync → prod checkout at 641d392 with pins.
3. job-search (volumes-only): `down -v`, ansible deploy → 5/5 healthy.
4. leagues-finance: mongodump safety net (8 KB → `.backup/`, restic-covered),
   `down -v`, ansible deploy → healthy, mongorestore (102 docs + 4 pre-existing
   `_migrations` dup-key skips, verified benign), endpoints 200.
5. Prune legacy images: `mongo:7` (1.19 GB) + `redis:7-alpine` removed.

## Verification
- `check-status.sh servy`: all containers Up, fail2ban 3/3, monit OK.
- `finance.leaguesphere.app` 200, `jobs.lehel.xyz` 200, `search.lehel.xyz` 200.
- Disk 86% → 85%.

## Follow-ups
- servyy-test checkout can't `git fetch` (access rights) — pinned compose was
  scp'd for the test run; fix deploy key or document the `user.docker.repo` flow.
- Test-host DNS/registry flaked post-reboot (transient, retries sufficed).
- `mongo:7.0` tag already absent at prune time; only `mongo:7` + `redis:7-alpine`
  removed.
