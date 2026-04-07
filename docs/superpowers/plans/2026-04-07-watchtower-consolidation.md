# Watchtower Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate all watchtower instances into two scoped instances in `portainer/docker-compose.yml` (`prod` at 2h, `dev` at 5min), removing standalone watchtowers from individual service directories.

**Architecture:** Each service declares its update scope via a `com.centurylinklabs.watchtower.scope` label. Two central watchtower instances in portainer watch for containers matching their scope — `prod` for stable third-party images, `dev` for actively developed personal images. No service other than portainer runs a watchtower container.

**Tech Stack:** Docker Compose, containrrr/watchtower

**Repos touched:**
- `/home/cda/dev/infrastructure/container` (portainer, groceries, energy, leagues-finance)
- `/home/cda/dev/leaguesphere` (deployed/docker-compose.staging.yaml)

---

### Task 1: Add `watchtower-dev` and rename `watchtower-prod` in portainer

**Files:**
- Modify: `portainer/docker-compose.yml`

- [ ] **Step 1: Rename existing `watchtower` service to `watchtower-prod` and update its container name**

In `portainer/docker-compose.yml`, change:
```yaml
  watchtower:
    restart: unless-stopped
    image: containrrr/watchtower
    container_name: ${COMPOSE_PROJECT_NAME}.watchtower
    labels:
      - traefik.enable=false
      - com.centurylinklabs.watchtower.scope=prod
    environment:
      # https://containrrr.dev/watchtower/arguments/
      WATCHTOWER_SCOPE: "prod"
      WATCHTOWER_CLEANUP: "true"
      WATCHTOWER_POLL_INTERVAL: 7200 # checks for updates every two hours
      WATCHTOWER_INCLUDE_RESTARTING: "true"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /etc/localtime:/etc/localtime:ro
```
To:
```yaml
  watchtower-prod:
    restart: unless-stopped
    image: containrrr/watchtower
    container_name: ${COMPOSE_PROJECT_NAME}.watchtower-prod
    labels:
      - traefik.enable=false
      - com.centurylinklabs.watchtower.scope=prod
    environment:
      WATCHTOWER_SCOPE: "prod"
      WATCHTOWER_CLEANUP: "true"
      WATCHTOWER_POLL_INTERVAL: 7200 # checks for updates every two hours
      WATCHTOWER_INCLUDE_RESTARTING: "true"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /etc/localtime:/etc/localtime:ro

  watchtower-dev:
    restart: unless-stopped
    image: containrrr/watchtower
    container_name: ${COMPOSE_PROJECT_NAME}.watchtower-dev
    labels:
      - traefik.enable=false
      - com.centurylinklabs.watchtower.scope=dev
    environment:
      WATCHTOWER_SCOPE: "dev"
      WATCHTOWER_CLEANUP: "true"
      WATCHTOWER_POLL_INTERVAL: 300 # checks for updates every 5 minutes
      WATCHTOWER_INCLUDE_RESTARTING: "true"
      TZ: "Europe/Berlin"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /etc/localtime:/etc/localtime:ro
```

- [ ] **Step 2: Validate compose syntax**

```bash
cd /home/cda/dev/infrastructure/container
docker compose -f portainer/docker-compose.yml config --quiet
```
Expected: no output (silent success)

- [ ] **Step 3: Commit**

```bash
git add portainer/docker-compose.yml
git commit -m "feat: add watchtower-dev to portainer, rename watchtower to watchtower-prod"
```

---

### Task 2: Remove standalone watchtower from `groceries`, change scope to `dev`

**Files:**
- Modify: `groceries/docker-compose.yml`

- [ ] **Step 1: Remove watchtower service and update scope label**

Remove the entire `watchtower:` service block from `groceries/docker-compose.yml`.

Change the `groceries` service label:
```yaml
      - com.centurylinklabs.watchtower.scope=groceries
```
To:
```yaml
      - com.centurylinklabs.watchtower.scope=dev
```

- [ ] **Step 2: Validate compose syntax**

```bash
cd /home/cda/dev/infrastructure/container
docker compose -f groceries/docker-compose.yml config --quiet
```
Expected: no output (silent success)

- [ ] **Step 3: Commit**

```bash
git add groceries/docker-compose.yml
git commit -m "chore: remove standalone watchtower from groceries, use dev scope"
```

---

### Task 3: Remove standalone watchtower from `energy`, change scope to `dev`

**Files:**
- Modify: `energy/docker-compose.yml`

- [ ] **Step 1: Remove watchtower service and update scope label**

Remove the entire `watchtower:` service block from `energy/docker-compose.yml`.

Change the `energy` service label:
```yaml
      - com.centurylinklabs.watchtower.scope=energy
```
To:
```yaml
      - com.centurylinklabs.watchtower.scope=dev
```

- [ ] **Step 2: Validate compose syntax**

```bash
cd /home/cda/dev/infrastructure/container
docker compose -f energy/docker-compose.yml config --quiet
```
Expected: no output (silent success)

- [ ] **Step 3: Commit**

```bash
git add energy/docker-compose.yml
git commit -m "chore: remove standalone watchtower from energy, use dev scope"
```

---

### Task 4: Add `dev` scope label to `leagues-finance`

**Files:**
- Modify: `leagues-finance/docker-compose.yml`

- [ ] **Step 1: Add watchtower scope label to the `app` service**

In `leagues-finance/docker-compose.yml`, the `app` service has no `labels:` block. Add one:
```yaml
  app:
    image: dachrisch/league.finance:latest
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
      - traefik.http.routers.${SERVICE_NAME}.tls.certresolver=letsencrypthttpresolver
      - traefik.http.routers.${SERVICE_NAME}.middlewares=crawler-ratelimit@file
      - com.centurylinklabs.watchtower.scope=dev
```

- [ ] **Step 2: Validate compose syntax**

```bash
cd /home/cda/dev/infrastructure/container
docker compose -f leagues-finance/docker-compose.yml config --quiet
```
Expected: no output (silent success)

- [ ] **Step 3: Commit**

```bash
git add leagues-finance/docker-compose.yml
git commit -m "feat: add dev watchtower scope to leagues-finance"
```

---

### Task 5: Remove standalone watchtower from leaguesphere staging, change scope to `dev`

**Files:**
- Modify: `/home/cda/dev/leaguesphere/deployed/docker-compose.staging.yaml`

Note: this is a **different git repository** (`/home/cda/dev/leaguesphere`). All git commands in this task run from there.

- [ ] **Step 1: Remove watchtower service block**

Remove the entire `watchtower:` service block from `deployed/docker-compose.staging.yaml` (lines 92–112).

- [ ] **Step 2: Change scope labels from `ls-staging` to `dev`**

Change all occurrences of:
```yaml
      - com.centurylinklabs.watchtower.scope=ls-staging
```
To:
```yaml
      - com.centurylinklabs.watchtower.scope=dev
```

There are 3 occurrences: on `www`, `app`, and the removed watchtower service (already gone after step 1 — so 2 remaining on `www` and `app`).

- [ ] **Step 3: Validate compose syntax**

```bash
cd /home/cda/dev/leaguesphere
docker compose -f deployed/docker-compose.staging.yaml config --quiet
```
Expected: no output (silent success)

- [ ] **Step 4: Commit**

```bash
cd /home/cda/dev/leaguesphere
git add deployed/docker-compose.staging.yaml
git commit -m "chore: remove standalone watchtower from staging, use dev scope"
```
