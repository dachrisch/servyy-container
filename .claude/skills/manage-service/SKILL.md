---
name: manage-service
description: Guide through creating, editing, and deploying services with Ansible
type: skill
---

# Manage Service Skill

Guide for creating and editing containerized services in the servyy-container infrastructure. Covers Ansible structure, Molecule testing, CI/CD pipeline, and production deployment.

## Overview

### Service Structure
```
service-name/
├── docker-compose.yml          # Service definition
├── .env.example               # Environment template (optional)
├── scripts/                   # Custom scripts (optional)
├── config/                    # Configuration files (optional)
└── ansible/
    └── plays/
        └── roles/
            └── [role-name]/
                ├── tasks/main.yml
                ├── defaults/main.yml
                ├── vars/
                ├── templates/
                ├── handlers/main.yml
                └── molecule/
                    └── default/
```

### Key Principles

1. **git-tracked everything**: All changes go through git, never manual SSH edits
2. **Test before production**: Always deploy to servyy-test.lxd first
3. **Ansible automation**: Infrastructure managed through Ansible, not containers
4. **Clear naming**: Use descriptive names (not "app" - causes DNS conflicts)
5. **Idempotent operations**: Ansible tasks should be safe to run multiple times

## Common Pitfalls & Solutions

### ❌ Pitfall: Manual Container Modifications
**Problem**: Editing files directly on servers via SSH
**Solution**: Always modify Ansible roles/templates and redeploy
```bash
# WRONG ❌
ssh lehel.xyz "docker exec container vi /path/to/file"

# RIGHT ✅
# Edit ansible/plays/roles/service/templates/file.j2
./servyy.sh --tags "docker,user.docker.service"
```

### ❌ Pitfall: Hardcoded docker_env_file
**Problem**: `docker_env_file: ".env"` override prevents env_suffix from working
**Solution**: Remove hardcoded paths, let defaults handle it
```yaml
# WRONG ❌
- role: docker_service
  vars:
    docker_env_file: ".env"  # Blocks suffix logic

# RIGHT ✅
- role: docker_service
  vars:
    # No override - env_suffix will be appended
```

### ❌ Pitfall: Orphaned Containers
**Problem**: Renamed services leave old containers running, blocking redeployment
**Solution**: Check for orphaned containers before deploy
```bash
# Check what's running
docker ps -a | grep old_service_name

# Remove if needed
docker rm container_id

# Then redeploy
```

### ❌ Pitfall: Network DNS Failures
**Problem**: Frontend can't reach backend on multi-network setup
**Solution**: Ensure both services on same network (typically `proxy`)
```yaml
# In docker-compose.yml
services:
  backend:
    networks:
      - proxy        # Frontend reaches it here
      - internal     # Private network OK too
```

### ❌ Pitfall: Service Named "app"
**Problem**: DNS ambiguity when multiple services named "app"
**Solution**: Use descriptive names
```yaml
# WRONG ❌
services:
  app:
    container_name: service.app

# RIGHT ✅
services:
  api:
    container_name: service.api
```

### ❌ Pitfall: Forgetting Container Restart on Config Change
**Problem**: Updated startup.sh or config files don't apply to running container
**Solution**: Add notify handler to restart container on changes
```yaml
- name: Deploy startup script
  ansible.builtin.copy:
    src: startup.sh
    dest: /path/to/startup.sh
    mode: '0755'
  notify: restart service container
```

### ❌ Pitfall: GitHub Host Key Changed
**Problem**: SSH clones fail after GitHub rotates keys
**Solution**: Update SSH known_hosts in startup script
```bash
# In startup.sh
ssh-keygen -R github.com 2>/dev/null || true
ssh-keyscan -t ed25519 github.com >> /root/.ssh/known_hosts 2>/dev/null || true
```

## Development Workflow

### 1. Create Service Structure
```bash
# Create service directory
mkdir -p service-name

# Create docker-compose.yml
# Create ansible/plays/roles/service/tasks/main.yml
# Create ansible/plays/roles/service/defaults/main.yml
```

### 2. Add to Ansible Deployment
Edit `ansible/plays/user.yml`:
```yaml
- role: docker_service
  vars:
    service_dir: service-name
    env_templates:
      - src: docker.env.j2
        dest: .env
  tags: [user.docker, user.docker.service-name]
```

### 3. Create Environment Template
Create `ansible/plays/roles/docker_service/templates/service-name/.env.j2`:
```jinja2
SERVICE_VAR={{ service.some_var }}
ANOTHER_VAR={{ another_value }}
```

### 4. Add Secrets (if needed)
Update `ansible/plays/vars/secrets.yml`:
```yaml
service:
  var1: "value1"
  var2: "value2"
```

### 5. Test on servyy-test
```bash
# Initialize test environment
cd scripts && ./setup_test_container.sh

# Deploy
cd ../ansible && ./servyy-test.sh --tags "user.docker.service-name"

# Verify
ssh servyy-test.lxd "docker ps | grep service"
ssh servyy-test.lxd "docker logs service.name --tail 20"
```

### 6. Deploy to Production
```bash
# Get approval first
./servyy.sh --tags "user.docker.service-name"

# Verify
ssh lehel.xyz "docker ps | grep service"
ssh lehel.xyz "curl https://service.lehel.xyz"
```

## Molecule Testing

### Why Tests Matter
- ✅ Validates changes before CI
- ✅ Prevents breaking existing functionality
- ✅ Faster iteration than waiting for CI
- ✅ Catches permission/networking issues CI won't

### Create Tests
```bash
cd ansible/plays/roles/service

# Tests already exist
# Edit molecule/default/converge.yml to test your role
```

### Key Testing Principles

**1. Test on servyy-test BEFORE CI**
```bash
# Real LXD environment with Docker
cd scripts && ./setup_test_container.sh
cd ../ansible && ./servyy-test.sh
```

**2. Handle Docker Container Limitations**
```yaml
# Some tasks can't work in containers (systemd timers, hardware)
- name: Setup timer
  when: ansible_virtualization_type != 'docker'
  ...
```

**3. Use include_role Pattern Correctly**
```yaml
# RIGHT ✅ - Ansible discovers role by name
- include_role:
    name: service_name

# WRONG ❌ - Path-based roles break in CI
- include_role:
    name: "{{ playbook_dir }}/../../roles/service_name"
```

**4. Verify Configuration Actually Applied**
```yaml
# Don't just check skipped tasks
- name: Verify file exists
  stat:
    path: /etc/service/config.yml
  register: config_stat
  assert:
    that:
      - config_stat.stat.exists
```

### Run Tests
```bash
# Test single scenario
cd ansible/plays/roles/service
molecule test

# Test with specific scenario
molecule test --scenario-name staging

# Debugging
molecule converge  # Setup only (don't tear down)
molecule login     # SSH into test container
molecule destroy   # Clean up
```

## CI/CD Infrastructure

### GitHub Actions Pipeline
Located in `.github/workflows/ci.yml`

**What it does:**
1. Runs Molecule tests for all scenarios in parallel
2. Validates Ansible syntax
3. Runs linting (ansible-lint)
4. Reports results back to PR

**Test Matrix:**
- Each role can have multiple scenarios
- Scenarios run in parallel for speed
- CI only accepts PRs with passing tests

### Adding Role to CI
Edit `.github/workflows/ci.yml` matrix:
```yaml
roles:
  - { name: "service", scenarios: ["default", "staging"] }
```

## servyy-test vs Production

### Test Environment (servyy-test.lxd)
- **Purpose**: Validate changes before production
- **Setup**: `./scripts/setup_test_container.sh`
- **Deploy**: `./servyy-test.sh`
- **Teardown**: `./scripts/delete_test_container.sh`
- **Advantages**: Fast iteration, safe to break, isolated
- **Limitations**: LXD container, not full production

### Production (lehel.xyz)
- **Purpose**: Live infrastructure serving users
- **Deploy**: `./servyy.sh` (requires git push first)
- **Rules**:
  - ✅ Test on servyy-test first
  - ✅ Get explicit user approval
  - ✅ git pull must succeed on server
  - ✅ Monitor after deployment
- **Safety**: Slow, careful, requires approval

### Environment Differences

| Aspect | servyy-test | Production |
|--------|-------------|-----------|
| Host | LXD container | Bare metal |
| Systemd timers | ❌ Can't run | ✅ Works |
| Hardware access | ❌ Limited | ✅ Full |
| Networking | Virtual | Real ISP |
| Firewall | Simple | fail2ban + rules |
| Backups | ❌ No | ✅ Restic |
| Monitoring | Limited | Full stack |
| SSL certs | Self-signed | Let's Encrypt |

### Deployment Checklist

- [ ] Changes committed to git
- [ ] Pushed to origin/master
- [ ] Tested on servyy-test.lxd
- [ ] All Molecule tests pass
- [ ] User explicitly approves production
- [ ] Container healthy after deploy
- [ ] Logs show no errors
- [ ] Service responds to health checks
- [ ] External URLs work (if applicable)
- [ ] Monitoring shows activity

## Service Naming Convention

### Format: `{directory}.{service-name}`

```yaml
# docker-compose.yml
services:
  api:                    # Service name (descriptive!)
    container_name: ${COMPOSE_PROJECT_NAME}.api
    # This creates: myservice.api

# Result
Container: myservice.api
URL: https://myservice.lehel.xyz  (if exposed)
```

**Good names:**
- `leaguesphere.app` ✅
- `leagues-finance.api` ✅
- `photoprism.photoprism` ✅ (directory.service)
- `monitor.grafana` ✅

**Bad names:**
- `something.app` ❌ (conflicts with other "app" services)
- `service.service` ❌ (confusing)

## Quick Reference

### Deploy to Test
```bash
cd scripts && ./setup_test_container.sh
cd ../ansible && ./servyy-test.sh --tags "user.docker.service-name"
```

### Deploy to Production
```bash
git push origin master
cd ansible && ./servyy.sh --tags "user.docker.service-name"
```

### Run Tests
```bash
cd ansible/plays/roles/service
molecule test
```

### Check Service
```bash
# Test environment
ssh servyy-test.lxd "docker ps | grep service"

# Production
ssh lehel.xyz "docker ps | grep service"
ssh lehel.xyz "docker logs service.name --tail 20"
```

### Troubleshoot Service
```bash
# Check logs
docker logs container_name

# Check network
docker network inspect proxy

# Check configuration
cat /path/to/.env

# Restart container
docker restart container_name

# Execute command in container
docker exec container_name command
```

## Key Files to Know

| Path | Purpose |
|------|---------|
| `ansible/plays/user.yml` | Main deployment orchestration |
| `ansible/plays/roles/*/` | Reusable role definitions |
| `ansible/plays/vars/secrets.yml` | Encrypted credentials |
| `opencode/docker-compose.yml` | Service definition |
| `opencode/scripts/startup.sh` | Container initialization |
| `.github/workflows/ci.yml` | Automated testing pipeline |
| `molecule/default/molecule.yml` | Test configuration |

## Remember

> **The three rules of infrastructure:**
> 1. Everything in git
> 2. Test before production
> 3. Automate everything
