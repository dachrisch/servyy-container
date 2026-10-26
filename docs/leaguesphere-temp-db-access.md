# Temporary prod DB access — the operator and user flow

> Companion to `docs/plans/2026-10-25-prod-db-temp-credentials.md` (the design and
> its evidence). This is the sheet a person follows: who asks, who approves, what
> they get, and how it ends.

## The shape of it

```
person needs live data
        │
        ├─ staff: /dbaccess/requests/new/  → handle from the login, tables from the list, TTL ≤ 8 h
        │                                      → state: requested, an AccessEvent
        │
        ├─ a SECOND staff user with `dbaccess.approve_requests`: approve or deny
        │                                      → state: approved | rejected
        │                                        (approving your own request is refused
        │                                         by a database constraint, not a view)
        │
        ├─ db-access sidecar, ≤ 15 s: re-validates, snapshots bak_<table>_<date>,
        │                             CREATE USER dbeaver_prod_<person>@'172.25.%',
        │                             SELECT + UPDATE on the named tables only
        │                                      → state: active, credential handed over once
        │
        ├─ the person works through the shared tunnel
        │
        └─ ls-db-access-reap.timer, every 5 min after created_at + 8 h:
                                    kill the sessions, DROP USER, correct the row
                                               → state: dropped
```

The **app owns the request and the record; it does not own the account or the clock.**
It cannot `CREATE USER` (that is a global privilege and its own grant is schema-scoped),
and it cannot extend a session: the reaper computes expiry from `created_at` plus a constant
it holds itself.

## What the person does

1. Any staff member can ask. The handle is not typed: it is derived from the login
   (lowercase letters and digits), so the account is `dbeaver_prod_<login>` and always names a
   real person.
2. They open `/dbaccess/requests/new/`, filter and pick the tables from the curated list, choose a
   TTL, and give the purpose and a ticket reference.
3. A second staff user approves. **This cannot be the person who asked.**
4. Within about fifteen seconds the request page offers **Show password**. That is the only
   place the credential appears; every reveal is recorded.
5. DBeaver. The tunnel account is transport only — the identity is the minted MySQL user:

   | | prod | stage |
   |---|---|---|
   | SSH host / port | `servy.lehel.xyz` / 22 | `servy.lehel.xyz` / 22 |
   | SSH user | `dbeaver_tunnel` | `dbeaver_stage` |
   | SSH auth | Vaultwarden: `dbeaver prod tunnel key (servy)` | Vaultwarden: `dbeaver stage tunnel key (servy)` |
   | Main host / port | `127.0.0.1` / `33063` | `127.0.0.1` / `33064` |
   | Database | `web35_db8` | `leaguesphere_stage` |
   | User | `dbeaver_prod_<handle>` | `dbeaver_prod_<handle>` |

   Both ports are a `db-tunnel` socat *inside* the stack, not a published mysql port: a forwarded
   login has to enter the compose network so that mysql sees `172.25.%` / `172.26.%` and the
   account's grant matches. Stage's plain publish (`127.0.0.1:33062`) delivers the host's address
   instead and answers `1045` for every minted account; it stays available for anything granted
   from the host address. The account allows 4 connections, 60 s per statement, `SELECT` on the
   schema and `SELECT, UPDATE` on the requested tables only — no `INSERT`, `DELETE` or DDL.

6. When done — same day — anyone who can see the session clicks **Revoke now**. Otherwise the
   cap does it within five minutes of the eighth hour.

## What the account can and cannot do

| | |
|---|---|
| `SELECT` | the whole schema — a diagnosis needs context |
| `UPDATE` | **only** the tables named on the request |
| `CREATE` | nothing. The `bak_<table>_<date>` copies exist already, taken before the grant |
| `INSERT` / `DELETE` / DDL | nothing |
| connections | 4 at most; one statement is killed at 60 s |
| hosts | `172.25.%` only — the app's private network, not the finance network |

## Rules the person works under

1. Auto-commit **off**. A data-grid edit emits one `UPDATE` per keystroke.
2. Scope the rows with a `SELECT` first, in the same transaction, and state the row count.
3. Check the snapshot exists (`SELECT COUNT(*) FROM bak_<table>_<date>`) before the first write.
   The account has no `CREATE`, so if it is missing you must stop and ask for a new request.
4. One table per transaction; re-run the scoping `SELECT` before `COMMIT`; prefer `ROLLBACK`
   to debugging a committed mistake.
5. Keep the statements in a `.sql` file and hand it over. That file plus the audit log
   (`server_audit.log`) and the binlog are the record of what happened.
6. Two days after the session, `bak_<table>_<date>` is still in the database. Drop it once the
   fix has been verified on stage by `ls_db_sync` — not before.

## Rolling it out

The role provisions **every LeagueSphere stack running on the host**: servy runs prod (from
`container`) and stage (from `container-stage`), servyy-test.lxd runs one. Each stack gets its
own `dba.env`, its own provisioner account and its own sweep in the reaper; the compose
directory is read from the running container's compose label, not hardcoded in the role.

One ordering rule: `dba.env` lives next to the compose file that reads it, so the role must run
**before** the deploy that introduces the `db-access` service. The play already runs
`ls_dbeaver_access` before `ls_app`, so a combined run is safe — but a bare
`--tags ls.app.deploy` run fails with `env file .../dba.env not found`.

State as of 2026-10-26: the **stage** stack has both halves deployed and rehearsed end to end
(request → approve → mint → reveal → revoke → drop, see
`history/2026-10-26_temporary-prod-db-access.md`). Prod's half still waits.

**Rolling a branch to stage (normal route).** `leaguesphere/backend:staging` is pushed by the tag
pipeline (CircleCI `deploy_staging`), so a PR branch is validated by cutting a throwaway staging
release from it:

```bash
gh workflow run deploy.yaml --ref <branch> -f environment=staging -f bump_type=patch
```

That bumps the version files (`4.43.1 → 4.43.2-rc.1`), commits and tags `v4.43.2-rc.1` on the
branch; the tag pipeline runs the full matrix, pushes `:staging` and `:v<version>`, and can fail on
`check_release_sequence` or the test shards before anything lands. Watchtower-dev (300 s poll)
then blue-green replaces the stage app and `www` with the new images — that is the stage rollout.
The version commit must be reset to the master state before the branch is merged
(`scripts/check_version_sequence.py` enforces it).

**Fallback when the registry is closed** (revoked Docker Hub credential, pipeline unavailable):
build the image from the branch and load it on the host, then:

```bash
# on a build host (servyy-test.lxd), from the branch checkout:
docker build -f container/app.Dockerfile -t leaguesphere/backend:staging .
docker save leaguesphere/backend:staging | gzip | ssh servy.lehel.xyz 'gunzip | docker load'
# watchtower-dev (300 s poll) would put the registry image back within minutes:
ssh servy.lehel.xyz 'docker stop portainer.watchtower-dev'
# `-e app_compose_pull=never` is not enough on its own: the role's
# `Pull Docker images for staging` task (tag `ls.app.deploy.pull`, force_source: yes)
# re-tags :staging from the registry, and the container then runs the old published
# image (healthy, but /dbaccess/ 404). Skip that tag too.
# app.branch lives in git-crypt vars, so override the whole dict with extra vars
# (extra vars beat the role's include_vars) and never let compose pull the tag:
./servyy.sh --tags ls.app.stage --skip-tags ls.db.sync,ls.app.deploy.pull \
  -e dbeaver_dbaccess_enabled=true -e app_compose_pull=never \
  -e @/path/to/stage-app-dict.json --limit servy.lehel.xyz
```

Compose compares the image *reference*, not the image id, so after loading a new build do
`docker rm -f leaguesphere_stage.staging-app` before the deploy or the container is not recreated.
Restart `portainer.watchtower-dev` when the rehearsal is over.

**State 2026-10-26 (final):** stage runs the **CI-built** image of `feat/dbaccess-flow` — tag
`v4.43.2-rc.1`, `leaguesphere/backend:staging` = `sha256:a212f96f9e05`, pulled by
`portainer.watchtower-dev` (running again, blue-green cutover) with the frontend image from the
same tag. `DBACCESS_ENABLED=true`, allow-list seeded, migrations applied at container start.


Stage first:

```bash
cd ansible
# 1. infra half for stage only. --skip-tags keeps prod's tunnel account and its
#    sshd restart out of this run; prod's dba.env is not written either.
./servyy.sh --tags ls.dbeaver --skip-tags ls.dbeaver.tunnel \
  -e dbeaver_app_filter=leaguesphere_stage --limit servy.lehel.xyz
# 2. app half for stage only. --skip-tags is required: ls_db_sync also carries ls.app.stage.
#    The flag must be passed here - it defaults to false, so without it the stage app comes up
#    with the surface switched off and there is nothing to validate.
./servyy.sh --tags ls.app.stage --skip-tags ls.db.sync \
  -e dbeaver_dbaccess_enabled=true --limit servy.lehel.xyz
# 3. seed the allow-list in the staging app
ssh servy.lehel.xyz "docker exec leaguesphere_stage.staging-app python manage.py dbaccess_sync_tables"
```

Prod, once stage is good — the flag stays off until the allow-list is seeded and an approver
holds the permission:

```bash
./servyy.sh --tags ls.dbeaver --limit servy.lehel.xyz
./servyy.sh --tags ls.app.pull,ls.app.env,ls.app.deploy \
  -e dbeaver_dbaccess_enabled=false --limit servy.lehel.xyz
ssh servy.lehel.xyz "docker exec leaguesphere.app python manage.py dbaccess_sync_tables"
# grant dbaccess.approve_requests to one named human, then flip it on:
./servyy.sh --tags ls.app.env,ls.app.deploy \
  -e dbeaver_dbaccess_enabled=true --limit servy.lehel.xyz
```

`ls.app.env` is not optional in those commands: without it `ls.env` is never re-rendered and the
feature stays off regardless of the flag.

## Operating it

**Enable / disable.** `DBACCESS_ENABLED` in `ls.env` (rendered from `ls_app`). **Off unless the
deploy passes `-e dbeaver_dbaccess_enabled=true`.** Approval additionally needs the
`dbaccess.approve_requests` permission — grant it in the Django admin
(*dbaccess → Approve requests*) to a named human, not to a group that includes the requester.

**Seed the table list** after a deploy and after any schema change:

```bash
ssh servy.lehel.xyz "docker exec leaguesphere.app python manage.py dbaccess_sync_tables"
```

Identity, session and admin-log tables are inserted as `grantable=False` rather than skipped, so
the request form can explain their absence.

**Rotate a stack's provisioner password** (the sidecar's credential). One password file per
stack on the controller:

```bash
ls ~/.dbeaver_provisioner_servy_*                    # controller
rm ~/.dbeaver_provisioner_servy_leaguesphere_stage   # the stage stack
cd ansible && ./servyy.sh --tags ls.dbeaver.provision \
  -e dbeaver_app_filter=leaguesphere_stage --limit servy.lehel.xyz
cd /var/jail/home/leaguesphere/container-stage/deployed
docker compose -p leaguesphere_stage up -d --force-recreate db-access
```

The same command without `-e dbeaver_app_filter` rotates both stacks on servy (prod's file is
`~/.dbeaver_provisioner_servy_leaguesphere`).

**Rotate the shared tunnel key:** `./servyy.sh --tags ls.dbeaver -e dbeaver_tunnel_rotate_key=true`.
Everyone's DBeaver profile needs the new key; existing sessions keep working until their cap.

**Check the safety net is alive** (one unit, one sweep per stack — the journal lines are
prefixed with the database they concern):

```bash
ssh servy.lehel.xyz "systemctl status ls-db-access-reap.timer --no-pager | head -4"
ssh servy.lehel.xyz "sudo journalctl -u ls-db-access-reap.service -n 20 --no-pager"
```

**What the provisioner account may do** (and may not): `CREATE USER` globally, and
`SELECT, INSERT, UPDATE, CREATE` on the application schema with `GRANT OPTION`, so it can take the
`bak_<table>_<date>` snapshot and hand out `SELECT`/`UPDATE` on named tables. It deliberately has
**no `PROCESS`**: that is global (it would expose every session's query text and allow killing any
connection) and MariaDB has no scoped variant.

Consequence for **Revoke now**: the sidecar drops the account within ~15 s, so no new connection
can be opened, but an already-open session keeps working until the reaper's next sweep kills it —
**within 5 minutes**. The reaper does that kill as root inside the container; it is the only
component that can. Nothing to do by hand unless the timer is down.

**Look at who holds what right now:**

```sql
-- as root inside the container
SELECT person, state, db_user, grant_host, created_at, activated_at
  FROM web35_db8.dbaccess_request
 WHERE state IN ('approved','active','revoke_requested');
```

## Failure modes worth knowing

| Symptom | Cause | Fix |
|---|---|---|
| request stays `approved` | sidecar down, or no `dba.env` | `docker logs leaguesphere.db-access`; the row is untouched until a tick succeeds |
| row flips to `failed` | unknown table, bad person, or a failed snapshot | the reason is in `failure_reason` and in `dbaccess_event` — fix and re-request |
| login refused with `172.24.0.x` in the error | the client is not coming from the backend network | the tunnel is the only supported path; do not add `database` to the sidecar |
| account gone before the cap | the reaper dropped it: pattern, state or age | `journalctl -u ls-db-access-reap` names the reason |
| revoked session still connected (≤ 5 min) | `KILL` needs the global `PROCESS` privilege the sidecar deliberately lacks, so the host reaper kills it on its next sweep | wait for the sweep, or `systemctl start ls-db-access-reap.service` |
| password page shows nothing | `DBACCESS_SECRET_KEY` missing or rotated | re-provision; the previous credential is unreadable by design |
| nobody can approve | permission not granted | Django admin → users → `dbaccess.approve_requests` |

## Deliberate absences

No self-service: a second person is the control, and the constraint enforces it. No per-person
SSH account: the tunnel is transport, the database account is identity, and attribution lives in
`dbaccess_event` + `server_audit.log`. No extension: a second day is a new request, a new account
and a new password.
