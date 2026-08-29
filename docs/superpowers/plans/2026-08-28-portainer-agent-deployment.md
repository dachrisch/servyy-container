# Portainer Master/Slave Architecture Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run Portainer **Server** on the master host `servy.lehel.xyz` and a Portainer **Agent** on the slave host `codey.lehel.xyz`, giving the leaguesphere team secure container observability and restart capability across both servers from a single UI.

**Architecture:** Master/slave Portainer topology. The Portainer Server runs on `servy.lehel.xyz` (the primary server, 49.13.6.173) and is exposed via Traefik at `portainer.lehel.xyz` with Let's Encrypt SSL. The Portainer Agent runs on `codey.lehel.xyz` (the secondary server, 217.217.227.124) and listens on port 9001. The server connects to the agent using the shared `AGENT_SECRET`; the agent's Docker socket is never exposed to the public internet. All secrets are encrypted with git-crypt.

**Tech Stack:** Portainer CE 2.x, Docker Compose, Ansible (`docker_service` role), Traefik, git-crypt

**Spec:** Design approved in brainstorming session 2026-08-28, updated for the master/slave server layout on 2026-08-29.

## Server Layout (updated 2026-08-29)

The DNS infrastructure now separates physical servers from public service names:

| Role | Physical server | Public IP | Ansible inventory host | DNS record |
|------|----------------|-----------|------------------------|------------|
| **Master** | servy.lehel.xyz | 49.13.6.173 | `lehel.xyz` | `lehel.xyz` ALIAS → servy.lehel.xyz |
| **Slave** | codey.lehel.xyz | 217.217.227.124 | `code.lehel.xyz` | `code.lehel.xyz` CNAME → codey.lehel.xyz |

- `*.lehel.xyz` CNAME → `servy.lehel.xyz` (wildcard catches all service subdomains on the master, incl. `portainer.lehel.xyz`)
- Ansible inventory hostnames are unchanged (`lehel.xyz`, `code.lehel.xyz`) — they resolve to the physical servers via ALIAS/CNAME, so `servyy.sh --limit lehel.xyz` / `--limit code.lehel.xyz` work as-is.

## Global Constraints

- **Portainer Server** → master: `servy.lehel.xyz` (inventory host `lehel.xyz`)
- **Portainer Agent** → slave: `codey.lehel.xyz` (inventory host `code.lehel.xyz`)
- All services deployed via Ansible (`plays/user.yml` → `docker_service` role)
- All secrets encrypted with git-crypt (`.env` files, `secrets.yml`)
- Portainer Server exposed via Traefik at `portainer.lehel.xyz` with Let's Encrypt SSL
- Portainer Agent exposed via the slave's Traefik at `a.codey.lehel.xyz` with Let's Encrypt SSL (no raw host port published)
- Agent auth uses the shared `AGENT_SECRET` (standard Portainer agent model — no mTLS/self-signed CA)
- Traefik middleware `ipallowlist` on the agent router restricts access to the master's IP (`49.13.6.173`)
- Container naming: `{directory}.{service}` (e.g., `portainer.server`, `portainer.agent`)
- RBAC: christian (admin), leaguesphere team (operator: observe + restart)
- Test on servyy-test.lxd before production deployment
- Existing Portainer server on the master (port 9000 UI + watchtower + ofelia) is **kept**; this plan adds the agent on the slave and reconciles the server config only where needed

---

### Task 1: Reconcile Portainer Server Directory (Master)

**Files:**
- Review: `portainer/docker-compose.yml` (exists on master)
- Create (if missing): `portainer/.gitignore`

**Step 1: Review existing state**

The master already runs Portainer Server via `docker_service` (`portainer: true` in `services_enabled`, UI on port 9000, Traefik at `portainer.lehel.xyz`). It also hosts watchtower (prod/dev) and ofelia-scheduler. **Do not replace this file wholesale** — only adjust what the agent needs.

**Step 2: Confirm the server listens on the agent API port (8000) for future Edge support (optional)**

Standard agent mode requires **no** inbound listener on the server (the server dials the agent on 9001). Only if the Edge agent model is chosen later would `8000:8000` be needed. For this plan, **no server port change is required**.

**Step 3: Ensure `.gitignore` exists**

```bash
cat > portainer/.gitignore << 'EOF'
.env
.env.local
*.key
*.crt
portainer_data/
EOF
```

**Step 4: Verify compose syntax**

```bash
docker-compose -f portainer/docker-compose.yml config --quiet && echo "✓ Syntax valid"
```

**Step 5: Commit (if anything changed)**

```bash
git add portainer/
git commit -m "chore: reconcile portainer server config for master/slave layout"
```

---

### Task 2: Create Portainer Server .env Template

**Files:**
- Create: `ansible/plays/roles/docker_service/templates/portainer/docker.env.j2` (only if the master needs env vars beyond the existing `.env`; the existing server already has an env template — review first)

**Step 1: Check existing template**

```bash
ls ansible/plays/roles/docker_service/templates/portainer/
# If docker.env.j2 exists, review and extend it; otherwise create it.
```

**Step 2: Create/extend .env template**

```jinja2
# ansible/plays/roles/docker_service/templates/portainer/docker.env.j2
COMPOSE_PROJECT_NAME=portainer
SERVICE_NAME=portainer
SERVICE_HOST=portainer.{{ inventory_hostname }}   # portainer.lehel.xyz on the master

# Admin user password (bcrypt-hashed; Portainer rejects sha512)
PORTAINER_ADMIN_PASSWORD={{ portainer_admin_password }}
```

> Note: `inventory_hostname` on the master is `lehel.xyz`, so `SERVICE_HOST` becomes `portainer.lehel.xyz` — covered by the `*.lehel.xyz` wildcard to servy. No DNS change needed.

**Step 3: Commit**

```bash
git add ansible/plays/roles/docker_service/templates/portainer/
git commit -m "feat: add portainer server env template"
```

---

### Task 3: Create Portainer Agent Directory & docker-compose.yml (Slave)

**Files:**
- Create: `portainer-agent/docker-compose.yml`
- Create: `portainer-agent/.gitignore`

**Step 1: Create portainer-agent directory**

```bash
mkdir -p portainer-agent
```

**Step 2: Create .gitignore**

```bash
cat > portainer-agent/.gitignore << 'EOF'
.env
.env.local
*.key
*.crt
EOF
```

**Step 3: Create docker-compose.yml for the agent**

Standard Portainer agent: listens on `9001`, authenticated via shared `AGENT_SECRET`. The server (on servy) reaches it via the slave's Traefik at `a.codey.lehel.xyz` (TLS terminated by Traefik). **No host port is published** — Traefik routes on the `proxy` network.

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

> Security: the `ipallowlist` middleware restricts the agent route to the master IP (`49.13.6.173`), so the Docker API is not reachable from the public internet — only the Portainer Server on servy can connect. This replaces the raw-port + firewall approach.

**Step 4: Create the DNS entry `a.codey.lehel.xyz`**

Add a DNS record so the agent has a public name:

| Record | Type | Value | TTL |
|--------|------|-------|-----|
| a.codey.lehel.xyz | A | 217.217.227.124 | 600 |
| a.codey.lehel.xyz | AAAA | 2a01:8740:1:fa3::54ad | 600 |

Created via the `dns-master` agent (Porkbun API), e.g.:
```
dns-master: "Create A + AAAA records for a.codey.lehel.xyz pointing to codey.lehel.xyz"
```

**Step 5: Verify syntax**

```bash
docker-compose -f portainer-agent/docker-compose.yml config --quiet && echo "✓ Syntax valid"
```

**Step 6: Commit**

```bash
git add portainer-agent/
git commit -m "feat: add portainer agent docker-compose configuration"
```

---

### Task 4: Create Portainer Agent .env Template

**Files:**
- Create: `ansible/plays/roles/docker_service/templates/portainer-agent/docker.env.j2`

**Step 1: Create template directory**

```bash
mkdir -p ansible/plays/roles/docker_service/templates/portainer-agent
```

**Step 2: Create .env template**

```jinja2
# ansible/plays/roles/docker_service/templates/portainer-agent/docker.env.j2
COMPOSE_PROJECT_NAME=portainer
SERVICE_NAME=portainer-agent
SERVICE_HOST=a.codey.lehel.xyz

# Agent secret — must match the value entered in the Portainer UI
# when adding codey.lehel.xyz as an environment/endpoint.
AGENT_SECRET={{ portainer_agent_secret }}
```

> `SERVICE_HOST` is the public Traefik hostname for the agent (`a.codey.lehel.xyz`), substituted into the Traefik router labels. The agent does **not** need a server address in standard agent mode; the server reaches the agent. (An Edge agent would instead need `EDGE=1` + server URL — not used here.)

**Step 3: Commit**

```bash
git add ansible/plays/roles/docker_service/templates/portainer-agent/
git commit -m "feat: add portainer agent env template"
```

---

### Task 5: Integrate Portainer Agent into the Existing Docker Service Role

**Files:**
- Modify: `ansible/plays/roles/user/tasks/docker_extras.yml` (if extra setup needed for the agent host)
- Modify: `ansible/plays/user.yml` (register the `portainer-agent` service with `docker_service`)

**Step 1: Register `portainer-agent` in user.yml**

Add a `docker_service` role entry for the agent (mirrors the existing `portainer` entry):

```yaml
    - role: docker_service
      vars:
        service_dir: portainer-agent
        env_templates:
          - src: docker.env.j2
            dest: .env
          - src: portainer-agent/docker.env.j2
            dest: portainer-agent.env
      when: "'portainer-agent' in (services | default([]))"
      tags: [user.docker, user.docker.portainer-agent]
```

**Step 2: Verify the agent's Traefik labels are consistent with existing services**

The `docker_service` role renders the generic `docker.env.j2` (which sets `SERVICE_HOST={{ service_host }}`), so the agent env template only needs to carry `AGENT_SECRET`. Ensure the compose uses `${SERVICE_NAME}` / `${SERVICE_HOST}` from the `.env` (as in the Task 3 compose) so `docker_service` fills them in automatically.

**Step 3: Commit**

```bash
git add ansible/plays/user.yml
git commit -m "feat: register portainer-agent service in docker_service role"
```

---

### Task 6: Add Portainer Secrets to git-crypt Encrypted Vault

**Files:**
- Modify: `ansible/plays/vars/secrets.yml` (git-crypt encrypted)

**Step 1: Ensure the secrets file is unlocked**

```bash
cd ansible && git-crypt status | grep secrets.yml
# If locked: git-crypt unlock
```

**Step 2: Add portainer secrets**

```yaml
# Admin password for Portainer (change after first login).
# Portainer accepts a plaintext or bcrypt hash — NOT sha512.
vault_portainer_admin_password: "{{ 'initial_password_change_me' | password_hash('bcrypt') }}"

# Agent secret — a static random string shared by server UI + agent env.
# Generate once: openssl rand -hex 32, then store the literal value here.
vault_portainer_agent_secret: "CHANGE_ME_RANDOM_HEX_32"
```

> The original plan used `lookup('password', '/dev/null ...')` at role-eval time — that is non-deterministic and breaks idempotency. Use a static value instead.

**Step 3: Verify encryption after commit**

```bash
git-crypt status secrets.yml   # Should show "encrypted"
```

**Step 4: Commit**

```bash
git add ansible/plays/vars/secrets.yml
git commit -m "feat: add portainer secrets to vault"
```

---

### Task 7: Integrate Portainer into Ansible Inventory & Deployment

**Files:**
- Modify: `ansible/production`
- Modify: `ansible/plays/user.yml`

**Step 1: Confirm master inventory entry (already present)**

`ansible/production` already has `portainer: true` under `lehel.xyz` → `services_enabled`. Keep it.

**Step 2: Add Portainer Agent to slave inventory**

Edit `ansible/production` — add `portainer-agent: true` under `code.lehel.xyz` → `services_enabled`:

```yaml
    code.lehel.xyz:
        with_docker: true
        with_containers: true
        has_10g_volume: false
        create_swap: true
        ansible_user: root
        services_enabled:
          traefik: true
          opencode: true
          opencode-authgate: true
          portainer-agent: true   # ← Add this
```

**Step 3: Confirm both services render**

```bash
cd ansible && ansible-playbook servyy.yml --syntax-check -i production
```

**Step 4: Commit**

```bash
git add ansible/production ansible/plays/user.yml
git commit -m "feat: integrate portainer-agent into ansible deployment"
```

---

### Task 8: Test Deployment on servyy-test.lxd

**Files:**
- No new files

**Step 1: Syntax check**

```bash
cd ansible && ansible-playbook servyy.yml --syntax-check
```

**Step 2: Initialize test environment**

```bash
cd scripts && ./setup_test_container.sh
```

**Step 3: Deploy to test**

```bash
cd ../ansible && ./servyy-test.sh --tags "docker"
```

**Step 4: Verify Portainer Server on test**

```bash
ssh servyy-test.lxd "docker ps | grep portainer"
ssh servyy-test.lxd "docker logs portainer.server --tail 20"
```

**Step 5: Verify Portainer Agent on test (if deployed)**

```bash
ssh servyy-test.lxd "docker logs portainer.agent --tail 20"
```

**Step 6: Verify health checks pass**

```bash
ssh servyy-test.lxd "docker ps --format 'table {{.Names}}\t{{.Status}}' | grep portainer"
```

> Note: a single `servyy-test.lxd` container cannot fully validate the cross-host master/slave connection. Do that during the production rollout (Tasks 9–10).

---

### Task 9: Deploy Portainer Server to Production (Master: servy.lehel.xyz)

**Files:**
- No new files

**Step 1: Get user approval**

Ask user: "Ready to ensure Portainer Server is live on servy.lehel.xyz (master, inventory `lehel.xyz`)? Exposed at https://portainer.lehel.xyz via Traefik. Approve? (y/n)"

**Step 2: Deploy to master only**

```bash
cd ansible && ./servyy.sh --tags "user.docker.portainer" --limit lehel.xyz
```

**Step 3: Wait for deployment and health check**

```bash
ssh lehel.xyz "docker ps -a | grep portainer"
# Wait for "healthy" status
```

**Step 4: Verify Traefik routing**

```bash
curl -I https://portainer.lehel.xyz 2>&1 | head -5
# Should show: HTTP/2 200 or 401/403 (auth required)
```

**Step 5: Verify certificate**

```bash
echo | openssl s_client -servername portainer.lehel.xyz -connect portainer.lehel.xyz:443 2>/dev/null | grep -A 2 "Issuer:"
# Should show Let's Encrypt certificate
```

---

### Task 10: Deploy Portainer Agent to Production (Slave: codey.lehel.xyz)

**Files:**
- No new files

**Step 1: Get user approval**

Ask user: "Ready to deploy Portainer Agent to codey.lehel.xyz (slave, inventory `code.lehel.xyz`)? The agent is exposed via Traefik at `a.codey.lehel.xyz` (Let's Encrypt, IP-restricted to the master) and registered in the Portainer UI with the shared agent secret. Approve? (y/n)"

**Step 2: Deploy agent to slave**

```bash
cd ansible && ./servyy.sh --tags "user.docker.portainer-agent" --limit code.lehel.xyz
```

**Step 3: Verify agent container is running**

```bash
ssh code.lehel.xyz "docker ps | grep portainer.agent"
# Should show "healthy"
```

**Step 4: Verify agent listens on 9001 (container-internal)**

```bash
ssh code.lehel.xyz "docker exec portainer.agent sh -c 'wget -qO- http://localhost:9001' | head -1"
```

**Step 5: Verify Traefik routing + TLS on the agent host**

```bash
ssh code.lehel.xyz "curl -s -o /dev/null -w '%{http_code}\n' https://a.codey.lehel.xyz --insecure"
# Expect a response proving Traefik reaches the agent (e.g. 404/400 from the agent API)
```

**Step 6: Verify Let's Encrypt certificate for `a.codey.lehel.xyz`**

```bash
echo | openssl s_client -servername a.codey.lehel.xyz -connect a.codey.lehel.xyz:443 2>/dev/null | grep -A 2 "Issuer:"
# Should show Let's Encrypt certificate
```

---

### Task 11: Register Slave Agent in Portainer UI & Configure RBAC

**Files:**
- No new files (UI configuration)

**Step 1: Access Portainer Web UI**

Navigate to: https://portainer.lehel.xyz

**Step 2: Login with admin**

Username: `admin`
Password: (use `vault_portainer_admin_password` from secrets.yml)

**Step 3: Add the slave environment**

- Go to: **Environments** → **Add environment**
- Choose **Docker Standalone** → **Agent**
- Name: `codey.lehel.xyz`
- Agent URL: `a.codey.lehel.xyz:443` (Traefik TLS termination on the slave; the agent itself stays on 9001 internally)
- Shared agent secret: `vault_portainer_agent_secret`
- Click **Connect**

**Step 4: Create team "leaguesphere"**

- Go to: Settings → Teams → Add Team
- Name: `leaguesphere`
- Description: LeagueSphere development team
- Click Create

**Step 5: Create users for team members**

- Go to: Settings → Users → Add User
- For each team member (1-4 people):
  - Username: (their name or email prefix)
  - Password: (auto-generate, they change on first login)
  - Team: `leaguesphere`
  - Role: `Operator` (can view and restart containers)
  - Click Create

**Step 6: Configure endpoint permissions**

- Go to: **Environments** → `codey.lehel.xyz`
- Access Control → Restrict access
- Add team: `leaguesphere` with `Operator` role
- Save

**Step 7: Verify permissions**

- Logout and login as a team member
- Should see both `lehel.xyz` (via server) and `codey.lehel.xyz` (via agent)
- Should be able to restart containers
- Should NOT be able to deploy or delete

**Step 8: Document credentials**

Create a note (or add to your password manager):
- Portainer URL: https://portainer.lehel.xyz
- Admin username: admin
- Team: leaguesphere (team members added above)
- Permissions: Operator (observe, restart only)

---

### Task 12: Create Documentation

**Files:**
- Create: `history/2026-08-29_portainer-master-slave-deployment.md`

**Step 1: Create history log**

```markdown
# Portainer Master/Slave Architecture Deployment

**Date:** 2026-08-29
**Deployed by:** claude
**Status:** Ready for deployment

## What Will Be Deployed

- **Portainer Server** on servy.lehel.xyz (master, inventory `lehel.xyz`)
  - Exposed: https://portainer.lehel.xyz (via Traefik, wildcard *.lehel.xyz)
  - SSL: Let's Encrypt (via Traefik)
  - Admin user: local account
  - Team: leaguesphere (1-4 members, Operator role)

- **Portainer Agent** on codey.lehel.xyz (slave, inventory `code.lehel.xyz`)
  - Exposed via slave Traefik at https://a.codey.lehel.xyz (Let's Encrypt)
  - IP-restricted to master (49.13.6.173) via Traefik ipallowlist middleware
  - Auth via shared AGENT_SECRET
  - Docker socket never exposed to the public internet

## Architecture

```
Internet → Traefik (portainer.lehel.xyz) → Portainer Server (servy.lehel.xyz)
                                              ↓ HTTPS (a.codey.lehel.xyz, AGENT_SECRET)
                                        Traefik (codey.lehel.xyz) → Portainer Agent (9001)
                                              ↓ (Unix socket)
                                        Docker daemon (codey.lehel.xyz)
```

## Implementation Process

1. Reconcile portainer/ server config on master (already deployed)
2. Create portainer-agent/ service directory + .env template
3. Register portainer-agent in docker_service role + inventory
4. Add secrets to git-crypt vault (bcrypt admin password, static agent secret)
5. Test on servyy-test.lxd
6. Deploy/verify Portainer Server on servy.lehel.xyz
7. Deploy Portainer Agent on codey.lehel.xyz
8. Register slave environment in UI with AGENT_SECRET
9. Configure RBAC: admin user + leaguesphere team with Operator role

## Verification Commands

**Check Portainer Server health:**
```bash
ssh lehel.xyz "docker ps | grep portainer"
ssh lehel.xyz "curl -k https://localhost:9443/api/status"
```

**Check Portainer Agent health:**
```bash
ssh code.lehel.xyz "docker ps | grep portainer.agent"
ssh code.lehel.xyz "docker logs portainer.agent --tail 20"
```

**Verify cross-host connectivity:**
```bash
ssh lehel.xyz "curl -s -o /dev/null -w '%{http_code}\n' https://a.codey.lehel.xyz --insecure"
```

## Access

- **URL:** https://portainer.lehel.xyz
- **Admin user:** admin (credentials in vault)
- **Team:** leaguesphere (observability + restart)
- **Team members:** 1-4 people with Operator role

## Rollback (if needed)

```bash
# Remove the agent from the slave:
ansible-playbook plays/remove_service.yml -e "target_host=code.lehel.xyz"  # portainer-agent
# Keep the server on the master (or remove via remove_service.yml on lehel.xyz)
```

## Notes

- Standard Portainer agent model — the server reaches the agent via Traefik (`a.codey.lehel.xyz`) with the shared secret
- Agent route IP-restricted to the master via Traefik ipallowlist middleware (49.13.6.173)
- RBAC configured in Portainer UI (not code-driven) — can be modified per team preference
- All secrets encrypted with git-crypt (admin password, agent secret)
```

**Step 2: Commit**

```bash
git add history/2026-08-29_portainer-master-slave-deployment.md
git commit -m "docs: add portainer master/slave deployment history"
```

---

### Task 13: Final Verification & Cleanup

**Files:**
- No new files

**Step 1: Verify git status**

```bash
git status  # Should be clean
```

**Step 2: Review all commits**

```bash
git log --oneline -10  # Show all commits from this plan
```

---

## Plan Complete

All tasks documented and ready for execution.