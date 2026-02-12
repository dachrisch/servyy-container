# OpenCode Service: Web Interface Integration

**Date:** 2026-02-12
**Status:** ✅ Completed
**Branch:** `feature/opencode` (merged to master)

## Problem

Required a self-hosted instance of OpenCode (anomalyco) with a web-based interface for LLM-assisted coding tasks, integrated into the existing `servyy-container` infrastructure behind Traefik.

## Solution

Integrated OpenCode as a new Docker service:
- **Image:** `ghcr.io/anomalyco/opencode:latest`
- **Interface:** Web UI enabled via `opencode web` command.
- **Port:** 4096 (standard OpenCode port).
- **Authentication:** HTTP Basic Auth secured via `OPENCODE_SERVER_PASSWORD`.
- **Persistence:** Persistent configuration and data stored in `opencode/data/`.
- **Reverse Proxy:** Traefik routing with TLS support via `opencode.lehel.xyz`.

## Implementation

### Files Created/Modified

**opencode/docker-compose.yml:**
- Defined the `opencode` service.
- Configured Traefik labels for routing, TLS, and load balancing.
- Set up volume mounts for persistent data.
- Configured environment variables via `.env` (generic) and `opencode.env` (app-specific).

**ansible/plays/vars/secrets.yml:**
- Added `OpenCode` to the `docker.services` registry.
- Added `opencode.server_password` for secure authentication.

**ansible/plays/roles/user/templates/opencode.env.j2:**
- Template for deploying `OPENCODE_SERVER_PASSWORD`.

**ansible/plays/roles/user/tasks/docker_repo_env.yml:**
- Added task to deploy `opencode.env`.

**ansible/plays/roles/user/tasks/docker_services.yml:**
- Added task to create the `opencode/data` directory with correct permissions.

### Architecture

```
Internet → Traefik (HTTPS, 443) 
           ↳ Router: opencode.lehel.xyz
             ↳ Service: opencode.app (Port 4096)
               ↳ Authentication: Basic Auth (opencode:PASSWORD)
```

## Deployment Timeline

1. **Created feature branch:** `feature/opencode`
2. **Scaffolded service:** `opencode/docker-compose.yml`
3. **Updated Ansible configuration:** Roles, templates, and secrets.
4. **Verified on test environment:** Deployed to `servyy-test.lxd`.
5. **Merged to master:** 2026-02-12
6. **Deployed to production:** 2026-02-12 23:10 CET

### Deployment Steps

```bash
# Push changes
git push origin master

# Deploy via Ansible
cd ansible
./servyy.sh --tags user.repo,user.docker.opencode,user.docker.env,user.docker.services.start --limit lehel.xyz
```

## Verification

### Container Status

```bash
$ ssh lehel.xyz "docker ps | grep opencode"
opencode.app         Up 5 minutes
```

### Logs Verification

```bash
$ ssh lehel.xyz "docker logs opencode.app --tail 20"
                                   ▄     
  █▀▀█ █▀▀█ █▀▀█ █▀▀▄ █▀▀▀ █▀▀█ █▀▀█ █▀▀█
  █  █ █  █ █▀▀▀ █  █ █    █  █ █  █ █▀▀▀
  ▀▀▀▀ █▀▀▀ ▀▀▀▀ ▀▀▀▀ ▀▀▀▀ ▀▀▀▀ ▀▀▀▀ ▀▀▀▀

  Local access:        http://localhost:4096
```

### Connectivity & Auth Check

```bash
# Basic Auth check (should return 401 without credentials)
$ curl -I https://opencode.lehel.xyz
HTTP/2 401
www-authenticate: Basic realm="Secure Area"
```

✅ **All checks passed**

## Operational Notes

### Authentication
- **Username:** `opencode` (Default)
- **Password:** Defined in `ansible/plays/vars/secrets.yml` (`opencode.server_password`).

### Configuration
OpenCode handles its own internal configuration (LLM API keys, etc.) via its Web UI, which are persisted in the `data/` volume.

## Rollback Plan

If issues arise:

```bash
# Option 1: Revert git commit
git revert <commit-id>
git push origin master
./servyy.sh --tags "user.repo,user.docker.services.start" --limit lehel.xyz

# Option 2: Stop service manually
ssh lehel.xyz "cd servyy-container/opencode && docker compose down"
```

## Lessons Learned

1. **Username Defaults:** OpenCode uses `opencode` as the default username for Basic Auth, which differs from common defaults like `admin`.
2. **Environment Variable Renaming:** Ensure environment variable names match the latest upstream versions (`OPENCODE_SERVER_PASSWORD` vs older `OPENCODE_PASSWORD`).
3. **Repository Sync:** Remember that Ansible clones from the remote repository; local changes must be pushed before they are visible to the deployment on the target host.
