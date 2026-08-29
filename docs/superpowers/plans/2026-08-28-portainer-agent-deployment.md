# Portainer Master/Slave Architecture Implementation Plan

**Goal:** Deploy Portainer Server (master: `servy.lehel.xyz`) + Agent (slave: `codey.lehel.xyz`) for secure container observability and restart capability across servers.

**Architecture:** Server on servy (49.13.6.173) exposed at `portainer.lehel.xyz` via Traefik. Agent on codey (217.217.227.124) at `a.codey.lehel.xyz` with IP-restricted access (server-only) and shared `AGENT_SECRET` auth. No raw host ports published.

**Tech Stack:** Portainer CE 2.x, Docker Compose, Ansible, Traefik, git-crypt

**Status:** Updated 2026-08-29 (automated RBAC, DNS validation, simplified)

## Quick Deployment Summary

| Aspect | Details |
|--------|---------|
| **Master** | servy.lehel.xyz (49.13.6.173) → `portainer.lehel.xyz` (Traefik) |
| **Slave** | codey.lehel.xyz (217.217.227.124) → `a.codey.lehel.xyz` (Traefik, IP-restricted) |
| **Services** | portainer (server) on lehel.xyz, portainer-agent on code.lehel.xyz |
| **DNS** | `*.lehel.xyz` → servy.lehel.xyz; `a.codey.lehel.xyz` → codey.lehel.xyz (new A/AAAA records) |
| **Auth** | Shared AGENT_SECRET (static, from secrets.yml) |
| **See Also** | CLAUDE.md: DNS management, SSH access, per-server deployment

## Constraints & Pre-Requisites

- Server: `lehel.xyz` (servy.lehel.xyz, 49.13.6.173) | Agent: `code.lehel.xyz` (codey.lehel.xyz, 217.217.227.124)
- Secrets encrypted with git-crypt; **keep offline backup of git-crypt key** (see Task 1, Step 2)
- Agent exposed at `a.codey.lehel.xyz` (A + AAAA records) with Traefik + Let's Encrypt SSL
- IP allowlist on agent route: only master (49.13.6.173) can access
- Container names: `portainer.server`, `portainer.agent`
- RBAC: admin (christian), leaguesphere team (Operator: observe + restart)
- Test on servyy-test.lxd before production
- Existing server (port 9000 UI + watchtower + ofelia) remains; only add agent to slave

---

### Task 1: Pre-Deployment Checklist

**Files:** None

**Step 1: Backup git-crypt key (CRITICAL)**

```bash
# Export the git-crypt key to a secure location (NOT in this repo)
# Store offline and distribute to team
git-crypt export-key ~/git-crypt-servyy-container.key

# Verify it works (on a fresh clone, after re-importing)
# git-crypt unlock ~/git-crypt-servyy-container.key
```

> **Why:** If the git-crypt key is lost, all encrypted files (`secrets.yml`, service `.env` files) become permanently unrecoverable. Store the key offline in a secure location (password manager, secure share with trusted team member, or HSM).

**Step 2: Review existing Portainer Server**

```bash
# Master already has portainer/ with server config (port 9000, Traefik at portainer.lehel.xyz)
# No changes needed; we only add the agent on the slave
ls portainer/docker-compose.yml
```

**Step 3: Ensure git status is clean**

```bash
git status  # Should show no uncommitted changes
```

---

### Task 2: Create .env Templates for Server & Agent

**Files:**
- Create/verify: `ansible/plays/roles/docker_service/templates/portainer/docker.env.j2`
- Create: `ansible/plays/roles/docker_service/templates/portainer-agent/docker.env.j2`

**Step 1: Portainer Server .env (master)**

```bash
mkdir -p ansible/plays/roles/docker_service/templates/portainer-agent
cat > ansible/plays/roles/docker_service/templates/portainer/docker.env.j2 << 'EOF'
COMPOSE_PROJECT_NAME=portainer
SERVICE_NAME=portainer
SERVICE_HOST=portainer.{{ inventory_hostname }}
PORTAINER_ADMIN_PASSWORD={{ portainer_admin_password }}
EOF
```

**Step 2: Portainer Agent .env (slave)**

```bash
cat > ansible/plays/roles/docker_service/templates/portainer-agent/docker.env.j2 << 'EOF'
COMPOSE_PROJECT_NAME=portainer
SERVICE_NAME=portainer-agent
SERVICE_HOST=a.codey.lehel.xyz
AGENT_SECRET={{ portainer_agent_secret }}
EOF
```

**Step 3: Commit**

```bash
git add ansible/plays/roles/docker_service/templates/portainer*/
git commit -m "feat: add portainer server and agent env templates"
```

---

### Task 3: Create Portainer Agent Directory & docker-compose.yml (Slave)

**Files:**
- Create: `portainer-agent/docker-compose.yml`
- Create: `portainer-agent/.gitignore`

**Step 1: Create directory and .gitignore**

```bash
mkdir -p portainer-agent
cat > portainer-agent/.gitignore << 'EOF'
.env
.env.local
*.key
*.crt
EOF
```

**Step 2: Create docker-compose.yml**

```yaml
# portainer-agent/docker-compose.yml
services:
  agent:
    image: portainer/agent:latest
    container_name: ${COMPOSE_PROJECT_NAME}.agent
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /var/lib/docker/volumes:/var/lib/docker/volumes
    environment:
      AGENT_PORT: "9001"
      AGENT_SECRET: ${AGENT_SECRET}
    networks:
      - proxy
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.${SERVICE_NAME}.rule=Host(`${SERVICE_HOST}`)"
      - "traefik.http.routers.${SERVICE_NAME}.entrypoints=websecure"
      - "traefik.http.routers.${SERVICE_NAME}.tls.certresolver=letsencryptdnsresolver"
      - "traefik.http.routers.${SERVICE_NAME}.middlewares=${SERVICE_NAME}-master-allow"
      - "traefik.http.middlewares.${SERVICE_NAME}-master-allow.ipallowlist.sourcerange=49.13.6.173/32"
      - "traefik.http.services.${SERVICE_NAME}.loadbalancer.server.port=9001"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9001", "--insecure"]
      interval: 30s
      timeout: 10s
      retries: 3

networks:
  proxy:
    external: true
```

**Step 3: Create DNS records**

Use `dns-master` agent to create A + AAAA for `a.codey.lehel.xyz`:
```
dns-master: "Create A + AAAA records for a.codey.lehel.xyz pointing to 217.217.227.124"
```

**Step 4: Commit**

```bash
git add portainer-agent/
git commit -m "feat: add portainer agent service (docker-compose + dns)"
```

---

### Task 4: Add Secrets & Register Services in Ansible

**Files:**
- Modify: `ansible/plays/vars/secrets.yml`
- Modify: `ansible/plays/user.yml`
- Modify: `ansible/production`

**Step 1: Add portainer secrets**

```bash
cd ansible
git-crypt unlock  # If locked
```

Add to `ansible/plays/vars/secrets.yml`:
```yaml
portainer_admin_password: "{{ 'change_me' | password_hash('bcrypt') }}"
portainer_agent_secret: "{{ lookup('pipe', 'openssl rand -hex 32') }}"
```

**Step 2: Register portainer-agent in user.yml**

Add to `ansible/plays/user.yml`:
```yaml
- role: docker_service
  vars:
    service_dir: portainer-agent
  when: "'portainer-agent' in (services | default([]))"
  tags: [user.docker, user.docker.portainer-agent]
```

**Step 3: Add to inventory**

Edit `ansible/production` — add to `code.lehel.xyz` → `services_enabled`:
```yaml
portainer-agent: true
```

**Step 4: Commit**

```bash
git add ansible/plays/vars/secrets.yml ansible/plays/user.yml ansible/production
git commit -m "feat: add portainer secrets and register agent in ansible"
```

---

### Task 5: Test on servyy-test.lxd

**Files:** None

**Step 1: Initialize & deploy**

```bash
cd scripts && ./setup_test_container.sh
cd ../ansible && ./servyy-test.sh --tags "user.docker"
```

**Step 2: Verify services**

```bash
ssh servyy-test.lxd "docker ps | grep portainer"
# Both portainer.server and portainer.agent should be running with status "healthy"
```

**Step 3: Check logs**

```bash
ssh servyy-test.lxd "docker logs portainer.server --tail 10"
ssh servyy-test.lxd "docker logs portainer.agent --tail 10"
```

> Note: Single-container test cannot validate cross-host connection; test that during production deployment (Tasks 6–7).

---

### Task 6: Validate DNS Before Production Deployment

**Files:** None

**Step 1: Verify DNS records**

```bash
# Check A + AAAA for agent endpoint
dig a.codey.lehel.xyz +short

# Expected output:
# 217.217.227.124       (A record)
# 2a01:8740:1:fa3::54ad (AAAA record)
```

**Step 2: Verify Let's Encrypt can reach the domain**

```bash
nslookup a.codey.lehel.xyz
curl -I https://a.codey.lehel.xyz 2>&1 | grep -i "tlsversion"
# Should complete without DNS or TLS errors
```

> If DNS fails, Let's Encrypt cert provisioning will fail silently during container startup.

---

### Task 7: Deploy to Production

**Files:** None

**Step 1: Deploy Portainer Server to master**

Ask user for approval, then:
```bash
cd ansible && ./servyy.sh --tags "user.docker.portainer" --limit lehel.xyz
```

Verify:
```bash
ssh lehel.xyz "docker ps | grep portainer.server"  # Should show "healthy"
curl -I https://portainer.lehel.xyz 2>&1 | head -5  # Should show HTTP 200/401
```

**Step 2: Deploy Portainer Agent to slave**

Ask user for approval, then:
```bash
cd ansible && ./servyy.sh --tags "user.docker.portainer-agent" --limit code.lehel.xyz
```

Verify:
```bash
ssh code.lehel.xyz "docker ps | grep portainer.agent"  # Should show "healthy"
ssh code.lehel.xyz "docker logs portainer.agent --tail 5"  # Check for connection errors
```

**Step 3: Validate cross-host connectivity**

From master, verify it can reach the agent via Traefik:
```bash
ssh lehel.xyz "curl -s -o /dev/null -w '%{http_code}\n' https://a.codey.lehel.xyz --insecure"
# Expect 200, 404, or 400 (not 502 or timeout)
```

---

### Task 8: Automate RBAC Configuration via Portainer API

**Files:**
- Create: `ansible/plays/roles/portainer_rbac/tasks/main.yml`
- Create: `ansible/plays/vars/portainer-rbac.yml`

**Step 1: Create RBAC configuration**

```bash
cat > ansible/plays/vars/portainer-rbac.yml << 'EOF'
portainer_rbac:
  teams:
    - name: leaguesphere
      description: LeagueSphere development team
  users:
    - username: alice
      password: "changeme123"  # User will change on first login
      team: leaguesphere
      role: operator
    - username: bob
      password: "changeme456"
      team: leaguesphere
      role: operator
EOF
```

**Step 2: Create Ansible playbook to register agent + configure RBAC**

```bash
mkdir -p ansible/plays/roles/portainer_rbac/tasks
cat > ansible/plays/roles/portainer_rbac/tasks/main.yml << 'EOF'
---
- name: Wait for Portainer API to be available
  uri:
    url: "https://portainer.lehel.xyz/api/status"
    method: GET
    validate_certs: false
    status_code: [200]
  retries: 30
  delay: 2

- name: Get Portainer auth token
  uri:
    url: "https://portainer.lehel.xyz/api/auth"
    method: POST
    body_format: json
    body:
      username: admin
      password: "{{ portainer_admin_password }}"
    validate_certs: false
  register: portainer_auth

- name: Register agent environment
  uri:
    url: "https://portainer.lehel.xyz/api/endpoints"
    method: POST
    headers:
      Authorization: "Bearer {{ portainer_auth.json.jwt }}"
    body_format: json
    body:
      Name: "codey.lehel.xyz"
      EndpointType: 2  # Agent
      URL: "https://a.codey.lehel.xyz"
      TLSConfig:
        TLS: false
      EdgeID: ""
      EdgeKey: ""
      EdgeAsyncMode: false
      EdgeCheckinInterval: 0
      PublicURL: ""
      GroupID: 1
    validate_certs: false
  register: endpoint_result

- name: Create team
  uri:
    url: "https://portainer.lehel.xyz/api/teams"
    method: POST
    headers:
      Authorization: "Bearer {{ portainer_auth.json.jwt }}"
    body_format: json
    body:
      Name: "{{ item.name }}"
      Description: "{{ item.description }}"
    validate_certs: false
  loop: "{{ portainer_rbac.teams }}"
  register: teams_result
  ignore_errors: true  # Team might already exist

- name: Create users and assign to team
  uri:
    url: "https://portainer.lehel.xyz/api/users"
    method: POST
    headers:
      Authorization: "Bearer {{ portainer_auth.json.jwt }}"
    body_format: json
    body:
      Username: "{{ item.username }}"
      Password: "{{ item.password }}"
      UserTheme: "auto"
      Role: 2  # Standard user
    validate_certs: false
  loop: "{{ portainer_rbac.users }}"
  ignore_errors: true  # User might already exist

- name: Configure endpoint access control
  uri:
    url: "https://portainer.lehel.xyz/api/endpoints/{{ endpoint_result.json.Id }}/access"
    method: POST
    headers:
      Authorization: "Bearer {{ portainer_auth.json.jwt }}"
    body_format: json
    body:
      Team: "{{ teams_result.results[0].json.Id }}"
      Role: 3  # Operator
    validate_certs: false
  ignore_errors: true
EOF
```

**Step 3: Register the playbook in plays/user.yml**

Add after docker_service tasks:
```yaml
- include_role:
    name: portainer_rbac
  when: "'portainer' in (services | default([]))"
  tags: [user, user.portainer-rbac]
```

**Step 4: Commit**

```bash
git add ansible/plays/roles/portainer_rbac/ ansible/plays/vars/portainer-rbac.yml
git commit -m "feat: automate portainer rbac configuration via api"
```

> **Manual fallback:** If API automation fails, log into UI at https://portainer.lehel.xyz (admin credentials from secrets.yml) and manually configure teams/users/permissions.

---

### Task 9: Documentation & Verification

**Files:**
- Create: `history/2026-08-29_portainer-master-slave-deployment.md`

**Step 1: Create deployment history**

```bash
cat > history/2026-08-29_portainer-master-slave-deployment.md << 'EOF'
# Portainer Master/Slave Deployment

**Date:** 2026-08-29 | **Status:** Complete

## What Was Deployed

- **Server:** servy.lehel.xyz (lehel.xyz) → portainer.lehel.xyz
- **Agent:** codey.lehel.xyz (code.lehel.xyz) → a.codey.lehel.xyz (IP-restricted to 49.13.6.173)
- **Auth:** Shared AGENT_SECRET (static, from secrets.yml)
- **RBAC:** Automated via Portainer API (leaguesphere team, Operator role)

## Architecture

```
portainer.lehel.xyz (Traefik) → Portainer Server (servy)
                                    ↓ HTTPS (a.codey.lehel.xyz)
                          Portainer Agent (codey, 9001)
                                    ↓ Unix socket
                            Docker daemon (codey)
```

## Verification

```bash
ssh lehel.xyz "docker ps | grep portainer"       # Server healthy?
ssh code.lehel.xyz "docker ps | grep portainer"  # Agent healthy?
ssh lehel.xyz "curl -k https://a.codey.lehel.xyz/api/agent/ping"  # Connected?
```

## Access

- URL: https://portainer.lehel.xyz
- Admin: admin (vault credentials)
- Team: leaguesphere (Operator: observe + restart)

## Cleanup (if needed)

```bash
ansible-playbook plays/remove_service.yml -e "target_host=code.lehel.xyz"  # portainer-agent
```
EOF
```

**Step 2: Final verification**

```bash
git status  # Should be clean
git log --oneline -10  # Review commits
```

**Step 3: Commit**

```bash
git add history/2026-08-29_portainer-master-slave-deployment.md
git commit -m "docs: add portainer deployment history"
```

---

## Plan Complete

8 tasks, simplified and ready for execution. Key improvements:
- ✅ Automated RBAC via Portainer API (not manual UI)
- ✅ Explicit DNS validation before production
- ✅ git-crypt key backup procedure (Task 1)
- ✅ Consolidated .env templates, secrets, and inventory into single commits
- ✅ Cleaner test/verify steps