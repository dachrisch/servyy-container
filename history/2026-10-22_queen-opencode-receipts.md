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

## Deployment
Pending. Deploy after the queen release that contains receipt reading.
1. servyy-test: `./servyy-test.sh --tags user.docker.env.finance,user.docker.finance`, then pull and recreate `finance.queen`. Test reaches production `code.lehel.xyz` like job-search on test does, so one "Beleg auslesen" can be verified there.
2. Production: same tags with `./servyy.sh` after approval. Watchtower then rolls the image.
