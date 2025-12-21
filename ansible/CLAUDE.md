# CLAUDE.md - Infrastructure Deployment Documentation

This file provides guidance to Claude Code when working with the servyy infrastructure deployment and management.

## Infrastructure Overview

This infrastructure manages the servyy deployment using Ansible automation with a clear separation between test and production environments. All infrastructure changes are managed through Ansible playbooks to ensure reproducibility and consistency.

**Main Repository:** `/home/cda/dev/infrastructure/container`

**Key Directories:**
```
infrastructure/container/
├── scripts/                    # Deployment and setup scripts
│   ├── setup_test_container.sh # LXC test container setup
│   ├── servyy-test.yaml       # LXC profile for test container
│   └── seed_vaultwarden.sh    # ONE-TIME Vaultwarden migration
├── ansible/                    # Ansible infrastructure
│   ├── servyy.yml             # Main playbook (imports system, user, app playbooks)
│   ├── servyy.sh              # Production deployment wrapper
│   ├── servyy-test.sh         # Test deployment wrapper
│   ├── ansible.cfg            # Ansible configuration
│   ├── production             # Production inventory
│   ├── testing                # Test inventory
│   ├── plugins/               # Custom Ansible plugins
│   │   └── lookup/
│   │       └── vaultwarden.py # Vaultwarden secret lookup
│   └── plays/                 # Playbooks and roles
│       ├── system.yml         # System-level configuration
│       ├── user.yml           # User-level configuration
│       ├── leaguesphere.yml   # Application deployment
│       ├── testing.yml        # Test-specific configuration
│       ├── roles/             # Ansible roles
│       └── vars/
│           ├── bootstrap_secrets.yml  # CRITICAL: git-crypt encrypted
│           ├── default.yml            # Default configuration
│           └── secrets.yml            # Legacy (to be deprecated)
└── deployed/                   # Production deployment files
    └── (copied to production server)
```

## Environment Architecture

### Test Environment (servyy-test.lxd)

- **Type:** LXC container on development machine
- **Hostname:** `servyy-test.lxd`
- **IP:** `10.185.182.207` (assigned by lxdbr0 bridge)
- **DNS:** Resolved via LXD DNS (systemd-resolved)
- **Purpose:** Full deployment testing before production changes
- **SSL:** mkcert self-signed certificates (local CA at `/etc/ssl/mkcert/`)
- **Inventory:** `ansible/testing`
- **Deployment Script:** `ansible/servyy-test.sh`
- **Container Profile:** `scripts/servyy-test.yaml`

**Test Container Features:**
- Nested LXC support (security.nesting=true)
- Privileged container (security.privileged=true)
- AppArmor unconfined (for Docker)
- Cloud-init SSH key injection
- Storage pool: `servyy` (directory-backed)
- Network: `lxdbr0` bridge

### Production Environment (servyy.lehel.xyz)

- **Type:** Physical/Virtual server
- **Hostname:** `servyy.lehel.xyz`
- **Purpose:** Live production deployment
- **SSL:** Let's Encrypt certificates
- **Inventory:** `ansible/production`
- **Deployment Script:** `ansible/servyy.sh`

## Setup Scripts

### Test Container Setup

**Script:** `/home/cda/dev/infrastructure/container/scripts/setup_test_container.sh`

**What it does:**
1. Creates LXC profile `servyy-test` from `servyy-test.yaml`
2. Creates storage pool `servyy` (if not exists)
3. Creates network bridge `lxdbr0` (if not exists)
4. Launches Ubuntu LXC container matching host OS version
5. Configures container as privileged with nesting enabled
6. Sets up local DNS resolution (systemd-resolved)
7. Waits for container to be accessible

**Usage:**
```bash
cd /home/cda/dev/infrastructure/container/scripts

# Create/start test container
./setup_test_container.sh

# Delete and recreate test container
./setup_test_container.sh -x
```

**After setup:**
- Container accessible at `servyy-test.lxd`
- SSH access: `ssh servyy-test.lxd` (uses injected SSH key)
- Ready for Ansible deployment via `ansible/servyy-test.sh`

### Container Profile (servyy-test.yaml)

Defines LXC container configuration:
- AppArmor profile: unconfined (required for Docker)
- SSH key: Automatically injected via cloud-init
- Network: Bridged to lxdbr0
- Storage: `servyy` pool
- User: `ubuntu` with passwordless sudo

## Deployment Scripts

### Test Deployment

**Script:** `ansible/servyy-test.sh`

```bash
#!/bin/zsh
set -x
ansible-playbook servyy.yml -i testing --skip-tags system.swap,ubuntu_pro "$@"
```

**Usage:**
```bash
cd /home/cda/dev/infrastructure/container/ansible

# Full deployment to test
./servyy-test.sh

# Deploy specific tags
./servyy-test.sh --tags docker

# Deploy specific roles
./servyy-test.sh --tags system

# Check mode (dry run)
./servyy-test.sh --check

# Verbose output
./servyy-test.sh -vvv
```

**Notes:**
- Skips `system.swap` and `ubuntu_pro` tags (not applicable for LXC containers)
- Uses `testing` inventory
- Passes all additional arguments to ansible-playbook

### Production Deployment

**Script:** `ansible/servyy.sh`

```bash
#!/bin/zsh
set -x
ansible-playbook servyy.yml -i production "$@"
```

**Usage:**
```bash
cd /home/cda/dev/infrastructure/container/ansible

# Full deployment to production
./servyy.sh

# Deploy specific tags
./servyy.sh --tags docker

# Check mode (dry run) - ALWAYS use before actual deployment
./servyy.sh --check
```

**CRITICAL:** Always test on servyy-test.lxd before running production deployment.

## Main Playbook Structure

**File:** `ansible/servyy.yml`

Imports four playbooks in sequence:
1. **plays/system.yml** - System-level configuration
   - Package installation
   - System services
   - Firewall rules
   - Storage Box configuration
   - Restic backup setup

2. **plays/user.yml** - User-level configuration
   - User creation
   - Docker setup
   - Docker Compose services
   - Environment files

3. **plays/leaguesphere.yml** - Application deployment
   - LeagueSphere application
   - Database configuration
   - Nginx/Traefik proxy

4. **plays/testing.yml** - Test-specific configuration
   - mkcert local CA
   - Vaultwarden testing
   - Extra hosts file entries

## Infrastructure Change Workflow

### CRITICAL POLICY - ZERO TOLERANCE

**NEVER make infrastructure changes directly on servers. ALL changes must go through Ansible.**

### Required Process

**1. Develop the Change**
- Create/modify Ansible playbooks, roles, or templates
- Update configuration in `/home/cda/dev/infrastructure/container/ansible`
- Document what changed and why

**2. Test on servyy-test.lxd (MANDATORY)**
```bash
# Deploy to test environment
cd /home/cda/dev/infrastructure/container/ansible
./servyy-test.sh

# Verify results
ssh servyy-test.lxd "verification commands here"

# Check logs
ssh servyy-test.lxd "journalctl -u service-name -n 50"
```

**3. Only After Successful Testing, Deploy to Production**
```bash
# Dry run first
./servyy.sh --check

# If dry run looks good, deploy
./servyy.sh

# Verify results
ssh servyy.lehel.xyz "verification commands here"
```

### Absolutely Forbidden Actions

**❌ NEVER:**
- SSH to production and edit files manually (vi/nano/sed/echo)
- Use scp/rsync to copy files directly to production
- Make "quick fixes" or "hotfixes" without Ansible
- Skip testing on servyy-test.lxd
- Assume "it's just a small change" makes testing optional
- Bypass automation for "urgent" changes

**✅ ALWAYS:**
1. Update Ansible automation
2. Test on servyy-test.lxd
3. Verify results
4. Deploy to production using same automation

### Why This Is Non-Negotiable

Real incidents that happened:
- Staging deployment overwrote production environment files
- Manual hotfixes corrupted running services
- Untracked changes couldn't be reproduced in disaster recovery
- Environment variable cross-contamination between staging and production

**Every manual change creates technical debt and disaster recovery risk.**

## Testing Workflow

### Complete Test Cycle

```bash
# 1. Setup/verify test container
cd /home/cda/dev/infrastructure/container/scripts
./setup_test_container.sh

# 2. Deploy infrastructure
cd ../ansible
./servyy-test.sh

# 3. Verify services
ssh servyy-test.lxd
ubuntu@servyy-test:~$ docker ps
ubuntu@servyy-test:~$ systemctl status docker
ubuntu@servyy-test:~$ curl -k https://pass.servyy-test.lxd
ubuntu@servyy-test:~$ exit

# 4. Run specific tests
./servyy-test.sh --tags testing.vaultwarden
./servyy-test.sh --tags testing.mkcert

# 5. If all tests pass, deploy to production
./servyy.sh --check
./servyy.sh
```

### Full Disaster Recovery Test

**Test complete infrastructure recovery from scratch:**

```bash
# 1. Delete test container completely
lxc delete servyy-test --force

# 2. Recreate from scratch
cd /home/cda/dev/infrastructure/container/scripts
./setup_test_container.sh

# 3. Deploy full infrastructure
cd ../ansible
./servyy-test.sh

# 4. Verify everything works:
# - Services running
# - Vaultwarden restored from backup
# - Applications accessible
# - Backups working
ssh servyy-test.lxd "docker ps && restic snapshots"
```

**Expected recovery time:** < 30 minutes (automated)

## Bootstrap Secrets (git-crypt)

**File:** `ansible/plays/vars/bootstrap_secrets.yml` (git-crypt encrypted)

**Purpose:** Contains ONLY the minimal secrets needed for disaster recovery.

**Contents:**
- Storage Box SSH key (for restic backup access)
- Vaultwarden API credentials (test and production)
- Vaultwarden master password (test only - prod requires human input)
- Restic password for HOME backup (`restic_password_home`)
- Restic password for ROOT backup (`restic_password_root`)

**Why minimal?**
- Reduces attack surface (fewer secrets in git)
- Vaultwarden is the primary secret store
- git-crypt only holds secrets needed to restore Vaultwarden

**Circular Dependency Resolution:**
- Vaultwarden data stored at `/home/cda/servyy-container/pass/vw-data`
- This directory is backed up by restic HOME backup
- Therefore `restic_password_home` MUST be in git-crypt bootstrap
- All other secrets can be stored in Vaultwarden and retrieved at runtime

## Disaster Recovery

### Scenario: Complete Infrastructure Loss

Everything lost except git-crypt unlock key (`local_keyfile`).

### Recovery Steps

```bash
# 1. Clone repository and unlock git-crypt
git clone https://github.com/dachrisch/infrastructure.git
cd infrastructure/container
git-crypt unlock /path/to/local_keyfile

# 2. For test environment:
cd scripts
./setup_test_container.sh
cd ../ansible
./servyy-test.sh

# 3. For production environment:
cd ansible
./servyy.sh
# (Will prompt for Vaultwarden master password)
```

**That's it!** The deployment is idempotent and will:
1. Deploy Storage Box SSH key from bootstrap_secrets.yml
2. Restore Vaultwarden from restic backup (if exists)
3. Start Vaultwarden container
4. Pull all other secrets from Vaultwarden
5. Deploy all infrastructure and applications

**Total Time:**
- Test environment: ~10-15 minutes
- Production environment: ~30-60 minutes (network-dependent)

## Secret Management with Vaultwarden

### Overview

Vaultwarden is the **PRIMARY** secret store (not a backup). The custom `vaultwarden` Ansible lookup plugin fetches secrets at deployment time.

### Lookup Plugin Configuration

**Plugin Path:** `ansible/plugins/lookup/vaultwarden.py`

**Configuration:** `ansible/ansible.cfg`
```ini
[defaults]
lookup_plugins = ./plugins/lookup
```

### Using Secrets in Playbooks

**Basic usage:**
```yaml
- name: Fetch database password
  set_fact:
    db_password: "{{ lookup('vaultwarden', 'apps/test/leaguesphere/db_credentials', field='password') }}"
    db_username: "{{ lookup('vaultwarden', 'apps/test/leaguesphere/db_credentials', field='username') }}"
```

**Available fields:**
- `username` - Login username
- `password` - Login password (default)
- `uris` - Login URIs
- `totp` - TOTP secret
- `notes` - Secure note content
- Custom field names (e.g., `host`, `database`, `port`)

**Environment Detection:**
The plugin automatically determines test vs production from the Vaultwarden server URL and adds the prefix `servyy/servyy-{environment}/` to item names.

### Item Naming Convention

**Format:** `servyy/servyy-{environment}/{category}/{env}/{service}/{secret_type}`

**Examples:**
- `servyy/servyy-test/infrastructure/test/storagebox/credentials`
- `servyy/servyy-test/apps/test/leaguesphere/db_credentials`
- `servyy/servyy-prod/apps/prod/leaguesphere/db_credentials`

**In playbooks, you only specify:** `apps/test/leaguesphere/db_credentials`
**Plugin automatically adds:** `servyy/servyy-test/` or `servyy/servyy-prod/`

### Initial Secret Migration

**Script:** `scripts/seed_vaultwarden.sh`

**Purpose:** ONE-TIME migration of secrets from git-crypt to Vaultwarden.

**IMPORTANT:** This is NOT used in disaster recovery. Disaster recovery restores Vaultwarden from restic backup.

**Usage:**
```bash
cd /home/cda/dev/infrastructure/container/scripts
./seed_vaultwarden.sh test   # Migrate test environment
./seed_vaultwarden.sh prod   # Migrate production environment
```

**What it does:**
- Reads secrets from git-crypt encrypted files
- Creates Vaultwarden items using `bw` CLI
- Validates files exist before creating items
- Uses proper naming convention with environment prefixes

## Common Operations

### Deploying Configuration Changes

```bash
# 1. Edit Ansible files
vim /home/cda/dev/infrastructure/container/ansible/plays/roles/user/tasks/docker_services.yml

# 2. Test on servyy-test
cd /home/cda/dev/infrastructure/container/ansible
./servyy-test.sh --tags docker

# 3. Verify
ssh servyy-test.lxd "docker ps"

# 4. Deploy to production
./servyy.sh --tags docker
```

### Deploying New Service

```bash
# 1. Add service configuration to appropriate role
vim ansible/plays/roles/user/templates/new-service.yml.j2

# 2. Add task to deploy service
vim ansible/plays/roles/user/tasks/docker_services.yml

# 3. Test deployment
./servyy-test.sh --tags docker

# 4. Verify service running
ssh servyy-test.lxd "docker ps | grep new-service"

# 5. Deploy to production
./servyy.sh --tags docker
```

### Updating Secrets

```bash
# 1. Update secret in Vaultwarden (web UI or bw CLI)

# 2. Re-deploy to pick up new secret
./servyy-test.sh --tags docker

# 3. Verify service with new secret
ssh servyy-test.lxd "verification commands"

# 4. Deploy to production
./servyy.sh --tags docker
```

### Restarting Services

**Via Ansible (preferred):**
```bash
./servyy-test.sh --tags docker
```

**Direct (only if Ansible unavailable):**
```bash
ssh servyy-test.lxd "docker restart service-name"
```

## Troubleshooting

### Test Container Issues

**Container won't start:**
```bash
# Check LXC status
lxc list
lxc info servyy-test

# Check logs
lxc console servyy-test

# Recreate container
cd /home/cda/dev/infrastructure/container/scripts
./setup_test_container.sh -x
./setup_test_container.sh
```

**DNS resolution not working:**
```bash
# Check DNS configuration
sudo resolvectl status lxdbr0

# Fix DNS
sudo resolvectl dns lxdbr0 "$(lxc network get lxdbr0 ipv4.address | cut -d'/' -f1)"
sudo resolvectl domain lxdbr0 "~$(lxc network get lxdbr0 dns.domain)"

# Test
host servyy-test.lxd
```

**SSH connection refused:**
```bash
# Wait for cloud-init to finish
lxc exec servyy-test -- cloud-init status --wait

# Check SSH service
lxc exec servyy-test -- systemctl status sshd

# Check known_hosts
ssh-keygen -f "$HOME/.ssh/known_hosts" -R "servyy-test.lxd"
```

### Ansible Issues

**Lookup plugin not found:**
```bash
# Verify ansible.cfg
cat ansible/ansible.cfg | grep lookup_plugins

# Should show:
# lookup_plugins = ./plugins/lookup
```

**Vault unlock fails:**
```bash
# Check Vaultwarden is running
ssh servyy-test.lxd "docker ps | grep vaultwarden"

# Check mkcert CA exists (test environment)
ssh servyy-test.lxd "ls -la /etc/ssl/mkcert/rootCA.pem"

# Check credentials in bootstrap_secrets.yml
cat ansible/plays/vars/bootstrap_secrets.yml | grep -A5 vaultwarden
```

**Deployment hangs:**
```bash
# Run with verbose output
./servyy-test.sh -vvv

# Check for specific task causing hang
# Ctrl+C and check last task in output
```

### Service Issues

**Docker service won't start:**
```bash
# Check service status
ssh servyy-test.lxd "systemctl status docker"

# Check Docker daemon
ssh servyy-test.lxd "docker info"

# Check logs
ssh servyy-test.lxd "journalctl -u docker -n 100"
```

**Container won't start:**
```bash
# Check container logs
ssh servyy-test.lxd "docker logs container-name"

# Check Docker Compose status
ssh servyy-test.lxd "cd /home/ubuntu/servyy-container && docker compose ps"

# Restart container
ssh servyy-test.lxd "docker restart container-name"
```

## Best Practices

### 1. Always Use Version Control
- Commit Ansible changes to git before testing
- Use meaningful commit messages
- Create branches for significant changes

### 2. Test Thoroughly
- Never skip testing on servyy-test.lxd
- Test failure scenarios (e.g., service restart, container recreate)
- Verify logs and service health after deployment

### 3. Use Ansible Tags
- Tag related tasks for selective deployment
- Use tags to speed up iterative testing
- Document tags in playbook comments

### 4. Document Changes
- Update CLAUDE.md when infrastructure changes
- Add comments to complex playbook tasks
- Keep README files current

### 5. Security
- Never commit plaintext secrets to git
- Use git-crypt for bootstrap secrets
- Store runtime secrets in Vaultwarden
- Rotate secrets periodically

### 6. Idempotency
- Ensure playbooks can run multiple times safely
- Use proper Ansible modules (not shell when possible)
- Test idempotency by running deployment twice

### 7. Backup Verification
- Regularly test disaster recovery procedure
- Verify restic backups are current
- Test Vaultwarden restore from backup

## Quick Reference

### Common Commands

```bash
# Test container
cd /home/cda/dev/infrastructure/container/scripts
./setup_test_container.sh              # Create/start test container
./setup_test_container.sh -x           # Delete and recreate

# Deployment
cd /home/cda/dev/infrastructure/container/ansible
./servyy-test.sh                       # Deploy to test
./servyy-test.sh --check               # Dry run (test)
./servyy-test.sh --tags docker         # Deploy specific tags
./servyy.sh                            # Deploy to production
./servyy.sh --check                    # Dry run (production)

# Container management
lxc list                               # List containers
lxc info servyy-test                   # Container details
lxc exec servyy-test -- bash           # Console access
lxc stop servyy-test                   # Stop container
lxc start servyy-test                  # Start container
lxc delete servyy-test --force         # Delete container

# SSH access
ssh servyy-test.lxd                    # Test environment
ssh servyy.lehel.xyz                   # Production

# Docker (on remote)
docker ps                              # List containers
docker logs service-name               # View logs
docker restart service-name            # Restart service
docker compose ps                      # Compose services status
```

### File Locations

```bash
# Local development
/home/cda/dev/infrastructure/container/

# On servyy-test.lxd (after deployment)
/home/ubuntu/servyy-container/         # Docker compose files
/etc/ssl/mkcert/                       # Local CA certificates
/etc/systemd/system/                   # Systemd services

# On servyy.lehel.xyz (production)
/home/provision/servyy-container/      # Docker compose files
/etc/letsencrypt/                      # SSL certificates
```

## Emergency Procedures

### Critical Service Down

1. **Check service status**
2. **Review logs immediately**
3. **Attempt service restart**
4. **If restart fails, check configuration**
5. **Contact on-call if needed**
6. **Document incident**

### Data Loss

1. **Stop all services immediately**
2. **Assess extent of data loss**
3. **Restore from most recent backup**
4. **Verify restored data integrity**
5. **Resume services**
6. **Document incident and improve backup strategy**

### Security Incident

1. **Isolate affected systems**
2. **Assess breach scope**
3. **Rotate all secrets immediately**
4. **Review access logs**
5. **Apply security patches**
6. **Document incident and improve security**
