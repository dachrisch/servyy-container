# opencode API-key access for automated clients — Design

**Date:** 2026-08-08
**Status:** Approved (brainstorm) — pending spec review → implementation plan
**Related:** `history/2026-02-12_opencode-web-integration.md`, CLAUDE.md § "Off-host Password Backup (Vaultwarden)"

## Problem

opencode (`opencode/`) is deployed with a single auth mechanism: HTTP Basic Auth enforced by the
`opencode` binary itself via `OPENCODE_SERVER_PASSWORD` (username fixed at `opencode`, no native
API-key or certificate support — confirmed against the running instance's `/doc` OpenAPI 3.1 spec
and upstream issue `anomalyco/opencode#5256`, an unresolved feature request for exactly this).

A second, automated client (a script/web process) needs to drive opencode's chat API — creating
sessions and sending/receiving messages, streaming responses — without sharing the human
operator's Basic Auth password. That client should not be able to reach the filesystem, shell/PTY,
project/VCS, or credential-management parts of the API.

## Goal

1. A distinct, revocable API key that a client presents via an `X-Api-Key` header to drive
   opencode's session/chat endpoints.
2. That key must not grant filesystem, shell/PTY, VCS/project, or credential-management access —
   only session creation and interaction within a session the client already knows the ID of (no
   listing of other sessions).
3. The human web UI (Basic Auth) is unaffected — this is a second, narrower door, not a
   replacement.
4. Defense in depth is preserved: opencode's own Basic Auth requirement stays enforced on the wire
   between Traefik and the app; nothing bypasses it.

**Non-goals:** wiring a web-search / searxng MCP tool into opencode's agent config (separate
follow-up); multiple named API keys for multiple clients (no second client exists yet — YAGNI,
revisit if one shows up); certificate/mTLS auth (API key was the chosen direction after comparing
options).

## Design

### 1. Architecture

```
API client → https://opencode.lehel.xyz/api/session/...  (header: X-Api-Key)
                │
                ▼
   Traefik router "opencode_apikey" (new, path-scoped, traefik/dynamic.yaml)
                │  middleware: forwardAuth → opencode-authgate (Caddy, internal-only)
                │  Caddy checks X-Api-Key; on match, responds 200 + Authorization: Basic <opencode creds>
                │  Traefik copies that header onto the forwarded request (authResponseHeaders)
                ▼
        opencode.web:4096  ← still enforces its own OPENCODE_SERVER_PASSWORD Basic Auth

Human browser → https://opencode.lehel.xyz/  (existing Host-only router, unchanged)
                ▼
        opencode.web:4096  ← prompts for Basic Auth as it does today
```

opencode never learns about API keys — it keeps demanding the same Basic Auth it always has. The
`opencode-authgate` container holds the mapping from API key → those Basic Auth credentials, and
only Traefik can reach it: no Traefik labels, no public router, no domain, no TLS cert.

### 2. `opencode-authgate` service

New top-level service directory, same flat pattern as every other service in this repo:

- `opencode-authgate/docker-compose.yml` — off-the-shelf `caddy:2-alpine`, no build step, on the
  `proxy` network. Chosen over a custom-built microservice (this repo has no custom-built images
  anywhere — everything is `image: <prebuilt>` + config/env templates) and over a third-party
  Traefik plugin (unofficial dependency, no clean way to rewrite the request into Basic Auth for
  opencode, would force disabling `OPENCODE_SERVER_PASSWORD` and losing app-level defense in
  depth).
- `opencode-authgate/Caddyfile` — static, checked into git plaintext (no secrets in it, just
  `{$OPENCODE_API_KEY}` / `{$OPENCODE_BASIC_AUTH_B64}` placeholders Caddy substitutes from its own
  environment at startup). Not git-crypt encrypted — it holds no secret values, only references.
- New role invocation in `ansible/plays/user.yml`: `service_dir: opencode-authgate`, tag
  `user.docker.opencode-authgate`, same `docker_service` role every other service uses.
- New env template `ansible/plays/roles/docker_service/templates/opencode-authgate/.env.j2`:
  ```
  OPENCODE_API_KEY={{ opencode.api_key }}
  OPENCODE_BASIC_AUTH_B64={{ ('opencode:' + opencode.server_password) | b64encode }}
  ```
  The raw `server_password` never leaves `secrets.yml`/`opencode.env` — the authgate only ever
  holds the precomputed Basic Auth token.

### 3. Secret: `opencode.api_key`

New key in `ansible/plays/vars/secrets.yml` (git-crypt encrypted), alongside the existing
`opencode:` block. Generated once as a random high-entropy token (`openssl rand -hex 32`) and
added directly — no dynamic-generation/seed-guard machinery needed (that exists in the restic role
to protect a *working backup repo's* password from silent regeneration; this is a fresh token with
no prior state to protect).

### 4. Traefik routing & path scoping

The new router, middleware, and the authgate's internal service address live together in
`traefik/dynamic.yaml` (the file-provider config, same place the existing `crawler-ratelimit`
middleware lives) — not as docker-compose labels on opencode's own compose file. This avoids
encoding a compound `Host && Path/Method` boolean rule inside a docker-compose label string (easy
to mis-escape), and keeps opencode's own `docker-compose.yml` untouched.

Scope: create a session, then act only within a session already known to the caller — no listing.

- **Allowed:** `POST /api/session` (create) · everything under `/api/session/{id}/...` (prompt,
  message, event stream, wait, context, history, interrupt, compact, agent, model, permission,
  question) — this covers chat, streaming responses, and replying to any tool-permission prompts
  raised during a session.
- **Blocked:** bare `GET /api/session` (list all) and `GET /api/session/active` (list active) —
  explicitly excluded even though they're path-adjacent to the allowed set.
- **Never matched by this router at all** (so never receive the injected Basic Auth header):
  `/api/fs/*`, `/file`, `/find*` (no folder access), `/api/pty`, `/pty` (no shell), `/vcs`,
  `/project` (no repo access), `/api/credential`, `/auth`, `/global`, `/mcp` (server management),
  `/experimental/*`, `/tui/*`. Requests to these paths fall through to the existing catch-all Host
  router instead, where opencode's own Basic Auth blocks them — a leaked API key can't reach these
  paths even indirectly.

Exact Traefik rule syntax (escaping, `Method()` matcher usage) is finalized in the implementation
plan; the requirement above is what it must enforce, verified with curl against servyy-test before
production.

### 5. Off-host backup (Vaultwarden)

New dedicated play `ansible/plays/opencode_authgate.yml`, mirroring the existing
`restic.yml`/`leaguesphere.yml` shape — the established pattern for anything needing Vaultwarden,
since only those two plays currently carry the `vw_master_password` prompt:

- `vars_prompt: vw_master_password` ("press enter to skip"), same UX as the existing two.
- `include_role: name: vaultwarden, tasks_from: push_items.yml` with
  `vaultwarden_item_username: "opencode"` and one item:
  ```
  name: "opencode api key (lehel.xyz)"
  secret: "{{ opencode.api_key }}"
  notes: >-
    X-Api-Key value for opencode's scoped ForwardAuth gate (opencode-authgate). Grants
    session-create + session-scoped chat access to https://opencode.lehel.xyz/api/session/*
    only — no filesystem, shell/PTY, VCS, project, or credential-management access. See
    docs/superpowers/specs/2026-08-08-opencode-api-key-forwardauth-design.md.
  ```
- Guarded by `when: vw_master_password | default('') | length > 0`, production-only (`lehel.xyz`),
  matching `ls_dbeaver_access`'s guards.
- Imported into `servyy.yml` after `plays/user.yml`, own tag (`opencode.vaultwarden`).

Deliberately **not** added to `user.yml` itself (the generic "Deploy Docker services" play used by
all services) — that would make every docker deploy of any service prompt for the Vaultwarden
master password, a real UX regression. A dedicated play keeps that blast radius at zero.

## Error handling

- **Missing/wrong `X-Api-Key`** → Caddy returns 401 → Traefik's forwardAuth short-circuits →
  client gets 401, request never reaches opencode.
- **authgate container down/unreachable** → Traefik treats a failed forwardAuth call as a failure,
  not a bypass → fails closed, same outcome as a wrong key. No fail-open risk.
- **Valid key, disallowed path** (e.g. `/api/fs/list`) → never matches this router → falls to the
  catch-all Host router → opencode's own Basic Auth blocks it (401), since no `Authorization`
  header was injected on that path. Same end result (denied), via the app's own auth rather than a
  custom scope error — this is the defense-in-depth we specifically wanted to keep.
- **Valid key, valid path, opencode itself errors** (bad session ID, model unavailable, etc.) →
  normal opencode API error passes through untouched; the gate only affects the initial auth
  decision.

## Testing

Per this repo's Molecule policy: no new scenario needed — `opencode-authgate` reuses the existing
generic `docker_service` role, which already has Molecule coverage for the templating/deploy
mechanism itself. What's new here (Caddy auth logic, Traefik routing rule) isn't Ansible logic, so
it's verified functionally instead:

1. Deploy to `servyy-test.lxd` first (`user.docker.opencode-authgate` tag + the new Traefik
   dynamic config).
2. Curl checks on test:
   - `POST /api/session`, no key → 401.
   - `POST /api/session`, wrong key → 401.
   - `POST /api/session`, correct key → 200, returns a session.
   - `GET /api/fs/list`, correct key → 401 (falls through to app-level auth, as designed).
3. Confirm the human web UI (`https://opencode.servyy-test.lxd/`) still prompts its normal Basic
   Auth, unaffected.
4. Only after all of the above pass on test **and** explicit user approval → deploy to
   `lehel.xyz` → repeat the same curl checks against production → run the `opencode.vaultwarden`
   tag once to mirror the key.

## Risks & decisions

- **Traefik rule complexity:** the compound path/method scoping rule is the crux of the whole
  security boundary; it lives in one file (`traefik/dynamic.yaml`) specifically so it stays easy
  to review, and is verified with explicit curl checks (including a negative check against
  `/api/fs/list`) rather than trusted by inspection alone.
- **Vaultwarden dependency:** requires the `bw` CLI and master password on the Ansible controller
  — the same operational dependency the existing restic and DBeaver-key pushes already carry.
- **Single static key:** no per-client revocation or rotation tooling beyond replacing the value
  in `secrets.yml` and redeploying `opencode-authgate`. Acceptable for one client; revisit if a
  second client needs independent revocation.

## Success criteria

- The API client can create a session and hold a chat conversation (including streamed responses)
  using only the `X-Api-Key` header, with no knowledge of opencode's own Basic Auth credentials.
- The same key is refused on `/api/fs/*`, `/api/pty`, `/vcs`, `/project`, `/api/credential`, and
  bare session-listing endpoints.
- The human web UI's Basic Auth flow is unchanged.
- The API key is present in Vaultwarden after running the `opencode.vaultwarden` tag.
