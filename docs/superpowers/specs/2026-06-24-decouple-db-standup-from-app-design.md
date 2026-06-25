# Decouple LeagueSphere DB stand-up from the running app — Design

**Date:** 2026-06-24
**Status:** Approved (brainstorm) — pending spec review → implementation plan
**Related:** `docs/superpowers/plans/2026-06-22-leaguesphere-local-mariadb-migration.md` (Task 11)

## Problem

The merged migration (leaguesphere PR #1377) made the local-MariaDB rollout **couple the DB
stand-up to the running app**. The prod compose currently:

- moves `app` off the `database` network onto `backend` + a new `egress` network,
- adds `app.depends_on: db: condition: service_healthy`,
- removes the `database` network (and a follow-up, `c7add5ce`, re-added `egress` to restore the
  app's lost outbound internet).

Because `app`'s network membership and `depends_on` change, deploying the migration to prod
(`./servyy.sh --tags ls.app.prod`) **recreates the live `app` (and `www`) container** — a
real, if brief, outage — *before* anything has been validated. The pre-seed phase (stand up db,
seed from external, back up, test restore) does not need the app changed at all, yet the current
shape forces app disruption to get there. This conflates two independent concerns:

1. **Stand up + validate the new DB** (seed, `mariadb-backup`, restic, restore drill) — safe,
   no app impact required.
2. **Cut the app over to the new DB** (flip `db_host`) — inherently recreates the app; belongs
   in a maintenance window.

## Goal

Make the DB stand-up and validation **fully non-disruptive to the running app**: deploying to
prod should *add only the `db` container*, leaving `app`/`www` byte-identical to what prod runs
today (so Docker does not recreate them). Defer every app-touching change to the cutover window.

Non-goals: changing the seed/backup/restore tooling (validated, unchanged); changing
`deploy.yaml` (its destructive path predates this migration — see Risks).

## Design

### 1. `leaguesphere/deployed/docker-compose.yaml` — revert app, keep db

Return `app` and the networks to **exactly the shape prod runs today** (pre-migration), and keep
only the additive `db` service.

| Element | Current (merged) | Target (this change) |
|---|---|---|
| `app.networks` | `[backend, egress]` | `[backend, database]` |
| `app.depends_on` | `db: service_healthy` | *(removed)* |
| `database` network | removed | restored (`internal: false`) |
| `egress` network | added (`driver: bridge`) | removed |
| `db` service | on `backend`, no ports, bind mounts | **unchanged** (kept) |
| `www` service | `[backend, proxy]`, `depends_on app` | **unchanged** |

Rationale: `db` lives on `backend`, which `app` already shares (for www-comms), so the db is
reachable-but-unused while `app.ls.env` keeps `MYSQL_HOST=external`. `app`'s outbound internet
(external APIs, and the external `s207` DB) continues via the `database` network (`internal:
false`). Since `app`/`www` definitions are identical to current prod, `docker compose up -d`
creates `db` and does **not** recreate `app`/`www`.

The network keeps the legacy name `database` during this phase **specifically** so `app`'s config
is unchanged. It is renamed to `egress` at cutover (Phase B), where the app is recreated anyway.

### 2. `container` repo — docs/plan only, no role code changes

- `ls_app/templates/ls.env.j2`: **no change** — already emits `MYSQL_HOST={{ app.db_host }}`
  (external) until `db_host` is flipped at cutover.
- `ls_app/tasks/deploy.yaml`: **no change** — see Risks (pre-existing, kept dormant + validated).
- Restructure `docs/superpowers/plans/2026-06-22-…-migration.md` Task 11 and
  `docs/leaguesphere-environments.md` cutover runbook into the two phases below.

### 3. Two-phase cutover

**Phase A — DB stand-up + validation (non-disruptive, no maintenance window):**
1. Deploy the reverted compose to prod: `./servyy.sh --tags ls.app.prod --limit lehel.xyz`
   → adds `leaguesphere.db` only; `app`/`www` keep running on external, untouched.
2. Bring up backups: `./servyy.sh --tags restic.init,restic.backup --limit lehel.xyz`.
3. Seed: `./servyy.sh --tags ls.db.migrate --limit lehel.xyz`; verify table/row parity vs external.
4. Restore drill on prod's db (optional, off the seeded set) — confidence before cutover.

**Phase B — cutover (maintenance window, app recreated once):**
1. Enter maintenance / make app read-only.
2. Final delta seed: `./servyy.sh --tags ls.db.migrate --limit lehel.xyz`.
3. In one deploy: rename `database`→`egress` in the compose **and** flip `app.db_host`→
   `leaguesphere.db` (`secret_main.yaml`); `./servyy.sh --tags ls.app.prod --limit lehel.xyz`.
   App recreates once, now pointed at the local db.
4. Smoke test (login, read, write); exit maintenance.
5. Switch `ls_db_sync_source` default → `local`.

### 4. Validation on `servyy-test` (before prod)

Rehearse Phase A against a box where the app is **already running on external**:
- Deploy the reverted compose; assert `docker compose ps` shows `app` and `www` **`Running`
  (same container IDs, not recreated)** and `db` newly `Created`/healthy.
- Confirm the `deploy.yaml` stop/volume path **stayed dormant** (no stop of app/www in the run
  output).
- Re-run seed + `mariadb-backup` + restic restore to confirm the DB pipeline still works under
  the reverted topology.

## Risks & decisions

- **`deploy.yaml` destructive stop-path (out of scope):** `deploy.yaml:38` can `state: stopped`
  the whole compose project before a db-volume cleanup, gated on a db-existence check. It
  predates this migration (stage-only originally) and, for prod, targets a *named* volume that
  bind-mounted prod doesn't use — effectively a no-op. We leave it unchanged and **validate it
  stays dormant** on test rather than hardening it here. Tracked as a possible follow-up.
- **Legacy network name `database`:** intentionally retained during Phase A to keep `app`
  unchanged; renamed to `egress` at cutover. Accepted.
- **Single-variable cutover preserved:** local db reuses prod `db_name`/`db_user`/`db_password`;
  Phase B changes `db_host` (+ the free network rename) only.

## Success criteria

- Deploying the reverted compose to a host with the app live adds `leaguesphere.db` with **zero
  app/www recreation** (verified by unchanged container IDs).
- Seed + backup + restore still pass on the reverted topology (test box).
- Plan/docs describe the two-phase cutover; Phase A carries no maintenance-window requirement.
