# Portainer Agent Architecture Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deploy Portainer Server on lehel.xyz with Portainer Agent on code.lehel, enabling secure remote container observability and restart capabilities for the leaguesphere team.

**Architecture:** Portainer Server runs on lehel.xyz exposed via Traefik (portainer.lehel.xyz) with SSL. Portainer Agent on code.lehel connects outbound via mTLS tunnel to the server's agent API. No inbound ports on code.lehel. All secrets (API tokens, TLS certs, passwords) encrypted via git-crypt.

**Tech Stack:** Portainer CE 2.x, Docker Compose, Ansible, Traefik, git-crypt, self-signed CA

**Spec:** Design approved in brainstorming session 2026-08-28

## Global Constraints

- All services deployed via Ansible (plays/user.yml)
- All secrets encrypted with git-crypt (docker-compose.yml, .env files)
- Portainer Server exposed via Traefik at `portainer.lehel.xyz` with Let's Encrypt SSL
- Agent uses mTLS (self-signed CA cert + client cert) for server communication
- Container naming: `{directory}.{service}` (e.g., `portainer.server`, `portainer.agent`)
- RBAC: christian (admin), leaguesphere team (operator: observe + restart)
- Test on servyy-test.lxd before production deployment

---

### Task 1: Create Portainer Server Directory & docker-compose.yml

**Files:**
- Create: `portainer/docker-compose.yml`
- Create: `portainer/.gitignore`

**Step 1: Create portainer directory structure**

```bash
mkdir -p portainer
cd portainer
```

**Step 2: Create .gitignore**

```bash
cat > .gitignore << 'EOF'
.env
.env.local
*.key
*.crt
portainer_data/
EOF
```

**Step 3: Create docker-compose.yml**

```yaml
# portainer/docker-compose.yml
version: '3.8'

services:
  server:
    image: portainer/portainer-ce:latest
    container_name: ${COMPOSE_PROJECT_NAME}.server
    restart: unless-stopped
    ports:
      - "8000:8000"  # Agent API (internal, will use TLS)
      - "9443:9443"  # Web UI (internal, proxied via Traefik)
    volumes:
      - portainer_data:/data
      - /var/run/docker.sock:/var/run/docker.sock
      - ./certs:/certs:ro  # TLS certs for agent communication
    environment:
      PORTAINER_ADMIN_PASSWORD: ${PORTAINER_ADMIN_PASSWORD}
      PORTAINER_EDGE_COMPUTE: "false"
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.${SERVICE_NAME}.rule=Host(`${SERVICE_HOST}`)"
      - "traefik.http.routers.${SERVICE_NAME}.entrypoints=websecure"
      - "traefik.http.routers.${SERVICE_NAME}.tls.certresolver=letsencryptdnsresolver"
      - "traefik.http.services.${SERVICE_NAME}.loadbalancer.server.port=9443"
      - "traefik.http.services.${SERVICE_NAME}.loadbalancer.server.scheme=https"
    networks:
      - proxy
    healthcheck:
      test: ["CMD", "curl", "-f", "https://localhost:9443", "--insecure"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  portainer_data:
    driver: local

networks:
  proxy:
    external: true
```

**Step 4: Verify docker-compose syntax**

```bash
docker-compose config --resolve-image-digests > /dev/null && echo "✓ Syntax valid"
```

**Step 5: Commit**

```bash
git add portainer/docker-compose.yml portainer/.gitignore
git commit -m "feat: add portainer server docker-compose configuration"
```

---

### Task 2: Create Portainer Server .env Template

**Files:**
- Create: `ansible/plays/roles/docker_service/templates/portainer/docker.env.j2`

**Step 1: Create template directory**

```bash
mkdir -p ansible/plays/roles/docker_service/templates/portainer
```

**Step 2: Create .env template**

```jinja2
# ansible/plays/roles/docker_service/templates/portainer/docker.env.j2
COMPOSE_PROJECT_NAME=portainer
SERVICE_NAME=portainer
SERVICE_HOST=portainer.{{ inventory_hostname }}

# Admin user password (will be hashed by Portainer on first run)
# Change this before first deployment and use Portainer UI to create additional users
PORTAINER_ADMIN_PASSWORD={{ portainer_admin_password }}
```

**Step 3: Commit**

```bash
git add ansible/plays/roles/docker_service/templates/portainer/
git commit -m "feat: add portainer server env template"
```

---

### Task 3: Create Portainer Agent Directory & docker-compose.yml

**Files:**
- Create: `portainer-agent/docker-compose.yml`
- Create: `portainer-agent/.gitignore`

**Step 1: Create portainer-agent directory**

```bash
mkdir -p portainer-agent
cd portainer-agent
```

**Step 2: Create .gitignore**

```bash
cat > .gitignore << 'EOF'
.env
.env.local
*.key
*.crt
EOF
```

**Step 3: Create docker-compose.yml for agent**

```yaml
# portainer-agent/docker-compose.yml
version: '3.8'

services:
  agent:
    image: portainer/agent:latest
    container_name: ${COMPOSE_PROJECT_NAME}.agent
    restart: unless-stopped
    ports:
      - "9001:9001"  # Internal communication only
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /var/lib/docker/volumes:/var/lib/docker/volumes
      - ./certs:/certs:ro  # TLS certs for secure communication
    environment:
      AGENT_PORT: "9001"
      AGENT_SECRET: ${AGENT_SECRET}
      # Server connection (outbound)
      PORTAINER_SERVER: ${PORTAINER_SERVER}
      PORTAINER_SERVER_CERT_PATH: /certs/server-cert.pem
    networks:
      - default
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9001", "--insecure"]
      interval: 30s
      timeout: 10s
      retries: 3
```

**Step 4: Verify syntax**

```bash
docker-compose config > /dev/null && echo "✓ Syntax valid"
```

**Step 5: Commit**

```bash
git add portainer-agent/docker-compose.yml portainer-agent/.gitignore
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

# Agent secret (must match on server side during environment add)
AGENT_SECRET={{ portainer_agent_secret }}

# Portainer Server endpoint (server hostname/IP)
PORTAINER_SERVER=portainer.lehel.xyz:8000
```

**Step 3: Commit**

```bash
git add ansible/plays/roles/docker_service/templates/portainer-agent/
git commit -m "feat: add portainer agent env template"
```

---

### Task 5: Create Portainer Server Ansible Role

**Files:**
- Create: `ansible/plays/roles/portainer_server/tasks/main.yml`
- Create: `ansible/plays/roles/portainer_server/tasks/init.yml`
- Create: `ansible/plays/roles/portainer_server/templates/admin-init.json.j2`
- Create: `ansible/plays/roles/portainer_server/defaults/main.yml`

**Step 1: Create role directory structure**

```bash
mkdir -p ansible/plays/roles/portainer_server/{tasks,templates,defaults}
```

**Step 2: Create defaults/main.yml**

```yaml
# ansible/plays/roles/portainer_server/defaults/main.yml
---
service_dir: portainer
portainer_admin_username: admin
portainer_admin_password: "{{ vault_portainer_admin_password }}"
portainer_agent_secret: "{{ vault_portainer_agent_secret }}"
```

**Step 3: Create tasks/init.yml (certificate generation)**

```yaml
# ansible/plays/roles/portainer_server/tasks/init.yml
---
- name: Create certs directory
  file:
    path: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}/certs"
    state: directory
    mode: '0700'
  register: certs_dir

- name: Generate self-signed CA key (for agent verification)
  openssl_privatekey:
    path: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}/certs/ca-key.pem"
    size: 2048
  when: certs_dir.changed

- name: Generate self-signed CA cert
  openssl_certificate:
    path: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}/certs/ca-cert.pem"
    privatekey_path: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}/certs/ca-key.pem"
    provider: selfsigned
    common_name: portainer-ca
  when: certs_dir.changed

- name: Generate server cert request
  openssl_csr:
    path: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}/certs/server.csr"
    privatekey_path: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}/certs/ca-key.pem"
    common_name: "portainer.{{ inventory_hostname }}"
    subject_alt_name:
      - "DNS:portainer.{{ inventory_hostname }}"
      - "DNS:localhost"
      - "IP:127.0.0.1"
  when: certs_dir.changed

- name: Sign server certificate with CA
  openssl_certificate:
    path: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}/certs/server-cert.pem"
    csr_path: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}/certs/server.csr"
    ownca_path: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}/certs/ca-cert.pem"
    ownca_privatekey_path: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}/certs/ca-key.pem"
    provider: ownca
    mode: '0644'
  when: certs_dir.changed

- name: Copy CA cert to portainer container mount (for agents)
  copy:
    src: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}/certs/ca-cert.pem"
    dest: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}/certs/ca-cert.pem"
    mode: '0644'
    remote_src: yes
```

**Step 4: Create tasks/main.yml**

```yaml
# ansible/plays/roles/portainer_server/tasks/main.yml
---
- name: Initialize certificates if needed
  include_tasks: init.yml
  tags: [portainer.certs]

- name: Ensure service directory exists
  file:
    path: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}"
    state: directory
    mode: '0755'

- name: Deploy docker-compose.yml
  copy:
    src: "{{ playbook_dir }}/../../{{ service_dir }}/docker-compose.yml"
    dest: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}/docker-compose.yml"
    mode: '0644'

- name: Template .env file (git-crypt encrypted)
  template:
    src: portainer/docker.env.j2
    dest: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}/.env"
    mode: '0600'
  vars:
    portainer_admin_password: "{{ portainer_admin_password }}"

- name: Deploy Portainer Server
  community.docker.docker_compose:
    project_src: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}"
    state: present
    pull: yes
  environment:
    COMPOSE_PROJECT_NAME: portainer
    SERVICE_NAME: portainer
    SERVICE_HOST: "portainer.{{ inventory_hostname }}"
  register: portainer_deploy

- name: Wait for Portainer to be healthy
  uri:
    url: "https://localhost:9443/api/status"
    validate_certs: no
  retries: 10
  delay: 5
  until: result.status == 200
  register: result
```

**Step 5: Create admin-init.json template (for future user setup)**

```jinja2
# ansible/plays/roles/portainer_server/templates/admin-init.json.j2
{
  "Username": "{{ portainer_admin_username }}",
  "Password": "{{ portainer_admin_password }}"
}
```

**Step 6: Commit**

```bash
git add ansible/plays/roles/portainer_server/
git commit -m "feat: add portainer server ansible role"
```

---

### Task 6: Create Portainer Agent Ansible Role

**Files:**
- Create: `ansible/plays/roles/portainer_agent/tasks/main.yml`
- Create: `ansible/plays/roles/portainer_agent/defaults/main.yml`

**Step 1: Create role directory structure**

```bash
mkdir -p ansible/plays/roles/portainer_agent/{tasks,defaults}
```

**Step 2: Create defaults/main.yml**

```yaml
# ansible/plays/roles/portainer_agent/defaults/main.yml
---
service_dir: portainer-agent
portainer_server: "portainer.lehel.xyz:8000"
portainer_agent_secret: "{{ vault_portainer_agent_secret }}"
portainer_server_ca_cert: "{{ lookup('file', playbook_dir + '/../../portainer/certs/ca-cert.pem') }}"
```

**Step 3: Create tasks/main.yml**

```yaml
# ansible/plays/roles/portainer_agent/tasks/main.yml
---
- name: Ensure service directory exists
  file:
    path: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}"
    state: directory
    mode: '0755'

- name: Ensure certs directory exists
  file:
    path: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}/certs"
    state: directory
    mode: '0700'

- name: Copy server CA certificate to agent (for TLS verification)
  copy:
    content: "{{ portainer_server_ca_cert }}"
    dest: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}/certs/server-cert.pem"
    mode: '0644'

- name: Deploy docker-compose.yml
  copy:
    src: "{{ playbook_dir }}/../../{{ service_dir }}/docker-compose.yml"
    dest: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}/docker-compose.yml"
    mode: '0644'

- name: Template .env file (git-crypt encrypted)
  template:
    src: portainer-agent/docker.env.j2
    dest: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}/.env"
    mode: '0600'
  vars:
    portainer_agent_secret: "{{ portainer_agent_secret }}"
    portainer_server: "{{ portainer_server }}"

- name: Deploy Portainer Agent
  community.docker.docker_compose:
    project_src: "{{ ansible_user_dir }}/servyy-container/{{ service_dir }}"
    state: present
    pull: yes
  environment:
    COMPOSE_PROJECT_NAME: portainer
    SERVICE_NAME: portainer-agent

- name: Wait for agent to be healthy
  uri:
    url: "http://localhost:9001"
  retries: 10
  delay: 5
  until: result.status == 200
  register: result
```

**Step 4: Commit**

```bash
git add ansible/plays/roles/portainer_agent/
git commit -m "feat: add portainer agent ansible role"
```

---

### Task 7: Add Portainer Secrets to Ansible Vault

**Files:**
- Modify: `ansible/plays/vars/secrets.yml` (git-crypt encrypted)

**Step 1: Check current secrets structure**

```bash
cd ansible/plays/vars && git-crypt status | grep secrets.yml
```

**Step 2: Add portainer secrets (unlocked)**

Edit `ansible/plays/vars/secrets.yml` and add:

```yaml
# Admin password for Portainer (change after first login)
vault_portainer_admin_password: "{{ 'initial_password_change_me' | password_hash('sha512') }}"

# Agent secret (random string, kept consistent across deployments)
vault_portainer_agent_secret: "{{ lookup('password', '/dev/null length=32 chars=ascii_letters,digits') }}"
```

**Step 3: Verify encryption (should show as binary after save)**

```bash
git-crypt status secrets.yml  # Should show as encrypted
```

**Step 4: Commit**

```bash
git add ansible/plays/vars/secrets.yml
git commit -m "feat: add portainer secrets to vault"
```

---

### Task 8: Integrate Portainer into Ansible Deployment

**Files:**
- Modify: `ansible/plays/user.yml`
- Modify: `ansible/production`

**Step 1: Add Portainer Server to lehel.xyz inventory**

Edit `ansible/production` and add under `lehel.xyz` services_enabled:

```yaml
lehel.xyz:
  services_enabled:
    traefik: true
    monitor: true
    portainer: true  # ← Add this
    # ... other services
```

**Step 2: Add Portainer Agent to code.lehel inventory**

Edit `ansible/production` and add under `code.lehel` services_enabled:

```yaml
code.lehel:
  services_enabled:
    opencode: true
    portainer_agent: true  # ← Add this
```

**Step 3: Add Portainer Server role invocation to user.yml**

Edit `ansible/plays/user.yml` and add (after traefik, before other services):

```yaml
- name: Deploy Portainer Server
  include_role:
    name: portainer_server
  when: "'portainer' in services_enabled"
  tags: [user.docker, user.docker.portainer]
```

**Step 4: Add Portainer Agent role invocation to user.yml**

Edit `ansible/plays/user.yml` and add (after portainer server):

```yaml
- name: Deploy Portainer Agent
  include_role:
    name: portainer_agent
  when: "'portainer_agent' in services_enabled"
  tags: [user.docker, user.docker.portainer_agent]
```

**Step 5: Add to docker_extras.yml service list**

Edit `ansible/plays/roles/user/tasks/docker_extras.yml` and add portainer services to the script list if needed.

**Step 6: Commit**

```bash
git add ansible/production ansible/plays/user.yml
git commit -m "feat: integrate portainer into ansible deployment"
```

---

### Task 9: Test Deployment on servyy-test.lxd

**Files:**
- No new files
- Testing: Deploy to test environment

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

**Step 5: Verify Portainer Agent on test (if both services deployed)**

```bash
ssh servyy-test.lxd "docker logs portainer.agent --tail 20"
```

**Step 6: Access Portainer UI (test)**

Note: Test environment won't have Traefik routing, access directly:
```bash
ssh servyy-test.lxd "curl -k https://localhost:9443 2>&1 | head -10"
```

**Step 7: Verify health checks pass**

```bash
ssh servyy-test.lxd "docker ps --format 'table {{.Names}}\t{{.Status}}' | grep portainer"
# Both should show "healthy"
```

---

### Task 10: Deploy Portainer Server to Production (lehel.xyz)

**Files:**
- No new files (all from previous tasks)

**Step 1: Get user approval before production deployment**

Ask user: "Ready to deploy Portainer Server to lehel.xyz? This will:
- Create portainer service on lehel.xyz
- Expose at https://portainer.lehel.xyz via Traefik
- Generate TLS certificates
- Require initial admin password setup

Approve? (y/n)"

**Step 2: Deploy to lehel.xyz only**

```bash
cd ansible && ./servyy.sh --tags "user.docker.portainer" --limit lehel.xyz
```

**Step 3: Wait for deployment and health check**

```bash
ssh lehel.xyz "docker ps -a | grep portainer.server"
# Wait for "healthy" status
```

**Step 4: Verify Traefik routing**

```bash
curl -I https://portainer.lehel.xyz 2>&1 | head -5
# Should show: HTTP/2 200 or 401 (auth required)
```

**Step 5: Verify certificate**

```bash
echo | openssl s_client -servername portainer.lehel.xyz -connect portainer.lehel.xyz:443 2>/dev/null | grep -A 2 "Issuer:"
# Should show Let's Encrypt certificate
```

**Step 6: View initial logs**

```bash
ssh lehel.xyz "docker logs portainer.server --tail 30"
```

**Step 7: Commit deployment verification**

```bash
git add .
git commit -m "deploy: portainer server live on lehel.xyz"
```

---

### Task 11: Deploy Portainer Agent to code.lehel

**Files:**
- No new files

**Step 1: Get user approval**

Ask user: "Ready to deploy Portainer Agent to code.lehel? The agent will:
- Run on code.lehel
- Connect outbound to portainer.lehel.xyz:8000 via mTLS
- Enable lehel.xyz Portainer to monitor code.lehel containers

Approve? (y/n)"

**Step 2: Deploy agent to code.lehel**

```bash
cd ansible && ./servyy.sh --tags "user.docker.portainer_agent" --limit code.lehel
```

**Step 3: Verify agent container is running**

```bash
ssh code.lehel "docker ps | grep portainer.agent"
# Should show "healthy"
```

**Step 4: Verify agent connectivity in logs**

```bash
ssh code.lehel "docker logs portainer.agent --tail 20 | grep -i 'connected\|connection'"
```

**Step 5: Check Portainer Server logs for agent registration**

```bash
ssh lehel.xyz "docker logs portainer.server --tail 30 | grep -i agent"
```

**Step 6: Commit**

```bash
git add .
git commit -m "deploy: portainer agent live on code.lehel"
```

---

### Task 12: Configure RBAC in Portainer UI

**Files:**
- No new files (UI configuration, not code)

**Step 1: Access Portainer Web UI**

Navigate to: https://portainer.lehel.xyz

**Step 2: Login with admin**

Username: `admin`
Password: (use `vault_portainer_admin_password` from secrets.yml)

**Step 3: Create team "leaguesphere"**

- Go to: Settings → Teams → Add Team
- Name: `leaguesphere`
- Description: LeagueSphere development team
- Click Create

**Step 4: Create users for team members**

- Go to: Settings → Users → Add User
- For each team member (1-4 people):
  - Username: (their name or email prefix)
  - Password: (auto-generate, they change on first login)
  - Team: `leaguesphere`
  - Role: `Operator` (can view and restart containers)
  - Click Create

**Step 5: Configure endpoint permissions**

- Go to: Environments → code.lehel agent
- Access Control → Restrict access
- Add team: `leaguesphere` with `Operator` role
- Save

**Step 6: Verify permissions**

- Logout and login as a team member
- Should see both lehel.xyz (via server) and code.lehel (via agent)
- Should be able to restart containers
- Should NOT be able to deploy or delete

**Step 7: Document credentials**

Create a note (or add to your password manager):
- Portainer URL: https://portainer.lehel.xyz
- Admin username: admin
- Team: leaguesphere (team members added above)
- Permissions: Operator (observe, restart only)

---

### Task 13: Create Documentation

**Files:**
- Create: `history/2026-08-28_portainer-agent-deployment.md`

**Step 1: Create history log**

```markdown
# Portainer Agent Architecture Deployment

**Date:** 2026-08-28
**Deployed by:** claude
**Status:** Ready for deployment

## What Will Be Deployed

- **Portainer Server** on lehel.xyz
  - Exposed: https://portainer.lehel.xyz (via Traefik)
  - SSL: Let's Encrypt (via Traefik)
  - Admin user: local account
  - Team: leaguesphere (1-4 members, Operator role)

- **Portainer Agent** on code.lehel
  - Lightweight agent container
  - Secure outbound connection to lehel.xyz:8000 (mTLS)
  - Uses self-signed CA certificate for verification
  - No inbound ports exposed

## Architecture

```
Internet → Traefik (portainer.lehel.xyz) → Portainer Server (lehel.xyz:9443)
                                          ↓ (mTLS tunnel, port 8000)
                                    Portainer Agent (code.lehel)
                                          ↓ (Unix socket)
                                    Docker daemon (code.lehel)
```

## Implementation Process

1. Create portainer/ and portainer-agent/ service directories
2. Create Ansible roles: portainer_server, portainer_agent
3. Add secrets to vault: admin password, agent secret
4. Integrate into ansible/plays/user.yml
5. Update ansible/production inventory with services_enabled
6. Test on servyy-test.lxd
7. Deploy to lehel.xyz (Portainer Server)
8. Deploy to code.lehel (Portainer Agent)
9. Configure RBAC: admin user + leaguesphere team with Operator role

## Verification Commands

**Check Portainer Server health:**
```bash
ssh lehel.xyz "docker ps | grep portainer.server"
ssh lehel.xyz "curl -k https://localhost:9443/api/status"
```

**Check Portainer Agent health:**
```bash
ssh code.lehel "docker ps | grep portainer.agent"
ssh code.lehel "docker logs portainer.agent --tail 20"
```

**Verify RBAC:**
- Login to https://portainer.lehel.xyz with team member account
- Should see both servers
- Should be able to observe containers
- Should be able to restart containers
- Should NOT be able to deploy or delete

## Access

- **URL:** https://portainer.lehel.xyz
- **Admin user:** admin (credentials in vault)
- **Team:** leaguesphere (observability + restart)
- **Team members:** 1-4 people with Operator role

## Future Enhancements

- Integrate with LDAP/OAuth for team authentication (optional)
- Add Portainer backup strategy (database backups to storagebox)
- Create dashboard for observability team
- Add alerting for container restarts (integration with Loki)

## Rollback (if needed)

```bash
cd ansible && ./servyy.sh --tags "user.docker.portainer,user.docker.portainer_agent" --limit lehel.xyz,code.lehel
# Or remove services:
ansible-playbook plays/remove_service.yml -e "target_host=lehel.xyz"  # portainer
ansible-playbook plays/remove_service.yml -e "target_host=code.lehel"  # portainer-agent
```

## Notes

- TLS certificates for agent communication are auto-generated and stored in git-crypt encrypted files
- Agent connects outbound (no inbound ports on code.lehel) — more secure than Portainer pulling
- RBAC configured in Portainer UI (not code-driven) — can be modified per team preference
- All secrets encrypted with git-crypt (admin password, agent secret)
```

**Step 2: Commit**

```bash
git add history/2026-08-28_portainer-agent-deployment.md
git commit -m "docs: add portainer agent deployment plan"
```

---

### Task 14: Final Verification & Cleanup

**Files:**
- No new files

**Step 1: Verify git status**

```bash
git status  # Should be clean
```

**Step 2: Review all commits**

```bash
git log --oneline -14  # Show all commits from this plan
```

---

## Plan Complete

All tasks documented and ready for execution.
