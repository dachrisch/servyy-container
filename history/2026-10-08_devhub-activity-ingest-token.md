# DevHub activity ingest token env (2026-10-08)

Realizes servyy-container#193 (child of devhub#270 "Agent Activity"). The
laptop `agent-relay` (setup-home) authenticates to DevHub's ingest endpoint
with a shared token; this change provisions it in the deployed devhub env.

## Change

- `ansible/plays/roles/docker_service/templates/devhub/web.env.j2`: add
  `ACTIVITY_INGEST_TOKEN={{ opencode.agent_secret }}`.
  - Reuses the existing `opencode.agent_secret` value from the git-crypt
    `secrets.yml` vault rather than minting a new secret (dachrisch call).
  - `web.env` only — `devhub.web` loads it via `env_file`, and the `.env`
    compose file does not need the token (no interpolation use).
  - Rendered at mode 0600 by `docker_service/tasks/env.yml`.

## Reachability

DevHub is already Traefik-fronted at `h.code.lehel.xyz` (TLS on codey), so the
token-authed `POST /api/activity/ingest` path needs no new routing. Confirming
a request reaches the app is blocked on devhub#271 (the receiving endpoint is
not implemented yet) and on test/prod deployment, which is done outside this
change.

## Related

- servyy-container#194 (conditional opencode-server activity plugin): closed
  as not-needed. devhub#272 phase-0 confirms `GET /api/session` (full fleet
  list) and `GET /event` (global SSE) are sufficient, so the trigger condition
  for #194 is not met.

## Validation status

- ansible-playbook syntax-check: `servyy.yml` on testing ✅
- yamllint on `ansible/plays` ✅ (only pre-existing line-length warnings)
- Deploy/rollout to `servyy-test.lxd` and `codey.lehel.xyz` done elsewhere.
