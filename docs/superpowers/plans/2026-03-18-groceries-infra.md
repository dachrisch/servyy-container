# Groceries Service Infrastructure Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the groceries-order-tracking app as a deployed Docker service on the servyy platform and remove the defunct jobs service.

**Architecture:** Follows the energy service pattern exactly — a `docker-compose.yml` with a scoped watchtower, a `groceries.env.j2` Jinja2 template for secrets, an Ansible task to deploy that env file, and a `secrets.yml` entry with credentials. Jobs is removed from the services list and its directory deleted.

**Tech Stack:** Docker Compose, Traefik, Ansible (git-crypt encrypted files), Watchtower

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Create | `groceries/docker-compose.yml` | Service definition + watchtower |
| Create | `ansible/plays/roles/user/templates/groceries.env.j2` | Secrets template |
| Modify | `ansible/plays/roles/user/tasks/docker_repo_env.yml` | Deploy groceries.env on server |
| Modify | `ansible/plays/vars/secrets.yml` | Add groceries vars + services entry, remove jobs |
| Delete | `jobs/` | Remove defunct service |

---

### Task 1: Create groceries docker-compose.yml

**Files:**
- Create: `groceries/docker-compose.yml`

Reference: `energy/docker-compose.yml` — the groceries compose must follow the same structure (service + scoped watchtower).

- [ ] **Step 1: Create `groceries/docker-compose.yml`**

```yaml
services:
  groceries:
    image: dachrisch/groceries-order-tracking:latest
    container_name: ${COMPOSE_PROJECT_NAME}.groceries
    restart: unless-stopped
    env_file:
      - .env
      - groceries.env
    networks:
      - proxy
    labels:
      - traefik.http.routers.${SERVICE_NAME}.tls=true
      - traefik.http.routers.${SERVICE_NAME}.rule=Host(`${SERVICE_HOST}`)
      - traefik.http.routers.${SERVICE_NAME}.tls.certresolver=letsencryptdnsresolver
      - traefik.http.routers.${SERVICE_NAME}.middlewares=crawler-ratelimit@file
      - traefik.http.routers.${SERVICE_NAME}_local_qualified.rule=Host(`${SERVICE_NAME}.${LOCAL_HOSTNAME}`)
      - traefik.http.routers.${SERVICE_NAME}_local_qualified.entrypoints=web
      - com.centurylinklabs.watchtower.scope=groceries
    healthcheck:
      test: node healthcheck.js
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 30s

  watchtower:
    restart: unless-stopped
    image: containrrr/watchtower
    container_name: ${COMPOSE_PROJECT_NAME}.watchtower
    labels:
      - traefik.enable=false
      - com.centurylinklabs.watchtower.scope=groceries
    environment:
      WATCHTOWER_CLEANUP: "true"
      WATCHTOWER_POLL_INTERVAL: "600"
      WATCHTOWER_INCLUDE_RESTARTING: "true"
      WATCHTOWER_SCOPE: "groceries"
      TZ: "Europe/Berlin"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /etc/localtime:/etc/localtime:ro
    healthcheck:
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 120s

networks:
  proxy:
    external: true
```

- [ ] **Step 2: Verify docker-compose syntax**

```bash
cd groceries && docker compose config --quiet
```

Expected: no output (clean parse)

- [ ] **Step 3: Commit**

```bash
git add groceries/docker-compose.yml
git commit -m "feat: add groceries docker-compose service"
```

---

### Task 2: Create groceries.env Jinja2 template

**Files:**
- Create: `ansible/plays/roles/user/templates/groceries.env.j2`

Reference: `ansible/plays/roles/user/templates/energy.env.j2` — same pattern, different vars.

- [ ] **Step 1: Create `groceries.env.j2`**

```jinja
# Groceries service secrets
MONGODB_URI={{ groceries.mongodb_uri }}
JWT_SECRET={{ groceries.jwt_secret }}
```

- [ ] **Step 2: Commit**

```bash
git add ansible/plays/roles/user/templates/groceries.env.j2
git commit -m "feat: add groceries.env Jinja2 template"
```

---

### Task 3: Add groceries secrets and services entry, remove jobs

**Files:**
- Modify: `ansible/plays/vars/secrets.yml`

Note: this file is git-crypt encrypted. It appears as plaintext when the repo is unlocked (normal editing applies). Verify with `git-crypt status` if unsure.

- [ ] **Step 1: Add `groceries` var block to `secrets.yml`**

After the `energy:` block, add:

```yaml
groceries:
  mongodb_uri: "<MONGODB_URI from the groceries MongoDB Atlas cluster>"
  jwt_secret: "<a strong random secret, e.g. openssl rand -base64 32>"
```

Generate jwt_secret:
```bash
openssl rand -base64 32
```

- [ ] **Step 2: Add groceries to `docker.services` list in `secrets.yml`**

Append after the `energy` service entry:

```yaml
    - name: Groceries
      dir: groceries
      depends: traefik
```

- [ ] **Step 3: Remove jobs from `docker.services` list**

Delete the entire jobs entry:
```yaml
    - name: Job Management
      dir: jobs
      depends: traefik
      manual: {}
```

- [ ] **Step 4: Commit**

```bash
git add ansible/plays/vars/secrets.yml
git commit -m "feat: add groceries secrets, remove jobs service"
```

---

### Task 4: Add Ansible task to deploy groceries.env

**Files:**
- Modify: `ansible/plays/roles/user/tasks/docker_repo_env.yml`

Reference: the existing `energy.env` task at line 18 — add an identical block for groceries below it.

- [ ] **Step 1: Add groceries.env task to `docker_repo_env.yml`**

After the `opencode.env` block, add:

```yaml
- name: Create groceries.env file for docker service
  template:
    src: groceries.env.j2
    dest: "{{(docker.remote_dir, 'groceries', 'groceries.env') | path_join}}"
    mode: '0600'
    owner: "{{create_user}}"
  tags:
    - user.docker.env
    - user.docker.env.groceries
```

- [ ] **Step 2: Check playbook syntax**

```bash
cd ansible && ansible-playbook servyy.yml --syntax-check
```

Expected: `playbook: servyy.yml` with no errors.

- [ ] **Step 3: Commit**

```bash
git add ansible/plays/roles/user/tasks/docker_repo_env.yml
git commit -m "feat: deploy groceries.env via Ansible"
```

---

### Task 5: Delete jobs directory

**Files:**
- Delete: `jobs/`

- [ ] **Step 1: Delete jobs directory**

```bash
git rm -r jobs/
```

- [ ] **Step 2: Commit**

```bash
git commit -m "chore: remove defunct jobs service"
```

---

### Task 6: Test on servyy-test

- [ ] **Step 1: Spin up test container**

```bash
cd scripts && ./setup_test_container.sh
```

- [ ] **Step 2: Run Ansible against test env**

```bash
cd ansible && ./servyy-test.sh --tags "docker"
```

- [ ] **Step 3: Verify groceries container is running**

```bash
ssh servyy-test.lxd "docker ps | grep groceries"
```

Expected: `groceries.groceries` container Up

- [ ] **Step 4: Verify jobs is gone**

```bash
ssh servyy-test.lxd "docker ps -a | grep jobs"
```

Expected: no output

- [ ] **Step 5: Check groceries logs for startup errors**

```bash
ssh servyy-test.lxd "docker logs groceries.groceries --tail 30"
```

Expected: server started on port 3000, MongoDB connected

---

### Task 7: Request production deployment approval

- [ ] **Step 1: Show what will be deployed**

Summarise: groceries service added at `groceries.lehel.xyz`, jobs removed.

- [ ] **Step 2: Ask user for explicit production approval**

Do NOT deploy to production without explicit "yes, deploy to prod" from the user.

- [ ] **Step 3: Deploy to production (after approval)**

```bash
cd ansible && ./servyy.sh --tags "docker" --limit lehel.xyz
```

- [ ] **Step 4: Verify production**

```bash
ssh lehel.xyz "docker ps | grep groceries"
curl -I https://groceries.lehel.xyz
```
