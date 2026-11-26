# OpenCode session pruner locked the live SQLite DB (2026-11-26)

## Problem

Active OpenCode sessions on `codey.lehel.xyz` stopped mid-turn with
`effect/sql/SqlError: Failed to execute statement` (underlying
`SQLiteError: database is locked`). The failed writes were persisted as `idle`
rows with `{'type':'unknown','message':'Failed to execute statement'}`; sending
another message resumed the session, so no data was lost. Failures occurred at
21:04 and 23:04 on 2026-11-25 and 08:04 on 2026-11-26 — minute 04 of several
hours, not once a day.

## Cause

Two compounding bugs in `opencode/`:

1. `opencode/scripts/prune-sessions.py` called `vacuum()` after any successful
   delete. `VACUUM` rebuilds the whole ~110 MB database while holding a
   write/exclusive lock; measured lock windows were 14–31 s. The pruner's
   `PRAGMA busy_timeout=60000` only applies to *its* connection — the server's
   separate connection hit its own shorter `LockTimeoutError` first. WAL mode
   does not make `VACUUM` non-blocking.
2. The Ofelia label was `ofelia.job-exec.prune-sessions.schedule=0 4 * * *`.
   `portainer.ofelia` runs `mcuadros/ofelia:latest`, whose parser requires
   **six seconds-first fields**. `0 4 * * *` was read as
   `sec=0, min=4, hour=*`, i.e. minute 04 of **every hour**. That multiplied the
   lock exposure from once a day to 24 times a day.

## Evidence summary

- Server log inside `opencode.web`: `Failed to drain Session` /
  `Failed to publish Session execution lifecycle` /
  `INSERT INTO kv ... database is locked`, all inside prune/VACUUM windows.
- `docker logs --timestamps portainer.ofelia` showed `prune-sessions` starts at
  every HH:04 and `vacuum ok` 14–31 s later; session errors fall inside those
  windows.
- Persisted `idle` error rows' millisecond timestamps match the end of the
  VACUUM windows to the second.
- Read-only diagnosis only: online-backup copy through `mode=ro`,
  `integrity_check=ok`, 0 freelist pages. No host/DB write was made during the
  investigation. OOM, disk/inode exhaustion, backup contention and restarts
  were checked and ruled out.
- Full report (scratchpad, not repo): `codey-investigation-report.md`,
  2026-11-26 08:15–09:20 UTC.

## Fix

- `opencode/scripts/prune-sessions.py`: removed the `vacuum()` call from
  `main()` and deleted the now-unused helper. Kept the bounded `DELETE`
  transaction and `PRAGMA busy_timeout=60000`. No `wal_checkpoint` was added —
  that needs measurement before being considered.
- `opencode/scripts/test_prune_sessions.py`: tests now trace the SQL issued by
  `main()`'s own connection and assert that no `VACUUM` statement runs (with or
  without deletes), that `busy_timeout=60000` is still applied, and that
  deletes still remove only idle sessions while fresh/active ones survive.
- `opencode/docker-compose.yml`: `prune-sessions` schedule is now
  `0 0 4 * * *` (daily 04:00 UTC); `npm-cache-clean` is now `0 0 5 * * 7`
  (Sunday 05:00 UTC). Comments updated to the seconds-first form.
- `claude-hub/docker-compose.yml`: the same 5-field misparse was found on
  `hub-force-cleanup` — `0 4 * * 7` was running at minute 04 of every hour
  **on Sundays**, not once at 04:00. Now `0 0 4 * * 7`.
- `ansible/plays/roles/opencode/tasks/main.yml` +
  `handlers/main.yml`: the compose-file task now notifies a new
  `recreate opencode container` handler. This uses `docker_compose_v2` with
  `state: present` (`docker compose up`), which recreates only containers
  whose compose config changed, preserving volumes/env/networks/labels. The
  pre-existing `restart opencode container` handler is deliberately
  `docker compose restart` (re-exec only) and cannot apply changed labels.
- Ofelia label audit (repo-wide, excluding `.worktrees/`): 9 matches. The three
  5-field live labels listed above were fixed; finance's three six-field
  labels, the two `@every 1h` heartbeats/reaper, and two quoted labels inside
  historical records (`history/2026-09-04_*`, `history/2026-11-24_*`) need no
  change.

## Verification (2026-11-26)

- TDD: new tests first — RED with `2 failed, 16 passed` (trace showed `VACUUM`
  after deletes and the `vacuum` helper still present). After the fix: GREEN,
  `python3 -m pytest opencode/scripts/test_prune_sessions.py -q` →
  `18 passed, 73 subtests passed`.
- `cd ansible && ansible-lint plays/roles/opencode` → passed, 0 failures /
  0 warnings in 9 files.
- `ansible-playbook servyy.yml --syntax-check -i testing` and
  `ansible-playbook plays/user.yml --syntax-check -i testing` → both OK.
- `git diff --check` → clean.
- Test deploy only: `cd ansible && ./servyy-test.sh --limit servyy-test.lxd
  --tags user.docker.opencode` → `ok=197 changed=19 unreachable=0 failed=0`;
  the `recreate opencode container` handler ran.
- `ssh servyy-test.lxd 'docker inspect opencode.web --format "{{json
  .Config.Labels}}"'`: `prune-sessions.schedule=0 0 4 * * *` and
  `npm-cache-clean.schedule=0 0 5 * * 7` (recreate applied the labels).
- The bind-mounted `/scripts/prune-sessions.py` in `opencode.web` contains no
  `VACUUM` statement and still has `PRAGMA busy_timeout=60000`.
- `servyy-test.lxd` has **no Ofelia container** (`docker ps -a` check), so
  Ofelia job registration/log scheduling could not be verified there. The
  label values themselves are verified.

## Deployment

Not deployed to production as part of this change; production needs explicit
approval. After approval:

```bash
cd ansible && ./servyy.sh --limit codey.lehel.xyz --tags user.docker.opencode
```

The pruner fix needs no container restart (bind mount); the compose label
change needs the recreate handler, which the deploy above triggers.
