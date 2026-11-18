# LeagueSphere prod database outage — the `MARIADB_AUTO_UPGRADE` flag (2026-11-18)

## Timeline (UTC)

| time | event |
|---|---|
| 10:06:12 | `./servyy.sh --limit servy.lehel.xyz --tags user.repo.clone,ls.app.prod,ls.app.stage,ls.demo --skip-tags ls.db.sync` starts (the LeagueSphere half of WP-0; leaguesphere PR #2436 → `b013e3f08`) |
| ~10:08:30 | `ls_app` pulls the jail checkout `6f37574e4` → `b013e3f08`, renders `ls.env`, pulls images, recreates `db`, `app`, `www`, `db-access`, `db-tunnel` |
| **10:08:31** | **old `leaguesphere.db` stopped → platform down (502)** |
| 10:09:20 | first `FATAL ERROR: Upgrade failed`; the entrypoint exits 1 and the container enters a restart loop (10 identical failures over the next 2 minutes) |
| 10:09:15 | the play aborts: `dependency failed to start: container leaguesphere.app is unhealthy`; `www` is left `created`, never started. Exit 2, wall clock 3m03s. Staging and demo are never touched |
| 10:12:11 | **manual restore begins**: the `MARIADB_AUTO_UPGRADE=1` line is deleted from the rendered `/var/jail/home/leaguesphere/container/deployed/ls.env` |
| 10:12:19 | `docker compose … up -d db` (recreate, because an env change needs one) |
| 10:12:22 | `mariadbd: ready for connections … 13.0.2-MariaDB-ubu2604-log`, **no upgrade step at all** |
| **10:12:28** | `leaguesphere.db` **healthy**, `RestartCount=0` |
| 10:13:15 | `docker compose … up -d` brings up `app` (healthy) and `www` |
| **10:15:02** | first successful public request after the outage (`302`, last 502 at 10:13:54) |

**Downtime: database ≈ 3m57s (10:08:31 → 10:12:28); public platform ≈ 6m31s
(10:08:31 → 10:15:02).** No data loss: `Gameinfo` 42, `auth_user` 345,
`gamedays_gameday` 781 — identical to the pre-deploy counts; 0 unapplied
migrations; datadir untouched apart from MariaDB's own crash recovery.

## The error

```
[Note] [Entrypoint]: Temporary server started.
[Note] [Entrypoint]: Backing up system database to system_mysql_backup_12.3.2-MariaDB.sql.zst
[Note] [Entrypoint]: Starting mariadb-upgrade
Reading datadir from the MariaDB server failed. Got the following error when executing the 'mysql' command line client
ERROR 2002 (HY000): Can't connect to server on 'leaguesphere.db' (115)
FATAL ERROR: Upgrade failed
```

## Mechanism

WP-0 added `MARIADB_AUTO_UPGRADE=1` to `ansible/plays/roles/ls_app/templates/ls.env.j2`
(history/2026-11-18_db-tier-wp0-version-fence.md, item 3) so that a watchtower
patch restart would run `mariadb-upgrade`. The comment there assumed the flag
only affects the server.

It does not, because of **which file it was put in**:

1. The LeagueSphere prod compose gives the `db` service `env_file: ls.env` —
   the same file the app reads. That file's whole job is to tell the *app*
   where the database is: `MYSQL_HOST=leaguesphere.db`.
2. So the **database container's own environment** now contains
   `MYSQL_HOST=leaguesphere.db`.
3. With `MARIADB_AUTO_UPGRADE=1`, the MariaDB entrypoint starts a temporary
   server **socket-only** (`port: 0`) and then runs `mariadb-upgrade`, which
   shells out to the `mysql` command-line client.
4. The `mysql` client honours the standard environment variable `MYSQL_HOST`
   and therefore dials **TCP to `leaguesphere.db`** instead of the socket. At
   that moment nothing listens on TCP (the temp server has networking off), and
   the name resolves to the container's own address, which is not up yet.
5. `ERROR 2002 (HY000)` → `FATAL ERROR: Upgrade failed` → the entrypoint exits
   1 → Docker restarts it → identical failure forever. Compose then fails the
   whole stack on the app's DB dependency, leaving `www` unstarted.

The deploy itself was correct (`mariadb:13.0` = the same image digest
`sha256:54f493ea…` the container already ran, watchtower scope `prod` → `db`).
**The tag was never the problem; the flag was.**

## What restored service

Host-local, reversible, no repo change: delete the one line from the rendered
`ls.env`, recreate only the `db` service with the same compose invocation
`ls_app` uses (`up -d db`, not `restart` — env changes need a recreate), then
`up -d` the rest. The entrypoint then starts mysqld directly, as before WP-0.

## Repo fix (this branch)

`ls_app/templates/ls.env.j2`: the `MARIADB_AUTO_UPGRADE=1` line is removed and
replaced by a comment recording why it must never go in that file. That is the
whole fix: every future `ls_app` run now renders an `ls.env` without the flag,
so the restart loop cannot come back.

`grep -rn MARIADB_AUTO_UPGRADE ansible/` still matches
`docker_service/templates/moodle.db.env.j2`. That one is **not** a latent copy
of this bug and stays: it is Moodle's *own* db-only env file (pre-dates WP-0,
added with the Moodle stack), its only consumers are `MARIADB_*` variables, and
it contains no `MYSQL_HOST` — moodle.db restarted on `mariadb:12.3` with the
flag during WP-0's own deploy and logged `MariaDB upgrade not required`. The
lesson is the env-file shape, not the variable: a DB-only file is safe, a file
shared with the app is not.

## Follow-up worth doing later

If auto-upgrade is ever wanted for the high tier, do **one** of these first, and
prove it on servyy-test before prod:

- give the `db` service its own env file (root password + `MARIADB_*` only, no
  `MYSQL_HOST`), the way the Moodle stack already does; or
- set `MYSQL_HOST=localhost` inside the `db` container so the upgrade client
  uses the socket regardless of what the app is told.

Also worth a guard: a tiny molecule/assert that the rendered `ls.env` never
contains `MARIADB_AUTO_UPGRADE` while it contains `MYSQL_HOST` — this failure is
invisible until the first restart, which is exactly why it reached production.

## Related

- `history/2026-11-18_db-tier-wp0-version-fence.md` — WP-0, where the flag was
  added (item 3; the entry also records WP-0c's `import_tasks` repair and the
  guard accumulator reset).
- `history/2026-11-18_db-tier-wp1-mongo-wipe.md` — WP-1, the other package whose
  first deploy after merge was its real test.
- `history/2026-10-28_offd-cutover.md` and the Moodle stack — the working
  counter-example: a DB-only env file (`moodle.db.env.j2`) that carries the flag
  safely because it has no `MYSQL_HOST`.
