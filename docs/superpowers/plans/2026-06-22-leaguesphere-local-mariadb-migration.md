# LeagueSphere Local MariaDB Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move LeagueSphere prod off the external MySQL (`s207.goserver.host`) onto a self-hosted, non-publicly-exposed MariaDB container with consistent `mariadb-backup` backups, hourly restic capture, tested restore, and a smooth pre-seed + delta cutover that keeps the external DB as a 14-day rollback.

**Architecture:** Add a `db` (MariaDB) service to the prod compose mirroring the proven staging setup, on an internal-only Docker network with no published ports. Seed it from the external DB via `mysqldump` while prod stays live on external; validate it live by repointing `ls_db_sync` (stage) at the new container; back it up with `mariadb-backup` → a dedicated hourly restic repo; then cut over by flipping a single env var (`db_host`).

**Tech Stack:** Ansible (roles under `ansible/plays/roles/`), Docker Compose (`leaguesphere/deployed/`), MariaDB + `mariadb-backup`, restic (SFTP to Hetzner Storage Box), systemd user timers.

## Global Constraints

- **Two repos, scoped commands only.** `git -C container …` / `git -C leaguesphere …`; non-git: `cd container && …` / `cd leaguesphere && …`. Never mix a single commit across repos.
- **Test-first, no manual prod edits.** Validate every change on `servyy-test.lxd` via Ansible before prod. Prod deploy requires explicit user approval. No `ssh`/`scp`/`sed` edits on prod.
- **No public DB exposure.** The `db` service has **no published host port** and lives only on the `internal: true` `backend` network.
- **Bind mount, never a named volume.** DB data and backup dirs MUST be bind mounts under `/var/jail/home/leaguesphere/container/` — a named Docker volume falls under restic's `/var/lib/docker` exclude and would be silently un-backed-up.
- **Single-var cutover.** The local DB is created with the **same** `db_name` / `db_user` / `db_password` the prod app already uses, so cutover changes only `app.db_host`.
- **External DB is read-only throughout and untouched after cutover** (14-day rollback retention).
- **`mariadb-backup` runs inside the container** (`docker exec leaguesphere.db …`) so its version always matches the server.
- Prod paths (verified): `ssh_chroot_jail_path = /var/jail`; prod `container_dir = /var/jail/home/leaguesphere/container`; `remote_user_home = /home/{{ create_user }}`.
- Container naming follows `{project}.{service}` → new prod service is `db` → container `leaguesphere.db`.
- Secrets (`secret_main.yaml`, `secret_stage.yaml`, `restic.yml` passwords) are git-crypt encrypted. The repo must be **unlocked** (`git -C container crypt unlock`) before editing. Never print secret values into commits or logs.

---

## File Structure

**`leaguesphere` repo:**
- `deployed/docker-compose.yaml` — add `db` service + `mysql-backup` bind mount; move `app` to `backend`; remove `database` network. *(Modify)*
- `deployed/mysql-init/01-create-staging-db.sh` — extend to also create the dedicated `mariadb-backup` user. *(Modify — shared with stage)*

**`container` repo:**
- `ansible/plays/roles/ls_app/tasks/deploy.yaml` — generalize the stage-only DB-init dance to also cover the prod `leaguesphere` project. *(Modify)*
- `ansible/plays/roles/ls_db_migrate/` — **new role**: external→local seed + final delta import. *(Create)*
- `ansible/plays/roles/ls_db_sync/tasks/main.yml` — source toggle: external host vs `leaguesphere.db` container. *(Modify)*
- `ansible/plays/roles/restic/templates/mariadb_backup.sh.j2` — **new**: in-container `mariadb-backup` → prepared `current/`. *(Create)*
- `ansible/plays/roles/restic/tasks/backup.yml` — deploy the mariadb-backup script + db restic backup script + two timers. *(Modify)*
- `ansible/plays/roles/restic/tasks/init.yml` — add `db` to env-file / sftp-mkdir / repo-init loops. *(Modify)*
- `ansible/plays/roles/restic/tasks/main.yml` — add env-aware `restore.yml` include for the DB path (repo `db`). *(Modify)*
- `ansible/plays/vars/restic.yml` — add `restic.db` block (repository, password, source_path, schedule). *(Modify)*
- `ansible/plays/roles/ls_app/vars/secret_main.yaml` — add `db_root_password` + backup-user creds (git-crypt). *(Modify)*
- `ansible/plays/leaguesphere.yml` — wire `ls_db_migrate` tags. *(Modify)*
- `container/docs/leaguesphere-environments.md` — update matrix + runbooks. *(Modify)*

---

## Task 0: Branches

- [ ] **Step 1: Confirm container branch**

Run: `git -C container rev-parse --abbrev-ref HEAD`
Expected: `feature/leaguesphere-local-mariadb-migration`

- [ ] **Step 2: Create matching leaguesphere branch**

```bash
git -C leaguesphere checkout -b feature/local-mariadb-prod-db
```
Expected: `Switched to a new branch 'feature/local-mariadb-prod-db'`

- [ ] **Step 3: Unlock secrets**

```bash
cd container && git crypt unlock   # if not already unlocked
grep -q 'db_host' ansible/plays/roles/ls_app/vars/secret_main.yaml && echo UNLOCKED
```
Expected: `UNLOCKED` (readable plaintext). If it prints binary garble, the repo is still locked — stop and unlock.

---

## Task 1: Add the `db` service to the prod compose (no public exposure)

**Files:**
- Modify: `leaguesphere/deployed/docker-compose.yaml`

**Interfaces:**
- Produces: container `leaguesphere.db` on network `backend` (internal), bind mounts `./mysql-data` and `./mysql-backup`, healthcheck name used by later tasks: `leaguesphere.db`.

- [ ] **Step 1: Add the `db` service** (mirror staging's `mysql`, but service name `db`). Insert under `services:` in `deployed/docker-compose.yaml`:

```yaml
  db:
    image: mariadb:latest
    container_name: ${COMPOSE_PROJECT_NAME}.db
    restart: unless-stopped
    command: >
      --character-set-server=utf8mb4
      --collation-server=utf8mb4_unicode_ci
    volumes:
      - "./mysql-data:/var/lib/mysql"
      - "./mysql-backup:/backup"
      - "./mysql-init:/docker-entrypoint-initdb.d:ro"
    env_file: ls.env
    networks:
      - backend
    healthcheck:
      test: ["CMD", "sh", "-c", "mariadb -h localhost --skip-ssl -u root -p$$MYSQL_ROOT_PASSWORD -e 'SELECT 1'"]
      interval: 15s
      timeout: 5s
      retries: 15
      start_period: 90s
    labels:
      - traefik.enable=false
      - io.portainer.accesscontrol.teams=leaguesphere
      - com.centurylinklabs.watchtower.scope=prod
```

- [ ] **Step 2: Move `app` onto `backend`, add a `depends_on`.** In the `app` service, replace its `networks:` list and add `depends_on`:

```yaml
    networks:
      - backend   # For www communication
    depends_on:
      db:
        condition: service_healthy
```
(Remove the `database` network line and its `# For external MySQL access` comment from `app`.)

- [ ] **Step 3: Remove the `database` network.** In the bottom `networks:` block delete:

```yaml
  database:
    internal: false  # Allow external connectivity for MySQL
```
Leave `backend: { internal: true }` and `proxy: { external: true }`.

- [ ] **Step 4: Validate compose syntax locally**

Run: `cd leaguesphere/deployed && SERVICE_NAME=x COMPOSE_PROJECT_NAME=leaguesphere SERVICE_HOST=x LOCAL_HOSTNAME=x docker compose -f docker-compose.yaml config -q && echo OK`
Expected: `OK` (no errors). It must show `leaguesphere.db` with no `ports:` and only the `backend` network.

- [ ] **Step 5: Assert no published ports / no database network**

Run: `cd leaguesphere/deployed && grep -nE 'ports:|database:' docker-compose.yaml || echo "NONE"`
Expected: `NONE`

- [ ] **Step 6: Commit**

```bash
git -C leaguesphere add deployed/docker-compose.yaml
git -C leaguesphere commit -m "feat(prod): add internal-only mariadb db service, drop external db network"
```

---

## Task 2: Create the backup user in mysql-init

**Files:**
- Modify: `leaguesphere/deployed/mysql-init/01-create-staging-db.sh`

**Interfaces:**
- Consumes: env vars from `ls.env` — `MYSQL_ROOT_PASSWORD`, `MYSQL_DB_NAME`, `MYSQL_USER`, `MYSQL_PWD`, and **new** `MYSQL_BACKUP_USER`, `MYSQL_BACKUP_PWD`.
- Produces: a `mariadb-backup`-capable user used by Task 7.

- [ ] **Step 1: Add the backup user grant.** Inside the existing `mariadb … <<-EOSQL … EOSQL` heredoc, after the `GRANT ALL PRIVILEGES ON ${MYSQL_DB_NAME}.*` line, add:

```sql
    CREATE USER IF NOT EXISTS '${MYSQL_BACKUP_USER}'@'localhost' IDENTIFIED BY '${MYSQL_BACKUP_PWD}';
    GRANT RELOAD, PROCESS, LOCK TABLES, REPLICATION CLIENT ON *.* TO '${MYSQL_BACKUP_USER}'@'localhost';
```
(Keep the existing `FLUSH PRIVILEGES;` at the end.)

- [ ] **Step 2: Guard against unset backup vars** (so stage, which won't set them, still works). At the top of the script after `set -e`, add:

```bash
MYSQL_BACKUP_USER="${MYSQL_BACKUP_USER:-}"
MYSQL_BACKUP_PWD="${MYSQL_BACKUP_PWD:-}"
```
And wrap the two new SQL lines so they only run when set — replace them with a conditional appended after the main heredoc:

```bash
if [ -n "${MYSQL_BACKUP_USER}" ]; then
  mariadb -h localhost -u root -p"${MYSQL_ROOT_PASSWORD}" <<-EOSQL
    CREATE USER IF NOT EXISTS '${MYSQL_BACKUP_USER}'@'localhost' IDENTIFIED BY '${MYSQL_BACKUP_PWD}';
    GRANT RELOAD, PROCESS, LOCK TABLES, REPLICATION CLIENT ON *.* TO '${MYSQL_BACKUP_USER}'@'localhost';
    FLUSH PRIVILEGES;
EOSQL
  echo "Backup user ${MYSQL_BACKUP_USER} created."
fi
```
(Remove the two SQL lines added in Step 1 from the first heredoc; the conditional block replaces them.)

- [ ] **Step 3: Lint the script**

Run: `bash -n leaguesphere/deployed/mysql-init/01-create-staging-db.sh && echo OK`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git -C leaguesphere add deployed/mysql-init/01-create-staging-db.sh
git -C leaguesphere commit -m "feat(db-init): optionally create mariadb-backup user"
```

---

## Task 3: Add prod DB secrets (git-crypt)

**Files:**
- Modify: `container/ansible/plays/roles/ls_app/vars/secret_main.yaml`

**Interfaces:**
- Produces: `app.db_root_password`, `app.db_backup_user`, `app.db_backup_password` for prod; leaves `app.db_host` **unchanged (external)** for now.

- [ ] **Step 1: Generate two passwords** (do not reuse external creds):

```bash
openssl rand -base64 24   # root password
openssl rand -base64 24   # backup-user password
```

- [ ] **Step 2: Add keys under the prod `app:` mapping** in `secret_main.yaml` (mirror the field names already present for stage in `secret_stage.yaml`). Add:

```yaml
  db_root_password: "<root password from step 1>"
  db_backup_user: "ls_backup"
  db_backup_password: "<backup password from step 1>"
```
Leave `db_host`, `db_name`, `db_user`, `db_password` as-is (external). The local container will create DB `db_name` + user `db_user`/`db_password` so cutover only changes `db_host`.

- [ ] **Step 3: Confirm the env template will emit the new vars.** `ls.env.j2` already emits `MYSQL_ROOT_PASSWORD`/`MYSQL_DATABASE`/`MYSQL_PASSWORD` when `app.db_root_password is defined`. Add the backup-user vars to the template so the init script receives them. In `container/ansible/plays/roles/ls_app/templates/ls.env.j2`, inside the existing `{% if app.db_root_password is defined %}` block, add:

```jinja
MYSQL_BACKUP_USER={{ app.db_backup_user }}
MYSQL_BACKUP_PWD={{ app.db_backup_password }}
```

- [ ] **Step 4: Syntax-check the playbook** (proves the template + vars parse)

Run: `cd container/ansible && ./servyy.sh --syntax-check`
Expected: `playbook: servyy.yml` with no errors.

- [ ] **Step 5: Commit (encrypted blob + template)**

```bash
git -C container add ansible/plays/roles/ls_app/vars/secret_main.yaml ansible/plays/roles/ls_app/templates/ls.env.j2
git -C container commit -m "feat(ls): prod db container creds + backup-user env"
```
Verify the secret stayed encrypted: `git -C container show --stat HEAD` and confirm the diff for `secret_main.yaml` is binary, not plaintext.

---

## Task 4: Generalize the deploy DB-init dance to prod

**Files:**
- Modify: `container/ansible/plays/roles/ls_app/tasks/deploy.yaml`

**Interfaces:**
- Consumes: `app.name` (`leaguesphere` for prod, `leaguesphere_stage` for stage), `app.db_root_password`, `app.db_name`.
- Produces: a healthy `{{ app.name }}.db` (prod) / `{{ app.name }}.mysql` (stage) with the database created on first boot.

Currently every DB step is gated `when: app.name == 'leaguesphere_stage'` and hardcodes `.mysql`. Prod uses service `db`. Introduce a per-app fact for the DB container name and broaden the gates to "any app that runs its own DB container."

- [ ] **Step 1: Add a DB-container fact at the top of `deploy.yaml`** (after the proxy-network task):

```yaml
- name: Determine DB container name for this app
  set_fact:
    ls_db_container: "{{ (app.name ~ '.db') if app.name == 'leaguesphere' else (app.name ~ '.mysql') }}"
    ls_runs_own_db: "{{ app.name in ['leaguesphere', 'leaguesphere_stage'] }}"
    ls_db_volume: "{{ (app.name ~ '_mysql-data') }}"
  tags:
    - ls.app.deploy
```

- [ ] **Step 2: Replace the DB-step gates and hardcoded names.** In `deploy.yaml`, for every task currently using `when: app.name == 'leaguesphere_stage'` for DB handling and `container: "{{ app.name }}.mysql"`:
  - change the container reference to `container: "{{ ls_db_container }}"`,
  - change the gate to `when: ls_runs_own_db | bool` (preserving any extra conditions, e.g. the `db_check.rc` checks),
  - change `name: "{{ app.name }}_mysql-data"` (volume removal) to `name: "{{ ls_db_volume }}"`.
  Leave the staging-image pull task gated to `app.name == 'leaguesphere_stage'` (prod uses `:latest`, pulled by compose).

- [ ] **Step 3: Fix the final health-wait container name.** The "Wait for backend container to be healthy" task computes `{{ app.name }}.staging-app` vs `.app`; leave as-is (correct for both).

- [ ] **Step 4: Syntax-check**

Run: `cd container/ansible && ./servyy.sh --syntax-check`
Expected: no errors.

- [ ] **Step 5: Deploy prod stack to TEST and verify the db container is healthy & not exposed**

```bash
cd container/ansible
./servyy-test.sh --tags ls.app.prod
ssh servyy-test.lxd "docker inspect -f '{{.State.Health.Status}}' leaguesphere.db"
ssh servyy-test.lxd "docker port leaguesphere.db || echo NO_PORTS"
# DBPW = app.db_root_password from Task 3 (read from secret_main.yaml; do not paste into shell history files)
ssh servyy-test.lxd "docker exec leaguesphere.db mariadb -u root -p\"$DBPW\" -e 'SHOW DATABASES;'"
```
Expected: health `healthy`; `NO_PORTS`; `SHOW DATABASES` lists the prod `db_name`.

- [ ] **Step 6: Commit**

```bash
git -C container add ansible/plays/roles/ls_app/tasks/deploy.yaml
git -C container commit -m "feat(ls_app): run own DB container for prod, not just stage"
```

---

## Task 5: `ls_db_migrate` role — external→local seed

**Files:**
- Create: `container/ansible/plays/roles/ls_db_migrate/tasks/main.yml`
- Create: `container/ansible/plays/roles/ls_db_migrate/defaults/main.yml`
- Modify: `container/ansible/plays/leaguesphere.yml`

**Interfaces:**
- Consumes: prod creds from `secret_main.yaml` (`app.db_host/db_user/db_password/db_name`), local container `leaguesphere.db`, `app.db_root_password`.
- Produces: local `leaguesphere.db` holding a `mysqldump` clone of external prod; re-runnable (on-demand re-seed). Tag: `ls.db.migrate`.

- [ ] **Step 1: Write `defaults/main.yml`**

```yaml
---
ls_migrate_local_container: "leaguesphere.db"
```

- [ ] **Step 2: Write `tasks/main.yml`** (adapts `ls_db_sync`'s export, targets the local prod container):

```yaml
---
- name: Install mysql client for export
  apt: { name: default-mysql-client, state: present, update_cache: false }

- name: Load production variables
  include_vars:
    file: "{{ playbook_dir }}/roles/ls_app/vars/secret_main.yaml"
    name: prod_app

- name: Set dump file path
  set_fact:
    ls_migrate_dump: "/tmp/ls_prod_seed_{{ ansible_facts['date_time']['epoch'] }}.sql"

- name: Export external prod DB (ignore views)
  shell: |
    IGNORE=$(mysql -h {{ prod_app.app.db_host }} -u {{ prod_app.app.db_user }} \
      -p'{{ prod_app.app.db_password }}' -N \
      -e "SELECT CONCAT('--ignore-table={{ prod_app.app.db_name }}.', table_name) \
          FROM information_schema.views WHERE table_schema='{{ prod_app.app.db_name }}'")
    mysqldump -h {{ prod_app.app.db_host }} -u {{ prod_app.app.db_user }} \
      -p'{{ prod_app.app.db_password }}' --single-transaction --quick --lock-tables=false \
      $IGNORE {{ prod_app.app.db_name }} > "{{ ls_migrate_dump }}"
  changed_when: true

- name: Wait for local DB health
  shell: docker inspect {{ ls_migrate_local_container }} --format='{{ "{{.State.Health.Status}}" }}'
  register: db_health
  until: db_health.stdout == 'healthy'
  retries: 30
  delay: 2
  changed_when: false

- name: Drop & recreate local prod database
  shell: |
    docker exec {{ ls_migrate_local_container }} \
      mariadb -u root -p'{{ prod_app.app.db_root_password }}' \
      -e "DROP DATABASE IF EXISTS {{ prod_app.app.db_name }}; \
          CREATE DATABASE {{ prod_app.app.db_name }} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
  changed_when: true

- name: Import dump into local prod database
  shell: |
    cat "{{ ls_migrate_dump }}" | docker exec -i {{ ls_migrate_local_container }} \
      mariadb -u root -p'{{ prod_app.app.db_root_password }}' {{ prod_app.app.db_name }}
  changed_when: true

- name: Remove dump
  file: { path: "{{ ls_migrate_dump }}", state: absent }
```

- [ ] **Step 3: Wire the role in `leaguesphere.yml`.** Add a play/role invocation guarded by tag `ls.db.migrate` targeting the host that runs the prod stack, e.g.:

```yaml
    - role: ls_db_migrate
      become_user: "{{ ls.user }}"
      tags:
        - ls.db.migrate
```
(Place it analogous to how `ls_db_sync` is wired; do not add it to the default `ls` run.)

- [ ] **Step 4: Syntax-check**

Run: `cd container/ansible && ./servyy.sh --syntax-check`
Expected: no errors.

- [ ] **Step 5: Seed on TEST and verify row parity**

```bash
cd container/ansible && ./servyy-test.sh --tags ls.db.migrate
# count tables locally vs external
ssh servyy-test.lxd "docker exec leaguesphere.db mariadb -u root -p<root> -N -e \
  'SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=\"<db_name>\";'"
```
Expected: local table count > 0 and matches the external schema's base-table count (views excluded).

- [ ] **Step 6: Commit**

```bash
git -C container add ansible/plays/roles/ls_db_migrate ansible/plays/leaguesphere.yml
git -C container commit -m "feat(ls_db_migrate): seed local prod db from external via mysqldump"
```

---

## Task 6: `mariadb-backup` script + timer

**Files:**
- Create: `container/ansible/plays/roles/restic/templates/mariadb_backup.sh.j2`
- Modify: `container/ansible/plays/roles/restic/tasks/backup.yml`

**Interfaces:**
- Consumes: `leaguesphere.db`, `app.db_backup_user`/`app.db_backup_password` (loaded from `secret_main.yaml`).
- Produces: a prepared physical backup at `/var/jail/home/leaguesphere/container/mysql-backup/current` refreshed before each restic run. systemd unit `mariadb-backup-ls`.

- [ ] **Step 1: Write `mariadb_backup.sh.j2`**

```bash
#!/bin/zsh
# mariadb-backup for leaguesphere prod db -> prepared 'current' set
set -euo pipefail
source "/home/{{ create_user }}/.zprezto/custom/functions/logdy" 2>/dev/null || true

CONTAINER="leaguesphere.db"
BACKUP_ROOT="{{ ls_backup_host_dir }}"   # /var/jail/home/leaguesphere/container/mysql-backup
NEW="$BACKUP_ROOT/new"
CUR="$BACKUP_ROOT/current"

sudo rm -rf "$NEW"
docker exec "$CONTAINER" sh -c 'rm -rf /backup/new && mkdir -p /backup/new'
docker exec "$CONTAINER" mariadb-backup --backup --target-dir=/backup/new \
  --user='{{ ls_backup_user }}' --password='{{ ls_backup_password }}'
docker exec "$CONTAINER" mariadb-backup --prepare --target-dir=/backup/new
# atomic-ish swap on host (paths are bind-mounted, same fs)
sudo rm -rf "$CUR.old" 2>/dev/null || true
[ -d "$CUR" ] && sudo mv "$CUR" "$CUR.old"
sudo mv "$NEW" "$CUR"
sudo rm -rf "$CUR.old"
echo "mariadb-backup current set refreshed at $CUR"
```

- [ ] **Step 2: Add deploy tasks to `backup.yml`** (load creds, render script, register timer). Append:

```yaml
- name: Load prod app vars for backup creds
  include_vars:
    file: "{{ playbook_dir }}/roles/ls_app/vars/secret_main.yaml"
    name: ls_prod
  tags: [restic.backup]

- name: Deploy mariadb-backup script
  template:
    src: mariadb_backup.sh.j2
    dest: "{{ remote_user_home }}/.backup-scripts/mariadb-backup-ls.sh"
    mode: '0750'
  vars:
    ls_backup_host_dir: "/var/jail/home/leaguesphere/container/mysql-backup"
    ls_backup_user: "{{ ls_prod.app.db_backup_user }}"
    ls_backup_password: "{{ ls_prod.app.db_backup_password }}"
  tags: [restic.backup]

- import_tasks: oneshot_include.yml
  vars:
    service:
      name: mariadb-backup-ls
      description: 'mariadb-backup of leaguesphere prod db'
      schedule: '{{ restic.schedules.backup_ls_db_dump | default("*-*-* *:40:00") }}'
      command: "{{ remote_user_home }}/.backup-scripts/mariadb-backup-ls.sh"
  tags: [restic.backup]
```
(The `:40` schedule runs 20 min before the hourly restic db run in Task 7.)

- [ ] **Step 3: Deploy to TEST and run the backup once**

```bash
cd container/ansible && ./servyy-test.sh --tags restic.backup
ssh servyy-test.lxd "systemctl --user start mariadb-backup-ls.service; sleep 5; \
  ls -la /var/jail/home/leaguesphere/container/mysql-backup/current | head"
```
Expected: `current/` contains `xtrabackup_checkpoints`, `ibdata1`, and the DB dir — a prepared backup.

- [ ] **Step 4: Commit**

```bash
git -C container add ansible/plays/roles/restic/templates/mariadb_backup.sh.j2 ansible/plays/roles/restic/tasks/backup.yml
git -C container commit -m "feat(restic): mariadb-backup prepared-set timer for prod db"
```

---

## Task 7: Dedicated hourly restic repo for the DB backup

**Files:**
- Modify: `container/ansible/plays/vars/restic.yml`
- Modify: `container/ansible/plays/roles/restic/tasks/init.yml`
- Modify: `container/ansible/plays/roles/restic/tasks/backup.yml`

**Interfaces:**
- Consumes: prepared set at `/var/jail/home/leaguesphere/container/mysql-backup/current`.
- Produces: hourly restic snapshots in repo `restic-ls-db`; `/etc/restic/env.db`; systemd unit `restic-backup-ls-db`.

- [ ] **Step 1: Add `restic.db` block** in `restic.yml` (mirror `restic.root`; runs with sudo because the path is outside the user home):

```yaml
  db:
    enabled: true
    repository: "sftp://storagebox/{{ storagebox_credentials.share }}/{{ inventory_hostname }}/restic-ls-db"
    password: "{{ restic_password_ls_db }}"
    source_path: "/var/jail/home/leaguesphere/container/mysql-backup/current"
```
And add a schedule + the dump schedule used by Task 6:

```yaml
  schedules:
    backup_ls_db: 'hourly'
    backup_ls_db_dump: '*-*-* *:40:00'
```

- [ ] **Step 2: Add `restic_password_ls_db`** to the encrypted secrets file that defines `restic_password_home`/`restic_password_root` (find it: `grep -rl restic_password_home container/ansible/plays/vars`). Generate with `openssl rand -base64 32`. Commit stays encrypted.

- [ ] **Step 3: Extend `init.yml` loops to include `db`.** Add `{name: 'db'}` to the `Check for existing restic environment files` loop; add a `db` entry to the `Deploy restic environment files` loop (`repository`/`password`/`env_name: db`); add `db` to the password-integrity `expected_pass` ternary (extend to handle `db` → `restic.db.password`); add `-mkdir …/restic-ls-db` to the sftp mkdir heredoc; add `"{{ restic.db }}"` to the `Initialize restic repositories` loop.

- [ ] **Step 4: Add the db restic backup script + timer to `backup.yml`** (mirror the root entry — `with_sudo: true`, reads `/etc/restic/env.db`):

```yaml
- name: Deploy restic backup script for ls-db
  template:
    src: restic_backup.sh.j2
    dest: "{{ remote_user_home }}/.backup-scripts/restic-backup-ls-db.sh"
    mode: '0750'
  vars:
    backup_name: "db"
    source_path: "{{ restic.db.source_path }}"
    exclude_caches: false
    log_file: "/var/log/restic/backup-ls-db.log"
    with_sudo: true
  tags: [restic.backup]

- import_tasks: oneshot_include.yml
  vars:
    service:
      name: restic-backup-ls-db
      description: 'Restic backup - leaguesphere prod db'
      schedule: '{{ restic.schedules.backup_ls_db }}'
      command: "{{ remote_user_home }}/.backup-scripts/restic-backup-ls-db.sh"
  tags: [restic.backup]
```
Also add `backup_ls_db: '/var/log/restic/backup-ls-db.log'` under `restic.logs` so init creates the log file.

- [ ] **Step 5: Deploy to TEST, init repo, run backup, list snapshots**

```bash
cd container/ansible && ./servyy-test.sh --tags restic.init,restic.backup
ssh servyy-test.lxd "systemctl --user start restic-backup-ls-db.service; sleep 10; \
  sudo bash -c 'source /etc/restic/env.db && restic snapshots --latest 1'"
```
Expected: at least one snapshot tagged `db` for host `servyy-test.lxd`.

- [ ] **Step 6: Commit**

```bash
git -C container add ansible/plays/vars/restic.yml ansible/plays/roles/restic/tasks/init.yml ansible/plays/roles/restic/tasks/backup.yml
git -C container commit -m "feat(restic): dedicated hourly repo for leaguesphere prod db backup"
```

---

## Task 8: Restore wiring (env-aware, repo `db`)

**Files:**
- Modify: `container/ansible/plays/roles/restic/tasks/main.yml`

**Interfaces:**
- Consumes: repo `db`, snapshots from Task 7.
- Produces: idempotent restore of the prepared backup path on fresh/empty hosts; fails on TEST when no snapshot (early warning).

- [ ] **Step 1: Add a restore include** after the existing Vaultwarden block in `main.yml`:

```yaml
- name: Restore LeagueSphere Prod DB Backup
  include_tasks: restore.yml
  vars:
    restore_path: "/var/jail/home/leaguesphere/container/mysql-backup/current"
    backup_name: "db"
    owner: "root"
  when: (with_containers | default(false)) | bool
  tags:
    - restic
    - restic.restore
```

- [ ] **Step 2: Document the recovery procedure** as a comment block above that task (copy-back is operational, not auto-run):

```yaml
# RECOVERY (manual, after restore.yml repopulates current/):
#   1. docker compose -p leaguesphere stop db
#   2. empty /var/jail/home/leaguesphere/container/mysql-data
#   3. docker run --rm -v mysql-data:/var/lib/mysql -v mysql-backup/current:/backup \
#        mariadb:latest mariadb-backup --copy-back --target-dir=/backup
#   4. chown -R 999:999 mysql-data   # mariadb uid in image
#   5. docker compose -p leaguesphere start db ; verify health
```

- [ ] **Step 3: Verify the restore SKIPS on a healthy TEST host** (db running, dir non-empty)

```bash
cd container/ansible && ./servyy-test.sh --tags restic.restore
```
Expected: task output shows `⏭️ SKIPPING RESTORE: Service containers are running` (or dir non-empty), not a failure.

- [ ] **Step 4: Commit**

```bash
git -C container add ansible/plays/roles/restic/tasks/main.yml
git -C container commit -m "feat(restic): env-aware restore wiring for leaguesphere prod db"
```

---

## Task 9: `ls_db_sync` source toggle (stage = live shadow)

**Files:**
- Modify: `container/ansible/plays/roles/ls_db_sync/tasks/main.yml`
- Modify: `container/ansible/plays/roles/ls_db_sync/defaults/main.yml`

**Interfaces:**
- Consumes: either external host creds or the local `leaguesphere.db` container, selected by `ls_db_sync_source`.
- Produces: `leaguesphere_stage` DB populated from the chosen source. Default flips to `local` after cutover.

- [ ] **Step 1: Add a source switch to `defaults/main.yml`**

```yaml
---
# 'external' = dump from s207.goserver.host (pre-cutover)
# 'local'    = dump from the local prod container leaguesphere.db (validation + post-cutover)
ls_db_sync_source: "external"
ls_db_sync_local_container: "leaguesphere.db"
```

- [ ] **Step 2: Branch the export task in `main.yml`.** Replace the single `Export DB ignoring all views` task with two mutually-exclusive tasks:

```yaml
- name: Export prod DB from EXTERNAL host (ignore views)
  when: ls_db_sync_source == 'external'
  shell: |
    IGNORE=$(mysql -h {{ prod_app.app.db_host }} -u {{ prod_app.app.db_user }} \
      -p'{{ prod_app.app.db_password }}' -N \
      -e "SELECT CONCAT('--ignore-table={{ prod_app.app.db_name }}.', table_name) \
          FROM information_schema.views WHERE table_schema='{{ prod_app.app.db_name }}'")
    mysqldump -h {{ prod_app.app.db_host }} -u {{ prod_app.app.db_user }} \
      -p'{{ prod_app.app.db_password }}' --single-transaction --quick --lock-tables=false \
      $IGNORE {{ prod_app.app.db_name }} > "{{ sql_dump_file }}"
  changed_when: true

- name: Export prod DB from LOCAL container (ignore views)
  when: ls_db_sync_source == 'local'
  shell: |
    IGNORE=$(docker exec {{ ls_db_sync_local_container }} mariadb -u root \
      -p'{{ prod_app.app.db_root_password }}' -N \
      -e "SELECT CONCAT('--ignore-table={{ prod_app.app.db_name }}.', table_name) \
          FROM information_schema.views WHERE table_schema='{{ prod_app.app.db_name }}'")
    docker exec {{ ls_db_sync_local_container }} mariadb-dump -u root \
      -p'{{ prod_app.app.db_root_password }}' --single-transaction --quick --lock-tables=false \
      $IGNORE {{ prod_app.app.db_name }} > "{{ sql_dump_file }}"
  changed_when: true
```
(Everything downstream — drop/recreate stage DB, import, restart — is unchanged.)

- [ ] **Step 3: Syntax-check**

Run: `cd container/ansible && ./servyy.sh --syntax-check`
Expected: no errors.

- [ ] **Step 4: Validate stage-from-local on TEST.** With the prod stack + seed already on TEST (Tasks 4–5) and the stage stack deployed there:

```bash
cd container/ansible
./servyy-test.sh --tags ls.app.stage           # ensure stage stack exists
./servyy-test.sh --tags ls.db.sync -e ls_db_sync_source=local
ssh servyy-test.lxd "docker exec leaguesphere_stage.mysql mariadb -u root -p<stage_root> -N \
  -e 'SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=\"leaguesphere_stage\";'"
```
Expected: stage table count matches the seeded local prod DB. Then smoke-test the stage app health endpoint.

- [ ] **Step 5: Commit**

```bash
git -C container add ansible/plays/roles/ls_db_sync
git -C container commit -m "feat(ls_db_sync): source toggle external|local for shadow validation"
```

---

## Task 10: Full restore drill on TEST (gate before cutover)

**Files:** none (verification runbook; capture results in `container/history/`).

- [ ] **Step 1: Snapshot exists** — `ssh servyy-test.lxd "sudo bash -c 'source /etc/restic/env.db && restic snapshots'"` shows ≥1 `db` snapshot.

- [ ] **Step 2: Simulate loss** — stop db, move aside the data dir:

```bash
ssh servyy-test.lxd "cd /var/jail/home/leaguesphere/container && docker compose -p leaguesphere stop db && sudo mv mysql-data mysql-data.bak && sudo mv mysql-backup/current /tmp/cur.bak"
```

- [ ] **Step 3: Restore from restic** — `./servyy-test.sh --tags restic.restore` (dir now empty → restore proceeds). Confirm `mysql-backup/current` is repopulated.

- [ ] **Step 4: copy-back + start** — run the recovery procedure from Task 8 Step 2.

- [ ] **Step 5: Verify** — db healthy and row counts match pre-loss:

```bash
ssh servyy-test.lxd "docker exec leaguesphere.db mariadb -u root -p<root> -N -e \
  'SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=\"<db_name>\";'"
```
Expected: equal to Task 5 Step 5 count. Record outcome in `container/history/2026-06-22_ls-db-restore-drill.md`.

- [ ] **Step 6: Commit the drill record**

```bash
git -C container add history/2026-06-22_ls-db-restore-drill.md
git -C container commit -m "docs(history): leaguesphere prod db restore drill on servyy-test"
```

---

## Task 11: Production cutover (read-only window) — **requires explicit approval**

**Files:**
- Modify: `container/ansible/plays/roles/ls_app/vars/secret_main.yaml` (flip `db_host`)
- Modify: `container/ansible/plays/roles/ls_db_sync/defaults/main.yml` (default → `local`)

> Do not run any prod step without the user's explicit go-ahead (repo policy).

- [ ] **Step 1: Pre-flight on prod** — deploy the build pieces (db container, backups) to prod with app still on external:

```bash
cd container/ansible
./servyy.sh --tags ls.app.prod --limit lehel.xyz     # brings up leaguesphere.db alongside live app
./servyy.sh --tags restic.init,restic.backup --limit lehel.xyz
ssh lehel.xyz "docker inspect -f '{{.State.Health.Status}}' leaguesphere.db"
```
Expected: `healthy`; app still serving on external DB.

- [ ] **Step 2: Seed + verify parity on prod** — `./servyy.sh --tags ls.db.migrate --limit lehel.xyz`; compare local vs external table/row counts.

- [ ] **Step 3: Enter read-only/maintenance** for the prod app (mechanism per environments doc — e.g. scale `app` to a maintenance page or set the app read-only). Confirm no writes are reaching external.

- [ ] **Step 4: Final delta seed** — `./servyy.sh --tags ls.db.migrate --limit lehel.xyz` (re-dumps external with no in-flight writes → local now identical).

- [ ] **Step 5: Flip the env var** — set prod `app.db_host: leaguesphere.db` in `secret_main.yaml`. Redeploy app:

```bash
./servyy.sh --tags ls.app.prod --limit lehel.xyz
ssh lehel.xyz "docker exec leaguesphere.app sh -c 'env | grep MYSQL_HOST'"
```
Expected: `MYSQL_HOST=leaguesphere.db`; app health `healthy`.

- [ ] **Step 6: Smoke test + lift maintenance.** Verify login, a read, and a write against prod. Then exit maintenance.

- [ ] **Step 7: Switch stage source to local permanently** — set `ls_db_sync_source: "local"` default. Commit:

```bash
git -C container add ansible/plays/roles/ls_app/vars/secret_main.yaml ansible/plays/roles/ls_db_sync/defaults/main.yml
git -C container commit -m "feat(prod): cut over leaguesphere to local mariadb; stage syncs from local"
```

---

## Task 12: Docs + 14-day rollback/decommission

**Files:**
- Modify: `container/docs/leaguesphere-environments.md`
- Create: `container/history/2026-06-22_leaguesphere-local-mariadb-migration.md`

- [ ] **Step 1: Update the environments matrix** — prod "Database" cell: external → container `leaguesphere.db` (db `<db_name>`); add the backup/restore + `mariadb-backup` + restic `db` repo notes; update the `ls_db_sync` description (source now `leaguesphere.db`); add the cutover/rollback runbook.

- [ ] **Step 2: Write the history log** — problem, solution, files changed (both repos), deployment results, the restore-drill outcome, verification commands, and the **rollback procedure**: revert `app.db_host` to external + `./servyy.sh --tags ls.app.prod`. Note the **14-day** retention deadline (decommission on/after **2026-07-06** assuming cutover on 2026-06-22; adjust to actual cutover date).

- [ ] **Step 3: Commit**

```bash
git -C container add docs/leaguesphere-environments.md history/2026-06-22_leaguesphere-local-mariadb-migration.md
git -C container commit -m "docs: leaguesphere local mariadb migration + rollback/decommission runbook"
```

- [ ] **Step 4 (after 14 days, separate change):** retire the `external` branch of `ls_db_sync`, remove external DB creds from `secret_main.yaml`, drop the `database`-network remnants if any remain. Out of scope for this PR — track as a follow-up.

---

## Self-Review Notes

- **Spec coverage:** topology/no-exposure (T1, T4), backup user (T2), creds (T3), seed (T5), `mariadb-backup` (T6), hourly restic repo (T7), restore wiring (T8), stage-shadow source swap (T9), restore drill (T10), pre-seed+delta cutover & rollback (T11), docs/decommission & 14-day retention (T12). The jail-coverage decision (dedicated hourly repo, bind-mount requirement) is realized in T6–T8 and the Global Constraints.
- **Tooling split honored:** `mysqldump` for seed (T5) and stage sync (T9); `mariadb-backup` for prod DR (T6). No `mariadb-backup` used cross-instance.
- **Single-var cutover** preserved: local DB reuses prod `db_name`/`db_user`/`db_password`; only `db_host` changes (T11 S5).
- **Test-first:** every implementation task verifies on `servyy-test.lxd` before T11's approval-gated prod steps.
