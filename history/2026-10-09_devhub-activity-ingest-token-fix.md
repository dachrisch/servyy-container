# devhub activity ingest token: fix the vault var reference (2026-10-09)

## Problem

PR #196 wired DevHub's `ACTIVITY_INGEST_TOKEN` to `{{ opencode.agent_secret }}`
in `devhub/web.env.j2`, but the vault has **no** `opencode.agent_secret` (the
only `agent_secret` is `portainer.agent_secret`, an unrelated value). The test
deploy on servyy-test failed at:

```
TASK [docker_service : Render env files for devhub]
failed: web.env.j2 → "object of type 'dict' has no attribute 'agent_secret'"
```

The PR's history note claimed it "reuses the existing vault value"; that value
never existed, so it was never exercised against the real vault.

## Fix

- Add a **dedicated** secret `devhub.activity_ingest_token` to the git-crypt
  vault (`ansible/plays/vars/secrets.yml`). Reusing an unrelated secret
  (`opencode.api_key`, `portainer.agent_secret`) would be a security smell —
  one value, two purposes.
- `devhub/web.env.j2`: `ACTIVITY_INGEST_TOKEN={{ devhub.activity_ingest_token }}`.

## The shared value

The producer is the setup-home laptop relay (`agent-config/bin/agent-relay.mjs`).
It reads the token from the setup-home vault var `agent_relay_token`
(→ `~/.config/agent-relay/token`, 0600). The two values **must be equal**
(devhub contract `docs/plans/2026-10-09-agent-activity-contract.md`).

Set here: `devhub.activity_ingest_token`. Mirror set in setup-home:
`ansible/plays/vars/secrets.yml` → `agent_relay_token`. Both generated together
(64 hex chars) in this change; they are the same value.

## Deployment

- servyy-test: `--tags "user.repo,user.docker.devhub"` (render + restart).
- production: same after test is green.
