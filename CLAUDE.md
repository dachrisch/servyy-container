# CLAUDE.md - servyy-container Infrastructure

> Self-hosted microservices platform (15+ Docker services) automated with Ansible
> **Last Updated:** 2025-11-23

## Quick Commands

```bash
# Production deployment
cd ansible && ./servyy.sh

# Test deployment
cd scripts && ./setup_test_container.sh && cd ../ansible && ./servyy-test.sh

# Service management
./scripts/status_docker_services.sh      # Check status
./scripts/startup_docker_services.sh     # Start all

# Ansible operations
ansible-playbook servyy.yml --syntax-check           # Validate
ansible-playbook servyy.yml --tags "user.docker.env" # Regen .env files
ansible-playbook servyy.yml --tags "docker"          # Docker only
ansible-playbook servyy.yml --limit lehel.xyz        # Single host
```

## git-crypt (CRITICAL)

**Encrypted patterns** (per `.gitattributes`):
- `docker-compose.yml`, `*.yaml`, `*.env`, `*.conf`, `secrets.*`, `secret_*`

**Rules:**
- Files appear as **plaintext when unlocked** - edit normally
- Auto-encrypted on commit
- Check status: `git-crypt status`
- Ansible auto-unlocks during deployment

## Architecture

```
Internet → Porkbun DNS (*.lehel.xyz) → Hetzner Firewall → Traefik (443/80)
    → Docker "proxy" network → Services
```

**Tech Stack:** Docker Compose | Traefik | Ansible | git-crypt | Prometheus/Grafana | rsync to Hetzner Storagebox

## Service Naming Convention

```
URL = {directory-name}.{inventory-hostname}
Example: photoprism/ → https://photoprism.lehel.xyz
```

**Environments:**
- Production: `*.lehel.xyz`
- Dev: `*.aqui.fritz.box`
- Test: `*.servyy-test.lxd`

## Services

| Service | URL | Purpose |
|---------|-----|---------|
| traefik | traefik.lehel.xyz | Reverse proxy, SSL |
| photoprism | photoprism.lehel.xyz | Photo library (MariaDB) |
| social | social.lehel.xyz | Pleroma (PostgreSQL) |
| git | git.lehel.xyz | Git hosting |
| monitor | monitor.lehel.xyz | Prometheus + Grafana |
| dns | dns.lehel.xyz | PiHole |
| portainer | portainer.lehel.xyz | Docker UI |
| pass | pass.lehel.xyz | Password manager |
| logging | logging.lehel.xyz | Centralized logging |

**Other:** achim-hoefer, bumbleflies, energy, jobs, me (static sites)

## Ansible Structure

```
ansible/
├── servyy.yml           # Main playbook
├── servyy.sh            # Production wrapper
├── servyy-test.sh       # Test wrapper
├── inventory/
│   ├── production       # lehel.xyz, aqui.fritz.box
│   └── testing_inventory
└── plays/
    ├── system.yml       # OS setup (packages, user, storage, monit)
    ├── user.yml         # Docker + services
    └── roles/{system,user,testing,ls_*}/
```

**Tags:** `system`, `docker`, `backup`, `user.docker.env`

## Adding a New Service

1. Create `{service}/docker-compose.yml`:
```yaml
services:
  app:
    image: {image}
    networks: [proxy]
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.${SERVICE_NAME}.rule=Host(`${SERVICE_HOST}`)"
      - "traefik.http.routers.${SERVICE_NAME}.entrypoints=websecure"
      - "traefik.http.routers.${SERVICE_NAME}.tls.certresolver=letsencrypt"
networks:
  proxy:
    external: true
```

2. Deploy: `ansible-playbook servyy.yml --tags "docker"`

## Key Scripts

| Script | Purpose |
|--------|---------|
| `scripts/setup_test_container.sh` | Create LXD test container |
| `scripts/delete_test_container.sh` | Remove test container |
| `scripts/cleanup_space.sh` | Free disk space |
| `hetzner/update_firewall.sh` | Update Hetzner firewall |

## Backup & Monitoring

**Backups** (daily via systemd timers to `/mnt/storagebox/backup/`):
- Home directory (03:00 UTC)
- Root filesystem (04:00 UTC)
- PhotoPrism DB (02:00 UTC)

**Monitoring:**
- monit: System-level (SSH, disk, memory)
- Prometheus + Grafana: Metrics & dashboards
- cAdvisor + Node Exporter: Container & system metrics

## Troubleshooting

```bash
# Service issues
docker logs {container}
docker-compose config
cat /home/user/containers/{service}/.env

# Network issues
docker network inspect proxy
docker logs traefik

# Backup issues
mount | grep storagebox
systemctl --user list-timers
```

## Conventions

**Commits:** `<type>: <description>` (feat/fix/chore/refactor/docs)

**Branches:** `master` (production), `claude/*` (dev)

**History logs:** For major changes, create `history/YYYY-MM-DD_description.md`

## Key Paths

| Location | Purpose |
|----------|---------|
| `/home/user/containers/{service}/` | Service directories (on server) |
| `/mnt/storagebox/backup/` | Backups |
| `ansible/plays/vars/secrets.yml` | Encrypted secrets |
| `ansible/plays/roles/user/templates/docker.env.j2` | .env template |
