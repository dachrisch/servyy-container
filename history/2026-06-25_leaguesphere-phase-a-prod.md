# 2026-06-25 — LeagueSphere Prod Phase A: local MariaDB stand-up (no cutover)

## Status

**Phase A complete on prod.** `leaguesphere.db` stands up beside the live app, seeded
(103 base tables) and backed up. The app **still runs on the external DB**
(`MYSQL_HOST=s207.goserver.host`) — no cutover. Phase B (the `db_host` flip + `database`→`egress`
rename, maintenance window) is still pending and approval-gated.

## What ran (from `container/ansible`, `--limit lehel.xyz`)

| Step | Command | Result |
|------|---------|--------|
| 1. Stand up db | `./servyy.sh --tags ls.app.prod` | `ok=36 changed=5 failed=0`; `leaguesphere.db` healthy |
| 2. Init + backup | `./servyy.sh --tags restic.init,restic.backup` | `ok=55 changed=13 failed=0` |
| 3. Seed (1st try) | `./servyy.sh --tags ls.db.migrate` | **FAILED** — `ERROR 1203 max_user_connections` |
| 3. Seed (retry) | `./servyy.sh --tags ls.db.migrate` | `ok=18 changed=4 failed=0`; local db = **103 base tables** |

Final state: `app`/`www`/`db` all `Up (healthy)`, prod login `200`, app on external DB.

## Two things that actually happened (not zero-touch)

### 1. app/www were recreated once (brief restart)

The `ls_app` role runs `git pull origin master` into the on-host `deployed/` checkout, then
`docker compose up`. Prod's checkout was **behind** `master`, so the pull brought a changed
compose + `ls.env`, and compose recreated `app`/`www` to match (container IDs changed:
`3a803cf8…`→`339b8d26…`, `c1f10bb8…`→`3f66a2bc…`). A few seconds' blip, then healthy.

**Why the servyy-test validation missed it:** on the test box the baseline already *was* the
reverted compose (deployed in decouple Task 2), so the redeploy was a true no-op and IDs were
unchanged. Prod had a real checkout delta. The "byte-identical to what prod runs today" premise
held only for an already-current checkout.

### 2. Transient prod login outage during the first seed (1203)

The first seed's `mysqldump` opened connections to the shared external host (`web35_8@s207`)
**on top of** the live prod app's pool **and** a still-running `servyy-test` `leaguesphere.app`
(left up from Task 2/3 validation) that connected to the **same external user**. The three
consumers exceeded `max_user_connections`, so the live app's own queries failed with
`OperationalError 1203` and `/login/` returned HTTP 500. The `db_guard` middleware logged
"Database connection guard detected failure". Stopping `servyy-test` freed the slots; prod
recovered on its own (no restart needed), and the seed retry succeeded with headroom.

**Lesson (now in the runbook):** before any prod seed, **stop every non-prod stack that points
at the external DB** — `servyy-test`, stage-on-external, local dev — because they share the same
`web35_8@s207` user and connection cap.

## Verification commands

```bash
ssh lehel.xyz "docker inspect -f '{{.State.Health.Status}}' leaguesphere.db"          # healthy
ssh lehel.xyz "docker exec leaguesphere.app printenv MYSQL_HOST"                       # s207.goserver.host (still external)
ssh lehel.xyz 'docker exec leaguesphere.db bash -c '\''mariadb -h localhost -u root -p"$MYSQL_ROOT_PASSWORD" -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=\"web35_db8\" AND table_type=\"BASE TABLE\";"'\'''   # 103
```

## Next

- **Phase B cutover** (migration plan Task 11 Phase B): in a maintenance window, final delta
  seed (app quiesced → avoids the 1203 contention), then the single `db_host` flip +
  `database`→`egress` rename. Approval-gated; not scheduled.
- The external DB stays as the live source and 14-day rollback until Phase B + retention.
