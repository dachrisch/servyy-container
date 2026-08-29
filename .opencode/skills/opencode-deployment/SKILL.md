---
name: opencode-deployment
description: Deploy and troubleshoot opencode service on lehel.xyz production
triggers:
  - deploy
  - prod
  - production
  - error
  - inspect
  - logs
  - container
  - ".lehel.xyz"
  - "502"
  - "down"
delegates_to:
  - opencode-contribution
reads:
  - docker-compose.yml
  - ansible/plays/roles/opencode
  - opencode/.env (on server)
  - service configuration
---

# OpenCode Deployment & Service Management

This skill manages opencode service deployment, diagnostics, and troubleshooting on lehel.xyz.

## Architecture Overview

**Production Environment: lehel.xyz**

```
Internet → traefik.lehel.xyz (reverse proxy) → Docker proxy network → opencode.web container
                                                         ↓
                                                 /root/.config/opencode/
                                                 (skills directory)
```

**Service Naming:**
- Container: `opencode.web`
- URL: `opencode.lehel.xyz` (https)
- Web Interface: `opencode.lehel.xyz:4096` (internal port)

**Key Volumes:**
- `opencode_root:/root` - Persists ~/.config, ~/.ssh, git clones
- `./scripts:/scripts:ro` - Startup scripts (read-only)
- `./bin:/opencode/bin:ro` - gh CLI wrapper (read-only)
- `./.ssh:/root/.ssh` - SSH keys for GitHub & lehel.xyz SSH

## SSH Access to Production

All diagnostics require SSH into lehel.xyz as `cda` user:
```bash
ssh lehel.xyz "docker ps | grep opencode"
ssh lehel.xyz "docker logs opencode.web --tail 50"
ssh lehel.xyz "docker exec opencode.web /bin/sh -c 'command here'"
```

## Common Diagnostics

### Check Container Status

```bash
# Is container running?
ssh lehel.xyz "docker ps | grep opencode"

# Container not in list? Check stopped containers
ssh lehel.xyz "docker ps -a | grep opencode"

# View container stats
ssh lehel.xyz "docker stats opencode.web --no-stream"
```

### View Logs

```bash
# Last 50 lines
ssh lehel.xyz "docker logs opencode.web --tail 50"

# Follow logs in real-time
ssh lehel.xyz "docker logs opencode.web --follow"

# Logs since last restart
ssh lehel.xyz "docker logs opencode.web --since 30m"
```

### Inspect Configuration

```bash
# Environment variables
ssh lehel.xyz "docker exec opencode.web env | grep -i opencode"

# .env file (volume-mounted)
ssh lehel.xyz "cat /home/cda/servyy-container/opencode/.env"

# Skills directory exists?
ssh lehel.xyz "docker exec opencode.web ls -la ~/.config/opencode/skills/"

# Check container IP/network
ssh lehel.xyz "docker inspect opencode.web | grep -A 5 'Networks'"
```

### Restart Container

```bash
# Graceful restart (recommended)
ssh lehel.xyz "docker restart opencode.web"

# Verify restart succeeded
ssh lehel.xyz "docker ps | grep opencode"
```

## Health Checks

```bash
# Traefik routing active?
ssh lehel.xyz "curl -I https://opencode.lehel.xyz"

# Container health status
ssh lehel.xyz "docker inspect opencode.web --format='{{.State.Health.Status}}'"

# Service responding?
ssh lehel.xyz "docker exec opencode.web curl -I http://localhost:4096/health"
```

## Common Issues & Diagnosis

### 502 Bad Gateway

**Symptom:** `opencode.lehel.xyz` returns 502 error

**Diagnosis steps:**
1. Container running? `docker ps | grep opencode`
2. Container healthy? Check health status above
3. Port mapping? `docker exec opencode.web curl http://localhost:4096/health`
4. View container logs: `docker logs opencode.web --tail 50`

**Common causes:**
- Container crash/restart loop → Check logs
- Port 4096 not responding → Check app startup
- Environment variable missing → Check `.env` file

### Container Won't Start

**Check logs first:**
```bash
ssh lehel.xyz "docker logs opencode.web"
```

**Common reasons:**
- Missing `.env` file: Check volume mount
- Startup script error: SSH into container, run startup.sh manually
- Port conflict: Check `docker ps` for port 4096 conflicts

**Debug inside container:**
```bash
ssh lehel.xyz "docker exec -it opencode.web /bin/sh"
# Then manually test startup steps, check env vars, etc.
```

### Skills Directory Empty

**Check if deployed:**
```bash
ssh lehel.xyz "docker exec opencode.web ls -la ~/.config/opencode/skills/"
```

**If missing or empty:**
1. Check source directory in git: `.opencode/skills/`
2. Re-deploy: `cd ansible && ./servyy.sh --tags "user.docker.opencode" --limit lehel.xyz`
3. Restart container: `ssh lehel.xyz "docker restart opencode.web"`

## Deployment Workflow

**IMPORTANT:** Always test on test environment FIRST (if skills modified).

```bash
# 1. Verify changes in git
git status

# 2. Test on test environment
cd ansible && ./servyy-test.sh --tags "user.docker.opencode"

# 3. Verify test deployment
ssh servyy-test.lxd "docker ps | grep opencode"
ssh servyy-test.lxd "docker exec opencode.web ls -la ~/.config/opencode/skills/"

# 4. Deploy to production (after user approval)
cd ansible && ./servyy.sh --tags "user.docker.opencode" --limit lehel.xyz

# 5. Verify production
ssh lehel.xyz "docker ps | grep opencode"
ssh lehel.xyz "docker logs opencode.web --tail 20"
```

## Deployment Tags

- `user.docker.opencode` - Only opencode service updates
- `docker` - All Docker services (slower, includes all services)
- Full deployment: `servyy.sh --limit lehel.xyz` (everything)

## When to Delegate

- **To opencode-contribution skill:** If issue is in project code/logic
- **To opencode-dependency skill:** If ansible playbook AND service need coordinated changes

## Key Paths on Server

| Path | Purpose |
|------|---------|
| `/home/cda/servyy-container/opencode/` | Service root on server |
| `/home/cda/servyy-container/opencode/.env` | Service environment file |
| `/home/cda/servyy-container/opencode/docker-compose.yml` | Compose config |
| `/home/cda/servyy-container/opencode/scripts/` | Startup scripts |
| Container: `/root/.config/opencode/skills/` | Deployed skills directory |
| Container: `/root/.ssh/` | SSH keys for auth |

## Container Port Mapping

- Host: 4096 (internal)
- Reverse proxy: Traefik (handles 443/80 → 4096)
- Health check: `curl http://localhost:4096/health`

## Monitoring

**Traefik logs for routing issues:**
```bash
ssh lehel.xyz "docker logs traefik.traefik --tail 50 | grep opencode"
```

**Docker daemon logs:**
```bash
ssh lehel.xyz "journalctl -u docker --no-pager -n 30"
```

**Container restart history:**
```bash
ssh lehel.xyz "docker inspect opencode.web --format='{{.RestartCount}} restarts'"
```

## Verification Checklist After Deployment

- [ ] Container is running: `docker ps | grep opencode`
- [ ] Health check passing: `docker inspect ... --format='{{.State.Health.Status}}'`
- [ ] Skills directory deployed: `docker exec opencode.web ls ~/.config/opencode/skills/`
- [ ] Service accessible: `curl -I https://opencode.lehel.xyz`
- [ ] No restart loops: `docker inspect ... | grep -i restart`
- [ ] Logs clean: `docker logs opencode.web --tail 20` (no errors)
