# leagues.finance Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the `leagues.finance` application into the `servyy-container` infrastructure, making it accessible at `finance.leaguesphere.app`.

**Architecture:** The application will be deployed as a Docker Compose project managed by Ansible. Traefik will handle SSL termination and routing. Secrets will be managed via `secrets.yml` and injected as environment variables.

**Tech Stack:** Ansible, Docker Compose v2, Traefik, Node.js, MongoDB.

---

### Task 1: Update Infrastructure Metadata and Secrets

**Files:**
- Modify: `ansible/plays/vars/secrets.yml`

- [ ] **Step 1: Add `leagues-finance` to the service list and define its secrets**

Add the service to the `docker.services` list and create a new `leagues_finance` block.

```yaml
# In ansible/plays/vars/secrets.yml

# 1. Update docker.services list:
docker:
  services:
    # ... existing services ...
    - name: Leagues Finance
      dir: leagues-finance
      depends: traefik

# 2. Add secret variables (using values from existing .env as defaults):
leagues_finance:
  google_client_id: "<REDACTED>"
  google_client_secret: "<REDACTED>"
  google_callback_url: "https://finance.leaguesphere.app/auth/google/callback"
  jwt_secret: "5f8a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f" # Example secure hex
  ls_db_host: "s207.goserver.host"
  ls_db_name: "web35_db8"
  ls_db_user: "web35_8"
  ls_db_password: "8iRaCetuqdAlgOB2"
```

- [ ] **Step 2: Commit changes**

```bash
git add ansible/plays/vars/secrets.yml
git commit -m "feat: add leagues-finance service and secrets to infrastructure"
```

### Task 2: Create Docker Compose Configuration

**Files:**
- Create: `leagues-finance/docker-compose.yml`

- [ ] **Step 1: Write `leagues-finance/docker-compose.yml`**

```yaml
services:
  app:
    image: dachrisch/leagues.finance:latest
    container_name: ${COMPOSE_PROJECT_NAME}.app
    restart: unless-stopped
    env_file:
      - .env
      - leagues-finance.env
    networks:
      - proxy
    labels:
      - traefik.http.routers.${SERVICE_NAME}.tls=true
      - traefik.http.routers.${SERVICE_NAME}.rule=Host(`finance.leaguesphere.app`)
      - traefik.http.routers.${SERVICE_NAME}.tls.certresolver=letsencryptdnsresolver
      - traefik.http.routers.${SERVICE_NAME}.middlewares=crawler-ratelimit@file
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/api/health"] # Update if app has different health endpoint
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 30s

  mongo:
    image: mongo:7
    container_name: ${COMPOSE_PROJECT_NAME}.mongo
    restart: unless-stopped
    volumes:
      - mongo_data:/data/db
    environment:
      MONGO_INITDB_DATABASE: leagues_finance
    networks:
      - proxy # Or a private network if isolation is preferred
    healthcheck:
      test: ["CMD", "mongosh", "--eval", "db.adminCommand('ping')"]
      interval: 10s
      timeout: 5s
      retries: 5

networks:
  proxy:
    external: true

volumes:
  mongo_data:
```

- [ ] **Step 2: Commit**

```bash
git add leagues-finance/docker-compose.yml
git commit -m "feat: add docker-compose configuration for leagues-finance"
```

### Task 3: Create Environment Template

**Files:**
- Create: `ansible/plays/roles/user/templates/leagues-finance.env.j2`

- [ ] **Step 1: Create the template file**

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
NODE_ENV=production
PORT=3000
```

- [ ] **Step 2: Commit**

```bash
git add ansible/plays/roles/user/templates/leagues-finance.env.j2
git commit -m "feat: add environment template for leagues-finance"
```

### Task 4: Update Ansible Environment Task

**Files:**
- Modify: `ansible/plays/roles/user/tasks/docker_repo_env.yml`

- [ ] **Step 1: Add task to generate the environment file**

Add the following block to the end of `ansible/plays/roles/user/tasks/docker_repo_env.yml`:

```yaml
- name: Create leagues-finance.env file for docker service
  template:
    src: leagues-finance.env.j2
    dest: "{{(docker.remote_dir, 'leagues-finance', 'leagues-finance.env') | path_join}}"
    mode: '0600'
    owner: "{{create_user}}"
  tags:
    - user.docker.env
    - user.docker.env.leagues-finance
```

- [ ] **Step 2: Commit**

```bash
git add ansible/plays/roles/user/tasks/docker_repo_env.yml
git commit -m "feat: add ansible task to deploy leagues-finance environment"
```

### Task 5: Verification on Test Environment

- [ ] **Step 1: Run Ansible for the test environment**

```bash
cd ansible
./servyy-test.sh --tags user.docker.env.leagues-finance,user.docker.services.start
```

- [ ] **Step 2: Verify service status in test container**

```bash
ssh servyy-test.lxd "docker ps | grep leagues-finance"
```

- [ ] **Step 3: Check application logs**

```bash
ssh servyy-test.lxd "docker logs leagues-finance.app"
```

### Task 6: Final Documentation and Cleanup

- [ ] **Step 1: Create History Entry**

Create `history/2026-04-06_leagues-finance-integration.md` with a summary of the changes and verification results.

- [ ] **Step 2: Final Commit**

```bash
git add history/2026-04-06_leagues-finance-integration.md
git commit -m "docs: document leagues-finance integration"
```
