# GEMINI.md - servyy-container Infrastructure

Comprehensive context for the `servyy-container` self-hosted microservices platform.

## Project Overview

`servyy-container` is a self-hosted infrastructure platform managing over 15 microservices using a combination of **Ansible** for orchestration and **Docker Compose** for service definitions.

### Key Technologies
- **Orchestration:** Ansible
- **Containerization:** Docker & Docker Compose v2
- **Reverse Proxy:** Traefik (with Let's Encrypt DNS-01 challenge)
- **Observability:** Prometheus, Grafana, Loki, Promtail
- **Security:** fail2ban (integrated with Loki), Hetzner Firewall, Monit
- **Backups:** Restic (stored on Hetzner Storagebox)
- **Secret Management:** git-crypt

### Core Architecture
The infrastructure follows a GitOps-like approach where the state is defined in this repository. Ansible ensures the remote server matches the repository state by:
1. Cloning the repository on the target host.
2. Generating environment files (`.env`) from templates and secrets.
3. Orchestrating Docker Compose deployments.
4. Configuring system-level services (backups, security, maintenance).

## Directory Structure

- `ansible/`: Main Ansible configuration.
  - `plays/`: Playbooks (`system.yml`, `user.yml`, etc.).
  - `roles/`: Modular Ansible roles (`system`, `user`, `testing`, `ls_*`).
  - `vars/`: Variables and secrets (managed via git-crypt).
- `scripts/`: Utility scripts for environment setup and maintenance.
- `history/`: Detailed records of major infrastructure changes and migrations.
- `[service-name]/`: Individual directories for each microservice (e.g., `traefik/`, `monitor/`, `photoprism/`), each containing a `docker-compose.yml`.

## Building and Running

### Deployment Commands

```bash
# Production deployment (targets lehel.xyz)
cd ansible && ./servyy.sh

# Test deployment (targets servyy-test.lxd)
cd scripts && ./setup_test_container.sh
cd ../ansible && ./servyy-test.sh

# Deploy specific components using tags
./servyy.sh --tags "docker"      # Only update Docker services
./servyy.sh --tags "backup"      # Only update backup configuration
./servyy.sh --tags "fail2ban"    # Only update security rules
```

### Verification

```bash
# Check running containers on production
ssh lehel.xyz "docker ps"

# Verify Traefik logs
ssh lehel.xyz "docker logs traefik.traefik --tail 50"

# Check active fail2ban jails
ssh lehel.xyz "sudo fail2ban-client status"
```

## Development Conventions

### Git Workflow
- **Branching:** Use `claude/feature-name` for development. `master` is reserved for production-ready state.
- **Commits:** Follow conventional commits: `<type>: <description>` (e.g., `feat: add new service`, `fix: update prometheus config`).
- **Secret Management:** Secrets are stored in `ansible/plays/vars/secrets.yml` and other `*.yaml`/`*.env` files. Ensure `git-crypt` is unlocked before editing.

### Deployment Rules
1. **Never** manually edit files on the server. Always use the Git -> Ansible workflow.
2. **Always** test changes on the LXD test environment before production.
3. **Always** request explicit user approval before running `servyy.sh` against production (`lehel.xyz`).

### Testing (Molecule)
New Ansible features or role modifications **must** include Molecule tests.
- Tests are located in `ansible/plays/roles/[role]/molecule/`.
- Run tests locally on `servyy-test.lxd` before pushing to CI.

### Logging & Monitoring
- **Container Names:** Follow the pattern `{directory}.{service}` (e.g., `monitor.grafana`).
- **Loki Queries:** Use `query_range` for log streams. Use the `container` label for filtering.
- **Retention:** Journald is limited to 500MB/4 weeks; Loki has a 31-day retention policy.

## Automated Maintenance
The infrastructure includes several automated maintenance tasks deployed via systemd timers:
- **Docker Cleanup:** Weekly aggressive prune of unused images and volumes.
- **Kernel Cleanup:** Monthly removal of old kernel packages.
- **Backups:** Daily restic backups of home, root, and database directories.
- **Log Rotation:** Managed via journald and logrotate for custom logs.
