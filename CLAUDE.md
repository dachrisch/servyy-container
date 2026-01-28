# CLAUDE.md - servyy-container Infrastructure

> Self-hosted microservices platform (15+ Docker services) automated with Ansible
> **Last Updated:** 2026-01-06 (Added Molecule Testing Requirements)

## Quick Commands

```bash
# Production deployment
cd ansible && ./servyy.sh

# Test deployment
cd scripts && ./setup_test_container.sh && cd ../ansible && ./servyy-test.sh

# Targeted deployment
cd ansible && ./servyy.sh --tags "docker" --limit lehel.xyz

# Recreate locked Restic repositories (DESTRUCTIVE)
cd ansible && ansible-playbook restic_recreate.yml --limit lehel.xyz

# Service management
ssh lehel.xyz "docker ps"                          # Check running containers
ssh lehel.xyz "docker logs {container} --tail 50"  # View logs
ssh lehel.xyz "docker restart {container}"         # Restart service
```

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
   - ✅ **ALWAYS** ask user for explicit approval before deploying to `lehel.xyz`
   - ✅ **ALWAYS** show what will be deployed and ask "Should I deploy to production?"
   - ❌ **NEVER** assume production deployment is approved
   - ❌ **NEVER** deploy to production automatically

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

**Current Coverage**: 7 scenarios across system/testing/user roles
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
- Pattern: `include_role` with `playbook_dir` variable
- Never use `import_tasks` for tasks using templates

**4. Verify What Was Actually Configured**
- Don't test skipped tasks
- Check file existence and content
- Validate service states where possible

### Examples

**See existing scenarios**:
- `ansible/plays/roles/system/molecule/` - System configuration
- `ansible/plays/roles/testing/molecule/` - Development utilities
- `ansible/plays/roles/user/molecule/` - User environment setup

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

## Key Services

| Service | Container Name | URL | Purpose |
|---------|---------------|-----|---------|
| traefik | traefik.traefik | traefik.lehel.xyz | Reverse proxy, SSL |
| monitor | monitor.{grafana,prometheus,loki,promtail} | monitor.lehel.xyz | Observability stack |
| photoprism | photoprism.photoprism | photoprism.lehel.xyz | Photo library |
| git | git.gitea | git.lehel.xyz | Git hosting |

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
├── inventory/production    # lehel.xyz, aqui.fritz.box
└── plays/
    ├── system.yml          # OS, fail2ban, monit, backups
    ├── user.yml            # Docker services, containers
    └── roles/{system,user,testing,ls_*}/
```

**Common Tags:**
- `system` - OS packages, fail2ban, monit
- `docker` - Docker services only
- `fail2ban` - fail2ban configuration
- `backup` - Backup timers
- `user.docker.env` - Regenerate .env files

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

## Common Pitfalls

1. **Container label mismatch:** Always verify actual container name with `docker ps`, not the compose service name
2. **Loki query vs query_range:** Use `/api/v1/query_range` for log stream queries, NOT `/api/v1/query`
3. **git-crypt locked files:** Run `git-crypt status` if files appear binary
4. **Ansible changes not applied:** Check if templates are deployed to correct paths with `--check` mode
5. **Dashboard not updating:** Restart Grafana after provisioning changes: `docker restart monitor.grafana`

## Adding a New Service

1. Create `{service}/docker-compose.yml`:
```yaml
services:
  app:
    container_name: ${COMPOSE_PROJECT_NAME}.app
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

2. Deploy: `cd ansible && ./servyy.sh --tags "docker" --limit lehel.xyz`

3. Verify:
```bash
ssh lehel.xyz "docker ps | grep {service}"
ssh lehel.xyz "docker logs {service}.app"
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
| `ansible/plays/vars/secrets.yml` | Encrypted Ansible secrets |
| `ansible/plays/roles/user/templates/docker.env.j2` | Service .env template |
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