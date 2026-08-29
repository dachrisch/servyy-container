# CLAUDE.md - servyy-container Infrastructure

> Self-hosted microservices platform (15+ Docker services) automated with Ansible
> **Last Updated:** 2026-08-28 (service undeployment workflow)

## Quick Commands

```bash
# Production deployment (all servers with their enabled services)
cd ansible && ./servyy.sh

# Test deployment
cd scripts && ./setup_test_container.sh && cd ../ansible && ./servyy-test.sh

# Deploy to specific server only
cd ansible && ./servyy.sh --limit lehel.xyz      # Primary server
cd ansible && ./servyy.sh --limit code.lehel     # Opencode server

# Deploy specific service to its server
cd ansible && ./servyy.sh --tags "user.docker.opencode" --limit code.lehel
cd ansible && ./servyy.sh --tags "user.docker.monitor" --limit lehel.xyz

# Remove a service (interactive, with confirmation)
cd ansible && ansible-playbook plays/remove_service.yml -e "target_host=lehel.xyz"

# Recreate locked Restic repositories (DESTRUCTIVE)
cd ansible && ansible-playbook restic_recreate.yml --limit lehel.xyz

# Service management (know which server has the service!)
ssh lehel.xyz "docker ps"                          # Check containers on lehel.xyz
ssh code.lehel "docker ps"                         # Check containers on code.lehel
ssh {server} "docker logs {container} --tail 50"   # View logs on specific server
ssh {server} "docker restart {container}"          # Restart on specific server
```

⚠️ **CRITICAL:** Always use `--limit {server}` to target the correct server!

## SSH Key-Based Access Setup

**SSH access between servers is configured automatically by Ansible roles.**

### How It Works

**For user workstation → server access:**
1. System role creates the `cda` user on both production servers
2. Copies your local SSH public key (`~/.ssh/id_rsa.pub`) to each server
3. Disables password authentication for security

**For service-to-service access (opencode → lehel.xyz):**
1. OpenCode role generates a dedicated SSH key (`id_servy`) for accessing lehel.xyz
2. Public key is added to lehel.xyz's authorized_keys with Docker network restrictions
3. OpenCode containers automatically get the private key mounted

### Initial Server Setup

**First time connecting to a new server:**

```bash
# code.lehel.xyz requires root access to bootstrap setup
ansible-playbook servyy.yml -i inventory/production -l code.lehel.xyz -u root

# Then Ansible will:
# 1. Create cda user with sudo privileges
# 2. Set up cda user's SSH authorized_keys
# 3. Disable password authentication
# 4. Deploy opencode with cross-server SSH access to lehel.xyz
```

### SSH Access Methods

**Your workstation → lehel.xyz (primary):**
```bash
ssh lehel.xyz                  # Uses SSH key from ~/.ssh/id_rsa.pub
ssh cda@lehel.xyz
```

**Your workstation → code.lehel.xyz (opencode server):**
```bash
ssh code.lehel.xyz             # Uses SSH key from ~/.ssh/id_rsa.pub
ssh cda@code.lehel.xyz         # Initial deployment still uses root access
ssh root@code.lehel.xyz        # For emergency access (Ansible-configured)
```

**OpenCode service (code.lehel.xyz) → lehel.xyz:**
```bash
# Automatically configured by opencode role
# Private key: /home/cda/servyy-container/opencode/.ssh/id_servy
# Used by: OpenCode containers to sync/pull from lehel.xyz
# Restricted: Docker networks only (172.16.0.0/12, 127.0.0.1)
```

### SSH Key Requirements

Ensure you have a local SSH public key before deploying:

```bash
# Check if key exists
ls -la ~/.ssh/id_rsa.pub

# If missing, generate one
ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -N ""
```

The Ansible setup uses this key for all servers.

### Service-to-Service SSH (OpenCode Access)

The OpenCode role automatically:
1. Generates `id_servy` SSH key for accessing lehel.xyz
2. Mounts the private key in opencode containers
3. Adds the public key to lehel.xyz's authorized_keys (Docker network restricted)
4. Adds lehel.xyz to known_hosts to avoid SSH prompts

**Testing cross-server access:**

```bash
# Verify opencode container can reach lehel
ssh code.lehel.xyz "docker exec opencode.opencode ssh -i /root/.ssh/id_servy cda@lehel.xyz whoami"

# Should return: cda
```

**Access rights:**
- ✅ OpenCode SSH key authorized on lehel.xyz
- ✅ Restricted to Docker network ranges (security)
- ✅ No password needed (key-based only)
- ✅ Automatic lehel.xyz fingerprint in known_hosts

## CRITICAL DEPLOYMENT RULES

**MANDATORY WORKFLOW - NO EXCEPTIONS:**

1. **NO Direct Server File Transfers**
   - ❌ **NEVER** use `scp`, `rsync`, or direct file transfers to servers
   - ❌ **NEVER** ssh into servers to manually edit files when git repo is active
   - ✅ **ALWAYS** use git workflow: create branch → commit → deploy via Ansible
   - This is a git-tracked repository - all changes MUST go through version control

2. **Test-First Deployment**
   - ✅ **ALWAYS** test on `servyy-test.lxd` first using `./servyy-test.sh`
   - ✅ **ALWAYS** verify services work correctly on test environment
   - ❌ **NEVER** deploy directly to production without testing

3. **Production Deployment Requires Explicit Approval**
   - ✅ **ALWAYS** ask user for explicit approval before deploying to production
   - ✅ **ALWAYS** identify which server(s) will be affected (check inventory first!)
   - ✅ **ALWAYS** show what will be deployed and ask "Should I deploy to {server}?"
   - ❌ **NEVER** assume production deployment is approved
   - ❌ **NEVER** deploy to production automatically
   - ❌ **NEVER** deploy to the wrong server (verify inventory: which server has this service?)

**Standard Git Workflow:**
```bash
# 1. Create feature branch
git checkout -b claude/feature-name

# 2. Make changes and commit
git add .
git commit -m "feat: description"

# 3. Test on test environment
cd scripts && ./setup_test_container.sh
cd ../ansible && ./servyy-test.sh

# 4. Verify test deployment works
ssh servyy-test.lxd "docker ps"

# 5. ASK USER FOR APPROVAL before production deployment
# Only after explicit user approval:
cd ansible && ./servyy.sh --limit lehel.xyz
```

## Deployment Workflow

### Standard Deployment Process

```bash
# 1. Make changes to configuration files
# 2. Test syntax
cd ansible && ansible-playbook servyy.yml --syntax-check

# 3. Deploy to production
./servyy.sh --limit lehel.xyz

# 4. Verify deployment
ssh lehel.xyz "docker ps | grep {service}"
ssh lehel.xyz "docker logs {service} --tail 20"
```

### Verifying Container Labels for Loki Queries

**Critical:** Promtail uses `{directory}.{service}` pattern for container names, NOT compose service names.

```bash
# Check actual container name/labels
ssh lehel.xyz "docker ps --format '{{.Names}}: {{.Label \"com.docker.compose.service\"}}'"

# Example output:
# traefik.traefik: reverse-proxy
# monitor.grafana: grafana

# For Loki queries, use the container name (first part):
{job="docker",container="traefik.traefik"}  # ✅ Correct
{job="docker",container="reverse-proxy"}    # ❌ Wrong
{job="docker",container="traefik"}          # ❌ Wrong
```

### Testing Loki Queries

```bash
# Use query_range (NOT query) for log queries
LOKI_URL="https://monitor.lehel.xyz/loki"
TENANT_ID="servyy-logs-k8x9m2p4q7"
END=$(date +%s)000000000
START=$((END - 3600000000000))  # Last 1 hour

curl -s -H "X-Scope-OrgID: $TENANT_ID" \
  "$LOKI_URL/api/v1/query_range" \
  --data-urlencode 'query={job="docker",container="traefik.traefik"} | json | DownstreamStatus >= 400' \
  --data-urlencode "start=$START" \
  --data-urlencode "end=$END" | jq
```

### Emergency Manual Updates (AVOID IF POSSIBLE)

**⚠️ WARNING:** Manual changes violate git workflow and should only be used in emergencies.
**ALWAYS** commit manual changes to git afterwards to keep repository in sync.

```bash
# Emergency example: Restart service only (NO file edits)
ssh lehel.xyz "docker restart monitor.grafana"

# If emergency file edit is absolutely required:
# 1. Make the change on server
# 2. IMMEDIATELY replicate change in git repo
# 3. Commit to git with explanation
# 4. Deploy via Ansible to verify git state matches server state
```

## Removing a Service Permanently

**Never remove services manually. Always use Ansible to decommission services.**

### Step 1: Remove Service from Server

Run the interactive removal playbook with confirmation prompt:

```bash
cd ansible
ansible-playbook plays/remove_service.yml -e "target_host=lehel.xyz"

# Prompts for:
# 1. Service name (e.g., 'opencode')
# 2. Confirmation ("Remove {service} containers, volumes, and directory? (yes/no)")
#
# Removes: containers, volumes, and service directory
```

### Step 2: Disable Service in Inventory

Disable the service in version control to prevent re-deployment:

```bash
# Edit: ansible/production
# Change the service flag from true to false:
#   services_enabled:
#     {service}: false    # ← Was 'true'

# Example for removing 'opencode':
git diff ansible/production
# Should show: -          opencode: true
#            +          opencode: false

git add ansible/production
git commit -m "chore: disable {service} service

- Containers and volumes removed from [hostname]
- Service marked as disabled in inventory
"
```

### Step 3: Clean Up Git Repository

Remove the service directory from version control:

```bash
# Remove service directory (if exists in git)
git rm -r {service}/

# Or if directory isn't in git:
# Just remove from git index if tracked
git status | grep "deleted:" # Verify removal

# Re-commit with service directory removal if applicable
git commit --amend -m "chore: remove {service} service

- Removed service directory from git
- Disabled in inventory (containers/volumes cleaned up on [hostname])
"

git push origin master
```

### Step 4: Deploy to Apply Inventory Changes

Deploy to confirm service is no longer deployed on next run:

```bash
cd ansible && ./servyy.sh --limit lehel.xyz

# Verify in output:
# - Service role should be skipped (when condition: service not in enabled list)
# - No "Deploy {service}" task should run
```

### Recovery (if needed)

If you need to re-enable a service:

```bash
# Edit: ansible/production
# Change:  {service}: false
# To:      {service}: true

# Then deploy:
cd ansible && ./servyy.sh --limit lehel.xyz

# Service will be redeployed (if directory exists in git)
```

## Molecule Testing (REQUIRED FOR NEW FEATURES)

**Before implementing new Ansible features, you MUST add Molecule tests.**

### Why Test-First Matters

1. **Validation**: Proves your changes work before production deployment
2. **CI Integration**: All tests run automatically on every push
3. **Regression Prevention**: Ensures existing functionality isn't broken
4. **Documentation**: Tests show how roles are meant to be used

### Standard Workflow for New Features

```
1. PLAN: Design the feature and required test coverage
2. TEST: Create/update Molecule scenario on servyy-test
3. IMPLEMENT: Write code until test passes
4. INTEGRATE: Add scenario to CI matrix
5. DOCUMENT: Update history/YYYY-MM-DD_*.md
```

**Current Coverage**: 8 scenarios across system/testing/user/docker_service roles
**Test Environment**: servyy-test.lxd (validates before CI)
**CI Platform**: GitHub Actions (runs all scenarios in parallel)

### Key Testing Principles

**1. Test on servyy-test BEFORE CI**
- Real LXD environment with Docker
- Catches issues CI won't (permissions, networking, etc.)
- Faster iteration than waiting for CI

**2. Handle Docker Container Limitations**
- Some tasks can't work in containers (systemd timers, hardware access)
- Use conditional execution: `when: ansible_virtualization_type != 'docker'`
- Tag untestable tasks: `molecule-notest`
- Mock infrastructure dependencies (storagebox, restic, etc.)

**3. Use include_role Pattern**
- Templates need proper resolution
- Pattern: `include_role` with role name (not path) — set `ANSIBLE_ROLES_PATH` in molecule.yml provisioner env
- Never use path-based role names (`{{ playbook_dir }}/../../`) — ansible-lint flags these and they break in CI
- Set `ANSIBLE_ROLES_PATH: "${MOLECULE_PROJECT_DIRECTORY}/.."` so the role is discoverable by name

**4. Verify What Was Actually Configured**
- Don't test skipped tasks
- Check file existence and content
- Validate service states where possible

### Examples

**See existing scenarios**:
- `ansible/plays/roles/system/molecule/` - System configuration
- `ansible/plays/roles/testing/molecule/` - Development utilities
- `ansible/plays/roles/user/molecule/` - User environment setup
- `ansible/plays/roles/docker_service/molecule/` - Generic Docker service role

**Reference documentation**:
- `history/2026-01-05_molecule-testing-validation.md` - Complete validation report
- `.github/workflows/ci.yml` - CI matrix configuration

**Testing is not optional** - if you modify a role, update or add tests. The CI will reject PRs without test coverage.

## git-crypt (CRITICAL)

**Encrypted patterns:** `docker-compose.yml`, `*.yaml`, `*.env`, `*.conf`, `secrets.*`, `secret_*`

**Rules:**
- Files appear as **plaintext when unlocked** - edit normally
- Auto-encrypted on commit
- Check status: `git-crypt status`

## Architecture

```
Internet → Porkbun DNS (*.lehel.xyz) → Hetzner Firewall → Traefik (443/80)
    → Docker "proxy" network → Services
    → Promtail → Loki (log aggregation)
```

**Tech Stack:** Docker Compose | Traefik | Ansible | git-crypt | Prometheus/Grafana/Loki | fail2ban

## Service Naming

```
Container: {directory}.{compose-service}
URL: {directory}.{inventory-hostname}

Example:
- Directory: monitor/
- Compose service: grafana
- Container: monitor.grafana
- URL: https://monitor.lehel.xyz
```

**Environments:**
- Production: `*.lehel.xyz` (lehel.xyz host)
- Dev: `*.aqui.fritz.box` (aqui.fritz.box host)
- Test: `*.servyy-test.lxd` (LXD container)

**⚠️ CRITICAL: DO NOT NAME SERVICES "app"**
- ❌ Never use `app` as a docker-compose service name or container name
- ❌ Reason: DNS conflicts when multiple services named "app" exist on same networks
- ✅ Use descriptive names: `finance-api`, `api`, `backend`, `webserver`, etc.
- ✅ Example: `leagues-finance.finance-api` instead of `leagues-finance.app`

This prevents DNS ambiguity where `getent hosts app` returns wrong service IP.

## Per-Server Service Deployment

**IMPORTANT:** Services are now deployed **per-server**, not uniformly across all servers.

Each server has its own set of enabled services defined in the ansible inventory. Before deploying or troubleshooting a service, **verify which server hosts that service**.

### How to Determine Which Server Has Which Service

**1. Check the Ansible Inventory**
```bash
cd ansible
grep -A 100 "services_enabled:" plays/production

# Output will show which services are enabled per server:
# lehel.xyz:
#   services_enabled:
#     traefik: true
#     monitor: true
#     opencode: true
#     photoprism: true
#     ...
#
# code.lehel:
#   services_enabled:
#     opencode: true
#     ...
```

**2. Query Running Services on a Server**
```bash
ssh {server} "docker ps --format '{{.Names}}'"

# Example:
ssh code.lehel "docker ps"  # Lists services on code.lehel
ssh lehel.xyz "docker ps"   # Lists services on lehel.xyz
```

**3. Deployment by Server**
When deploying a service, **always specify the correct server**:

```bash
# Deploy opencode to code.lehel ONLY
cd ansible && ./servyy.sh --tags "user.docker.opencode" --limit code.lehel

# Deploy all services to lehel.xyz
cd ansible && ./servyy.sh --limit lehel.xyz

# Deploy specific tag to all servers
cd ansible && ./servyy.sh --tags "docker" --limit all
```

### Common Per-Server Configurations

| Server | Role | Services |
|--------|------|----------|
| `lehel.xyz` | Primary production | traefik, monitor, photoprism, git, leaguesphere-*, etc. |
| `code.lehel` | Secondary (opencode-only) | opencode |
| `aqui.fritz.box` | Dev/testing | Various dev services |
| `servyy-test.lxd` | Test environment | Mirrors production for validation |

### Agent Responsibility: Know Your Server

When responding to requests like "deploy X" or "fix error in X":

1. **Identify the service**: What service is being referenced?
2. **Find the host**: Which server runs this service? (check inventory or `docker ps`)
3. **Connect to correct server**: `ssh {server}` before diagnosing or deploying
4. **Deploy to correct server**: Always use `--limit {server}` in ansible commands

**Example:**
- Request: "Deploy opencode"
- Action: Check inventory → opencode is on `code.lehel` → Deploy with `--limit code.lehel`
- Not: ~~Deploy to lehel.xyz~~ (wrong server!)

## Key Services

| Service | Container Name | URL | Purpose |
|---------|---------------|-----|---------|
| traefik | traefik.traefik | traefik.lehel.xyz | Reverse proxy, SSL |
| monitor | monitor.{grafana,prometheus,loki,promtail} | monitor.lehel.xyz | Observability stack |
| photoprism | photoprism.photoprism | photoprism.lehel.xyz | Photo library |
| git | git.gitea | git.lehel.xyz | Git hosting |
| leaguesphere-demo | leaguesphere-demo.{www,demo-app,mysql} | demo.leaguesphere.app | LeagueSphere demo (auto-resets nightly) |

> **LeagueSphere prod/stage/demo/test environments, setup, logs, and the
> "investigate-on-prod / reproduce-with-prod-data-on-stage" workflows:** see
> **[docs/leaguesphere-environments.md](docs/leaguesphere-environments.md)**.

**Logging Flow:**
- All Docker containers → stdout/stderr
- Promtail scrapes Docker logs + system logs (`/var/log/syslog`, `/var/log/auth.log`)
- Loki stores logs with 31-day retention
- Grafana provides log exploration + dashboards

## Ansible Structure

```
ansible/
├── servyy.yml              # Main playbook
├── servyy.sh / servyy-test.sh
├── inventory/production    # Defines servers and their enabled services
└── plays/
    ├── system.yml          # OS, fail2ban, monit, backups
    ├── user.yml            # Docker services, containers
    └── roles/{system,user,testing,docker_service,ls_*}/
```

**Inventory File: `ansible/production`**
- Defines all servers (lehel.xyz, code.lehel, aqui.fritz.box, etc.)
- Each server has `services_enabled:` dict specifying which services run there
- Services NOT in enabled list are skipped during deployment
- Example: opencode only enabled on code.lehel, not on lehel.xyz

**Common Tags:**
- `system` - OS packages, fail2ban, monit
- `docker` - Docker services only
- `fail2ban` - fail2ban configuration
- `backup` - Backup timers
- `user.docker.env` - Regenerate .env files
- `user.docker.{service}` - Deploy specific service (e.g., `user.docker.opencode`)

## Backup & Monitoring

**Backups** (systemd timers → `/mnt/storagebox/backup/`):
- Home directory: 03:00 UTC daily
- Root filesystem: 04:00 UTC daily
- PhotoPrism DB: 02:00 UTC daily

**Monitoring Stack:**
- **Prometheus:** Metrics collection (Traefik, cAdvisor, Node Exporter)
- **Grafana:** Dashboards (HTTP Errors, Security, Services & Infra)
- **Loki:** Log aggregation (31-day retention)
- **Promtail:** Log collection (Docker + system logs)
- **monit:** System health monitoring (SSH, disk, memory)
- **fail2ban:** Intrusion prevention
  - Loki-based: SSH brute force, scanners, Traefik rate limiting, malicious bots
  - Script: `/usr/local/bin/blocklist/update-from-loki.sh` (runs every 5min)

## Troubleshooting

### Container Issues
```bash
# Check container status
ssh lehel.xyz "docker ps -a | grep {service}"

# View logs
ssh lehel.xyz "docker logs {container} --tail 50 --follow"

# Restart container
ssh lehel.xyz "cd servyy-container/{service} && docker-compose restart"

# Check .env file
ssh lehel.xyz "cat /home/cda/servyy-container/{service}/.env"
```

### Network Issues
```bash
# Inspect proxy network
ssh lehel.xyz "docker network inspect proxy"

# Check Traefik routing
ssh lehel.xyz "docker logs traefik.traefik --tail 50"
```

### Loki Query Issues
```bash
# List available labels
curl -s -H "X-Scope-OrgID: servyy-logs-k8x9m2p4q7" \
  "https://monitor.lehel.xyz/loki/api/v1/label/__name__/values"

# Check container labels
ssh lehel.xyz "docker ps --format '{{.Names}}'"

# Test query (use query_range for log streams)
curl -s -H "X-Scope-OrgID: servyy-logs-k8x9m2p4q7" \
  "https://monitor.lehel.xyz/loki/api/v1/query_range" \
  --data-urlencode 'query={job="docker"}' \
  --data-urlencode "start=$(($(date +%s)-3600))000000000" \
  --data-urlencode "end=$(date +%s)000000000"
```

### fail2ban Issues
```bash
# Check active jails
ssh lehel.xyz "sudo fail2ban-client status"

# View loki-blocklist jail
ssh lehel.xyz "sudo fail2ban-client status loki-blocklist"

# Test Loki blocklist script
ssh lehel.xyz "sudo bash /usr/local/bin/blocklist/update-from-loki.sh"

# Check fail2ban logs
ssh lehel.xyz "sudo journalctl -u fail2ban -n 50 --no-pager"
```

## Common Issues & Solutions

### Environment File Naming Issues

**Problem:** Ansible deployment fails with "env file not found"
- **Cause:** Hardcoded `docker_env_file` in role vars overrides env_suffix logic
- **Solution:** Remove hardcoded `docker_env_file` from role invocation, let defaults handle it
- **Reference:** `history/2026-05-31_staging_env_file_fix.md`

```bash
# ❌ Wrong - prevents env_suffix from being appended
- role: ls_app
  vars:
    docker_env_file: ".env"  # This overrides suffix logic!

# ✅ Correct - lets default logic work
- role: ls_app
  vars:
    # No docker_env_file override - suffix will be appended
```

### Orphaned Containers Blocking Redeployment

**Problem:** Docker-compose fails saying container already exists
- **Cause:** Renamed/removed compose services leave old containers running
- **Solution:** Manually remove orphaned containers before redeployment
- **Reference:** `feedback_orphaned_containers.md`

```bash
# Find orphaned containers
ssh lehel.xyz "docker ps -a | grep {old_service_name}"

# Remove them
ssh lehel.xyz "docker rm {container_id}"

# Then retry deployment
cd ansible && ./servyy-test.sh
```

### LeagueSphere Network DNS Resolution Failures

**Problem:** Frontend can't reach backend - "unknown host" errors
- **Cause:** Multi-network containers need backend service on same networks as frontend
- **Solution:** Ensure backend service is on the `proxy` network
- **Reference:** `leaguesphere_network_dns.md`

```yaml
# ✅ Correct - backend on proxy network
services:
  backend:
    networks:
      - proxy        # Frontend can reach it via this network
      - internal     # Can also have private networks
```

### Deployment Requires Git Push First

**Problem:** Server can't find changes - "Permission denied" or file not found
- **Cause:** Ansible deploys from git, but server hasn't pulled latest commits
- **Solution:** Push to origin first, ensure server's git pull succeeds
- **Reference:** `feedback_deployment_git_pull.md`

```bash
# 1. Commit changes locally
git commit -m "feat: description"

# 2. Push to origin FIRST
git push origin master

# 3. Server's Ansible will pull during deployment
# (servyy.sh runs: git pull origin master)
```

### Test Environment Not Initialized

**Problem:** `servyy-test.sh` fails with "container not found" or permission errors
- **Cause:** Test LXD container hasn't been created or is misconfigured
- **Solution:** Initialize test container first

```bash
# Initialize test environment
cd scripts && ./setup_test_container.sh

# Then deploy
cd ../ansible && ./servyy-test.sh
```

## Common Pitfalls

1. **Container label mismatch:** Always verify actual container name with `docker ps`, not the compose service name
2. **Loki query vs query_range:** Use `/api/v1/query_range` for log stream queries, NOT `/api/v1/query`
3. **git-crypt locked files:** Run `git-crypt status` if files appear binary
4. **Ansible changes not applied:** Check if templates are deployed to correct paths with `--check` mode
5. **Dashboard not updating:** Restart Grafana after provisioning changes: `docker restart monitor.grafana`
6. **DNS service conflicts:** DO NOT use "app" as a service name - causes DNS ambiguity across networks. Use descriptive names like `finance-api`, `backend`, `webserver`, etc.

## Deployment Verification Checklist

Use this checklist after each deployment (test or production) to verify success:

### Pre-Deployment

- [ ] Changes committed to git
- [ ] Pushed to origin/master (if production)
- [ ] Tested on servyy-test.lxd (if production)
- [ ] All Ansible syntax checks passed: `ansible-playbook servyy.yml --syntax-check`
- [ ] User approved production deployment (if applicable)

### Ansible Execution

- [ ] Deployment completed without errors (exit code 0)
- [ ] PLAY RECAP shows: `failed=0` and `unreachable=0`
- [ ] Expected number of tasks ran (compare to previous deployments)
- [ ] No unexpected `FAILED` entries in output

### Docker Services

```bash
# Check all containers are running
ssh {host} "docker ps | wc -l"  # Compare to expected count

# Verify key services are healthy
ssh {host} "docker ps | grep traefik"
ssh {host} "docker ps | grep monitor"

# Check for restart loops (many restarts = unhealthy)
ssh {host} "docker ps --format '{{.Names}}: {{.Restarts}}' | grep -v ' 0$'"
```

### Network & Routing

```bash
# Verify proxy network exists
ssh {host} "docker network ls | grep proxy"

# Check Traefik is routing correctly
ssh {host} "curl -I https://{service}.{host} 2>/dev/null | head -1"
```

### Logs & Monitoring

```bash
# Check for errors in Traefik logs
ssh {host} "docker logs traefik.traefik --tail 20 | grep -i error"

# Check system logs for deployment issues
ssh {host} "journalctl -u docker --no-pager -n 20"

# Verify Loki is receiving logs (if monitoring deployed)
curl -s "https://monitor.lehel.xyz/loki/api/v1/label/__name__/values" | jq length
```

### Environment-Specific Checks

**For LeagueSphere deployments:**
```bash
# Check both production and staging containers
ssh {host} "docker ps | grep leaguesphere"

# Verify database connectivity
ssh {host} "docker logs leaguesphere.app --tail 20 | grep -i error"
ssh {host} "docker logs leaguesphere_stage.mysql --tail 20 | grep -i error"
```

**For production (lehel.xyz):**
```bash
# Verify SSL certificates are valid
ssh lehel.xyz "curl -I https://traefik.lehel.xyz 2>&1 | grep SSL"

# Check fail2ban is active
ssh lehel.xyz "sudo fail2ban-client status | grep -c 'jail'"
```

### Rollback Decision

If any check fails:
- [ ] Do NOT proceed with production deployment
- [ ] Investigate root cause in test environment
- [ ] Fix in git, commit, and re-test
- [ ] Only deploy after successful test verification

## Adding a New Service

1. Create `{service}/docker-compose.yml`:
```yaml
services:
  api:  # ✅ Use descriptive name (NOT "app")
    container_name: ${COMPOSE_PROJECT_NAME}.api
    image: {image}
    networks: [proxy]
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.${SERVICE_NAME}.rule=Host(`${SERVICE_HOST}`)"
      - "traefik.http.routers.${SERVICE_NAME}.entrypoints=websecure"
      - "traefik.http.routers.${SERVICE_NAME}.tls.certresolver=letsencryptdnsresolver"
networks:
  proxy:
    external: true
```
⚠️ **NEVER use "app" as service name** - causes DNS conflicts with other services

2. Add a role invocation to `ansible/plays/user.yml` using the `docker_service` role:
```yaml
# Simple service (single .env from docker.env.j2)
- role: docker_service
  vars:
    service_dir: my-service
  tags: [user.docker, user.docker.my-service]

# Service with extra env templates
- role: docker_service
  vars:
    service_dir: my-service
    env_templates:
      - src: docker.env.j2
        dest: .env
      - src: my-service/.env.j2
        dest: service.env
  tags: [user.docker, user.docker.my-service]
```

3. Add the service to the script list in `ansible/plays/roles/user/tasks/docker_extras.yml`.

4. Deploy: `cd ansible && ./servyy.sh --tags "docker" --limit lehel.xyz`

5. Verify:
```bash
ssh lehel.xyz "docker ps | grep {service}"
ssh lehel.xyz "docker logs {service}.api --tail 20"
curl -I https://{service}.lehel.xyz
```

## Conventions

**Commits:** `<type>: <description>`
- Types: `feat`, `fix`, `chore`, `refactor`, `docs`
- Example: `fix: correct Traefik container label in Loki queries`

**Branches:** `master` (production), `claude/*` (development)

**History logs:** Create `history/YYYY-MM-DD_description.md` for major changes

## Key Paths

| Location | Purpose |
|----------|---------|
| `/home/cda/servyy-container/{service}/` | Service directories on server |
| `/mnt/storagebox/backup/` | Backup storage |
| `/usr/local/bin/blocklist/update-from-loki.sh` | fail2ban Loki integration |
| `/var/log/fail2ban-loki.log` | fail2ban blocklist log |
| `ansible/plays/vars/secrets.yml` | Encrypted Ansible secrets (incl. `vaultwarden_api` API key) |
| `ansible/plays/vars/.restic_password_{home,root,ls_db}` | Restic password seed files (**source of truth**) |
| `ansible/plays/roles/restic/tasks/vaultwarden_push.yml` | Push restic passwords into Vaultwarden (handler-driven backup copy) |
| `ansible/plays/roles/docker_service/templates/docker.env.j2` | Default service .env template |
| `ansible/plays/roles/docker_service/templates/{service}/` | Per-service env templates |
| `monitor/provisioning/dashboards/` | Grafana dashboard JSON files |
| `monitor/provisioning/datasources/` | Grafana datasource configs |

## Quick Reference

```bash
# Deployment
cd ansible && ./servyy.sh --limit lehel.xyz

# Verify services
ssh lehel.xyz "docker ps"

# Check logs
ssh lehel.xyz "docker logs traefik.traefik --tail 20"

# Restart Grafana
ssh lehel.xyz "docker restart monitor.grafana"

# Test fail2ban
ssh lehel.xyz "sudo bash /usr/local/bin/blocklist/update-from-loki.sh"

# LeagueSphere demo management
ssh lehel.xyz "docker ps | grep leaguesphere-demo"              # Check demo containers
ssh lehel.xyz "docker logs leaguesphere-demo.demo-app --tail 20" # View demo logs
# Manual reset (Ofelia also runs this nightly at 00:00 UTC)
ssh lehel.xyz "docker exec leaguesphere-demo.demo-app /bin/bash -c 'rm -f /app/.demo_last_reset && /app/entrypoint.demo.sh'"

# View Loki logs
# Navigate to: https://monitor.lehel.xyz → Explore → Loki
# Query: {job="docker",container="traefik.traefik"} | json
```

## Backup & Recovery Rules

1. **Restic Restore Safeguards (MANDATORY)**
   - ❌ **NEVER** restore data while the target container is running
   - ❌ **NEVER** restore data into a non-empty directory (prevents corruption/overwrite)
   - ✅ **ALWAYS** verify target state (stopped container, empty/missing dir) before restore
   - ✅ **ALWAYS** test restore logic on `servyy-test.lxd` before applying to production

2. **Password Integrity**
   - ❌ **NEVER** overwrite Restic environment files (`/etc/restic/env.*`) if the password differs
   - ✅ **Manual intervention** is required if Restic passwords need to be changed/synchronized

3. **Repository Lockout Recovery**
   - **Manual Only:** Use `ansible-playbook restic_recreate.yml` to wipe and re-init locked repos
   - **Verification:** The playbook automatically verifies lockouts and requires explicit confirmation

4. **Off-host Password Backup (Vaultwarden)**
   - The restic passwords are mirrored into Vaultwarden (`pass.lehel.xyz`) as a human-readable backup copy
   - **Source of truth stays the seed files** `ansible/plays/vars/.restic_password_*` — Vaultwarden is a *copy*, not the master
   - **Automatic, handler-driven:** the restic play (`plays/restic.yml`) prompts for the Vaultwarden master password at the start of every run (press enter to skip). The push fires only when `init.yml` actually writes/updates an `/etc/restic/env.*` file, and only on production (`lehel.xyz`). Idempotent — creates missing Login items only. API key from `secrets.yml` (`vaultwarden_api`).
   - To force a push when nothing changed, re-run with the env files dirty (or temporarily touch them) — there is no standalone playbook.
   - ⚠️ Do **not** make Vaultwarden the source restic reads from at deploy time — restic backs up Vaultwarden, so a bare-metal restore must not depend on it. Keep an offline copy of the master + restic passwords.
   - Reference: `history/2026-06-29_restic-vaultwarden-copy.md`

5. **Seed-Password Recovery Guard (prevents silent generation)**
   - The restic role runs `tasks/seed_guard.yml` FIRST (before any `restic_password_*`
     is dereferenced). If a seed file `ansible/plays/vars/.restic_password_*` is missing
     (fresh/re-cloned controller), it refuses to let Ansible silently generate a new
     password. Recovery precedence: **seed file → Vaultwarden (auto) → operator prompt → generate**.
   - Missing seed + blank Vaultwarden master password (or `bw` unreachable) → **hard-fail**.
     Provide the VW master password at the prompt to pull the password from Vaultwarden,
     or restore the seed files from your offline copy first.
   - A new password is generated ONLY when the operator leaves the prompt blank after
     Vaultwarden was actually probed and had no matching item — i.e. a never-initialized repo.
   - Guards init AND the destructive `restic.recreate` path (so recreate's wipe/re-init
     decision uses the real password, not a wrong-password artifact).
   - Reference: `history/2026-06-29_restic-seed-guard.md`

> **Note:** CLAUDE.md elsewhere references a standalone `ansible-playbook restic_recreate.yml`
> — no such file exists; recreate runs via `--tags restic.recreate` through the restic role.

## Cleanup Automation

**Automated disk space management** (deployed via Ansible):

**Journal Logs** (declarative):
- Config: `/etc/systemd/journald.conf.d/retention.conf`
- Limit: 500MB max, 4-week retention
- No manual intervention required

**Docker Cleanup** (weekly):
- Schedule: Every Sunday at 02:00 CET
- Mode: Aggressive (`docker system prune -a -f --volumes`)
- Removes all unused images, containers, volumes
- Log: `/var/log/docker-cleanup.log`
- Monitoring: monit alerts if log not updated in 8 days

**Kernel Cleanup** (monthly):
- Schedule: 1st Sunday of each month at 01:00 CET
- Removes old kernel packages (preserves current kernel)
- Script: `/usr/local/bin/kernel-cleanup.sh`
- Log: `/var/log/kernel-cleanup.log`
- Monitoring: monit alerts if log not updated in 32 days

**Check cleanup status:**
```bash
# View cleanup timers
ssh lehel.xyz "systemctl list-timers | grep cleanup"

# Check Docker cleanup logs
ssh lehel.xyz "tail -50 /var/log/docker-cleanup.log"

# Check kernel cleanup logs
ssh lehel.xyz "tail -50 /var/log/kernel-cleanup.log"

# Verify monit monitoring
ssh lehel.xyz "sudo monit status | grep cleanup"
```
- branch on prod must always be master after rollout...branches are only allowed during deployment