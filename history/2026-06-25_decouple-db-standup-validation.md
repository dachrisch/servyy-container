# 2026-06-25 — Decouple LeagueSphere DB Stand-up: servyy-test Validation (Task 2 & 3)

## Status

**Decouple plan Tasks 0–3 complete.** Compose revert merged to leaguesphere `master` (#1390).
**Tasks 2 & 3 validated on `servyy-test.lxd` on 2026-06-25.** Phase A (DB stand-up) is proven
non-disruptive. Remaining: prod Phase A/B cutover (migration plan Task 11, approval-gated).

## Problem

The original MariaDB migration wired the prod compose so that adding `leaguesphere.db` also
changed the `app` service (networks `[backend, egress]`, `depends_on: db`). That would force a
recreation of the running `app`/`www` containers just to stand up the DB — turning a
non-disruptive prep step into one that needs a maintenance window. We needed to prove that the
DB can be stood up **beside** the running app with **zero effect**, deferring all app-affecting
changes to the actual cutover.

## Solution

The compose was reverted (#1390) so `app`/`www` are byte-identical to the pre-migration shape;
only the additive `db` service is new. This validation deployed that reverted compose to
`servyy-test` and proved, by container-ID comparison, that a redeploy creates only `db`.

## Validation results (servyy-test.lxd)

### Task 2 — non-disruptive deploy ✅

| Check | Result |
|-------|--------|
| Redeploy exit / Ansible recap | `EXIT=0`, `ok=36 changed=1 failed=0` (the one change = `db`) |
| `leaguesphere.app` container ID before vs after | `2d298896…` → `2d298896…` **identical (not recreated)** |
| `leaguesphere.www` container ID before vs after | `0739653f…` → `0739653f…` **identical (not recreated)** |
| New `leaguesphere.db` | created, `healthy` |
| App DB target | `MYSQL_HOST=s207.goserver.host` (still external; unwired from local db) |
| App networks | `backend` + `database` (reaches external) — not depending on `leaguesphere.db` |
| Destructive stop-path | "Stop containers before volume cleanup" → `skipping` on both passes |

### Task 3 — seed + backup under reverted topology ✅

| Check | Result |
|-------|--------|
| Seed (`ls.db.migrate`) | `ok=18 changed=4 failed=0`; local db = **103 base tables** (matches drill baseline) |
| `mariadb-backup` prepared `current/` set | complete (`ibdata1`, `mariadb_backup_checkpoints`, `web35_db8`, …) |

**Documented caveat (environmental, test-box only):** the first seed failed with
`ERROR 1203: User web35_8 already has more than 'max_user_connections' active connections`
because the live `leaguesphere.app` on the test box held connections to the shared external
host. Resolved per the plan's note: `docker stop leaguesphere.app` → re-run seed → restart app.
`www` briefly went unhealthy while app was stopped and recovered automatically. Not a defect in
the change; on prod, the cutover's maintenance window (Phase B) avoids this contention.

## Files changed (this docs commit)

| File | Change |
|------|--------|
| `docs/superpowers/plans/2026-06-24-decouple-db-standup.md` | Mark Task 2 & 3 done; add validation status banner |
| `docs/superpowers/plans/2026-06-22-leaguesphere-local-mariadb-migration.md` | Restructure Task 11 into Phase A (no window) / Phase B (windowed flip + rename) |
| `docs/leaguesphere-environments.md` | Rewrite cutover runbook into Phase A / Phase B |
| `history/2026-06-25_decouple-db-standup-validation.md` | This note |

## Verification commands

```bash
# Non-disruptive redeploy (Task 2)
cd container/ansible
ANSIBLE_SSH_ARGS="-o IdentitiesOnly=yes" ANSIBLE_PRIVATE_KEY_FILE="$HOME/.ssh/id_rsa" \
  ./servyy-test.sh -u ubuntu --tags ls.app.prod
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa ubuntu@servyy-test.lxd \
  "sudo docker inspect -f '{{.Id}}' leaguesphere.app leaguesphere.www"   # unchanged before/after
ssh ... "sudo docker inspect -f '{{.State.Health.Status}}' leaguesphere.db"   # healthy

# Seed + verify 103 base tables (Task 3)
./servyy-test.sh -u ubuntu --tags ls.db.migrate
# if ERROR 1203: sudo docker stop leaguesphere.app; re-run; sudo docker start leaguesphere.app
```

## Success criteria (all met)

- [x] Redeploy adds only `db` (`changed=1`); app/www container IDs unchanged
- [x] App stays on external DB (`MYSQL_HOST=s207.goserver.host`)
- [x] Destructive stop-path stays dormant (`skipping`)
- [x] Seed reaches the 103-table baseline; `mariadb-backup` produces a complete prepared set

## Next

- Open PRs for the docs (this branch) — decouple plan Task 5.
- Prod cutover = migration plan **Task 11 Phase A** (non-disruptive, can run anytime) then
  **Phase B** (maintenance window, approval-gated). Not yet scheduled.
