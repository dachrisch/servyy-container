# Prod DB access with temporary credentials — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
>
> **rev. 3 — architecture replaced (2026-10-25).** The per-person SSH account is gone. There is **one static tunnel account** and the **LeagueSphere app owns the identity**: a small sidecar container mints and drops the MySQL account, the app owns request → approval → state, and a host-side reaper enforces time. rev. 2's eight tasks collapse to two infrastructure pieces plus one app contract. The evidence that drove this is in the review pass below; the parts of rev. 2 that still hold are marked as such.

**Goal:** Give a named person DBeaver access to the LeagueSphere **prod** database through one shared, static SSH tunnel, with a **temporary MySQL account per session** that the web app provisions and that a host-side timer destroys — no prod password ever leaves the host, writes are scoped to named tables, and the account cannot outlive its approval.

**Architecture:** two small containers on the `leaguesphere` compose stack plus one host unit.

1. **Transport (static, deployed once).** One SSH account `dbeaver_tunnel` on `servy.lehel.xyz`, key-only, `permitopen="127.0.0.1:33063"`, `command="/bin/false"`, no shell. It reaches a loopback-only `socat` sidecar that relays to `db:3306`. Nothing per-person lives here.
2. **Identity (per session, app-managed).** A `dbaccess` sidecar in the same compose stack connects to `db` over the internal network as a **scoped provisioner** account. It mints `dbeaver_prod_<person>@'172.25.%'` with `SELECT` on the schema, `UPDATE` on a validated table list, `MAX_STATEMENT_TIME`/`MAX_USER_CONNECTIONS`, and drops it when the row says so.
3. **Control (app).** A `dbaccess` Django app owns requests, two-person approval, state and audit. No root, no `GRANT OPTION`, no host access.
4. **Enforcement (host).** A 5-minute reaper reads the request table as root through `docker exec` and drops anything past `created_at + hard cap`, in any state other than `active`, or on a host pattern other than `172.25.%`. It trusts time, not the app.

**Tech Stack:** Ansible (`ls_dbeaver_access`), `community.docker`, MariaDB 13.0.2, Docker Compose (leaguesphere repo), Django 5 + DRF + knox, OpenSSH, systemd timers.

---

## Verified baseline (2026-10-25, read from the running host)

| Fact | Value | Why it matters |
|---|---|---|
| Prod DB container | `leaguesphere.db`, db `web35_db8` (109 tables), app user `web35_8` | the app credential is never handed out |
| MariaDB | `13.0.2-MariaDB-ubu2604` | decides which SQL this plan may use |
| **App user grants** | `web35_8@'%'` → `ALL PRIVILEGES ON web35_db8.*` (schema-scoped) | **the app cannot `CREATE USER` / `GRANT`** — those are global privileges, so provisioning needs a second account |
| Prod DB networks | `leaguesphere_backend` = `172.25.0.0/16` (internal), `leaguesphere_database` = `172.24.0.0/16` (also holds `leagues-finance.finance-api`) | grant host must be `172.25.%` |
| `@@skip_name_resolve` | `ON` | IP patterns match directly |
| `@@log_bin` / `@@general_log` | `0` / `0` | **no SQL audit today** — being closed separately in `docs/plans/2026-10-26-mariadb-binlog-and-audit.md` (binlog ROW/FULL + `server_audit`, one restart). Until that lands, the app's event table is the only record |
| sshd | `PasswordAuthentication no`; `99-hardening.conf` already sets `AllowTcpForwarding local` | keep it |
| Existing stage tunnel | `dbeaver_stage` → `permitopen 127.0.0.1:33062` → `leaguesphere_stage.mysql` | unchanged by this revision |
| App shape | Django + DRF + knox; gunicorn; **no celery/rq** | nothing in the app can run "in 8 hours" — expiry stays on the host |
| App host access | jailed deploy, no docker socket, no systemd | the app cannot touch sshd, `useradd`, or units |
| Staff users | 32 `is_staff` of 344 total | a two-person rule is realistic |
| App hooks that already exist | `SiteConfiguration` singleton (kill switch), `gamedays.Permissions`/`UserPermissions`, `league_manager/management/commands/` | the new app fits existing patterns instead of inventing them |

**Probes run on the stage DB and dropped afterwards (2026-10-25)** — the privilege model this plan rests on:

| Probe, as a scoped provisioner | Result |
|---|---|
| `CREATE USER` / `ALTER USER … WITH MAX_STATEMENT_TIME` / `GRANT SELECT ON db.*` / `GRANT SELECT, UPDATE ON db.table` / `DROP USER` | allowed |
| `GRANT ALL ON *.*` **to itself** | `ERROR 1045` — denied |
| `GRANT CREATE USER ON *.*` to itself | `ERROR 1045` — denied |
| `GRANT SELECT ON mysql.*` to itself | `ERROR 1044` — denied |
| `GRANT SUPER ON *.*` to a temp user | `ERROR 1045` — denied |
| grant on another schema / `GRANT ALL` on its own schema | `ERROR 1044` — denied |
| `DELETE FROM db.table` with its own credential | `ERROR 1142` — denied |
| read `mysql.user` | `ERROR 1142` — denied |
| **`CREATE USER x@'%'`** | **allowed — MariaDB cannot restrict the host pattern** |

Two consequences, both designed around below: the provisioner **cannot escalate**, and the **host pattern must be re-enforced outside the database**.

Also re-verified for rev. 2 and still true: `REVOKE IF EXISTS` is not supported in 13.0.2 (irrelevant now — `DROP USER` is enough); `CREATE TABLE … AS SELECT` is denied to a `SELECT`+`UPDATE` account, and wildcard grants on `bak_%` are accepted but not honoured (so the pre-session snapshot is still taken by a privileged caller, see Task 3); a `172.25.%` user authenticates from `leaguesphere_backend` and is denied from `leaguesphere_database`.

**Docker network facts (scratch stack, 2026-10-25):** `ports:` on a container whose only network is `internal: true` is **silently dropped** (no listener, no error); a multi-homed container dials its peer over its **non-internal** network. Hence the socat sidecar sits on `backend` + a dedicated publish-only bridge, never on `database`.

**Environment note:** this checkout has no `ansible-playbook` on `PATH`. Every `./servyy.sh` / `./servyy-test.sh` command must run on the machine that has the toolchain. Read-only `ssh servy.lehel.xyz "docker exec …"` probes work from here.

---

## Review pass — what rev. 3 changed, and what it cost

The question that replaced rev. 2 was: *if the tunnel is static, the app only has to hand out and manage a database account — is a tiny sidecar enough?* Tested, yes — with two costs that must be accepted deliberately.

| # | Change | Why |
|---|---|---|
| C1 | **One static SSH account** (`dbeaver_tunnel`), no per-person `useradd`/sshd fragment/keypair | the transport was never where the control lives; N accounts meant N manual teardown steps and a private key stored server-side |
| C2 | **The app owns the identity layer**, executed by a sidecar with a **scoped provisioner** account | the app's own credential cannot `CREATE USER` (verified); a second account is unavoidable, so its scope is the design |
| C3 | **`/etc/ls-db-grants/` registry deleted**; the request table is the registry | one source of truth; the reaper reads it directly |
| C4 | **Reaper computes expiry from `created_at + hard cap`**, not from the app's `expires_at` | a compromised or buggy app can shorten a session, never extend one |
| C5 | **Host pattern is re-enforced by the reaper**, not only by the sidecar | `CREATE USER x@'%'` is allowed by MariaDB (verified) — the DB will not help |
| C6 | **`bak_` snapshot moves to the provisioner**, taken before the grants are applied | same privilege reality as rev. 2: the temp user cannot create tables |
| C7 | Vaultwarden leaves the flow (the app reveals the credential once) | the person may have no vault account; the ops backup stays available for the manual path |
| C8 | **Two-person approval becomes a software control** — this is the real cost | see "Trust boundaries": an internet-facing app now gates a privileged action |

**What this buys:** ~7 h instead of ~5 h, but 2 infra tasks instead of 6, no per-person host state, no private key on the server, and — the reason to do it at all — provisioning takes seconds instead of a playbook run.

**What it costs:**
1. **The approval is only as strong as the app.** If the sidecar blindly executes what the app says, then a compromised app mints credentials. The mitigations below (hard cap, reaper, journald-side audit, alerting) bound the damage; they do not restore the human-in-the-loop guarantee that rev. 2 had.
2. **Attribution moves entirely into the app.** One SSH account means the sshd log shows one user, and with no binlog the app's event table is the only record of who held access. It must be append-only and mirrored off-box.
3. **Expiry authority now lives in a container that Watchtower could swap.** Addressed by excluding the sidecar from auto-updates and pinning its image by digest.

---

## Trust boundaries

| Domain | Holds | Can it mint credentials? | Worst case if fully compromised |
|---|---|---|---|
| `leaguesphere.app` (web) | app DB credential | **no** (`CREATE USER` is global; the app has schema-scoped ALL) | read/write `web35_db8`, forge approvals |
| `leaguesphere.db-access` (sidecar) | scoped provisioner credential | yes — `172.25.%` only, `SELECT`+`UPDATE` only, ≤ 8 h | mint a schema-wide account (possibly on a broader host pattern, caught by the reaper) |
| `leaguesphere.db-tunnel` (socat) | nothing | no | a loopback relay with no credential |
| `dbeaver_tunnel` (SSH) | a rotated key | no | reach one loopback port |
| reaper (host, root via `docker exec`) | container root env | yes — it is root | total |

The middle row is the point: the sidecar is deliberately *more* powerful than the web app, and it is the only component with a new privilege. Keep its surface as small as the rest of the system allows (no ports, no volumes, read-only rootfs, no new privileges, own env file).

---

## Task 1: One static tunnel account (Ansible)

**Files:**
- Modify: `ansible/plays/roles/ls_dbeaver_access/defaults/main.yml`
- Modify: `ansible/plays/roles/ls_dbeaver_access/tasks/main.yml`
- Rename: `ansible/plays/roles/ls_dbeaver_access/templates/dbeaver_stage_sshd.conf.j2` → `templates/dbeaver_sshd.conf.j2`

**Step 1: Rename the template and generalize its body** (comments stay word-for-word; the rendered `dbeaver_stage.conf` must stay byte-identical)

```bash
cd /root/dev/dachrisch/servyy-container
git mv ansible/plays/roles/ls_dbeaver_access/templates/dbeaver_stage_sshd.conf.j2 \
       ansible/plays/roles/ls_dbeaver_access/templates/dbeaver_sshd.conf.j2
```

```jinja
# Managed by Ansible (ls_dbeaver_access role) - do not edit by hand.
# authorized_keys already restricts this key to local forwarding only
# (restrict,port-forwarding + permitopen) - this block is the enforcement
# layer that actually closes remote (-R) forwarding, which authorized_keys
# options alone cannot do (there is no per-key "local-only" option, only
# the blanket sshd AllowTcpForwarding local/remote/yes/no).
Match User {{ tunnel.user }}
    AllowTcpForwarding local
    X11Forwarding no
```

**Step 2: Replace `defaults/main.yml`**

```yaml
---
# ---------------------------------------------------------------------------
# SSH tunnel accounts for LeagueSphere DB access.
#
# rev. 3: the prod tunnel is ONE static account. The person is identified by the
# MySQL account the sidecar mints (dbeaver_prod_<person>@'172.25.%'), not by an
# SSH account - which is why the two names differ on purpose.
#
# `key_rotate_days` documents the intended rotation, not a mechanism: re-running
# with -e dbeaver_tunnel_rotate_key=true replaces the keypair and re-pushes the
# authorized_keys entry. A leaked tunnel key is useless without a live temp DB
# credential, but it should not be permanent either.
# ---------------------------------------------------------------------------

dbeaver_stage_tunnel:
  name: stage
  user: dbeaver_stage
  ssh_key_filename: "dbeaver_stage_key_{{ inventory_hostname_short }}"
  local_port: "33062"
  hosts:
    - servy.lehel.xyz
    - servyy-test.lxd
  vault_item_name: "dbeaver stage tunnel key ({{ inventory_hostname_short }})"

dbeaver_prod_tunnel:
  name: prod
  user: dbeaver_tunnel
  ssh_key_filename: "dbeaver_tunnel_key_{{ inventory_hostname_short }}"
  local_port: "33063"
  hosts:
    - servy.lehel.xyz
  vault_item_name: "dbeaver prod tunnel key ({{ inventory_hostname_short }})"

dbeaver_tunnels: "{{ [dbeaver_stage_tunnel, dbeaver_prod_tunnel] }}"

# --- sidecar / reaper (see Tasks 2-5) --------------------------------------
dbeaver_provision_hosts:
  - servy.lehel.xyz
  - servyy-test.lxd
dbeaver_db_name: web35_db8
dbeaver_db_container: "leaguesphere.db"
dbeaver_sidecar_service: "db-access"
dbeaver_sidecar_container: "leaguesphere.db-access"
dbeaver_grant_host_pattern: "172.25.%"   # re-asserted by the reaper
dbeaver_ttl_cap_hours: 8                 # the reaper's authority, not the app's
# `dbeaver_provisioner_password` is NOT defaulted here: it lives in
# ansible/plays/vars/secrets.yml (git-crypt'd) and must never be regenerated on
# a normal run - doing so would lock the sidecar out of the database it just
# created accounts in. Rotating it is a deliberate, two-step operation
# (Task 2 rerun + sidecar restart).
```

**Step 3: Replace the setup block in `tasks/main.yml`** — same shape as rev. 2, but `exclusive: true` now guards a *static* identity, so add the rotation switch:

```yaml
---
- name: Validate tunnel definitions
  assert:
    that:
      - item.user is match('^[a-z][a-z0-9_]{1,30}$')
      - item.name is match('^[a-z0-9-]{1,40}$')
      - item.local_port is match('^[0-9]{4,5}$')
    quiet: true
  loop: "{{ dbeaver_tunnels }}"
  loop_control:
    label: "{{ item.user }}"
  when: inventory_hostname in item.hosts
  tags:
    - ls.dbeaver

- name: Set up restricted SSH tunnel accounts
  block:
    - name: Create dedicated {{ item.user }} account (no shell, no extra groups)
      user:
        name: "{{ item.user }}"
        state: present
        shell: /usr/sbin/nologin
        create_home: true
      loop: "{{ dbeaver_tunnels }}"
      loop_control:
        label: "{{ item.user }}"
      when: inventory_hostname in item.hosts

    - name: Generate the SSH keypair for {{ item.user }}
      openssh_keypair:
        path: "~/.ssh/{{ item.ssh_key_filename }}"
        type: rsa
        size: 4096
        state: present
        # The prod tunnel is shared by everyone, so its key is rotated on demand
        # rather than only when it happens to be missing.
        force: "{{ (dbeaver_tunnel_rotate_key | default(false) | bool) and item.name == 'prod' }}"
      delegate_to: localhost
      become_user: "{{ local_user }}"
      loop: "{{ dbeaver_tunnels }}"
      loop_control:
        label: "{{ item.user }}"
      when: inventory_hostname in item.hosts

    - name: Restrict {{ item.user }} to its single permitted destination
      authorized_key:
        user: "{{ item.user }}"
        state: present
        exclusive: true
        key: "{{ lookup('file', '~/.ssh/' + item.ssh_key_filename + '.pub') }}"
        key_options: >-
          restrict,port-forwarding,permitopen="127.0.0.1:{{ item.local_port }}",command="/bin/false"
      loop: "{{ dbeaver_tunnels }}"
      loop_control:
        label: "{{ item.user }}"
      when: inventory_hostname in item.hosts

    - name: Deploy sshd Match block for {{ item.user }}
      template:
        src: dbeaver_sshd.conf.j2
        dest: "/etc/ssh/sshd_config.d/dbeaver-{{ item.name }}.conf"
        mode: '0644'
        validate: 'sshd -t -f %s'
      vars:
        tunnel: "{{ item }}"
      loop: "{{ dbeaver_tunnels }}"
      loop_control:
        label: "{{ item.name }}"
      when: inventory_hostname in item.hosts
      register: dbeaver_sshd_conf

    - name: Restart sshd when a Match block changed
      systemd:
        name: ssh
        state: restarted
      when: dbeaver_sshd_conf.results | selectattr('changed') | list | length > 0
  when: inventory_hostname in ['servy.lehel.xyz', 'servyy-test.lxd']
  tags:
    - ls.dbeaver
```

**Step 4: Keep `tasks/vault_push.yml`** exactly as rev. 2 left it (one key item per tunnel + the leaguesphere deploy key), imported last. On prod this now pushes a single shared key item: `dbeaver prod tunnel key (servy)`.

**Step 5: Check + deploy + prove the stage fragment did not change**

```bash
cd ansible
ansible-playbook plays/leaguesphere.yml --syntax-check -i production
ansible-lint plays/roles/ls_dbeaver_access/
./servyy-test.sh --tags ls.dbeaver --limit servyy-test.lxd --check --diff
./servyy-test.sh --tags ls.dbeaver --limit servyy-test.lxd
ssh servyy-test.lxd "sudo sshd -T -C user=dbeaver_stage | grep -E 'allowtcpforwarding|x11forwarding'"
```

Expected: `allowtcpforwarding local`, `x11forwarding no`, and no diff on `/etc/ssh/sshd_config.d/dbeaver-stage.conf`.

**Step 6: Commit**

```bash
git add ansible/plays/roles/ls_dbeaver_access/
git commit -m "refactor(ls_dbeaver): one static prod tunnel account"
```

---

## Task 2: The scoped provisioner account (Ansible)

The sidecar needs an account that can mint users. This is the only new privilege in the system, so it is created by Ansible (not by the app) and scoped as tightly as the reality allows.

**Files:**
- Create: `ansible/plays/roles/ls_dbeaver_access/tasks/provisioner.yml`
- Create: `ansible/plays/roles/ls_dbeaver_access/templates/dba.env.j2`

**Step 1: Write `tasks/provisioner.yml`**

```yaml
---
# Creates the account the sidecar uses. Deliberately:
#   * CREATE USER is global (there is no schema-scoped variant) - unavoidable.
#   * GRANT OPTION is scoped to the app schema only, so the account can hand out
#     SELECT/UPDATE there and nothing else. Verified: it cannot grant ALL on
#     *.*, cannot grant another schema, cannot grant itself anything.
#   * It therefore also holds SELECT+UPDATE on the schema (you can only grant
#     what you hold). That is the honest cost: this credential is as powerful as
#     the app credential, and it is the sidecar's alone.
- name: Read the app credentials for this host
  include_vars:
    file: "{{ playbook_dir }}/roles/ls_app/vars/{{ 'secret_main.yaml' if inventory_hostname == 'servy.lehel.xyz' else 'secret_stage.yaml' }}"
    name: dbeaver_app

- name: Derive container and grant host for this host
  set_fact:
    dbeaver_db_container: >-
      {{ (dbeaver_app.name ~ '.db') if dbeaver_app.name == 'leaguesphere'
         else (dbeaver_app.name ~ '.mysql') }}
    dbeaver_db_name: "{{ dbeaver_app.db_name }}"
    dbeaver_sidecar_container: "{{ dbeaver_app.name }}.db-access"
    dbeaver_sidecar_service: "db-access"
  no_log: true

- name: Read the network this DB is reached from
  community.docker.docker_network_info:
    name: "{{ dbeaver_app.name }}_backend"
  register: dbeaver_backend_net

- name: Derive the provisioner host pattern from the backend subnet
  set_fact:
    dbeaver_grant_host_pattern: >-
      {{ (dbeaver_backend_net.network.IPAM.Config[0].Subnet.split('/')[0].split('.')[0:2]
          | join('.')) ~ '.%' }}

- name: Refuse to provision outside the internal backend network
  assert:
    that:
      - dbeaver_grant_host_pattern == '172.25.%'
    fail_msg: >-
      {{ dbeaver_app.name }}_backend is {{ dbeaver_backend_net.network.IPAM.Config[0].Subnet }},
      not 172.25.0.0/16. Re-verify which containers share that network.
    quiet: true
  when: inventory_hostname == 'servy.lehel.xyz'

- name: Create the provisioner account inside the DB container
  community.docker.docker_container_exec:
    container: "{{ dbeaver_db_container }}"
    command: mariadb -h 127.0.0.1 -u root --batch
    stdin: |
      CREATE USER IF NOT EXISTS 'dbaccess'@'{{ dbeaver_grant_host_pattern }}'
        IDENTIFIED BY '{{ dbeaver_provisioner_password }}';
      ALTER USER 'dbaccess'@'{{ dbeaver_grant_host_pattern }}'
        IDENTIFIED BY '{{ dbeaver_provisioner_password }}';
      GRANT CREATE USER ON *.* TO 'dbaccess'@'{{ dbeaver_grant_host_pattern }}';
      GRANT SELECT, UPDATE ON `{{ dbeaver_db_name }}`.*
        TO 'dbaccess'@'{{ dbeaver_grant_host_pattern }}' WITH GRANT OPTION;
      GRANT INSERT, UPDATE ON `{{ dbeaver_db_name }}`.`dbaccess_event`
        TO 'dbaccess'@'{{ dbeaver_grant_host_pattern }}';
    env:
      MYSQL_PWD: "{{ dbeaver_app.db_root_password }}"
  no_log: true

- name: Show what the provisioner actually got
  community.docker.docker_container_exec:
    container: "{{ dbeaver_db_container }}"
    command: >-
      mariadb -h 127.0.0.1 -u root --batch --skip-column-names
      -e "SHOW GRANTS FOR 'dbaccess'@'{{ dbeaver_grant_host_pattern }}'"
    env:
      MYSQL_PWD: "{{ dbeaver_app.db_root_password }}"
  register: dbeaver_prov_grants
  changed_when: false

- name: Print the effective provisioner grants
  debug:
    var: dbeaver_prov_grants.stdout_lines

- name: Write the sidecar environment file next to the compose file
  template:
    src: dba.env.j2
    dest: "{{ (container_dir, dbeaver_app.container_dir, 'dba.env') | path_join }}"
    mode: '0600'
    owner: "{{ ls.user }}"
    group: "{{ ls.user }}"
  vars:
    container_dir: "{{ (ssh_chroot_jail_path, 'home', ls.user, 'container') | path_join }}"
  no_log: true
  when: inventory_hostname == 'servy.lehel.xyz'
```

`templates/dba.env.j2`:

```jinja
# Managed by Ansible (ls_dbeaver_access) - do not edit by hand.
# Read ONLY by the db-access sidecar. It is deliberately a separate file from
# ls.env so leaguesphere.app and leaguesphere.www never see the provisioner
# password.
DBACCESS_HOST=db
DBACCESS_PORT=3306
DBACCESS_USER=dbaccess
DBACCESS_PASSWORD={{ dbeaver_provisioner_password }}
DBACCESS_DB={{ dbeaver_db_name }}
DBACCESS_HOST_PATTERN={{ dbeaver_grant_host_pattern }}
DBACCESS_TTL_CAP_HOURS={{ dbeaver_ttl_cap_hours }}
```

The password itself lives in the git-crypt'd vars (`ansible/plays/vars/secrets.yml` as `dbeaver_provisioner_password`, per-host), generated once — never regenerated on a normal run, or the sidecar would lose its login.

**Step 2: Commit**

```bash
git add ansible/plays/roles/ls_dbeaver_access/
git commit -m "feat(ls_dbeaver): scoped provisioner account + sidecar env"
```

---

## Task 3: The `db-access` sidecar (leaguesphere repo)

**Files:**
- Create: `/root/dev/dachrisch/leaguesphere/deployed/dba/tick.sh`
- Modify: `/root/dev/dachrisch/leaguesphere/deployed/docker-compose.yaml` (two services + one network)

**Step 1: Write `deployed/dba/tick.sh`** — one pass, no HTTP, no listening socket, no free-form SQL.

```bash
#!/bin/sh
# Managed by Ansible (ls_dbeaver_access) - do not edit by hand.
#
# One pass of the DB-access executor. It reads INTENTS from dbaccess_request,
# validates them itself (it never trusts the row), mints or drops the MySQL
# account, and writes the outcome back. Anything it does not understand is
# parked as state='failed' - never guessed at.
set -eu

: "${DBACCESS_HOST:?}" "${DBACCESS_USER:?}" "${DBACCESS_PASSWORD:?}" "${DBACCESS_DB:?}"
HOST_PATTERN="${DBACCESS_HOST_PATTERN:?}"
TTL_CAP_H="${DBACCESS_TTL_CAP_HOURS:-8}"
TABLE_RE='^[a-z][a-z0-9_]{0,63}$'
PERSON_RE='^[a-z][a-z0-9]{1,20}$'

sql() {
  mariadb -h "$DBACCESS_HOST" -P "${DBACCESS_PORT:-3306}" \
          -u "$DBACCESS_USER" -p"$DBACCESS_PASSWORD" \
          --batch --skip-column-names "$@"
}

# The account name is derived HERE, never taken from the row: the row may only
# name a person, and the shape of the identity belongs to the executor.
db_user_for() { printf 'dbeaver_prod_%s' "$1"; }

sql_file() { sql "$DBACCESS_DB" < "$1"; }

########################################
# 1. approved -> active
########################################
sql "$DBACCESS_DB" -e "
  SELECT id, person, tables_csv, created_at
    FROM dbaccess_request
   WHERE state='approved'
   ORDER BY id
   LIMIT 5" | while IFS="$(printf '\t')" read -r id person tables _; do
  user=$(db_user_for "$person")

  # ---- validation. Any failure parks the request, it does not guess. --------
  fail() {
    echo "db-access: request $id rejected: $1" >&2
    sql "$DBACCESS_DB" -e "
      UPDATE dbaccess_request
         SET state='failed', failure_reason='$1', updated_at=NOW()
       WHERE id=$id AND state='approved'"
  }

  case "$person" in
    *[!a-z0-9]*) fail "person must match $PERSON_RE"; continue ;;
  esac
  [ "${#person}" -le 21 ] || { fail "person too long"; continue; }

  # every requested table must exist AND match the identifier shape
  valid_tables=""
  for t in $(printf '%s' "$tables" | tr ',' ' '); do
    case "$t" in
      *[!a-z0-9_]*) fail "table '$t' is not a plain identifier"; continue 2 ;;
    esac
    exists=$(sql -e "SELECT COUNT(*) FROM information_schema.tables
                      WHERE table_schema='$DBACCESS_DB' AND table_name='$t'")
    [ "$exists" = "1" ] || { fail "unknown table '$t'"; continue 2; }
    valid_tables="$valid_tables $t"
  done
  [ -n "$valid_tables" ] || { fail "empty table list"; continue; }

  echo "db-access: minting $user for tables:$valid_tables"

  # ---- pre-session snapshot, as the provisioner (the temp user cannot) ------
  # Fail the whole request rather than hand out a grant with no way back.
  today=$(date +%Y%m%d)
  for t in $valid_tables; do
    sql "$DBACCESS_DB" -e "
      CREATE TABLE IF NOT EXISTS \`bak_${t}_${today}\`
        AS SELECT * FROM \`${t}\`" || { fail "snapshot of $t failed"; continue 2; }
  done

  # ---- the credential ------------------------------------------------------
  pw=$(head -c 512 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)

  sql "$DBACCESS_DB" <<SQL || { fail "mint failed"; continue; }
CREATE USER IF NOT EXISTS '${user}'@'${HOST_PATTERN}' IDENTIFIED BY '${pw}';
ALTER USER '${user}'@'${HOST_PATTERN}' IDENTIFIED BY '${pw}';
ALTER USER '${user}'@'${HOST_PATTERN}'
  WITH MAX_STATEMENT_TIME 60 MAX_USER_CONNECTIONS 4;
REVOKE ALL PRIVILEGES, GRANT OPTION FROM '${user}'@'${HOST_PATTERN}';
GRANT SELECT ON \`${DBACCESS_DB}\`.* TO '${user}'@'${HOST_PATTERN}';
SQL

  for t in $valid_tables; do
    sql "$DBACCESS_DB" -e "
      GRANT SELECT, UPDATE ON \`${DBACCESS_DB}\`.\`${t}\`
        TO '${user}'@'${HOST_PATTERN}'" || { fail "grant on $t failed"; continue 2; }
  done

  # Password lands in `secret` for the app to hand out; the app moves it to
  # `secret_ct` and nulls this column on first reveal (Task 4).
  sql "$DBACCESS_DB" -e "
    UPDATE dbaccess_request
       SET state='active', db_user='${user}', grant_host='${HOST_PATTERN}',
           secret='${pw}', activated_at=NOW(), updated_at=NOW()
     WHERE id=${id} AND state='approved'"
  echo "db-access: $user active"
done

########################################
# 2. revoke / expiry -> drop
########################################
sql "$DBACCESS_DB" -e "
  SELECT id, db_user, grant_host
    FROM dbaccess_request
   WHERE state IN ('revoke_requested','expired')
     AND db_user IS NOT NULL
   ORDER BY id
   LIMIT 5" | while IFS="$(printf '\t')" read -r id user host; do
  echo "db-access: dropping $user@$host (request $id)"
  sql -e "SELECT id FROM information_schema.processlist WHERE user='${user}'" \
    | while read -r pid; do
        case "$pid" in ''|*[!0-9]*) continue ;; esac
        sql -e "KILL ${pid}" || true
      done
  sql -e "DROP USER IF EXISTS '${user}'@'${host}'" || true
  sql "$DBACCESS_DB" -e "
    UPDATE dbaccess_request
       SET state='dropped', secret=NULL, dropped_at=NOW(), updated_at=NOW()
     WHERE id=${id}"
done
```

**Step 2: Add the services to `deployed/docker-compose.yaml`**

```yaml
  # Loopback-only TCP endpoint for the dbeaver_tunnel SSH account.
  # Two network facts drive the wiring (verified on a scratch stack):
  #   * `ports:` on a container whose only network is internal:true is silently
  #     dropped - no listener, no error;
  #   * a multi-homed container dials its peer over its NON-internal network, so
  #     joining `database` would make MySQL see 172.24.x and the 172.25.% grant
  #     would refuse the login.
  db-tunnel:
    image: alpine/socat:1.8.1.3
    container_name: ${COMPOSE_PROJECT_NAME}.db-tunnel
    restart: unless-stopped
    command: TCP-LISTEN:33063,fork,reuseaddr TCP:db:3306
    ports:
      - "127.0.0.1:33063:33063"
    networks:
      - backend
      - tunnel
    labels:
      - traefik.enable=false
      - io.portainer.accesscontrol.teams=leaguesphere

  # Mints and drops the temporary MySQL accounts. Privileged by design, so:
  # no published port, no volume, read-only rootfs, no new privileges, its own
  # env file, and NO watchtower label (auto-swapping this is a supply-chain hole).
  # It talks to the app only through rows in web35_db8 - there is no RPC surface.
  db-access:
    image: mariadb:latest
    container_name: ${COMPOSE_PROJECT_NAME}.db-access
    restart: unless-stopped
    entrypoint: ["/bin/sh", "/opt/dba/tick.sh"]
    command: ["--loop"]
    env_file: dba.env
    volumes:
      - ./dba:/opt/dba:ro
    networks:
      - backend          # 172.25.x - the grant host depends on it
    read_only: true
    tmpfs:
      - /tmp
    user: "65534:65534"
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    labels:
      - traefik.enable=false
      - io.portainer.accesscontrol.teams=leaguesphere
```

and the network:

```yaml
networks:
  backend:
    internal: true
  database:
    internal: false  # Allow external connectivity for MySQL
  # Publish-only bridge for db-tunnel: a port can only be published from a
  # non-internal network, and joining `database` would flip the DB connection's
  # source IP to 172.24.x. No other service joins it.
  tunnel:
    internal: false
  proxy:
    external: true
```

The `--loop` flag is handled at the top of `tick.sh`:

```sh
if [ "${1:-}" = "--loop" ]; then
  while :; do
    /bin/sh /opt/dba/tick.sh || echo "db-access: tick failed" >&2
    sleep 15
  done
fi
```

**Step 3: Validate and deploy**

```bash
cd /root/dev/dachrisch/leaguesphere/deployed
docker compose -f docker-compose.yaml config --quiet
ssh servy.lehel.xyz "docker inspect -f '{{.State.StartedAt}}' leaguesphere.db"   # record this
cd /root/dev/dachrisch/servyy-container/ansible
./servyy.sh --tags ls.app.pull,ls.app.deploy --limit servy.lehel.xyz
ssh servy.lehel.xyz "docker inspect -f '{{.State.StartedAt}}' leaguesphere.db"   # must be unchanged
ssh servy.lehel.xyz "docker logs --tail 20 leaguesphere.db-access"
```

Expected: `leaguesphere.db-tunnel` and `leaguesphere.db-access` up, `leaguesphere.db` with the **same** start time (the sidecar is additive; the DB container is never recreated), and no error in the sidecar log. `pull: always` + `recreate: auto` can still recreate `db` if `mariadb:latest` moved upstream — if it does, treat that as a DB restart event, not a sidecar deploy.

**Step 4: Commit (twice: compose+script, then deploy verified)**

```bash
cd /root/dev/dachrisch/leaguesphere
git add deployed/dba/tick.sh deployed/docker-compose.yaml
git commit -m "feat(dbaccess): sidecar that mints temporary DB accounts"
git push origin HEAD && gh pr create --fill
```

---

## Task 4: The app contract (leaguesphere repo)

The sidecar needs a table it can read and update. That table, and the approval that fills it, belong to the app.

**Files (leaguesphere repo):**
- Create: `dbaccess/__init__.py`, `dbaccess/apps.py`, `dbaccess/models.py`, `dbaccess/admin.py`, `dbaccess/views.py`, `dbaccess/api.py`, `dbaccess/urls.py`
- Create: `dbaccess/migrations/0001_initial.py`
- Modify: `league_manager/settings/base.py` (INSTALLED_APPS + settings)
- Modify: `league_manager/urls.py` (staff-only routes)

**Step 1: `dbaccess/models.py`**

```python
import secrets

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth.models import User
from django.db import models


class AccessRequest(models.Model):
    """One request for one person. Rows are created by the app, executed by the
    db-access sidecar, and reaped by the host timer - three writers, one table."""

    STATE = [
        ("draft", "Draft"),
        ("requested", "Requested"),
        ("approved", "Approved"),
        ("active", "Active"),
        ("revoke_requested", "Revoke requested"),
        ("expired", "Expired"),
        ("dropped", "Dropped"),
        ("rejected", "Rejected"),
        ("failed", "Failed"),
    ]

    requester = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    approver = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    # the handle the DB account is built from; validated again by the sidecar
    person = models.CharField(max_length=21)
    purpose = models.TextField()
    ticket_url = models.URLField(blank=True)
    tables_csv = models.TextField(help_text="comma-separated table names")
    ttl_hours = models.PositiveSmallIntegerField(default=4)

    state = models.CharField(max_length=20, choices=STATE, default="draft", db_index=True)
    failure_reason = models.TextField(blank=True)

    db_user = models.CharField(max_length=32, blank=True, null=True)
    grant_host = models.CharField(max_length=32, blank=True, null=True)
    # plaintext only for the handover window; the app moves it to secret_ct on
    # first reveal and the reaper nulls it at the cap.
    secret = models.TextField(blank=True, null=True)
    secret_ct = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)   # the reaper's clock
    activated_at = models.DateTimeField(null=True, blank=True)
    dropped_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["state", "created_at"])]
        constraints = [
            # A two-person rule that a view can bypass is not a rule.
            models.CheckConstraint(
                check=models.Q(approver__isnull=True) | ~models.Q(approver=models.F("requester")),
                name="dbaccess_approver_is_not_requester",
            ),
            models.CheckConstraint(
                check=models.Q(ttl_hours__gte=1) & models.Q(ttl_hours__lte=8),
                name="dbaccess_ttl_within_cap",
            ),
        ]

    # --- credential handling -------------------------------------------------
    @staticmethod
    def _fernet():
        return Fernet(settings.DBACCESS_SECRET_KEY.encode())

    def reveal(self):
        """Return the password once and move it out of the plaintext column."""
        if not self.secret and not self.secret_ct:
            return None
        if self.secret:
            self.secret_ct = self._fernet().encrypt(self.secret.encode()).decode()
            self.secret = None
            self.save(update_fields=["secret", "secret_ct", "updated_at"])
            return self._fernet().decrypt(self.secret_ct.encode()).decode()
        return self._fernet().decrypt(self.secret_ct.encode()).decode()

    def tables(self):
        return [t.strip() for t in self.tables_csv.split(",") if t.strip()]


class GrantableTable(models.Model):
    """Curated allow-list. The requester picks from this, never from a text box,
    and the sidecar still re-validates against information_schema."""

    name = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=120, blank=True)
    grantable = models.BooleanField(default=True)
    note = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.name


class AccessEvent(models.Model):
    """Append-only. Until binlog + server_audit land (see the 2026-10-26 plan),
    this is the only record of who held access."""

    request = models.ForeignKey(AccessRequest, on_delete=models.CASCADE, related_name="events")
    at = models.DateTimeField(auto_now_add=True)
    actor = models.CharField(max_length=64)          # username, or "system"
    action = models.CharField(max_length=32)         # requested/approved/…/revealed
    detail = models.TextField(blank=True)
    from_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-at"]
```

`GrantableTable` gets seeded from `information_schema` by a management command (`python manage.py dbaccess_sync_tables`), with `auth_user`, `django_session`, `django_admin_log` and anything else PII-flagged landing as `grantable=False`.

**Step 2: Settings**

```python
INSTALLED_APPS = [ ..., "dbaccess", ]

# Key for the one-time credential reveal. Lives in ls.env, never in the DB, so a
# restored backup holds ciphertext only.
DBACCESS_SECRET_KEY = os.environ.get("DBACCESS_SECRET_KEY")
DBACCESS_TTL_CAP_HOURS = int(os.environ.get("DBACCESS_TTL_CAP_HOURS", "8"))
DBACCESS_ENABLED = os.environ.get("DBACCESS_ENABLED", "false") == "true"
```

**Step 3: The surfaces** — all staff-gated, all reusing what exists:

| Surface | Where | Rules |
|---|---|---|
| Request form | `/dbaccess/request/` (staff) | person, purpose, ticket, table multi-select from `GrantableTable`, TTL ≤ cap, then `state=requested` |
| Approval queue | `/dbaccess/queue/` (staff with `DB-Session-Approver` in `gamedays.Permissions`) | approve/deny with a reason; the model constraint blocks self-approval |
| Session page | `/dbaccess/<id>/` | countdown, tables, "revoke now" (→ `revoke_requested`), one-time reveal button |
| Admin | `dbaccess/admin.py` | read-mostly; `AccessEvent` is `has_add/change/delete = False` |
| Kill switch | `SiteConfiguration`-style flag | `DBACCESS_ENABLED=false` → no new approvals accepted |

`AccessEvent` rows are written on every transition, and the sidecar inserts its own (`action='activated'` / `'dropped'`) — that column is the only place the executor's view and the app's view meet.

**Step 4: Migration + smoke test on the test host**

```bash
cd /root/dev/dachrisch/leaguesphere
python manage.py makemigrations dbaccess && python manage.py migrate
python manage.py dbaccess_sync_tables
python manage.py test dbaccess
```

**Step 5: Commit**

```bash
git add dbaccess/ league_manager/settings/base.py league_manager/urls.py
git commit -m "feat(dbaccess): request, approval and reveal for temporary DB accounts"
```

---

## Task 5: The reaper (Ansible) — the authority

`/etc/ls-db-grants/` is gone. The reaper reads the app's table as root (through `docker exec`, so no new credential) and enforces **time and host pattern**, not the app's arithmetic.

**Files:**
- Create: `ansible/plays/roles/ls_dbeaver_access/templates/ls-db-access-reap.sh.j2`
- Create: `.../ls-db-access-reap.{service,timer}.j2`
- Create: `.../tasks/reaper.yml`

**Step 1: The script**

```bash
#!/bin/bash
# Managed by Ansible (ls_dbeaver_access) - do not edit by hand.
#
# Drops temp accounts that have outlived the HARD CAP, that the app says are not
# active, or that exist on any host pattern other than the expected one.
#
# It never trusts expires_at: the cap is computed from created_at, so a buggy or
# compromised app can shorten a session but cannot extend one.
set -euo pipefail

DB_CONTAINER="{{ dbeaver_db_container }}"
DB="{{ dbeaver_db_name }}"
PATTERN="{{ dbeaver_grant_host_pattern }}"
CAP_H="{{ dbeaver_ttl_cap_hours }}"

run_sql() {
  docker exec -i "$DB_CONTAINER" sh -c \
    'exec mariadb -h 127.0.0.1 -u root -p"$MYSQL_ROOT_PASSWORD" --batch --skip-column-names'
}

# 1. every dbeaver_prod_* account in the server ...
run_sql <<'SQL' | while IFS=$'\t' read -r user host; do
SELECT user, host FROM mysql.user WHERE user LIKE 'dbeaver\_prod\_%';
SQL
  reason=""
  if [ "$host" != "$PATTERN" ]; then
    reason="host pattern '$host' is not '$PATTERN'"
  else
    # 2. ... must be backed by an active row inside the cap
    verdict=$(run_sql <<SQL
SELECT CASE
         WHEN COUNT(*) = 0 THEN 'no-request-row'
         WHEN SUM(state='active') = 0 THEN 'not-active'
         WHEN MIN(created_at) < NOW() - INTERVAL ${CAP_H} HOUR THEN 'past-cap'
         ELSE 'ok'
       END
  FROM \`${DB}\`.\`dbaccess_request\`
 WHERE db_user='${user}';
SQL
)
    [ "$verdict" = "ok" ] || reason="$verdict"
  fi

  [ -z "$reason" ] && continue

  echo "ls-db-access-reap: dropping ${user}@${host} (${reason})"
  while read -r pid; do
    [[ "$pid" =~ ^[0-9]+$ ]] || continue
    run_sql <<<"KILL ${pid};" || true
  done < <(run_sql <<SQL
SELECT id FROM information_schema.processlist WHERE user='${user}';
SQL
)
  run_sql <<<"DROP USER IF EXISTS '${user}'@'${host}';" || true
  run_sql <<<"UPDATE \`${DB}\`.\`dbaccess_request\`
                 SET state='dropped', secret=NULL, dropped_at=NOW(), updated_at=NOW()
               WHERE db_user='${user}' AND state <> 'dropped';" || true
done
```

**Step 2: Unit + timer** (5 minutes; `Persistent=true`; `ConditionPathExists` is not possible any more, so the unit is simply cheap and quiet — it runs one `mysql.user` query when nothing exists)

```ini
[Unit]
Description=Reap expired temporary LeagueSphere DB accounts

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/ls-db-access-reap
```

```ini
[Unit]
Description=Reap temporary LeagueSphere DB accounts every 5 minutes

[Timer]
OnCalendar=*:0/5
AccuracySec=30s
Persistent=true

[Install]
WantedBy=timers.target
```

**Step 3: `tasks/reaper.yml`** — same shape as rev. 2's `expiry_timer.yml` (include `provisioner.yml` for the derived names, create `/usr/local/sbin` script, deploy units, enable timer). It runs on every provision host **unconditionally**: the safety net must exist with no active grant.

**Step 4: Commit**

```bash
git add ansible/plays/roles/ls_dbeaver_access/
git commit -m "feat(ls_dbeaver): reap temp accounts by hard cap and host pattern"
```

---

## Task 6: Rehearse the whole loop on `servyy-test.lxd`

**Step 1: Deploy the role and both sidecars on the test host**

```bash
cd ansible && ./servyy-test.sh --tags ls.dbeaver,ls.app.pull,ls.app.deploy --limit servyy-test.lxd
ssh servyy-test.lxd "docker ps --format '{{.Names}}' | grep -E 'db-access|db-tunnel|mysql'"
```

**Step 2: Create a request as staff, approve it as a second user** (the test host's admin UI or a shell)

```bash
ssh servyy-test.lxd "docker exec leaguesphere_stage.staging-app python manage.py shell -c \"
from dbaccess.models import AccessRequest
from django.contrib.auth.models import User
r = AccessRequest.objects.create(requester=User.objects.get(username='<a>'),
      approver=User.objects.get(username='<b>'), person='rehearsal',
      purpose='rehearsal', tables_csv='divisions', ttl_hours=2, state='approved')
print(r.id)\""
```

Expected within ~15 s: the sidecar log shows `minting dbeaver_prod_rehearsal`, the row flips to `active`, and `bak_divisions_<date>` exists. Then:

```bash
ssh servyy-test.lxd "docker run --rm --network leaguesphere_stage_backend \
  -e MYSQL_PWD=<secret-from-the-row> mariadb:latest \
  mariadb -h leaguesphere_stage.mysql -u dbeaver_prod_rehearsal \
  -e 'SELECT 1; SHOW GRANTS; SELECT @@max_statement_time;'"
```

Expected: `1`, `USAGE … WITH MAX_USER_CONNECTIONS 4 MAX_STATEMENT_TIME 60.000000`, grants for the schema (`SELECT`) and `divisions` (`SELECT, UPDATE`).

**Step 3: Prove the boundaries hold**

| Check | Expect |
|---|---|
| `UPDATE auth_user SET last_login=last_login LIMIT 1` as the temp user | `ERROR 1142` |
| connect as the temp user from `--network leaguesphere_stage_database` | `ERROR 1045` (host pattern) |
| `CREATE TABLE notbak (id int)` as the temp user | `ERROR 1142` (no CREATE) |
| provisioner tries `GRANT ALL ON *.*` | `ERROR 1045` (verified already on prod's engine) |

**Step 4: Prove the reaper, including the two cases the app cannot cause**

```bash
# (a) normal expiry: backdate the row past the cap
ssh servyy-test.lxd "docker exec leaguesphere_stage.mysql mariadb -uroot -p\"\$MYSQL_ROOT_PASSWORD\" \
  -e \"UPDATE leaguesphere_stage.dbaccess_request SET created_at = NOW() - INTERVAL 9 HOUR WHERE person='rehearsal'\""
ssh servyy-test.lxd "sudo systemctl start ls-db-access-reap.service; sudo journalctl -u ls-db-access-reap -n 5 --no-pager"
```

Expected: `dropping dbeaver_prod_rehearsal@172.26.% (past-cap)` and the account gone.

```bash
# (b) the hole: an account minted on a wider host pattern
ssh servyy-test.lxd "docker exec leaguesphere_stage.mysql mariadb -uroot -p\"\$MYSQL_ROOT_PASSWORD\" \
  -e \"CREATE USER dbeaver_prod_smuggled@'%' IDENTIFIED BY 'x'\""
ssh servyy-test.lxd "sudo systemctl start ls-db-access-reap.service"
```

Expected: `dropping dbeaver_prod_smuggled@% (host pattern '%' is not '172.26.%')`. This is the check that makes the static-tunnel design defensible — prove it on the test host before trusting it on prod.

```bash
# (c) a live session must be killed, not merely orphaned
```

Start a `SLEEP(120)` as the temp user, then run the reaper: the client must die with `ERROR 1927 … Connection was killed`.

**Step 5: Commit** the rehearsal notes into the history entry (Task 7).

---

## Task 7: Documentation and history

**Files:**
- Modify: `docs/leaguesphere-environments.md` (replace the rev. 2 "operator workflow" text)
- Create: `history/2026-10-25_leaguesphere-prod-db-temp-access.md`

**Step 1: The operator doc**

```markdown
### Temporary prod DB access (app-managed)

Prod DB access is requested and approved in the app, and expires on its own:

1. Staff user opens `/dbaccess/request/`, picks the person handle, the tables from the
   curated list, and a TTL (≤ 8 h).
2. A second staff user with `DB-Session-Approver` approves it. Self-approval is blocked
   by a database constraint, not a view.
3. Within ~15 s the `db-access` sidecar mints `dbeaver_prod_<person>@'172.25.%'`,
   snapshots the named tables as `bak_<table>_<date>`, and the session page shows the
   password once.
4. DBeaver → SSH host `servy.lehel.xyz`, user `dbeaver_tunnel`, the shared tunnel key;
   Main host `127.0.0.1`, port `33063`; DB `web35_db8`, user `dbeaver_prod_<person>`.
5. "Revoke now" on the session page drops it within 15 s. Otherwise `ls-db-access-reap`
   kills it at `created_at + 8 h` — the cap is enforced by the host, not by the app.

The SSH tunnel is shared and static; it carries no identity on purpose. Who held access
is recorded in `dbaccess_request` / `dbaccess_event`, which is the only such record
because prod runs without a binlog.
```

**Step 2: History entry** — the architecture swap and its evidence: the provisioner probe table, the `CREATE USER x@'%'` hole and how the reaper closes it, the two Docker network facts, the app-credential grant listing that made a second account unavoidable, and what was rehearsed on `servyy-test.lxd` versus verified on prod.

**Step 3: Commit**

```bash
git add docs/leaguesphere-environments.md history/2026-10-25_leaguesphere-prod-db-temp-access.md
git commit -m "docs: document app-managed temporary prod DB access"
```

---

## Session runbook (what the person actually does)

**DBeaver setup** — the same for everyone, which is the point of the static tunnel:

| Tab | Field | Value |
|---|---|---|
| SSH | Host / Port | `servy.lehel.xyz` / 22 |
| SSH | User | `dbeaver_tunnel` |
| SSH | Auth | the shared tunnel key (Vaultwarden: `dbeaver prod tunnel key (servy)`) |
| Main | Host / Port | `127.0.0.1` / `33063` |
| Main | Database / User | `web35_db8` / `dbeaver_prod_<person>` (password from the session page) |

**Rules**

1. Auto-commit **off** — a data-grid edit emits one `UPDATE` per keystroke.
2. Every write is preceded by a scoped `SELECT` in the same transaction; state the row count in the change note.
3. Confirm the role's pre-session snapshot exists (`SELECT COUNT(*) FROM bak_<table>_<date>`) before the first write. You have no `CREATE`, so you cannot take one yourself.
4. One table per transaction; re-run the scoping `SELECT` before `COMMIT`; prefer `ROLLBACK`.
5. Single statements stay under 60 s (`MAX_STATEMENT_TIME`) — an unbounded `SELECT *` is killed mid-flight.
6. Keep the statements in a `.sql` file and hand it over. With no binlog it is the only statement-level record.
7. Since the tunnel is shared, the DB account is the identity: never share a session's password, and don't reuse a machine where the tunnel key sits in a shell history.
8. A second day is a new request, a new account, a new password.

---

## Verification matrix (prod, in this order)

| # | Check | Command | Expected |
|---|---|---|---|
| 1 | Tunnel endpoint is loopback-only | `ssh servy.lehel.xyz "ss -tlnp \| grep 33063"` | `127.0.0.1:33063`, never `0.0.0.0` |
| 2 | DB container untouched by the deploy | `docker inspect -f '{{.State.StartedAt}}' leaguesphere.db` | unchanged from before |
| 3 | Provisioner cannot escalate | `SHOW GRANTS FOR 'dbaccess'@'172.25.%'` | `CREATE USER ON *.*` + `SELECT,UPDATE ON web35_db8.* WITH GRANT OPTION`, nothing global else |
| 4 | Tunnel account cannot get a shell | `ssh -i … dbeaver_tunnel@servy.lehel.xyz` | no output, exit 1 |
| 5 | Sidecar cannot be reached from outside | `docker port leaguesphere.db-access` | empty |
| 6 | Mint path | approve a request, wait ≤ 15 s | row `active`, `bak_<t>_<date>` exists, sidecar log line |
| 7 | Temp user authenticates from the backend net | `docker run --network leaguesphere_backend … -u dbeaver_prod_<p> -e 'SELECT 1'` | `1` |
| 8 | Writes outside the named tables are denied | same with `UPDATE auth_user …` | `ERROR 1142` |
| 9 | Limits are live | `SHOW GRANTS` + `SELECT @@max_statement_time` | `60.000000`, `MAX_USER_CONNECTIONS 4` |
| 10 | **Source IP through the tunnel is 172.25.x** | open a login through the tunnel, then read `information_schema.processlist` as root | `172.25.0.x`, never `172.24.0.x` |
| 11 | Reaper: past cap | backdate `created_at`, run the unit | journal line + account gone |
| 12 | **Reaper: host-pattern smuggled account** | create `dbeaver_prod_x@'%'` as root, run the unit | dropped with `host pattern` reason |
| 13 | Reaper kills live sessions | open a `SLEEP(120)`, run the unit | client dies: `ERROR 1927` |
| 14 | Revoke is fast | click "revoke now" | account gone ≤ 15 s, row `dropped` |
| 15 | Stage tunnel unaffected | `./servyy-test.sh --tags ls.dbeaver --check --diff --limit servyy-test.lxd` | no changes |
| 16 | sshd config stays valid | `sudo sshd -t` | exit 0 |
| 17 | Audit table is append-only | `SHOW GRANTS FOR 'web35_8'@'%'` shows no `DELETE` path used, and admin refuses delete | `AccessEvent` immutable in the UI |

## Rollback

| Component | Rollback |
|---|---|
| Sidecar | `docker compose stop db-access` — grants already issued keep working until the reaper drops them (≤ cap) |
| Reaper | `systemctl disable --now ls-db-access-reap.timer`; then drop accounts by hand |
| Provisioner | `DROP USER 'dbaccess'@'172.25.%'` — the sidecar can no longer mint anything |
| Tunnel | `git revert` Task 1, redeploy; stage is unaffected either way |
| Sidecars | `git revert` the compose commit + `./servyy.sh --tags ls.app.pull,ls.app.deploy` |
| App | `git revert` the `dbaccess` app; the table stays, the sidecar keeps working against it |
| A bad data change | `bak_<table>_<date>` — **never** a whole-DB restore if a snapshot exists |

## Effort

| Task | Estimate |
|---|---|
| 1 — static tunnel | 45 min |
| 2 — provisioner account + env | 30 min |
| 3 — sidecar + compose | 2 h |
| 4 — app contract (models, admin, views, migration) | 2 h 30 |
| 5 — reaper + timer | 45 min |
| 6 — full rehearsal on the test host | 1 h |
| 7 — docs + history | 30 min |
| **Total** | **≈ 8 h** |

## Open decisions before Task 3 runs against prod

1. **Do you accept that a web app now gates a privileged action?** This is the one decision that cannot be undone by scoping: if the app is compromised, the sidecar mints credentials, bounded by the cap and the reaper. rev. 2 kept a human in the loop; rev. 3 does not.
2. **PII / contractor:** an external person holds live user data on their laptop. If that is not allowed, this plan is the wrong answer and an anonymised clone is the right one.
3. **`INSERT`/`DELETE`:** default is `SELECT` + `UPDATE`. Widening it is a per-session decision recorded on the request.
4. **Who may approve?** A new `DB-Session-Approver` permission on `gamedays.Permissions`, or "any staff user except the requester"? The former is a control, the latter is a formality.
5. **Credential handover:** one-time reveal in the app (default, needs `DBACCESS_SECRET_KEY` in `ls.env`) or Vaultwarden for anyone who already has an account. Doing both doubles the leak paths.
6. **Tunnel key rotation:** 90 days, or only on suspicion? A shared key is a shared secret; rotation is the only expiry mechanism it has.
