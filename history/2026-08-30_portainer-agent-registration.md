# 2026-08-30 — Portainer agent registration (server ↔ agent handshake)

## Problem

PR #85 deployed a Portainer **server** (`servy.lehel.xyz`, `49.13.6.173`) and a
**agent** (`codey.lehel.xyz`, `217.217.227.124`). Both were reachable, but wiring
the agent into the server as an *Agent* environment failed at `POST /api/endpoints`
with `400 Invalid environment name` and later `500 Agent already paired with another
Portainer instance`.

The RBAC role (`ansible/plays/roles/portainer_rbac`) is opt-in
(`-e portainer_rbac_enabled=true --tags user.portainer-rbac`, host
`servy.lehel.xyz`).

## Root causes & fixes

### 1. Agent has no `--name` flag (crash loop)
`portainer/agent` reports its name from `os.Hostname()`; it has **no** `--name`/`--agent-name`
flag. Adding `command: ["--name","codey"]` crash-looped the agent
(`unknown long flag '--name'`).
**Fix:** `hostname: codey` in `portainer-agent/docker-compose.yml`.

### 2. `400 Invalid environment name` — wrong request format
Portainer's `POST /api/endpoints` reads `Name` from **multipart/form-data**, not JSON
(`endpoint_create.go` → `RetrieveMultiPartFormValue(r,"Name",false)` returns the literal
"invalid environment name" when `Name` is absent). The role posted JSON with the wrong key
(`EndpointType` instead of `EndpointCreationType`) and `TLS: false`.
**Fix:** `body_format: form-multipart` with `EndpointCreationType=2`, `TLS=true`,
`TLSSkipVerify=true`, `TLSSkipClientVerify=true`, `ContainerEngine=docker`.
(Also required: `TLSSkipClientVerify=true` or the server demands a client cert file → 400
"Invalid certificate file".)

### 3. `500 Agent already paired` — server must share the agent secret
The agent runs in **secret mode** (`AGENT_SECRET` env set). The server verifies signed
requests using the shared secret, which it reads from the **`AGENT_SECRET` environment
variable**, *not* from Settings (the `PUT /api/settings` `AgentSecret` field is blanked in
responses and is not applied at request time). Without it, the server's requests lack the
secret → agent rejects the signature.
**Fix:** added `AGENT_SECRET: ${AGENT_SECRET}` to the server compose
(`portainer/docker-compose.yml`) and its env template
(`ansible/plays/roles/docker_service/templates/portainer/docker.env.j2`), both sourced from
`portainer.agent_secret`.

### 4. Idempotency (role)
The role now also `PUT /api/settings` with `AgentSecret` (harmless / redundant given the env
var) so a fresh server without the env would still pair. Endpoint registration is guarded by
`when: no endpoint named 'codey' exists`, so re-runs are no-ops.

## Files changed
- `portainer-agent/docker-compose.yml` — `hostname: codey` (was crashing `--name` command)
- `portainer/docker-compose.yml` — server `environment: AGENT_SECRET: ${AGENT_SECRET}`
- `ansible/plays/roles/docker_service/templates/portainer/docker.env.j2` — `AGENT_SECRET=…`
- `ansible/plays/roles/portainer_rbac/tasks/main.yml` — multipart registration + AgentSecret PUT
- `ansible/plays/user.yml` — RBAC play host renamed `servy.lehel.xyz` (PR #84 host rename)
- `ansible/plays/vars/secrets.yml` — `portainer.admin_password` + `portainer.api_user: cda`
  (the stale `admin` creds no longer worked)
- `portainer-agent/docker.env.j2` — `AGENT_SECRET` already present

## Verification
- Agent `/v2/ping` = `204` from server over IPv4 **and** IPv6 (Traefik `serversTransport`
  `insecureSkipVerify` + IP allowlist `49.13.6.173/32,172.18.0.0/16`).
- `POST /api/endpoints` (multipart) → `200`:
  `{"Id":9,"Name":"codey","Type":2,"Status":1,"URL":"https://a.codey.lehel.xyz","Agent":{"Version":"2.45.0"}}`
  (`Status:1` = server can reach + snapshot the agent).
- Full RBAC role idempotent: `ok=31 changed=0 failed=0` on re-run.

## Deployment notes
- Server deploy tag: `user.docker.portainer` (on `servy.lehel.xyz`).
- Agent deploy tag: `user.docker.portainer-agent` (on `codey.lehel.xyz`).
- Compose is read from the remote clones `/home/cda/servyy-container/portainer` (server) and
  `/home/cda/servyy-container/portainer-agent` (agent); `git pull` there before deploy.
- Portainer server + agent are both `2.45.0`.

## Known issues / follow-ups
- The `PUT /api/settings` AgentSecret step in the role is redundant now that the server uses the
  `AGENT_SECRET` env var; left in for defense-in-depth.
- `portainer_rbac.teams` / `portainer_rbac.users` are still empty — RBAC teams/users can be added
  later via `vars` without changing the role.
