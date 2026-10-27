# Temporary prod DB access (app-managed)

**Date:** 2026-10-26
**Status:** ⚠️ **PREPARED — stage infrastructure deployed, feature still off.**
The role's infra half is live on servy's **stage** stack (`dba.env`, `dbaccess@'172.26.%'`,
reaper timer); prod is untouched and the `db-access` sidecar is not running anywhere yet —
it arrives with the app PR, which is not merged. Update this entry after the rehearsal.

| Repo | Change | PR |
|---|---|---|
| `leaguesphere` | `dbaccess` app (request/approve/reveal), `deployed/dba/tick.sh` (the executor), `db-access` sidecar in both compose files, prod `db-tunnel` socat | #2093 |
| `servyy-container` | one static tunnel account, scoped provisioner, host reaper, `dba.env` rendering, app secret, this entry | this PR |

## Summary

Prod database access is now requested and approved in the web app, executed by a small
sidecar container, and ended by a host-side timer:

* **Transport is static.** One SSH account (`dbeaver_tunnel`) with a shared, rotateable key
  reaches one loopback port. It carries **no identity** on purpose.
* **Identity is per session.** The `db-access` sidecar mints
  `dbeaver_prod_<person>@'172.25.%'` with `SELECT` on the schema and `UPDATE` only on the
  tables named on the request, `MAX_STATEMENT_TIME 60`, `MAX_USER_CONNECTIONS 4`.
* **The app owns the flow, not the privilege.** It records the request, the approval and the
  audit trail, and it cannot `CREATE USER` — that is a global privilege, and its own grant is
  schema-scoped.
* **The host owns the clock.** `ls-db-access-reap.timer` drops anything past
  `created_at + 8 h`, in a state the app did not leave `active`, or on a host pattern that is
  not the expected one.

This supersedes the per-person SSH account design in rev. 2 of the plan. The reasoning, the
probes and the PITR/audit context are in
`docs/plans/2026-10-25-prod-db-temp-credentials.md`.

## Why this shape

| Constraint (verified 2026-10-26) | Consequence |
|---|---|
| `web35_8@'%'` holds `ALL PRIVILEGES ON web35_db8.*` — schema-scoped, so **no `CREATE USER`** | a second account is unavoidable; the design is therefore "how tightly can that account be scoped", not "should there be one" |
| A scoped provisioner (`CREATE USER ON *.*` + `SELECT,UPDATE ON db.* WITH GRANT OPTION`) cannot `GRANT ALL ON *.*`, cannot touch another schema, cannot grant itself anything, and cannot read `mysql.user` | the minting credential is powerful but not escalatory — proven on the staging DB before writing the role |
| **The same account *can* create `x@'%'`** | MariaDB will not restrict the host pattern, so the pattern is asserted in the sidecar and re-checked by the reaper on every sweep |
| A port published from an `internal: true`-only container produces no listener | the socat sidecar needs one non-internal network |
| A multi-homed container dials its peer over its **non-internal** network | joining `database` would flip the source to `172.24.x` and the grant would refuse the login; hence a dedicated `tunnel` bridge |
| The temporary account has no `CREATE` | the pre-session `bak_<table>_<date>` snapshot is taken by the provisioner, before any grant |

## Detailed changes

### `ls_dbeaver_access` (this repo)

| File | Change |
|---|---|
| `defaults/main.yml` | two tunnel definitions: stage (per host, unchanged) and **prod** (one static `dbeaver_tunnel`, port 33063); provision hosts; `dbeaver_ttl_cap_hours: 8`; `dbeaver_app_filter` (narrow a run to one stack) |
| `tasks/main.yml` | tunnel block (`ls.dbeaver.tunnel`) loops over the list; then stack discovery, `provisioner.yml` per stack, `reaper.yml`, `vault_push.yml` |
| `tasks/discover.yml` | finds the stacks that are **actually running** on the host: the DB container name comes from the stack, the compose directory from the container's `com.docker.compose.project.working_dir` label, the grant pattern from the `<stack>_backend` subnet |
| `templates/dbeaver_stage_sshd.conf.j2` → `dbeaver_sshd.conf.j2` | `Match User {{ tunnel.user }}`; the rendered stage fragment is **byte-identical** (verified with `diff`) |
| `tasks/vault_push.yml` | key backup only — the temporary DB credentials deliberately do **not** go to Vaultwarden; the app reveals them once |
| `tasks/provisioner.yml` | creates `dbaccess@<pattern>` per stack, asserts the pattern is that stack's backend network, renders that stack's `dba.env` |
| `templates/dba.env.j2` | the sidecar's own env file, separate from `ls.env` so the app and nginx never see the provisioner password; one file per stack |
| `tasks/reaper.yml` + 3 templates | `/usr/local/sbin/ls-db-access-reap` + service + 5-minute timer; **one unit, one sweep per stack** (`container|db|pattern|cap` list), each stack isolated so a broken one cannot stop the others |
| `ls_app/templates/ls.env.j2` | `DBACCESS_ENABLED` (**default `false`**), `DBACCESS_SECRET_KEY`, `DBACCESS_TTL_CAP_HOURS` |
| `ls_app/vars/secret_{main,stage}.yaml` (git-crypt) | `app.dbaccess_secret_key` — a Fernet key per stack |

One host can run more than one LeagueSphere stack (servy: prod from `container`, stage from
`container-stage`), so the role is stack-aware: it discovers both, provisions each into its own
compose directory, and the reaper sweeps both. Nothing is hardcoded to a path — a missed stack
would mean `docker compose up` failing on the stack that was skipped (`env file .../dba.env not
found`), which is exactly what the first version of this role did.

The provisioner password is generated **once per stack** on the controller
(`~/.dbeaver_provisioner_<host>_<app>`) and never regenerated by a normal run: regenerating it
would lock that sidecar out of the database it just created accounts in. Rotation is a deliberate
two-step (delete the file, re-run the role, recreate the sidecar) documented in
`docs/leaguesphere-temp-db-access.md`.

### `leaguesphere` (other repo)

`dbaccess` models (with the two constraints), staff pages, admin, allow-list sync command,
migration, 21 tests; `deployed/dba/tick.sh`; `db-access` in both compose files; `db-tunnel` +
`tunnel` network on prod; CI scope and shard entries.

## Verification performed

### Static

- `ansible-playbook plays/leaguesphere.yml --syntax-check -i production` → `playbook: plays/leaguesphere.yml`.
- `yamllint -c .yamllint.yml ansible/plays/roles/ls_dbeaver_access` → clean.
- The reaper template renders (two stacks) and passes `bash -n`.
- The stage sshd fragment renders byte-identically to the deployed one.
- `docker compose config` → exit 0 for both app-repo compose files, with `db-access` present.
- The app's own suite covers the constraints, reveal and permission paths (see that PR).

### Stage rollout (real, prod untouched)

`./servyy.sh --tags ls.dbeaver --skip-tags ls.dbeaver.tunnel -e dbeaver_app_filter=leaguesphere_stage --limit servy.lehel.xyz`

- Discovery found **2 stack(s)**: `leaguesphere`, `leaguesphere_stage`; provisioning was narrowed
  to `leaguesphere_stage` and prod's provisioner include was skipped.
- `/var/jail/home/leaguesphere/container-stage/deployed/dba.env` written, `0600
  leaguesphere:leaguesphere`, `DBACCESS_HOST=mysql`, `DBACCESS_DB=leaguesphere_stage`,
  `DBACCESS_HOST_PATTERN=172.26.%`.
- `leaguesphere_stage.mysql`: `dbaccess@'172.26.%'` with `CREATE USER ON *.*`,
  `SELECT, INSERT, UPDATE ON leaguesphere_stage.* WITH GRANT OPTION`.
- `ls-db-access-reap.timer` enabled + active; the script covers **both** stacks
  (`leaguesphere.db|web35_db8|172.25.%|8` and `leaguesphere_stage.mysql|leaguesphere_stage|172.26.%|8`)
  and a manual run exits 0.
- A second run is idempotent (`changed=0`).
- Prod untouched: no `container/deployed/dba.env`, no `dbaccess`, `dbeaver_*` or
  `dbeaver_tunnel` account, no `dbeaver-prod.conf`, prod DB container untouched.

### Credential and safety-net rehearsal on stage (no app deployed)

- The sidecar's **own statements** were executed as `dbaccess@'172.26.%'` with the provisioned
  password: `CREATE USER`, `ALTER USER … MAX_STATEMENT_TIME`, `REVOKE ALL`, `GRANT SELECT`,
  `GRANT SELECT,UPDATE` on a named table, `CREATE TABLE bak_… AS SELECT … LIMIT 0`, `DROP USER`
  → all OK. `DROP TABLE` on the snapshot → denied (as intended; the operator drops backups).
- A smuggled `dbeaver_prod_probe@'%'` was planted and reaped by the deployed script
  (`host pattern '%' is not '172.26.%'`), exit 0.
- The ledger path was exercised on a scratch schema (`reap_probe`) with three accounts: the
  smuggled one, one past the 8 h cap, and one fresh and active. The first two were killed and
  dropped with correct `dbaccess_request`/`dbaccess_event` rows (including a reason containing
  quotes); the fresh one survived. Scratch schema and accounts removed afterwards.
- The deployed reaper now runs silently and exits 0 on both stacks (no ledger on either stack
  yet, so the ledger writes are skipped instead of erroring).

### Bugs found while validating (all fixed in this PR)

| Bug | Effect if shipped |
|---|---|
| `include_vars: name:` binds the whole document, so `dbeaver_app.name` never resolved | the role died on the first provisioning host with "dict has no attribute 'name'" |
| tags on a dynamic `include_tasks` do **not** propagate | `--tags ls.dbeaver.provision` / `.reap` loaded the file and then skipped every task in it, i.e. rotation and the documented safety-net check silently did nothing. Task files are now wrapped in tagged blocks |
| `GRANT ... ON db.dbaccess_event` | MariaDB refuses a table-level grant on a table that does not exist (ERROR 1146), and the role runs **before** the migration that creates it → the whole run aborted on a fresh host. `INSERT` is now schema-wide (without `GRANT OPTION`) |
| the role assumed one stack and one hardcoded `container` path | on servy it wrote stage's `dba.env` nowhere, so `docker compose up` on stage failed with `env file .../dba.env not found` |
| the provisioner had no `CREATE` on the schema | the sidecar's pre-session `bak_<table>_<date>` snapshot fails, so **every** request is parked as `failed` on the first tick (reproduced with the real credential: `CREATE command denied`) |
| the provisioner had no `PROCESS`, so the sidecar's `KILL` is a no-op | `DROP USER` does not disconnect a session, so a revoked person kept writing and then vanished from `mysql.user` — invisible to the account sweep. The reaper now kills lingering `dbeaver_prod_*` sessions itself, as root (≤ 5 min) |
| the reaper wrote the ledger unconditionally and interpolated values unescaped | an ERROR in the journal every five minutes on a host without the schema yet, and a failed `UPDATE`/`INSERT` whenever the reason held a quote — which the pattern reason always does |

**Not verified (needs the app PR merged):** a mint driven by the app, a revoke driven by the app
(the kill/drop path itself was exercised on a scratch schema, including the session kill), and the
full request → approve → connect → expire cycle.

## Impact assessment

| | |
|---|---|
| **Privilege** | one new MySQL account (`dbaccess`) with `CREATE USER`, `PROCESS`-free, and schema-scoped `SELECT, INSERT, UPDATE, CREATE … WITH GRANT OPTION` (MariaDB merges `CREATE` into the schema grant, so it inherits the option; the sidecar's code never grants it). Nothing else in the stack gains privilege; the app never gets it |
| **Revocation** | account dropped in ~15 s; an already-open session is killed by the reaper on its next sweep (**≤ 5 min**) — the sidecar cannot kill it without a global `PROCESS` |
| **New container** | `db-access` per stack: no port, no volume, read-only rootfs, `cap_drop: ALL`, no-new-privileges, **no watchtower label** |
| **New host unit** | `ls-db-access-reap.timer`, every 5 minutes, quiet when there is nothing to reap; one sweep per stack on the host |
| **App surface** | four staff pages behind `is_staff`, approval additionally behind `dbaccess.approve_requests`; **off unless `-e dbeaver_dbaccess_enabled=true`** |
| **Secrets** | one new git-crypt'd key per stack (`app.dbaccess_secret_key`), one controller-side generated password per stack |
| **Existing behaviour** | the stage tunnel (`dbeaver_stage`, 33062), the sshd hardening and all other roles are untouched; prod's stack is untouched by the stage rollout |

## Rollback

| Component | How |
|---|---|
| The whole flow | `DBACCESS_ENABLED=false` + `./servyy.sh --tags ls.app.env,ls.app.deploy`; the pages 404 into the feature switch |
| Minting | `docker compose -p leaguesphere stop db-access`; already-minted accounts keep working until the reaper drops them (≤ cap) |
| Reaper | `systemctl disable --now ls-db-access-reap.timer`, then drop accounts by hand |
| Provisioner | `DROP USER 'dbaccess'@'172.26.%'` (stage) / `'dbaccess'@'172.25.%'` (prod) — the sidecar can then mint nothing; delete the matching controller file `~/.dbeaver_provisioner_<host>_<app>` |
| Tunnel | `git revert` the role change and redeploy; stage is unaffected either way |

## Stage rehearsal (app half), 2026-10-26

The app half went to stage from the PR branch, because the registry path was closed on both ends:
`leaguesphere/backend:staging` is only pushed by the tag pipeline's `deploy_staging` job (branch
pipelines never push it), and the Docker Hub PAT in `~/.docker/config.json` (user `dachrisch`) is
revoked — `docker login` and the auth endpoint both answer `401 incorrect username or password`.
So the image was built from `feat/dbaccess-flow` on servyy-test.lxd
(`container/app.Dockerfile`), copied to servy with `docker save | docker load`, retagged
`leaguesphere/backend:staging`, and the compose file was pulled from the branch by overriding
`app.branch` (extra vars beat the role's `include_vars`).

Three defects surfaced that no unit test could have caught:

1. **Table names disagreed with the sidecar.** `AccessRequest`/`AccessEvent` left `db_table` to
   Django, which created `dbaccess_accessrequest` / `dbaccess_accessevent`, while
   `deployed/dba/tick.sh` selects from `dbaccess_request` / `dbaccess_event`. Every tick logged
   `ERROR 1146 ... Table 'leaguesphere_stage.dbaccess_request' doesn't exist` and no account was
   ever minted — requests would have been approvable in prod with nothing happening. Fixed on the
   branch (`f0ddd79`): explicit `db_table` in both models, the same in the never-released
   `0001_initial`, and `test_table_names_match_the_sidecar_sql` to pin the contract.
2. **Mounted directories were unreadable.** The ansible `git pull` runs with the deploy account's
   umask (`0027`), so `deployed/mysql-conf` landed `0750` and `deployed/dba/tick.sh` `0750`. mysqld
   (uid 999) could not read `/etc/mysql/conf.d` and crash-looped; the sidecar, which drops ALL
   capabilities *including `DAC_OVERRIDE`*, could not read its own script as root
   (`Permission denied`). Prod would have failed the same way — its compose has no `mysql-conf`
   mount yet, so this was the first deploy that created one. Fixed in `ls_app`:
   `app_world_readable_dirs` (`mysql-conf`, `dba`) is widened to `u=rwX,go=rX` right after the pull,
   before `ls.env`/`dba.env` are rendered, so the secrets keep `0600`.
3. **watchtower-dev owns the stage containers.** `portainer.watchtower-dev` polls every 300 s and,
   within a minute, replaced the locally loaded image with the registry's (old) `:staging`. A branch
   rehearsal therefore needs `docker stop portainer.watchtower-dev`, plus `-e app_compose_pull=never`
   and `--skip-tags ls.app.deploy.pull` so compose does not pull the tag over the loaded image.

Result of the rehearsal on `stage.leaguesphere.app` (image built from `f0ddd79`):

| Step | Evidence |
|---|---|
| Request | form `200`, POST `302`, state `requested` |
| Self-approval | `403 Forbidden` |
| Approval | `302`, state `approved`, approver recorded |
| Mint | sidecar tick → `active`, `dbeaver_prod_rehearsal@'172.26.%'` |
| Grants | `SELECT` on `leaguesphere_stage.*`, `SELECT, UPDATE` on the requested table only; `MAX_USER_CONNECTIONS 4`, `MAX_STATEMENT_TIME 60` |
| Login as the minted account | read on the requested table OK; `CREATE`, `INSERT`, `DELETE` denied `1142` |
| Reveal | `200`, 24-char credential, `revealed` event |
| Revoke | `302` → `revoke_requested` → sidecar → `dropped`, `dropped_at` set, no `dbeaver%` account left |

One design gap the rehearsal made visible: the tick grants `SELECT` on the whole schema, so the
tables on `NEVER_GRANTABLE` (`auth_user` password hashes, sessions, `django_admin_log`) are readable
by any minted account even though the request form will not offer them. The curated list currently
restricts only what can be *requested* and what can be *written*; if "withheld" is meant to include
reads, the mint has to grant `SELECT` per table instead of on the schema.

## Next steps

1. Merge both PRs.
2. Deploy the app half for **stage only** —
   `--tags ls.app.stage --skip-tags ls.db.sync -e dbeaver_dbaccess_enabled=true` (without the
   skip, `ls_db_sync` also carries the `ls.app.stage` tag and would dump/import prod into stage;
   without the flag, `DBACCESS_ENABLED` renders `false` and there is nothing to validate). That
   brings up the `db-access` sidecar the stage `dba.env` is already waiting for. Then
   `dbaccess_sync_tables` in the staging app.
3. Rehearse on stage: create + approve a request, watch `active` within 15 s, prove
   `UPDATE auth_user` is denied, prove the `@'%'` smuggled account is reaped, prove a live
   session is killed. Record the result here.
4. Only then enable on prod (role for both stacks: `dba.env` + `dbaccess@'172.25.%'`, the tunnel
   account and its Vaultwarden push), with the feature flag still off until
   `dbaccess_sync_tables` has run and `dbaccess.approve_requests` is granted to one named human.
5. Wire the remaining open decisions from the plan: whether `INSERT`/`DELETE` is ever granted,
   whether `QUERY_DML` (reads) should be logged during a session, and who signs off on the
   revoke.

## UI pass after the stage review, 2026-10-26

Walking the flow on stage turned up three defects that the rehearsal's HTTP assertions could not
see: the request form was unstyled Django output; the "Person" field asked the requester to type a
handle that then became a MySQL account name; and an approver was offered Approve/Deny on their own
request, which only led to a bare `HttpResponseForbidden` page.

Fixed on `feat/dbaccess-flow` (`bdb6fc5e`, image `sha256:786c68d4a5ee`):

| Defect | Fix |
|---|---|
| no styling | widgets carry Bootstrap 5 classes from `forms.py` (`form-control`, `form-select`, `form-select` + `size=12` for the table list), fields sit in cards, `_field.html` renders label/help/error the same way everywhere |
| "Person" was typed | removed from the form. `access_handle(username)` derives it (lowercased, alphanumeric, capped at 19 characters — `dbeaver_prod_` uses 13 of `db_user`'s 32); the form shows the resulting account name as static text and the view rejects a login with no letters or digits |
| 112-entry list box | client-side filter input, selection counter and "clear selection" (vanilla JS, no new dependency) |
| confirmation twice | the templates rendered `messages` in addition to `base.html`, which already renders them globally |
| Approve/Deny on your own request | `RequestDetailView` exposes `is_mine`, and `can_approve` is now `may_approve and not is_mine and approver is None`; the page explains why instead of offering the button |
| bare 403 | `DecideView` still answers `403` (the guard is unchanged) but renders `dbaccess/forbidden.html` inside `base.html`, with a way back |

Verification on stage (`stage.leaguesphere.app`, image `sha256:786c68d4a5ee`, health `200`,
`/dbaccess/` `302` → login): a temporary staff user saw `dbeaver_prod_stagecheck` on
`/dbaccess/requests/new/` with no `person` input; their own request page contained no
`/decide/` URL and the POST answered `403` with the styled page. 43 dbaccess tests pass, including
new ones for `access_handle()` (case, symbols, 19-char cap, unusable login) and for the requester's
absent decide controls. The temporary user and its request were deleted afterwards.

**Deploy trap, worth repeating:** `-e app_compose_pull=never` alone is not enough.
`Pull Docker images for staging` (tag `ls.app.deploy.pull`, `force_source: yes`) re-tags
`leaguesphere/backend:staging` from the registry, so the recreated container runs the old published
image — the symptom is a healthy container where `/dbaccess/` is `404`. Skip
`ls.app.deploy.pull` as well, then `docker rm -f leaguesphere_stage.staging-app`.

## Proper rollout through the pipeline, 2026-10-26

The local-image path above was a rehearsal crutch. The normal route was then used, and it works —
no revoked credential is involved, because the pipeline carries its own Docker Hub token in the
CircleCI `staging` context:

```bash
gh workflow run deploy.yaml --ref feat/dbaccess-flow -f environment=staging -f bump_type=patch
```

| Step | Evidence |
|---|---|
| `Deploy (Stage / Demo)` | run `40385300816`, success; `4.43.1 → 4.43.2-rc.1`, commit `116c868b`, tag `v4.43.2-rc.1` pushed on the branch |
| CircleCI tag pipeline | full matrix (all shards + e2e + image builds + compose test) → `deploy_staging` success; pushed `leaguesphere/backend:staging` and `:v4.43.2-rc.1` |
| Watchtower-dev | restarted, first poll at 20:31, blue-green replaced the app at 20:34 and `www` right after |
| Running image | `sha256:a212f96f9e05`, `league_manager.__version__` = `4.43.2-rc.1` |
| Migrations | entrypoint ran `migrate` on start: "No migrations to apply" (stage was already current) |
| UI on stage | form `200` showing `dbeaver_prod_<login>` with no `person` field; own request page has no `/decide/` link; crafted POST → styled `403` |

The branch now carries the version-bump commit **and** the tag. The tag stays (it names the image
stage is running); the bump commit has to be reset to the master state before merge, which
`scripts/check_version_sequence.py` enforces at PR time.

Two things this settles:

1. **The registry is not closed.** The revoked PAT is local to this controller's
   `~/.docker/config.json`; CI authenticates with its own secret, so `:staging` publishes normally.
   The `docker save | docker load` recipe stays documented as a fallback only.
2. **Watchtower is the stage roller.** Re-enabling `portainer.watchtower-dev` is the deploy step for
   stage: it pulled both images and cut over blue-green, health-gated. Nothing else needed to run.

## Stage gets the same tunnel executor, 2026-10-26

Handing the flow to a human exposed a hole the HTTP rehearsal could not: stage mints the
`dbeaver_prod_<person>@'172.26.%'` accounts, but its tunnel target was the plain mysql publish
(`127.0.0.1:33062`), and a forwarded connection arrives from the *host's* address. Measured with
the sidecar's own provisioner account, which carries the identical grant pattern:

```
ERROR 1045 (28000): Access denied for user 'dbaccess'@'192.168.0.1'
```

So no human could have logged in to stage with a minted account. Prod never had the problem
because its tunnel lands on a `db-tunnel` socat that dials `db:3306` from inside the compose
network. Stage now has the same service (`deployed/docker-compose.staging.yaml`, `aa83541b`):
`TCP-LISTEN:33064 → mysql:3306`, joined to `backend` (172.26.x) plus a publish-only `tunnel`
network, because a port cannot be published from an internal network and `mysql` must not be
reachable over the publishing one. The `dbeaver_stage` key was narrowed to
`permitopen="127.0.0.1:33062"` before; `local_ports` (`9c90e69`) lets it carry both, so the old
publish keeps working for anything granted from the host address.

End-to-end through the tunnel, with a throwaway requester/approver pair (deleted afterwards):

| Check | Result |
|---|---|
| Request → approve (second user, via the UI) | state `approved` → `active` within 25 s |
| Minted account | `dbeaver_prod_tunnelcheck@172.26.%`, secret set |
| Login over `127.0.0.1:33064` (same path as DBeaver) | `CURRENT_USER() = dbeaver_prod_tunnelcheck@172.26.%`, peer `172.26.0.4` |
| Grants | `SELECT` on `leaguesphere_stage`.*, `SELECT, UPDATE` on `divisions`, `MAX_USER_CONNECTIONS 4`, `MAX_STATEMENT_TIME 60` |
| Snapshot | `bak_divisions_20261026` exists with the same row count as the source |
| `UPDATE` on a non-requested table | `ERROR 1142` |
| `CREATE TABLE`, `DELETE` on a granted table | `ERROR 1142` |
| Revoke in the app | `dropped` within 25 s, no `dbeaver%` account left in `mysql.user` |

DBeaver: SSH `dbeaver_stage@servy.lehel.xyz:22` with the stage tunnel key, main host
`127.0.0.1:33064`, database `leaguesphere_stage`, user `dbeaver_prod_<login>`, password from
**Show password**.

## Prod rollout, 2026-10-27

Both PRs were merged (`#2092` binlog/audit, `#2093` dbaccess), released as **4.44.0**
(`#2098`, tag `v4.44.0`), and CircleCI pushed `leaguesphere/backend:latest` through
`deploy_staging` → `hold_production` (auto-approved, no live games) → `deploy_production`.

```bash
# infra half first: dba.env must exist before the compose that mounts it
./servyy.sh --tags ls.dbeaver --limit servy.lehel.xyz
# app half with the feature still OFF
./servyy.sh --tags ls.app.pull,ls.app.env,ls.app.deploy \
  -e dbeaver_dbaccess_enabled=false --limit servy.lehel.xyz
ssh servy.lehel.xyz "docker exec leaguesphere.app python manage.py dbaccess_sync_tables"
# grant dbaccess.approve_requests to one named human, then switch it on
./servyy.sh --tags ls.app.env,ls.app.deploy \
  -e dbeaver_dbaccess_enabled=true --limit servy.lehel.xyz
```

| Check | Result |
|---|---|
| Containers | `leaguesphere.{db,app,www,db-access,db-tunnel}` all up |
| App version | `4.44.0` |
| `/dbaccess/` | `302` → login (was `404` before the flag) |
| `/health/` | `200` |
| Allow-list | `dbaccess_sync_tables`: 104 grantable, 8 withheld |
| Approver | `dbaccess.approve_requests` granted to `chrisd` (superusers can approve too; a second named human is still needed so nobody has to rely on that) |
| Prod tunnel path | `127.0.0.1:33063` → socat → mysql: peer `172.25.0.3`, `CURRENT_USER() = dbaccess@172.25.%` (the pattern the minted accounts are granted from) |
| Binlog | `log_bin=1`, `binlog_format=ROW` |

Two things the rollout taught, both now fixed:

1. **The statement audit was never writing.** The plugin loaded (`SERVER_AUDIT ACTIVE`) but
   `server_audit_logging` was never set, so neither stack produced a `server_audit.log` — the
   only trace was the plugin's startup line in the container log. The timestamp format also used
   strftime spelling; the plugin uses DATE_FORMAT semantics (`%M` = month name, `%i` = minute) and
   printed `2026-10-26 22:October:02`. `SET GLOBAL` closed the gap immediately, `#2099` makes it
   survive a restart (`server_audit_logging = ON`, `%Y-%m-%d %H:%i:%S`), and both DB containers
   were restarted at 07:22 UTC to read it.
2. **Watchtower-prod bounced the database four hours later** (image `mariadb:latest` changed) and
   that restart reverted the runtime `SET GLOBAL`. The config file is now the durable source, but
   it is worth remembering that a watchtower sweep can restart the prod DB container.

Follow-up worth doing: `.circleci/scope-exclude.txt` lists `deployed/mysql-conf/.*` (and
`deployed/dba/.*`), so a PR touching only those paths never runs `test_compose_network` or
`check_migrations` — the two required checks of the `PR` ruleset — and can only be merged with
`--admin` (`#2099` was). Mapping those paths to `run-compose` would make the ruleset satisfiable
for exactly the changes that alter how the container runs.

Also noted: `leaguesphere`'s PRs are GitHub *stacked* PRs, so `gh pr merge` refuses them
("must be merged using the asynchronous merge REST API"). Merge the top PR with
`gh api -X PUT repos/<owner>/<repo>/pulls/<n>/merge-async -f merge_method=squash` and poll
`GET .../merge-async/<uuid>`; merging the lower PR after its base has gone retargets it to
`master` and re-runs CI, which costs another full pipeline.

## Least-privilege follow-up: reads are granted table by table, 2026-10-27

The rollout shipped with `GRANT SELECT ON <db>.*`, so the curated allow-list bounded only what
could be *requested*. Measured on prod: every minted account could read `auth_user` (password
hashes), `django_session`, `django_admin_log`, `knox_authtoken` (274 rows), the
`oauth2_provider_*` bearer tokens (0 rows that day, live the moment an OAuth client logs in),
`officials_moodleremembertoken` — and `dbaccess_request.secret`, the **plaintext credential of any
live session nobody had revealed yet**. Reads were also invisible: `server_audit_events` was
`CONNECT,QUERY_DML_NO_SELECT`.

Fixed in `#2102`, released as **4.44.2**:

| Change | Effect |
|---|---|
| `tick.sh` grants `SELECT` per row of `dbaccess_grantabletable WHERE grantable=1` (one connection, ~92 statements) plus `SELECT` on the requested tables' `bak_<table>_<date>` snapshots | no schema-wide grant anywhere; the runbook's "verify the safety copy" step still works |
| `NEVER_GRANTABLE` grew from 8 to 20: `auth_group*`, `knox_authtoken`, `oauth2_provider_{access,refresh,id}token|grant|application`, `officials_moodleremembertoken`, `dbaccess_request`, `dbaccess_event`, `dbaccess_grantabletable` | the token tables and the feature's own tables leave the allow-list |
| `server_audit_events = CONNECT,QUERY` | a temporary session's statements — including the refused ones — are in `server_audit.log`; the app accounts stay excluded |

Verified on both stacks with a real mint (then revoked and deleted):

```
grants                 94 lines, e.g. GRANT SELECT ON `leaguesphere_stage`.`divisions`
divisions / snapshot   rows=4 / rows=4
auth_user              1142
dbaccess_request       1142
knox_authtoken         1142
oauth2_provider_accesstoken 1142
audit   2026-10-27 09:09:09,…,dbeaver_prod_grantcheckp,…,'SELECT COUNT(*) FROM dbaccess_request',1142
```

Operational consequence: a table added by a deploy is unreadable until `dbaccess_sync_tables` runs.
That command is already a documented post-deploy step; the failure is a loud `1142` rather than
silent access. Both stacks now report `112 tables, 20 permanently withheld`.
