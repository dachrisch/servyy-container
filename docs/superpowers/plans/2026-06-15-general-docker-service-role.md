# General `docker_service` Role Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify all Docker service deployment into a single reusable `docker_service` Ansible role, replacing the array-based loop in the `user` role and the two dedicated `user_searxng`/`user_job_search` roles.

**Architecture:** The new `docker_service` role encapsulates env file rendering + docker-compose deployment for a single service, invoked once per service in `user.yml` with role-level vars. Templates are consolidated into the role's `templates/` directory with per-service subdirectories. Specialized non-deployment tasks (finance import setup, mongo health checks, etc.) move to a new `docker_extras.yml` in the `user` role.

**Tech Stack:** Ansible, `community.docker.docker_compose_v2`, Molecule (docker driver), Jinja2 templates

---

## File Structure

**Create:**
- `ansible/plays/roles/docker_service/defaults/main.yml` — role interface vars
- `ansible/plays/roles/docker_service/tasks/main.yml` — entry point
- `ansible/plays/roles/docker_service/tasks/env.yml` — env file rendering loop
- `ansible/plays/roles/docker_service/tasks/deploy.yml` — docker-compose deploy
- `ansible/plays/roles/docker_service/templates/docker.env.j2` — generic env template (updated to use role vars)
- `ansible/plays/roles/docker_service/templates/energy/.env.j2` — moved from `user/templates/energy.env.j2`
- `ansible/plays/roles/docker_service/templates/groceries/.env.j2` — moved from `user/templates/groceries.env.j2`
- `ansible/plays/roles/docker_service/templates/opencode/.env.j2` — moved from `user/templates/opencode.env.j2`
- `ansible/plays/roles/docker_service/templates/leagues-finance/.env.j2` — moved from `user/templates/leagues-finance.env.j2`
- `ansible/plays/roles/docker_service/templates/finance/.env.j2` — moved from `user/templates/finance.env.j2`
- `ansible/plays/roles/docker_service/templates/searxng/.env.j2` — moved from `user_searxng/templates/env.j2` (updated to use role vars)
- `ansible/plays/roles/docker_service/templates/searxng/settings.yml.j2` — moved from `user_searxng/templates/settings.yml.j2`
- `ansible/plays/roles/docker_service/templates/job-search/.env.j2` — moved from `user_job_search/templates/env.j2` (updated to use role vars)
- `ansible/plays/roles/docker_service/templates/job-search/api.env.j2` — moved from `user_job_search/templates/api.env.j2`
- `ansible/plays/roles/docker_service/templates/job-search/crawler.env.j2` — moved from `user_job_search/templates/crawler.env.j2`
- `ansible/plays/roles/docker_service/molecule/default/molecule.yml` — molecule config
- `ansible/plays/roles/docker_service/molecule/default/prepare.yml` — install python/docker SDK
- `ansible/plays/roles/docker_service/molecule/default/converge.yml` — test play
- `ansible/plays/roles/docker_service/molecule/default/verify.yml` — assertions
- `ansible/plays/roles/user/tasks/docker_extras.yml` — specialized tasks from docker_services.yml (minus the service loop)
- `ansible/plays/templates/searxng/settings.yml.j2` — symlink target for play-level template access (see Task 6)

**Modify:**
- `ansible/plays/user.yml` — replace 3-play structure with single play + explicit docker_service invocations
- `ansible/plays/roles/user/tasks/main.yml` — remove docker_repo_env.yml/docker_services.yml, add docker_extras.yml
- `ansible/plays/roles/user/tasks/bumbleflies.yml` — remove docker.services dependency
- `.github/workflows/ci.yml` — replace user_searxng/user_job_search with docker_service in molecule matrix

**Delete:**
- `ansible/plays/roles/user/tasks/docker_repo_env.yml`
- `ansible/plays/roles/user/tasks/docker_services.yml`
- `ansible/plays/roles/user/templates/energy.env.j2`
- `ansible/plays/roles/user/templates/finance.env.j2`
- `ansible/plays/roles/user/templates/groceries.env.j2`
- `ansible/plays/roles/user/templates/leagues-finance.env.j2`
- `ansible/plays/roles/user/templates/opencode.env.j2`
- `ansible/plays/roles/user_searxng/` (entire directory)
- `ansible/plays/roles/user_job_search/` (entire directory)

---

## Task 1: Create `docker_service` role — defaults and directory skeleton

**Files:**
- Create: `ansible/plays/roles/docker_service/defaults/main.yml`
- Create directory: `ansible/plays/roles/docker_service/tasks/`
- Create directory: `ansible/plays/roles/docker_service/templates/`
- Create directory: `ansible/plays/roles/docker_service/molecule/default/`

- [ ] **Step 1: Create the role directory tree**

```bash
mkdir -p ansible/plays/roles/docker_service/defaults
mkdir -p ansible/plays/roles/docker_service/tasks
mkdir -p ansible/plays/roles/docker_service/templates
mkdir -p ansible/plays/roles/docker_service/molecule/default
```

- [ ] **Step 2: Create `defaults/main.yml`**

```yaml
---
service_dir: ""
service_name: "{{ service_dir }}"
service_host: "{{ service_dir }}.{{ inventory_hostname }}"
env_templates:
  - src: docker.env.j2
    dest: .env
compose_file: docker-compose.yml
manual: false
```

Write to `ansible/plays/roles/docker_service/defaults/main.yml`.

- [ ] **Step 3: Verify the file**

```bash
cat ansible/plays/roles/docker_service/defaults/main.yml
```

Expected: file contents match Step 2 exactly.

- [ ] **Step 4: Commit**

```bash
git add ansible/plays/roles/docker_service/defaults/main.yml
git commit -m "feat(docker_service): scaffold role with defaults interface"
```

---

## Task 2: Create `docker_service` role tasks

**Files:**
- Create: `ansible/plays/roles/docker_service/tasks/main.yml`
- Create: `ansible/plays/roles/docker_service/tasks/env.yml`
- Create: `ansible/plays/roles/docker_service/tasks/deploy.yml`

- [ ] **Step 1: Create `tasks/main.yml`**

```yaml
---
- include_tasks: env.yml

- include_tasks: deploy.yml
  when: not manual
```

Write to `ansible/plays/roles/docker_service/tasks/main.yml`.

- [ ] **Step 2: Create `tasks/env.yml`**

```yaml
---
- name: Render env files for {{ service_dir }}
  template:
    src: "{{ item.src }}"
    dest: "{{ docker.remote_dir }}/{{ service_dir }}/{{ item.dest }}"
    mode: "0600"
  loop: "{{ env_templates }}"
```

Write to `ansible/plays/roles/docker_service/tasks/env.yml`.

- [ ] **Step 3: Create `tasks/deploy.yml`**

```yaml
---
- name: Deploy {{ service_dir }}
  community.docker.docker_compose_v2:
    project_src: "{{ docker.remote_dir }}/{{ service_dir }}"
    project_name: "{{ service_name }}"
    files:
      - "{{ compose_file }}"
    state: present
  tags: [molecule-notest]
```

Write to `ansible/plays/roles/docker_service/tasks/deploy.yml`.

- [ ] **Step 4: Syntax check**

```bash
cd ansible && ansible-playbook plays/user.yml --syntax-check 2>&1 | tail -20
```

This will fail because `user.yml` still references `user_searxng`/`user_job_search`, but the YAML itself should parse. Expected: no YAML syntax errors in the new files.

- [ ] **Step 5: Commit**

```bash
git add ansible/plays/roles/docker_service/tasks/
git commit -m "feat(docker_service): add env rendering and deploy tasks"
```

---

## Task 3: Migrate templates into `docker_service` role

**Files:**
- Create/modify: 10 template files in `ansible/plays/roles/docker_service/templates/`

The `docker.env.j2` template currently uses dict vars (`service.host`, `service.name`, `user.id`, `user.group`) that were set inline in the old task. The new role exposes these as top-level role vars and Ansible facts. Update the template to use `service_host`, `service_name`, `ansible_user_uid`, `ansible_user_gid`.

- [ ] **Step 1: Create updated `templates/docker.env.j2`**

```jinja2
SERVICE_HOST={{ service_host }}
SERVICE_NAME={{ service_name }}
LOCAL_HOSTNAME={{ ansible_facts['hostname'] }}
IPV4_HOST={{ ansible_facts['default_ipv4']['address'] | default(lookup('dig', ansible_host)) }}
UID={{ ansible_user_uid | default(0) }}
GID={{ ansible_user_gid | default(0) }}
DOCKER_DATA_ROOT={{ extension_drive.path | default('/var/lib') }}/docker
```

Write to `ansible/plays/roles/docker_service/templates/docker.env.j2`.

- [ ] **Step 2: Create per-service template subdirectories and copy content**

```bash
mkdir -p ansible/plays/roles/docker_service/templates/energy
mkdir -p ansible/plays/roles/docker_service/templates/groceries
mkdir -p ansible/plays/roles/docker_service/templates/opencode
mkdir -p ansible/plays/roles/docker_service/templates/leagues-finance
mkdir -p ansible/plays/roles/docker_service/templates/finance
mkdir -p ansible/plays/roles/docker_service/templates/searxng
mkdir -p ansible/plays/roles/docker_service/templates/job-search
```

- [ ] **Step 3: Create `templates/energy/.env.j2`**

Copy content from `ansible/plays/roles/user/templates/energy.env.j2` (no changes needed — uses `energy.*` vault vars):

```jinja2
# Energy service secrets
MONGODB_URI={{ energy.mongodb_uri }}
AUTH_SECRET={{ energy.auth_secret }}
ENCRYPTION_KEY={{ energy.encryption_key }}
NEXT_TELEMETRY_DISABLED=1
```

Write to `ansible/plays/roles/docker_service/templates/energy/.env.j2`.

- [ ] **Step 4: Create `templates/groceries/.env.j2`**

```jinja2
# Groceries service secrets
MONGODB_URI={{ groceries.mongodb_uri }}
JWT_SECRET={{ groceries.jwt_secret }}
```

Write to `ansible/plays/roles/docker_service/templates/groceries/.env.j2`.

- [ ] **Step 5: Create `templates/opencode/.env.j2`**

```jinja2
OPENCODE_SERVER_PASSWORD={{ opencode.server_password }}
CIRCLECI_TOKEN={{ opencode.circleci_token }}
```

Write to `ansible/plays/roles/docker_service/templates/opencode/.env.j2`.

- [ ] **Step 6: Create `templates/leagues-finance/.env.j2`**

```jinja2
# Leagues Finance service secrets
GOOGLE_CLIENT_ID={{ leagues_finance.google_client_id }}
GOOGLE_CLIENT_SECRET={{ leagues_finance.google_client_secret }}
GOOGLE_CALLBACK_URL={{ leagues_finance.google_callback_url }}
JWT_SECRET={{ leagues_finance.jwt_secret }}
LS_DB_HOST={{ leagues_finance.ls_db_host }}
LS_DB_NAME={{ leagues_finance.ls_db_name }}
LS_DB_USER={{ leagues_finance.ls_db_user }}
LS_DB_PASSWORD={{ leagues_finance.ls_db_password }}
MONGO_URI=mongodb://mongo:27017/leagues_finance
MONGODB_DISABLE_TRANSACTIONS=true
REDIS_URL=redis://redis:6379
CLIENT_URL=https://finance.leaguesphere.app
NODE_ENV=production
PORT=3000
```

Write to `ansible/plays/roles/docker_service/templates/leagues-finance/.env.j2`.

- [ ] **Step 7: Create `templates/finance/.env.j2`**

```jinja2
# Firefly III service secrets
APP_KEY={{ finance.app_key }}
DB_PASSWORD={{ finance.db_password }}
POSTGRES_PASSWORD={{ finance.db_password }}
FIREFLY_III_CLIENT_ID={{ finance.importer_client_id | default('') }}
SERVICE_HOST_IMPORTER={{ finance.importer_host }}

# Firefly III Data Importer - Automated Imports
AUTO_IMPORT_SECRET={{ finance.auto_import_secret }}
CAN_POST_FILES=true
CAN_POST_AUTOIMPORT=true
IMPORT_DIR_ALLOWLIST=/import

# Enable Banking credentials
ENABLE_BANKING_APP_ID={{ finance.enable_banking_app_id }}
ENABLE_BANKING_PRIVATE_KEY={{ enable_banking_private_key_b64 }}
```

Write to `ansible/plays/roles/docker_service/templates/finance/.env.j2`.

- [ ] **Step 8: Create `templates/searxng/.env.j2`**

Update the original `user_searxng/templates/env.j2` to use role vars (`service_host` instead of `searxng_service_host`):

```jinja2
# Searxng Environment Configuration
# Managed by Ansible - do not edit manually

SEARXNG_SECRET_KEY={{ vault_searxng_secret_key }}
SERVICE_HOST={{ service_host }}
TRAEFIK_ENTRYPOINT=websecure
TRAEFIK_TLS=true
TRAEFIK_CERTRESOLVER=letsencryptdnsresolver
```

Write to `ansible/plays/roles/docker_service/templates/searxng/.env.j2`.

- [ ] **Step 9: Create `templates/searxng/settings.yml.j2`**

Copy verbatim from `ansible/plays/roles/user_searxng/templates/settings.yml.j2`:

```jinja2
# Searxng Settings Configuration
# https://docs.searxng.org/admin/settings/settings.html
# Managed by Ansible - do not edit manually

use_default_settings:
  engines:
    keep_only:
      - google
      - duckduckgo lite
      - brave

server:
  secret_key: "{{ vault_searxng_secret_key }}"
  bind_address: 0.0.0.0
  port: 8080
  image_proxy: true

search:
  formats:
    - html
```

Read the full file first (`ansible/plays/roles/user_searxng/templates/settings.yml.j2`) and copy ALL content to `ansible/plays/roles/docker_service/templates/searxng/settings.yml.j2`.

- [ ] **Step 10: Create `templates/job-search/.env.j2`**

Update the original to use `service_host` instead of `job_search_service_host`:

```jinja2
# Managed by Ansible - do not edit manually
SERVICE_HOST={{ service_host }}
TRAEFIK_ENTRYPOINT={{ job_search_traefik_entrypoint | default('websecure') }}
TRAEFIK_TLS={{ job_search_traefik_tls | default('true') }}
TRAEFIK_CERTRESOLVER={{ job_search_traefik_certresolver | default('letsencryptdnsresolver') }}
```

Write to `ansible/plays/roles/docker_service/templates/job-search/.env.j2`.

- [ ] **Step 11: Create `templates/job-search/api.env.j2`**

```jinja2
# Managed by Ansible - do not edit manually
NODE_ENV=production
LOG_LEVEL=info
JWT_SECRET={{ job_search_jwt_secret }}
SEARXNG_URL={{ job_search_searxng_url }}
SEARXNG_TOKEN={{ job_search_searxng_token }}
```

Write to `ansible/plays/roles/docker_service/templates/job-search/api.env.j2`.

- [ ] **Step 12: Create `templates/job-search/crawler.env.j2`**

```jinja2
# Managed by Ansible - do not edit manually
SEARXNG_URL={{ job_search_searxng_url }}
SEARXNG_TOKEN={{ job_search_searxng_token }}
```

Write to `ansible/plays/roles/docker_service/templates/job-search/crawler.env.j2`.

- [ ] **Step 13: Verify all templates exist**

```bash
find ansible/plays/roles/docker_service/templates -type f | sort
```

Expected output (10 files):
```
ansible/plays/roles/docker_service/templates/docker.env.j2
ansible/plays/roles/docker_service/templates/energy/.env.j2
ansible/plays/roles/docker_service/templates/finance/.env.j2
ansible/plays/roles/docker_service/templates/groceries/.env.j2
ansible/plays/roles/docker_service/templates/job-search/.env.j2
ansible/plays/roles/docker_service/templates/job-search/api.env.j2
ansible/plays/roles/docker_service/templates/job-search/crawler.env.j2
ansible/plays/roles/docker_service/templates/leagues-finance/.env.j2
ansible/plays/roles/docker_service/templates/opencode/.env.j2
ansible/plays/roles/docker_service/templates/searxng/.env.j2
ansible/plays/roles/docker_service/templates/searxng/settings.yml.j2
```

- [ ] **Step 14: Commit**

```bash
git add ansible/plays/roles/docker_service/templates/
git commit -m "feat(docker_service): migrate all env templates from user and dedicated roles"
```

---

## Task 4: Write Molecule tests for `docker_service`

**Files:**
- Create: `ansible/plays/roles/docker_service/molecule/default/molecule.yml`
- Create: `ansible/plays/roles/docker_service/molecule/default/prepare.yml`
- Create: `ansible/plays/roles/docker_service/molecule/default/converge.yml`
- Create: `ansible/plays/roles/docker_service/molecule/default/verify.yml`

The molecule test covers three scenarios via a single converge:
1. **Simple service** (`traefik`-style): only `docker.env.j2` → `.env`
2. **Multi-template service** (`job-search`-style): three env files
3. **Manual service** (`monitor`-style): env rendered, compose skipped

Compose tasks are tagged `molecule-notest` in the role so they're skipped in tests. Verify checks file existence and content.

- [ ] **Step 1: Write the failing test — create `molecule/default/verify.yml`**

```yaml
---
- name: Verify
  hosts: all
  become: true
  tasks:
    - name: Check simple service .env exists
      ansible.builtin.stat:
        path: /home/molecule/simple-svc/.env
      register: simple_env
      failed_when: not simple_env.stat.exists

    - name: Check simple service .env has correct permissions
      ansible.builtin.stat:
        path: /home/molecule/simple-svc/.env
      register: simple_env_perms
      failed_when: simple_env_perms.stat.mode != '0600'

    - name: Verify simple service .env contains SERVICE_HOST
      ansible.builtin.command:
        cmd: grep -q 'SERVICE_HOST=simple-svc\.' /home/molecule/simple-svc/.env
      changed_when: false

    - name: Verify simple service .env contains SERVICE_NAME
      ansible.builtin.command:
        cmd: grep -q 'SERVICE_NAME=simple-svc' /home/molecule/simple-svc/.env
      changed_when: false

    - name: Check job-search .env exists
      ansible.builtin.stat:
        path: /home/molecule/job-search/.env
      register: js_env
      failed_when: not js_env.stat.exists

    - name: Check job-search api.env exists
      ansible.builtin.stat:
        path: /home/molecule/job-search/api.env
      register: js_api_env
      failed_when: not js_api_env.stat.exists

    - name: Check job-search crawler.env exists
      ansible.builtin.stat:
        path: /home/molecule/job-search/crawler.env
      register: js_crawler_env
      failed_when: not js_crawler_env.stat.exists

    - name: Verify job-search api.env has JWT_SECRET
      ansible.builtin.command:
        cmd: grep -q 'JWT_SECRET=test-jwt-secret' /home/molecule/job-search/api.env
      changed_when: false

    - name: Verify job-search api.env has SEARXNG_TOKEN
      ansible.builtin.command:
        cmd: grep -q 'SEARXNG_TOKEN=test-searxng-token' /home/molecule/job-search/api.env
      changed_when: false

    - name: Verify job-search crawler.env has SEARXNG_URL
      ansible.builtin.command:
        cmd: grep -q 'SEARXNG_URL=https://search.lehel.xyz' /home/molecule/job-search/crawler.env
      changed_when: false

    - name: Verify all env files have mode 0600
      ansible.builtin.stat:
        path: "/home/molecule/{{ item }}"
      register: env_stat
      failed_when: env_stat.stat.mode != '0600'
      loop:
        - simple-svc/.env
        - job-search/.env
        - job-search/api.env
        - job-search/crawler.env

    - name: Check manual service .env exists (env IS rendered for manual)
      ansible.builtin.stat:
        path: /home/molecule/manual-svc/.env
      register: manual_env
      failed_when: not manual_env.stat.exists

    - name: Verify SERVICE_HOST in manual service .env
      ansible.builtin.command:
        cmd: grep -q 'SERVICE_HOST=manual-svc\.' /home/molecule/manual-svc/.env
      changed_when: false
```

Write to `ansible/plays/roles/docker_service/molecule/default/verify.yml`.

- [ ] **Step 2: Write `molecule/default/converge.yml`**

```yaml
---
- name: Converge
  hosts: all
  become: true
  vars:
    docker:
      remote_dir: /home/molecule
    extension_drive:
      path: /var/lib
    job_search_jwt_secret: test-jwt-secret
    job_search_searxng_token: test-searxng-token
    job_search_searxng_url: https://search.lehel.xyz

  pre_tasks:
    - name: Create service directories
      ansible.builtin.file:
        path: "/home/molecule/{{ item }}"
        state: directory
        mode: "0755"
      loop:
        - simple-svc
        - job-search
        - manual-svc

  tasks:
    - name: Deploy simple service
      ansible.builtin.include_role:
        name: "{{ playbook_dir }}/../../"
        tasks_from: main.yml
      vars:
        service_dir: simple-svc

    - name: Deploy multi-template job-search service
      ansible.builtin.include_role:
        name: "{{ playbook_dir }}/../../"
        tasks_from: main.yml
      vars:
        service_dir: job-search
        env_templates:
          - { src: docker.env.j2, dest: .env }
          - { src: job-search/.env.j2, dest: .env }
          - { src: job-search/api.env.j2, dest: api.env }
          - { src: job-search/crawler.env.j2, dest: crawler.env }

    - name: Deploy manual service (env only, no compose)
      ansible.builtin.include_role:
        name: "{{ playbook_dir }}/../../"
        tasks_from: main.yml
      vars:
        service_dir: manual-svc
        manual: true
```

Write to `ansible/plays/roles/docker_service/molecule/default/converge.yml`.

Note: The job-search converge renders `.env` twice (docker.env.j2 then job-search/.env.j2 both to `.env`). This tests that the loop works for multiple templates including override scenarios. In production, job-search uses `docker.env.j2` → `.env` and `job-search/.env.j2` → `.env` (second overwrites first with service-specific content). Adjust if this behavior is undesirable.

- [ ] **Step 3: Write `molecule/default/prepare.yml`**

```yaml
---
- name: Prepare
  hosts: all
  gather_facts: false
  tasks:
    - name: Install Python and Docker SDK for Ansible
      raw: |
        apt-get update
        apt-get install -y python3 python3-apt python3-requests python3-docker sudo
      changed_when: false
```

Write to `ansible/plays/roles/docker_service/molecule/default/prepare.yml`.

- [ ] **Step 4: Write `molecule/default/molecule.yml`**

```yaml
---
dependency:
  name: galaxy
  options:
    requirements-file: ../../../../../requirements.yml

driver:
  name: docker

platforms:
  - name: instance-docker-service
    image: geerlingguy/docker-ubuntu2204-ansible:latest
    command: ""
    volumes:
      - /sys/fs/cgroup:/sys/fs/cgroup:rw
      - /var/run/docker.sock:/var/run/docker.sock
    cgroupns_mode: host
    privileged: true
    pre_build_image: true

provisioner:
  name: ansible
  playbooks:
    converge: converge.yml
    verify: verify.yml
  config_options:
    defaults:
      action_warnings: true
      allow_world_readable_tmpfiles: true
      roles_path: ../../../
  env:
    ANSIBLE_FORCE_COLOR: "1"

verifier:
  name: ansible

scenario:
  test_sequence:
    - dependency
    - cleanup
    - destroy
    - syntax
    - create
    - prepare
    - converge
    - verify
    - cleanup
    - destroy
```

Write to `ansible/plays/roles/docker_service/molecule/default/molecule.yml`.

- [ ] **Step 5: Commit the molecule tests**

```bash
git add ansible/plays/roles/docker_service/molecule/
git commit -m "test(docker_service): add molecule scenario for simple, multi-template, and manual services"
```

---

## Task 5: Run Molecule tests on servyy-test

**Files:** No new files — this step validates Task 4.

- [ ] **Step 1: Run molecule tests from the role directory**

```bash
cd ansible/plays/roles/docker_service && molecule test --scenario-name default
```

Expected: All tasks converge, all verify assertions pass. Tests should take ~2–3 minutes.

- [ ] **Step 2: If tests fail — diagnose and fix**

If env files are not found: check `docker.remote_dir` is defined in converge.yml vars.
If template vars are undefined: check that role defaults are loaded (the `include_role` must pick up defaults from `defaults/main.yml`).
If permissions fail: check the `mode: "0600"` in `tasks/env.yml`.

Fix issues and re-run:
```bash
molecule test --scenario-name default
```

- [ ] **Step 3: Verify molecule passes cleanly**

```bash
molecule test --scenario-name default 2>&1 | tail -30
```

Expected: `PLAY RECAP` shows `failed=0 unreachable=0`. The scenario should end with `Scenario.test_sequence: destroy`.

- [ ] **Step 4: Commit any fixes**

```bash
git add -p
git commit -m "fix(docker_service): fix molecule test issues"
```

(Only if fixes were needed.)

---

## Task 6: Rewrite `user.yml` with explicit docker_service invocations

**Files:**
- Modify: `ansible/plays/user.yml`
- Create: `ansible/plays/templates/searxng/` directory

The new `user.yml` replaces the three-play structure (user + user_searxng + user_job_search) with a single play. The `pre_tasks` section handles the finance PEM key reading and the searxng-specific setup (stop/ownership/settings.yml) that the generic role cannot encapsulate. The `roles` section has one explicit `docker_service` invocation per service.

**Key decisions:**
- `opencode` is in the custom-env category (has `opencode.env` with secrets), not simple.
- `searxng` overrides `service_host` to `search.{{ inventory_hostname }}` and uses only `searxng/.env.j2` → `.env`.
- `job-search` uses three env files with the original separate template per file (not `.env` override).
- `monitor` is `manual: true` — env rendered, compose skipped.
- Services with `pass`, `portainer`, `me` from the old secrets.yml array are retained with `manual: true` if they were manual before (check secrets.yml for the `manual` field).

- [ ] **Step 1: Create play templates directory for searxng settings.yml**

The searxng `settings.yml.j2` deploy happens in a play-level pre_task. Ansible looks for templates in `{playbook_dir}/templates/` when used outside a role.

```bash
mkdir -p ansible/plays/templates/searxng
cp ansible/plays/roles/docker_service/templates/searxng/settings.yml.j2 \
   ansible/plays/templates/searxng/settings.yml.j2
```

- [ ] **Step 2: Read current `user.yml` to understand all services in secrets.yml**

Check `ansible/plays/vars/secrets.yml` to list all entries in `docker.services[]` — especially which have `manual: {}` set. Also note: `me`, `portainer`, `pass`, `dns` in the original list.

```bash
grep -A 1 "manual" ansible/plays/vars/secrets.yml 2>/dev/null || echo "git-crypt - check manually"
```

If git-crypt is locked, check the file directly to confirm which services are manual.

- [ ] **Step 3: Write the new `user.yml`**

Replace the entire content of `ansible/plays/user.yml` with:

```yaml
---
- name: Setup user specific options
  hosts: all
  strategy: free
  remote_user: "{{ create_user }}"
  become: true
  become_user: "{{ create_user }}"
  vars_files:
    - vars/default.yml
    - vars/restic.yml
    - vars/secrets.yml
  roles:
    - user
  tags:
    - user

- name: Deploy Docker services
  hosts: all
  strategy: free
  remote_user: "{{ create_user }}"
  become: true
  become_user: "{{ create_user }}"
  vars_files:
    - vars/default.yml
    - vars/restic.yml
    - vars/secrets.yml
  tags:
    - user
    - user.docker
  pre_tasks:
    - name: Read and encode Enable Banking PEM key
      ansible.builtin.slurp:
        src: "{{ docker.local_dir }}/finance/import/eb.pem"
      register: pem_file
      delegate_to: localhost
      tags:
        - user.docker.env
        - user.docker.env.finance

    - name: Set Enable Banking private key fact
      ansible.builtin.set_fact:
        enable_banking_private_key_b64: >-
          {{ pem_file['content'] | regex_replace('-----BEGIN PRIVATE KEY-----\n|-----END PRIVATE KEY-----\n', '')
          | regex_replace('\n', '') }}
      tags:
        - user.docker.env
        - user.docker.env.finance

    - name: Stop searxng before config update
      community.docker.docker_compose_v2:
        project_src: "{{ docker.remote_dir }}/searxng"
        state: absent
      ignore_errors: true
      tags:
        - user.docker.searxng
        - molecule-notest

    - name: Fix searxng core-config directory ownership
      ansible.builtin.file:
        path: "{{ docker.remote_dir }}/searxng/core-config"
        state: directory
        owner: "{{ ansible_facts['user_id'] }}"
        group: "{{ ansible_facts['user_id'] }}"
        recurse: true
      become: true
      become_user: root
      tags:
        - user.docker.searxng

    - name: Deploy searxng settings.yml
      ansible.builtin.template:
        src: searxng/settings.yml.j2
        dest: "{{ docker.remote_dir }}/searxng/core-config/settings.yml"
        mode: "0600"
      tags:
        - user.docker.searxng

  roles:
    # Simple services — generic .env only
    - role: docker_service
      vars: { service_dir: traefik }
      tags: [user.docker, user.docker.traefik]

    - role: docker_service
      vars: { service_dir: git }
      tags: [user.docker, user.docker.git]

    - role: docker_service
      vars: { service_dir: photoprism }
      tags: [user.docker, user.docker.photoprism]

    - role: docker_service
      vars: { service_dir: bumbleflies }
      tags: [user.docker, user.docker.bumbleflies]

    - role: docker_service
      vars: { service_dir: achim-hoefer }
      tags: [user.docker, user.docker.achim-hoefer]

    - role: docker_service
      vars: { service_dir: pass, manual: true }
      tags: [user.docker, user.docker.pass]

    - role: docker_service
      vars: { service_dir: portainer }
      tags: [user.docker, user.docker.portainer]

    # Services with additional env templates
    - role: docker_service
      vars:
        service_dir: opencode
        env_templates:
          - { src: docker.env.j2, dest: .env }
          - { src: opencode/.env.j2, dest: opencode.env }
      tags: [user.docker, user.docker.opencode]

    - role: docker_service
      vars:
        service_dir: energy
        env_templates:
          - { src: docker.env.j2, dest: .env }
          - { src: energy/.env.j2, dest: energy.env }
      tags: [user.docker, user.docker.energy]

    - role: docker_service
      vars:
        service_dir: groceries
        env_templates:
          - { src: docker.env.j2, dest: .env }
          - { src: groceries/.env.j2, dest: groceries.env }
      tags: [user.docker, user.docker.groceries]

    - role: docker_service
      vars:
        service_dir: leagues-finance
        env_templates:
          - { src: docker.env.j2, dest: .env }
          - { src: leagues-finance/.env.j2, dest: leagues-finance.env }
      tags: [user.docker, user.docker.leagues-finance]

    - role: docker_service
      vars:
        service_dir: finance
        env_templates:
          - { src: docker.env.j2, dest: .env }
          - { src: finance/.env.j2, dest: finance.env }
      tags: [user.docker, user.docker.finance]

    # Searxng — custom .env replacing docker.env.j2, non-standard service_host
    - role: docker_service
      vars:
        service_dir: searxng
        service_host: "search.{{ inventory_hostname }}"
        service_name: searxng
        env_templates:
          - { src: searxng/.env.j2, dest: .env }
      tags: [user.docker, user.docker.searxng]

    # Job search — three env files
    - role: docker_service
      vars:
        service_dir: job-search
        service_host: "jobs.{{ inventory_hostname }}"
        job_search_jwt_secret: "{{ vault_job_search_jwt_secret }}"
        job_search_searxng_token: "{{ vault_searxng_brave_token }}"
        job_search_searxng_url: https://search.lehel.xyz
        env_templates:
          - { src: docker.env.j2, dest: .env }
          - { src: job-search/.env.j2, dest: .env }
          - { src: job-search/api.env.j2, dest: api.env }
          - { src: job-search/crawler.env.j2, dest: crawler.env }
      tags: [user.docker, user.docker.job-search]

    # Manual services — env rendered, compose not started
    - role: docker_service
      vars: { service_dir: dns, manual: true }
      tags: [user.docker, user.docker.dns]

    - role: docker_service
      vars: { service_dir: monitor, manual: true }
      tags: [user.docker, user.docker.monitor]
```

Write to `ansible/plays/user.yml`.

**Note:** Cross-check the services against the original `docker.services[]` in `secrets.yml`. If there are services listed there not covered above (e.g., `me`), add them. The `me` service (if present) was likely `manual: true` — add it accordingly.

- [ ] **Step 4: Syntax check the new user.yml**

```bash
cd ansible && ansible-playbook plays/user.yml --syntax-check 2>&1
```

This will fail until `user_searxng` and `user_job_search` are deleted (Task 8). The new `docker_service` role is referenced and should be found. Confirm there are no YAML parse errors in the new structure itself.

- [ ] **Step 5: Commit**

```bash
git add ansible/plays/user.yml ansible/plays/templates/
git commit -m "feat: rewrite user.yml with explicit docker_service role invocations"
```

---

## Task 7: Refactor `user` role tasks

**Files:**
- Create: `ansible/plays/roles/user/tasks/docker_extras.yml`
- Modify: `ansible/plays/roles/user/tasks/main.yml`
- Modify: `ansible/plays/roles/user/tasks/bumbleflies.yml`

The `docker_extras.yml` file preserves the specialized non-loop tasks from `docker_services.yml` (finance import setup, opencode data dir, mongo health check, lingering, photo-index oneshot). The service-start loop and `docker_repo_env.yml` are deleted.

- [ ] **Step 1: Create `docker_extras.yml`**

This replaces `docker_services.yml` but REMOVES the array-loop service start task (now done by explicit roles in `user.yml`). Retain all other tasks exactly.

```yaml
---
- name: Create docker script for services
  template:
    src: docker_command.sh.j2
    dest: "{{ (remote_user_home, 'forall_docker_services.sh') | path_join }}"
    mode: 0770
    owner: "{{ create_user }}"
  vars:
    services:
      - { dir: traefik }
      - { dir: git, depends: traefik }
      - { dir: photoprism, depends: traefik }
      - { dir: bumbleflies, depends: traefik }
      - { dir: achim-hoefer, depends: traefik }
      - { dir: opencode }
      - { dir: energy }
      - { dir: groceries }
      - { dir: leagues-finance }
      - { dir: finance }
      - { dir: searxng }
      - { dir: job-search }
      - { dir: portainer }
      - { dir: dns, manual: {} }
      - { dir: monitor, manual: {} }
      - { dir: pass, manual: {} }
    services_root: "{{ docker.remote_dir }}"
  tags:
    - user.docker.services.script

- name: Create finance import directory
  file:
    path: "{{ (docker.remote_dir, 'finance', 'import') | path_join }}"
    state: directory
    owner: "{{ create_user }}"
    group: "docker"
    mode: '0755'
  tags:
    - user.docker.env

- name: Create finance import config from template
  template:
    src: finance-import-config.json.j2
    dest: "{{ (docker.remote_dir, 'finance', 'import', 'import_config.json') | path_join }}"
    owner: "{{ create_user }}"
    group: "docker"
    mode: '0644'
  tags:
    - user.docker.env

- name: Create finance import script from template
  template:
    src: run-import.sh.j2
    dest: "{{ (docker.remote_dir, 'finance', 'import', 'run-import.sh') | path_join }}"
    owner: "{{ create_user }}"
    group: "docker"
    mode: '0755'
  tags:
    - user.docker.env

- name: Create OpenCode data directory
  file:
    path: "{{ (docker.remote_dir, 'opencode', 'data') | path_join }}"
    state: directory
    owner: "{{ create_user }}"
    group: "docker"
    mode: '0775'
  become: true
  become_user: root
  when: with_containers | default(false)
  tags:
    - user.docker.opencode

- name: Wait for leagues-finance mongo to become healthy
  community.docker.docker_container_info:
    name: "leagues-finance.mongo"
  register: lf_mongo_info
  until: >
    lf_mongo_info.container is defined and
    lf_mongo_info.container.State.Health.Status is defined and
    lf_mongo_info.container.State.Health.Status == 'healthy'
  retries: 15
  delay: 2
  failed_when: false
  tags:
    - user.docker.services.start

- name: Remove corrupted mongo volume and restart if unhealthy
  when: >
    lf_mongo_info.container is not defined or
    lf_mongo_info.container.State.Health.Status != 'healthy'
  block:
    - name: Stop leagues-finance containers
      community.docker.docker_compose_v2:
        project_src: "{{ (docker.remote_dir, 'leagues-finance') | path_join }}"
        project_name: leagues-finance
        state: stopped

    - name: Remove leagues-finance mongo_data volume
      community.docker.docker_volume:
        name: leagues-finance_mongo_data
        state: absent

    - name: Restart leagues-finance containers
      community.docker.docker_compose_v2:
        project_src: "{{ (docker.remote_dir, 'leagues-finance') | path_join }}"
        project_name: leagues-finance
        state: present

    - name: Wait for mongo after volume reset
      community.docker.docker_container_info:
        name: "leagues-finance.mongo"
      register: lf_mongo_retry
      until: >
        lf_mongo_retry.container is defined and
        lf_mongo_retry.container.State.Health.Status == 'healthy'
      retries: 15
      delay: 2
  tags:
    - user.docker.services.start

- name: Ensure lingering enabled
  command: "loginctl enable-linger {{ create_user }}"
  args:
    creates: "/var/lib/systemd/linger/{{ create_user }}"
  tags:
    - user.docker.systemd.linger

- import_tasks: includes/oneshot.yml
  vars:
    service:
      name: docker-photo-index
      description: 'Docker Compose - Photo Index'
      schedule: '00/2:30'
      command: "{{ (docker.remote_dir, 'scripts', 'index-photos.sh') | path_join }}"
  tags:
    - user.docker.systemd.service.index
```

Write to `ansible/plays/roles/user/tasks/docker_extras.yml`.

- [ ] **Step 2: Update `main.yml` — remove old includes, add docker_extras.yml**

Read `ansible/plays/roles/user/tasks/main.yml`, then replace:

```yaml
- import_tasks: docker_repo_env.yml
  tags:
    - user.repo.docker.env
    - user.docker
  when: with_containers | default(false)
```

Remove this block entirely (no replacement — env rendering is now done by docker_service roles in user.yml).

Also replace:

```yaml
- import_tasks: docker_services.yml
  tags:
    - user.docker.services
    - user.docker
  when: with_containers | default(false)
```

With:

```yaml
- import_tasks: docker_extras.yml
  tags:
    - user.docker.services
    - user.docker
  when: with_containers | default(false)
```

- [ ] **Step 3: Fix `bumbleflies.yml` — remove docker.services dependency**

Read `ansible/plays/roles/user/tasks/bumbleflies.yml`. It currently uses:
```yaml
set_fact:
  dir_bumbleflies: "{{ (docker.services | selectattr('name', 'equalto', 'Bumbleflies') | first).dir }}"
```

Since `docker.services` is being removed, replace this with a hardcoded value:

```yaml
---
- name: Setting working dir for bumbleflies service
  set_fact:
    docker_dir_bumbleflies: "{{ (docker.remote_dir, 'bumbleflies') | path_join }}"

- name: Configure safe directory for {{ docker_dir_bumbleflies }}/site
  git_config:
    name: safe.directory
    scope: global
    value: "{{ docker_dir_bumbleflies }}/site"
```

Write to `ansible/plays/roles/user/tasks/bumbleflies.yml`.

- [ ] **Step 4: Verify user role syntax**

```bash
cd ansible && ansible-playbook plays/user.yml --syntax-check 2>&1 | grep -E "ERROR|FAILED|ok"
```

Expected: No ERROR lines in the user role or docker_extras.yml parsing.

- [ ] **Step 5: Commit**

```bash
git add ansible/plays/roles/user/tasks/docker_extras.yml \
        ansible/plays/roles/user/tasks/main.yml \
        ansible/plays/roles/user/tasks/bumbleflies.yml
git commit -m "refactor(user): replace docker_repo_env/docker_services with docker_extras, drop docker.services dependency"
```

---

## Task 8: Delete deprecated roles and templates

**Files:**
- Delete: `ansible/plays/roles/user/tasks/docker_repo_env.yml`
- Delete: `ansible/plays/roles/user/tasks/docker_services.yml`
- Delete: `ansible/plays/roles/user/templates/energy.env.j2`
- Delete: `ansible/plays/roles/user/templates/finance.env.j2`
- Delete: `ansible/plays/roles/user/templates/groceries.env.j2`
- Delete: `ansible/plays/roles/user/templates/leagues-finance.env.j2`
- Delete: `ansible/plays/roles/user/templates/opencode.env.j2`
- Delete: `ansible/plays/roles/user_searxng/` (entire directory)
- Delete: `ansible/plays/roles/user_job_search/` (entire directory)

- [ ] **Step 1: Delete deprecated user role task files**

```bash
rm ansible/plays/roles/user/tasks/docker_repo_env.yml
rm ansible/plays/roles/user/tasks/docker_services.yml
```

- [ ] **Step 2: Delete moved templates from user role**

```bash
rm ansible/plays/roles/user/templates/energy.env.j2
rm ansible/plays/roles/user/templates/finance.env.j2
rm ansible/plays/roles/user/templates/groceries.env.j2
rm ansible/plays/roles/user/templates/leagues-finance.env.j2
rm ansible/plays/roles/user/templates/opencode.env.j2
```

- [ ] **Step 3: Delete `user_searxng` role**

```bash
rm -rf ansible/plays/roles/user_searxng
```

- [ ] **Step 4: Delete `user_job_search` role**

```bash
rm -rf ansible/plays/roles/user_job_search
```

- [ ] **Step 5: Verify deletions**

```bash
ls ansible/plays/roles/ | sort
```

Expected: `docker_service`, `ls_access`, `ls_app`, `ls_db_sync`, `ls_demo`, `ls_setup`, `restic`, `system`, `testing`, `user` — no `user_searxng`, no `user_job_search`.

```bash
ls ansible/plays/roles/user/templates/ | grep "env.j2"
```

Expected: only `docker.env.j2` remains (the others moved to docker_service role).

```bash
ls ansible/plays/roles/user/tasks/ | grep "docker_"
```

Expected: `docker_extras.yml`, `docker_setup.yml` — no `docker_repo_env.yml`, no `docker_services.yml`.

- [ ] **Step 6: Full syntax check**

```bash
cd ansible && ansible-playbook plays/user.yml --syntax-check 2>&1
```

Expected: Exits cleanly with `playbook: plays/user.yml` and no errors.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: delete deprecated user_searxng, user_job_search roles and moved templates"
```

---

## Task 9: Update CI matrix

**Files:**
- Modify: `.github/workflows/ci.yml`

Replace `user_searxng` and `user_job_search` molecule matrix entries with `docker_service`.

- [ ] **Step 1: Read current CI matrix**

Read `.github/workflows/ci.yml` and find the `molecule-test` job's `matrix.include` section.

- [ ] **Step 2: Update the matrix**

Find and remove:
```yaml
          - role: user_searxng
            scenario: default
          - role: user_job_search
            scenario: default
```

Add in their place:
```yaml
          - role: docker_service
            scenario: default
```

- [ ] **Step 3: Verify CI file is valid YAML**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "VALID"
```

Expected: `VALID`

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: replace user_searxng/user_job_search with docker_service in molecule matrix"
```

---

## Task 10: Full validation on test environment

**Files:** No new files — this step validates the entire refactor.

- [ ] **Step 1: Ensure test container is initialized**

```bash
cd scripts && ./setup_test_container.sh
```

Expected: Exits with `servyy-test.lxd container ready`.

- [ ] **Step 2: Run syntax check on all plays**

```bash
cd ansible && ansible-playbook servyy.yml --syntax-check 2>&1 | tail -5
```

Expected: No syntax errors.

- [ ] **Step 3: Deploy to test environment**

```bash
cd ansible && ./servyy-test.sh 2>&1 | tail -40
```

Expected: `PLAY RECAP` shows `failed=0 unreachable=0`.

- [ ] **Step 4: Verify key containers started**

```bash
ssh servyy-test.lxd "docker ps --format '{{.Names}}: {{.Status}}'" 2>&1
```

Expected: `traefik.traefik`, `git.gitea`, `photoprism.photoprism`, `searxng.core`, `job-search.api` (or similar names) are all `Up`.

- [ ] **Step 5: Verify env files rendered correctly**

```bash
ssh servyy-test.lxd "ls ~/servyy-container/searxng/.env ~/servyy-container/job-search/api.env ~/servyy-container/job-search/crawler.env"
```

Expected: All files exist (no `ls: cannot access` errors).

```bash
ssh servyy-test.lxd "grep -q 'SERVICE_HOST=searxng' ~/servyy-container/searxng/.env && echo 'searxng env OK'"
```

Expected: `searxng env OK`.

- [ ] **Step 6: Verify Molecule passes**

```bash
cd ansible/plays/roles/docker_service && molecule test --scenario-name default 2>&1 | tail -15
```

Expected: `failed=0 unreachable=0`.

- [ ] **Step 7: Commit final state**

```bash
git add -A
git commit -m "chore: final validation cleanup"
```

(Only if there were minor fixes during validation.)

- [ ] **Step 8: Push branch to origin for CI**

```bash
git push origin HEAD
```

Expected: CI triggers and all molecule jobs pass (check GitHub Actions).

---

## Self-Review

**Spec coverage:**

| Spec requirement | Covered by |
|---|---|
| `docker_service` role with defaults interface | Task 1 |
| `tasks/main.yml` with `include_tasks` env + deploy | Task 2 |
| `env.yml` — single clean loop, no special cases | Task 2 |
| `deploy.yml` — `docker_compose_v2` | Task 2 |
| Templates consolidated into role | Task 3 |
| Delete `user/tasks/docker_repo_env.yml` | Task 8 |
| Delete `user/tasks/docker_services.yml` | Task 7 + 8 |
| Delete `docker.services[]` array dependency | Task 7 (bumbleflies.yml), Task 8 |
| Delete `roles/user_searxng/` | Task 8 |
| Delete `roles/user_job_search/` | Task 8 |
| Explicit role invocations in `user.yml` | Task 6 |
| `manual: true` for monitor (env rendered, compose skipped) | Task 6 |
| Molecule tests for new role | Task 4 |
| `ls_*` roles unchanged | Not touched in any task |
| `user` role retained (non-docker tasks unchanged) | Task 7 (only docker includes changed) |

**Gaps and deviations from spec:**
1. **`opencode` and `searxng` moved to custom-env category** — spec shows them as "simple" but both have service-specific secrets that require additional env templates. This is a safe deviation that preserves service functionality.
2. **`settings.yml.j2` deployment** — spec says delete `user_searxng` entirely but doesn't address the `settings.yml` config file. Handled by moving template to play-level `ansible/plays/templates/searxng/` and deploying via `pre_tasks` in `user.yml`.
3. **Finance PEM key** — requires `pre_tasks` in `user.yml` to read from localhost before role renders the template. Not addressed in spec but necessary.
4. **`docker.services[]` in `secrets.yml`** — spec says remove the array, but `secrets.yml` is git-crypt encrypted. The array needs to be manually removed from `secrets.yml` after the roles no longer reference it. Add a note to do this as a cleanup step after Task 8.
5. **`forall_docker_services.sh` script** — now uses a hardcoded inline list in `docker_extras.yml` since `docker.services[]` is removed. Update the list if services change.
6. **`job-search` .env rendering** — `job-search/.env.j2` overwrites the `.env` written by `docker.env.j2` since both render to `dest: .env`. If the job-search service needs both `SERVICE_HOST` (from docker.env.j2) AND `TRAEFIK_ENTRYPOINT` (from job-search/.env.j2), the job-search template should include `SERVICE_HOST={{ service_host }}` explicitly, or the order should be reversed so docker.env.j2 overwrites. Verify by checking the job-search docker-compose.yml for which env vars it actually reads.

**Placeholder scan:** No TBD, TODO, or "similar to" patterns in this plan.

**Type consistency:** `service_dir`, `service_name`, `service_host`, `env_templates`, `manual`, `docker.remote_dir` — used consistently across all tasks.
