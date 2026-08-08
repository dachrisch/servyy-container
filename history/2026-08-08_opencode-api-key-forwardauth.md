# opencode API-Key ForwardAuth Gate

**Date:** 2026-08-08
**Status:** ✅ Completed, deployed to production
**Branch:** `claude/opencode-api-key-forwardauth` (merged via PR #58)
**Design spec:** `docs/superpowers/specs/2026-08-08-opencode-api-key-forwardauth-design.md`
**Implementation plan:** `docs/superpowers/plans/2026-08-08-opencode-api-key-forwardauth.md`

## Problem

`opencode` (an AI coding-agent web server, `opencode/`) was only reachable via HTTP Basic Auth
(`OPENCODE_SERVER_PASSWORD`, the human operator's password). A second, automated client (a
script/web process) needed to drive opencode's session/chat API — creating sessions, sending
prompts, reading streamed responses — without sharing that human password, and without gaining
access to opencode's filesystem, shell/PTY, VCS/project, or credential-management endpoints.

opencode itself has no native API-key or certificate auth (confirmed against its `/doc` OpenAPI
spec and an unresolved upstream feature request, `anomalyco/opencode#5256`) — only Basic Auth.

## Solution

A second, narrower door in front of the existing one:

- **`opencode-authgate`** — a new internal-only Caddy container. Checks a static `X-Api-Key`
  header; on match, responds `200` with `Authorization: Basic <opencode's real creds>`. No public
  route (`traefik.enable=false`), reachable only from Traefik over the `proxy` Docker network.
- **Traefik `forwardAuth`** — a new middleware (`traefik/dynamic.yaml`) pointing at the authgate,
  and a new router (labels on `opencode/docker-compose.yml`, alongside the existing router) scoped
  to `POST /api/session` (create) and `/api/session/{ses_<id>}/...` (session-scoped chat/prompt/
  message/event/permission endpoints) — requiring **both** a matching path/method **and** a
  present `X-Api-Key` header. `authResponseHeaders: ["Authorization"]` injects the vended Basic
  Auth credential onto the forwarded request.
- opencode itself is unmodified and never learns about API keys — it keeps enforcing the same
  Basic Auth it always has. Defense in depth: a bug in the new router only ever costs a 401 for a
  legitimate caller, never a bypass of opencode's own auth.
- The key is mirrored into Vaultwarden (`ansible/plays/opencode_authgate.yml`, reusing the existing
  generalized `vaultwarden` role) for both `servyy-test.lxd` and `lehel.xyz`.

### Files changed

- `opencode-authgate/{docker-compose.yml,Caddyfile}` — new service
- `ansible/plays/vars/secrets.yml` — new `opencode.api_key`
- `ansible/plays/roles/docker_service/templates/opencode-authgate/.env.j2` — new env template
- `ansible/plays/user.yml` — new `docker_service` role invocation
- `traefik/dynamic.yaml` — new `opencode-apikey-auth` forwardAuth middleware
- `opencode/docker-compose.yml` — new `${SERVICE_NAME}_apikey` router labels
- `ansible/plays/opencode_authgate.yml` (new) + `ansible/servyy.yml` — Vaultwarden mirror play
- `ansible/plays/roles/user/tasks/docker_extras.yml` — registered in the bulk-ops service list

## Two real bugs found and fixed during review (before reaching production)

1. **Session-listing bypass.** The original router rule excluded `/api/session/active` via
   `!PathPrefix(\`/api/session/active\`)` — a raw string-prefix negation. A bare trailing slash,
   `GET /api/session/`, satisfied `PathPrefix(\`/api/session/\`)` while *not* matching the negated
   prefix, so it slipped through and returned the full session list with a valid injected
   credential. Confirmed live (200 + real session data) before the fix. **Fixed** by replacing the
   negation with a positive allow-list, `PathRegexp(\`^/api/session/ses_[A-Za-z0-9]+(/|$$)\`)`,
   anchored on opencode's actual session-ID shape.
2. **Human web UI hijack.** The router matched on path+method alone, with no regard for which auth
   header was present. Browsers auto-attach cached Basic Auth to every same-origin request, and
   opencode's own web UI calls this exact same `/api/session` REST API internally — so the router
   was intercepting the operator's own browser traffic and 401ing it at the authgate (which only
   understands `X-Api-Key`), breaking real chat functionality in the UI. **Fixed** by requiring
   `HeaderRegexp(\`X-Api-Key\`, \`.+\`)` on the router rule, so only requests actually carrying the
   header get routed to the gate.

Both were caught by review (task-level and final whole-branch), not by the original implementation
or its own tests — see the plan file's task history for the full review trail.

## Deployment Results

Deployed 2026-08-08 to `lehel.xyz` via `./servyy.sh --tags "user.repo,user.docker.opencode-authgate,user.docker.traefik,user.docker.opencode,user.docker.env" --limit lehel.xyz`. `PLAY RECAP: failed=0 unreachable=0`.

**Production-only issue found during post-deploy verification (not a code bug):** Traefik
(container uptime several weeks at deploy time) did not hot-reload the updated `dynamic.yaml`
despite `providers.file.watch: true` — logged `middleware "opencode-apikey-auth@file" does not
exist`, which silently routed *every* request to the pre-existing catch-all router. The gate was a
complete no-op until caught. `dynamic.yaml`'s on-disk content was correct throughout; this looks
like a long-uptime inotify-watch staleness issue on repeated file rewrites, not something specific
to this feature. **Fixed** with `docker restart traefik.traefik`; confirmed clean (no middleware
errors) and re-verified.

### Verification (production, post-restart)

```bash
PW=$(grep server_password: ansible/plays/vars/secrets.yml | awk -F'"' '{print $2}')
REAL_KEY=$(ssh lehel.xyz "grep OPENCODE_API_KEY /home/cda/servyy-container/opencode-authgate/authgate.env | cut -d= -f2")

curl -sk -o /dev/null -w '%{http_code}\n' https://opencode.lehel.xyz/api/session -X POST                                    # 401 (no key)
curl -sk -o /dev/null -w '%{http_code}\n' -H 'X-Api-Key: wrong' https://opencode.lehel.xyz/api/session -X POST              # 401 (wrong key)
curl -sk -o /dev/null -w '%{http_code}\n' -H "X-Api-Key: $REAL_KEY" -d '{}' https://opencode.lehel.xyz/api/session -X POST  # 200 (correct key)
curl -sk -o /dev/null -w '%{http_code}\n' -H "X-Api-Key: $REAL_KEY" https://opencode.lehel.xyz/api/fs/list                  # 401 (blocked path)
curl -sk -o /dev/null -w '%{http_code}\n' -H "X-Api-Key: $REAL_KEY" https://opencode.lehel.xyz/api/session                  # 401 (bare listing)
curl -sk --path-as-is -o /dev/null -w '%{http_code}\n' -H "X-Api-Key: $REAL_KEY" https://opencode.lehel.xyz/api/session/    # 401 (trailing-slash regression check)
curl -sk -o /dev/null -w '%{http_code}\n' -u "opencode:$PW" -d '{}' https://opencode.lehel.xyz/api/session -X POST          # 200 (human browser, unaffected)
curl -sk -I https://opencode.lehel.xyz/ | grep -i www-authenticate                                                          # Basic realm="Secure Area"
```

**8/8 pass.** Also confirmed via `docker logs traefik.traefik` access-log entries that requests are
routed through the *correct* router by name (`opencode_apikey@docker` for gated-path checks vs.
`opencode@docker` catch-all for blocked-path and human-browser checks) — routing verified
structurally, not only by status code.

Vaultwarden items pushed for both `servyy-test` and `lehel` (`opencode.vaultwarden` tag), each
named `opencode api key (<host>)`, username `opencode`.

## Success Criteria

- ✅ API client can create a session and chat using only `X-Api-Key` — no knowledge of opencode's
  Basic Auth credentials.
- ✅ The same key is refused on `/api/fs/*`, `/api/pty`, `/vcs`, `/project`, `/api/credential`, and
  bare session-listing.
- ✅ The human web UI's Basic Auth flow is unchanged (including its own internal API calls — the
  bug found during review).
- ✅ The API key is present in Vaultwarden for both `servyy-test` and production.

## Known Issues / Future Enhancements

- Single static key, no per-client rotation/revocation beyond replacing the value in `secrets.yml`
  and redeploying `opencode-authgate` — acceptable for the one known client; revisit if a second
  client needs independent revocation (YAGNI at time of writing).
- The router's positive allow-list is coupled to opencode's current session-ID format (`ses_`
  prefix). If opencode changes ID prefixing, the rule fails closed (falls through to Basic Auth,
  not a security hole) but the API key stops working until the rule is updated.
- The effective capability of this key is broader than its narrow HTTP surface suggests: it can
  drive opencode's agent, which holds real credentials (GitHub PAT, git-crypt key, CircleCI token,
  an SSH key). Documented explicitly in the Vaultwarden item notes and the design spec so future
  readers don't underestimate the blast radius of a leaked key.
- Wiring a web-search/searxng MCP tool into opencode's agent config was explicitly out of scope —
  separate follow-up if/when the automated client needs opencode to answer with live web results.
- `opencode-authgate` has no healthcheck or `watchtower.scope=prod` label (deliberately — floating
  `caddy:2-alpine` tag, no auto-update desired for a security component). Not registered for
  auto-update; bump the image manually if needed.
