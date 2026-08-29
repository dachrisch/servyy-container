# Portainer Master/Slave Deployment

**Date:** 2026-08-29 | **Status:** Implemented (config) — production deploy pending
**Issue:** [#83](https://github.com/dachrisch/servyy-container/issues/83)

## What Was Added

- **Agent service** `portainer-agent/` (docker-compose.yml + .gitignore) on `code.lehel.xyz`.
  Exposed at `a.codey.lehel.xyz` via Traefik with an IP allowlist restricting access
  to the master (`49.13.6.173` only). No raw host ports published.
- **Env templates** for both the server (`portainer/docker.env.j2`, injects
  `PORTAINER_ADMIN_PASSWORD`) and the agent (`portainer-agent/docker.env.j2`, injects
  `AGENT_SECRET`). Both share `COMPOSE_PROJECT_NAME=portainer` so container names are
  `portainer.portainer` / `portainer.agent`.
- **Secrets** (`secrets.yml`): `portainer.admin_password` (plaintext, used by RBAC API
  auth), `portainer.admin_password_bcrypt` (injected into the server env), and
  `portainer.agent_secret` (shared auth between server and agent).
- **Ansible registration**: `portainer-agent` role in `user.yml` (tags
  `user.docker.portainer-agent`) and `portainer-agent: true` in the `code.lehel.xyz`
  inventory. The server role now uses the custom env template.
- **RBAC automation** (`roles/portainer_rbac` + `vars/portainer-rbac.yml`): idempotently
  registers the `codey.lehel.xyz` agent endpoint and creates the `leaguesphere` team with
  Operator access. Opt-in via `-e portainer_rbac_enabled=true`.

## Required Before Production Deploy (manual)

1. **DNS**: create `A` + `AAAA` records for `a.codey.lehel.xyz` → `217.217.227.124`
   (matching the master IP in the agent's Traefik `ipallowlist`). Without these, Let's
   Encrypt cert provisioning fails. (Plan Task 6.)
2. **git-crypt key backup** (Plan Task 1) — keep an offline copy of the key.
3. **Deploy order**: server (`--limit lehel.xyz --tags user.docker.portainer`) then agent
   (`--limit code.lehel.xyz --tags user.docker.portainer-agent`), then verify cross-host
   connectivity, then run RBAC (`-e portainer_rbac_enabled=true --tags user.portainer-rbac`).
   (Plan Tasks 5/7/8.)

## Verification

```bash
ssh lehel.xyz "docker ps | grep portainer.portainer"   # healthy
ssh code.lehel.xyz "docker ps | grep portainer.agent"  # healthy
ssh lehel.xyz "curl -k https://a.codey.lehel.xyz/api/agent/ping"  # reachable from master
```

## Access

- URL: https://portainer.lehel.xyz (admin; password in `secrets.yml`)
- Team: `leaguesphere` (Operator: observe + restart)
- Manual fallback: configure teams/users in the UI if the API automation is not used.
