# job-search Service Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the `job-search` Docker service into the servyy-container Ansible infrastructure so deployments to test (`servyy-test.lxd`) and production (`lehel.xyz`) are automated and version-controlled.

**Architecture:** A dedicated Ansible role `user_job_search` generates three env files from Jinja2 templates populated with Ansible vault secrets, then runs `docker compose up`. The docker-compose.yml lives in `job-search/` in this repo and uses env vars for all environment-specific Traefik settings. The testing inventory overrides defaults to use plain HTTP for servyy-test.lxd.

**Tech Stack:** Ansible, community.docker.docker_compose_v2, Molecule (docker driver, geerlingguy/docker-ubuntu2204-ansible), Jinja2 templates, git-crypt (for secrets.yml encryption)

---

## File Map

| Action | Path |
|--------|------|
| CREATE | `job-search/docker-compose.yml` |
| CREATE | `ansible/plays/roles/user_job_search/defaults/main.yml` |
| CREATE | `ansible/plays/roles/user_job_search/tasks/main.yml` |
| CREATE | `ansible/plays/roles/user_job_search/templates/env.j2` |
| CREATE | `ansible/plays/roles/user_job_search/templates/api.env.j2` |
| CREATE | `ansible/plays/roles/user_job_search/templates/crawler.env.j2` |
| CREATE | `ansible/plays/roles/user_job_search/molecule/default/molecule.yml` |
| CREATE | `ansible/plays/roles/user_job_search/molecule/default/prepare.yml` |
| CREATE | `ansible/plays/roles/user_job_search/molecule/default/converge.yml` |
| CREATE | `ansible/plays/roles/user_job_search/molecule/default/verify.yml` |
| MODIFY | `ansible/plays/vars/secrets.yml` — add `vault_job_search_jwt_secret` |
| MODIFY | `ansible/testing` — add `job_search_*` host vars for servyy-test.lxd |
| MODIFY | `ansible/plays/user.yml` — add `Deploy job-search service` play |

---

### Task 1: Add docker-compose.yml to repo

**Files:**
- Create: `job-search/docker-compose.yml`

The source of truth is `deploy/servyy-test/docker-compose.yml` in the job-search project. We adapt it by:
- Parameterising all Traefik labels with env vars
- Dropping the hardcoded `_local` routers
- Dropping explicit `ports:` mappings (Traefik handles routing)
- Adding `name: job-search` for explicit project naming

- [ ] **Create `job-search/docker-compose.yml`**

```yaml
name: job-search

services:
  mongodb:
    image: mongo:7.0
    container_name: job-search-mongodb
    restart: unless-stopped
    volumes:
      - mongodb_data:/data/db
    networks:
      - internal
    healthcheck:
      test: ["CMD", "mongosh", "--eval", "db.adminCommand('ping')"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: job-search-redis-app
    restart: unless-stopped
    volumes:
      - redis_data:/data
    networks:
      - internal
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  api:
    image: dachrisch/job-search-api:latest
    container_name: job-search-api
    restart: unless-stopped
    env_file:
      - .env
      - api.env
    environment:
      MONGODB_URI: mongodb://mongodb:27017/job_search
      REDIS_URL: redis://redis:6379
    depends_on:
      mongodb:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - internal
      - proxy
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:3000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    labels:
      - traefik.enable=true
      - traefik.http.routers.job-search-api.rule=Host(`${SERVICE_HOST}`) && PathPrefix(`/api`)
      - traefik.http.routers.job-search-api.entrypoints=${TRAEFIK_ENTRYPOINT:-websecure}
      - traefik.http.routers.job-search-api.tls=${TRAEFIK_TLS:-true}
      - traefik.http.routers.job-search-api.tls.certresolver=${TRAEFIK_CERTRESOLVER:-letsencryptdnsresolver}
      - traefik.http.services.job-search-api.loadbalancer.server.port=3000
      - com.centurylinklabs.watchtower.scope=dev

  frontend:
    image: dachrisch/job-search-frontend:latest
    container_name: job-search-frontend
    restart: unless-stopped
    env_file:
      - .env
    networks:
      - proxy
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:80"]
      interval: 30s
      timeout: 10s
      retries: 3
    labels:
      - traefik.enable=true
      - traefik.http.routers.job-search-frontend.rule=Host(`${SERVICE_HOST}`)
      - traefik.http.routers.job-search-frontend.entrypoints=${TRAEFIK_ENTRYPOINT:-websecure}
      - traefik.http.routers.job-search-frontend.tls=${TRAEFIK_TLS:-true}
      - traefik.http.routers.job-search-frontend.tls.certresolver=${TRAEFIK_CERTRESOLVER:-letsencryptdnsresolver}
      - traefik.http.services.job-search-frontend.loadbalancer.server.port=80
      - com.centurylinklabs.watchtower.scope=dev

  crawler:
    image: dachrisch/job-search-crawler:latest
    container_name: job-search-crawler
    restart: unless-stopped
    env_file:
      - crawler.env
    environment:
      API_URL: http://job-search-api:3000
    networks:
      - internal
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
    labels:
      - com.centurylinklabs.watchtower.scope=dev

volumes:
  mongodb_data:
  redis_data:

networks:
  internal:
  proxy:
    external: true
```

- [ ] **Commit**

```bash
git add job-search/docker-compose.yml
git commit -m "feat: add job-search docker-compose.yml with parameterised Traefik labels"
```

---

### Task 2: Create Ansible role defaults and templates

**Files:**
- Create: `ansible/plays/roles/user_job_search/defaults/main.yml`
- Create: `ansible/plays/roles/user_job_search/templates/env.j2`
- Create: `ansible/plays/roles/user_job_search/templates/api.env.j2`
- Create: `ansible/plays/roles/user_job_search/templates/crawler.env.j2`

- [ ] **Create `ansible/plays/roles/user_job_search/defaults/main.yml`**

```yaml
---
container_project_name: job-search
container_home: "{{ ansible_facts['user_dir'] }}/servyy-container"
job_search_service_host: jobs.lehel.xyz
job_search_traefik_entrypoint: websecure
job_search_traefik_tls: "true"
job_search_traefik_certresolver: letsencryptdnsresolver
job_search_jwt_secret: "{{ vault_job_search_jwt_secret }}"
job_search_searxng_token: "{{ vault_searxng_brave_token }}"
job_search_searxng_url: https://search.lehel.xyz
```

- [ ] **Create `ansible/plays/roles/user_job_search/templates/env.j2`**

```jinja2
# Managed by Ansible - do not edit manually
SERVICE_HOST={{ job_search_service_host }}
SERVICE_NAME={{ container_project_name }}
TRAEFIK_ENTRYPOINT={{ job_search_traefik_entrypoint }}
TRAEFIK_TLS={{ job_search_traefik_tls }}
TRAEFIK_CERTRESOLVER={{ job_search_traefik_certresolver }}
```

- [ ] **Create `ansible/plays/roles/user_job_search/templates/api.env.j2`**

```jinja2
# Managed by Ansible - do not edit manually
NODE_ENV=production
LOG_LEVEL=info
JWT_SECRET={{ job_search_jwt_secret }}
```

- [ ] **Create `ansible/plays/roles/user_job_search/templates/crawler.env.j2`**

```jinja2
# Managed by Ansible - do not edit manually
SEARXNG_URL={{ job_search_searxng_url }}
SEARXNG_TOKEN={{ job_search_searxng_token }}
```

- [ ] **Commit**

```bash
git add ansible/plays/roles/user_job_search/
git commit -m "feat: add user_job_search role defaults and env templates"
```

---

### Task 3: Create Ansible role tasks

**Files:**
- Create: `ansible/plays/roles/user_job_search/tasks/main.yml`

- [ ] **Create `ansible/plays/roles/user_job_search/tasks/main.yml`**

```yaml
---
- name: Generate .env file
  ansible.builtin.template:
    src: env.j2
    dest: "{{ container_home }}/{{ container_project_name }}/.env"
    mode: "0600"

- name: Generate api.env file
  ansible.builtin.template:
    src: api.env.j2
    dest: "{{ container_home }}/{{ container_project_name }}/api.env"
    mode: "0600"

- name: Generate crawler.env file
  ansible.builtin.template:
    src: crawler.env.j2
    dest: "{{ container_home }}/{{ container_project_name }}/crawler.env"
    mode: "0600"

- name: Deploy job-search services
  community.docker.docker_compose_v2:
    project_src: "{{ container_home }}/{{ container_project_name }}"
    state: present
  tags: [molecule-notest]
```

- [ ] **Commit**

```bash
git add ansible/plays/roles/user_job_search/tasks/main.yml
git commit -m "feat: add user_job_search role tasks"
```

---

### Task 4: Add vault secret

**Files:**
- Modify: `ansible/plays/vars/secrets.yml`

The file is encrypted with git-crypt. Edit it directly — git-crypt will encrypt on commit.

- [ ] **Add `vault_job_search_jwt_secret` to `ansible/plays/vars/secrets.yml`**

Open the file and add this line alongside the other `vault_searxng_*` lines:

```yaml
vault_job_search_jwt_secret: "4e5157bac2a373b95635c25a0faad92ed274b50583b1e8e50a60020cd9f0130d"
```

- [ ] **Verify the file is recognised as unlocked (not binary)**

```bash
git-crypt status ansible/plays/vars/secrets.yml
```

Expected output: `encrypted: ansible/plays/vars/secrets.yml`  
(This means it will be auto-encrypted on commit — the file is currently readable because git-crypt is unlocked.)

- [ ] **Commit**

```bash
git add ansible/plays/vars/secrets.yml
git commit -m "feat: add vault_job_search_jwt_secret to secrets"
```

---

### Task 5: Add host vars to testing inventory

**Files:**
- Modify: `ansible/testing`

- [ ] **Add job_search host vars to `servyy-test.lxd` in `ansible/testing`**

The current `servyy-test.lxd` block ends with `searxng_traefik_certresolver: ""`. Add the job_search overrides immediately after:

```yaml
      job_search_service_host: job-search.servyy-test.lxd
      job_search_traefik_entrypoint: web
      job_search_traefik_tls: "false"
      job_search_traefik_certresolver: ""
```

The full `servyy-test.lxd` block should look like:

```yaml
    servyy-test.lxd:
      ansible_host: servyy-test.lxd
      root_user: ubuntu
      with_containers: true
      with_docker: false
      skip_storagebox: true
      searxng_service_host: search.servyy-test.lxd
      searxng_traefik_entrypoint: web
      searxng_traefik_tls: "false"
      searxng_traefik_certresolver: ""
      job_search_service_host: job-search.servyy-test.lxd
      job_search_traefik_entrypoint: web
      job_search_traefik_tls: "false"
      job_search_traefik_certresolver: ""
```

- [ ] **Commit**

```bash
git add ansible/testing
git commit -m "feat: add job_search host vars to servyy-test.lxd inventory"
```

---

### Task 6: Add play to user.yml

**Files:**
- Modify: `ansible/plays/user.yml`

- [ ] **Append the job-search play to `ansible/plays/user.yml`**

Add this block at the end of the file, after the existing `Deploy Searxng service` play:

```yaml
- name: Deploy job-search service
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
    - name: user_job_search
      vars:
        container_project_name: job-search
        container_home: "{{ ansible_facts['user_dir'] }}/servyy-container"
  tags:
    - user
    - user.docker
    - user.docker.job-search
```

- [ ] **Verify Ansible syntax**

Run from the `ansible/` directory:

```bash
cd ansible && ansible-playbook plays/user.yml --syntax-check
```

Expected: `playbook: plays/user.yml` with no errors.

- [ ] **Commit**

```bash
git add ansible/plays/user.yml
git commit -m "feat: add job-search play to user.yml playbook"
```

---

### Task 7: Write Molecule tests

**Files:**
- Create: `ansible/plays/roles/user_job_search/molecule/default/molecule.yml`
- Create: `ansible/plays/roles/user_job_search/molecule/default/prepare.yml`
- Create: `ansible/plays/roles/user_job_search/molecule/default/converge.yml`
- Create: `ansible/plays/roles/user_job_search/molecule/default/verify.yml`

- [ ] **Create `ansible/plays/roles/user_job_search/molecule/default/molecule.yml`**

```yaml
---
dependency:
  name: galaxy
  options:
    requirements-file: ../../../../../requirements.yml

driver:
  name: docker

platforms:
  - name: instance-job-search
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

- [ ] **Create `ansible/plays/roles/user_job_search/molecule/default/prepare.yml`**

```yaml
---
- name: Prepare
  hosts: all
  gather_facts: false
  tasks:
    - name: Install Python and Docker SDK for Ansible
      raw: |
        apt-get update
        apt-get install -y python3 python3-apt python3-requests python3-docker sudo systemd
      changed_when: false
```

- [ ] **Create `ansible/plays/roles/user_job_search/molecule/default/converge.yml`**

```yaml
---
- name: Converge
  hosts: all
  become: true
  vars:
    container_project_name: job-search
    container_home: /home/molecule
    vault_job_search_jwt_secret: "test-jwt-secret-for-molecule"
    vault_searxng_brave_token: "test-searxng-token-for-molecule"
  pre_tasks:
    - name: Create proxy network for testing
      community.docker.docker_network:
        name: proxy
        state: present

    - name: Create job-search service directory
      ansible.builtin.file:
        path: /home/molecule/job-search
        state: directory
        mode: "0755"

    - name: Create docker-compose.yml for testing
      ansible.builtin.copy:
        dest: /home/molecule/job-search/docker-compose.yml
        mode: "0644"
        content: |
          name: job-search
          services:
            api:
              container_name: job-search-api
              image: alpine:latest
              command: ["sh", "-c", "echo ok"]
              networks:
                - proxy
              labels:
                - "traefik.enable=true"
          networks:
            proxy:
              external: true
  tasks:
    - name: Include user_job_search role  # noqa: role-name[path]
      ansible.builtin.include_role:
        name: "{{ playbook_dir }}/../../"
        tasks_from: main.yml
```

- [ ] **Create `ansible/plays/roles/user_job_search/molecule/default/verify.yml`**

```yaml
---
- name: Verify
  hosts: all
  become: true
  tasks:
    - name: Check job-search directory exists
      ansible.builtin.stat:
        path: /home/molecule/job-search
      register: job_search_dir
      failed_when: not job_search_dir.stat.exists

    - name: Check .env file exists
      ansible.builtin.stat:
        path: /home/molecule/job-search/.env
      register: env_file
      failed_when: not env_file.stat.exists

    - name: Check api.env file exists
      ansible.builtin.stat:
        path: /home/molecule/job-search/api.env
      register: api_env_file
      failed_when: not api_env_file.stat.exists

    - name: Check crawler.env file exists
      ansible.builtin.stat:
        path: /home/molecule/job-search/crawler.env
      register: crawler_env_file
      failed_when: not crawler_env_file.stat.exists

    - name: Verify .env contains SERVICE_HOST
      ansible.builtin.command:
        cmd: grep -q 'SERVICE_HOST=' /home/molecule/job-search/.env
      changed_when: false

    - name: Verify api.env contains JWT_SECRET
      ansible.builtin.command:
        cmd: grep -q 'JWT_SECRET=test-jwt-secret-for-molecule' /home/molecule/job-search/api.env
      changed_when: false

    - name: Verify crawler.env contains SEARXNG_TOKEN
      ansible.builtin.command:
        cmd: grep -q 'SEARXNG_TOKEN=test-searxng-token-for-molecule' /home/molecule/job-search/crawler.env
      changed_when: false

    - name: Verify .env does not contain CLAUDE_API_KEY
      ansible.builtin.command:
        cmd: grep -rq 'CLAUDE_API_KEY' /home/molecule/job-search/
      register: claude_key_check
      changed_when: false
      failed_when: claude_key_check.rc == 0
```

- [ ] **Commit**

```bash
git add ansible/plays/roles/user_job_search/molecule/
git commit -m "test: add molecule scenario for user_job_search role"
```

---

### Task 8: Run Molecule tests locally on servyy-test

- [ ] **Run molecule test from the role directory**

```bash
cd ansible/plays/roles/user_job_search && molecule test
```

Expected: All steps pass, ending with `INFO     Verifier completed successfully.`

If molecule is not installed locally, run it on servyy-test:

```bash
ssh servyy-test.lxd "cd /home/cda/servyy-container && molecule test -s default" 
```

- [ ] **Commit any fixes needed**

```bash
git add -p
git commit -m "fix: correct molecule test issues"
```

---

### Task 9: Deploy to servyy-test and verify

- [ ] **Push to origin so the server can pull**

```bash
git push origin master
```

- [ ] **Deploy to servyy-test**

```bash
cd ansible && ./servyy-test.sh --tags "user.docker.job-search"
```

Expected: PLAY RECAP shows `failed=0`, `unreachable=0`.

- [ ] **Verify containers are running on servyy-test**

```bash
ssh servyy-test.lxd "docker ps | grep job-search"
```

Expected output (5 containers):
```
job-search-frontend   dachrisch/job-search-frontend:latest   ...   Up
job-search-api        dachrisch/job-search-api:latest        ...   Up (healthy)
job-search-crawler    dachrisch/job-search-crawler:latest    ...   Up (healthy)
job-search-mongodb    mongo:7.0                              ...   Up (healthy)
job-search-redis-app  redis:7-alpine                         ...   Up (healthy)
```

- [ ] **Verify env files were generated correctly**

```bash
ssh servyy-test.lxd "cat /home/cda/servyy-container/job-search/.env"
```

Expected:
```
SERVICE_HOST=job-search.servyy-test.lxd
SERVICE_NAME=job-search
TRAEFIK_ENTRYPOINT=web
TRAEFIK_TLS=false
TRAEFIK_CERTRESOLVER=
```

- [ ] **Verify frontend is reachable via Traefik**

```bash
curl -s -o /dev/null -w "%{http_code}" http://job-search.servyy-test.lxd/
```

Expected: `200`

- [ ] **Verify API health endpoint**

```bash
curl -s http://job-search.servyy-test.lxd/api/health
```

Expected: JSON response with `{"status":"ok"}` or similar.
