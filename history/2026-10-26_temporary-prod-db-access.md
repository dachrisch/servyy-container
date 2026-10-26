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
