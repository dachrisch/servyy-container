# 2026-10-22 — queen: opencode access for receipt reading

## Problem
queen 0.22+ (bumbleflies/queen PR #142, "booking automation") reads receipt PDFs through the shared opencode server to suggest bookings. Without `OPENCODE_API_KEY` in queen's env, receipt reading stays disabled.

## Solution
`ansible/plays/roles/docker_service/templates/finance/queen.env.j2` now sets:
- `OPENCODE_BASE_URL=https://code.lehel.xyz`
- `OPENCODE_API_KEY={{ opencode.api_key }}`

This reuses the existing key that job-search, devhub and dontforget use. opencode-authgate already accepts it, so the authgate needs no change. The model settings (`QUEEN_OPENCODE_MODELS`, `QUEEN_OPENCODE_PAID_MODEL`) are left unset, so queen's defaults apply: free registry models, then `opencode-go:deepseek-v4.1-flash` as the single paid fallback.

## Files changed
- `ansible/plays/roles/docker_service/templates/finance/queen.env.j2`

## Verification (local)
- The template renders with the key from `plays/vars/secrets.yml` (64 characters; value not printed).
- `ansible-playbook servyy.yml -i testing --syntax-check` passes.

## Deployment (done 2026-10-22)
PR #216 → merged as `fdd84cf`.

1. servyy-test: `./servyy-test.sh --tags user.docker.env.finance,user.docker.finance`, then `docker compose pull queen && docker compose up -d queen` to pick up `bumblecode/queen:latest` (0.22.1). Verified: `finance.queen` healthy, `/health` → `{"status":"ok","db":"connected"}`, `OpencodeClient` present, and `GET https://code.lehel.xyz/api/model` with the container's key returns 200.
   Note: Traefik is not running on servyy-test right now, so the test-host URL (`queen.servyy-test.lxd`) is unreachable — verification was done via `docker exec` on the container.
2. Production: `./servyy.sh --tags user.docker.repo,user.docker.env.finance,user.docker.finance`. Verified: `finance.queen` recreated on 0.22.1, both `OPENCODE_*` vars present, `https://queen.bumbleflies.de/health` → `{"status":"ok","db":"connected"}`, opencode `/api/model` with the container key returns 200.

Not yet exercised: an actual "Beleg auslesen" run on a receipt PDF (needs an upload in the UI).
