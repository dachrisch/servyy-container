# 2026-10-22 — queen: opencode access for receipt reading

## Problem
queen 0.22+ (bumbleflies/queen PR #142, "booking automation") reads receipt PDFs through the shared opencode server to suggest bookings. Without `OPENCODE_API_KEY` in queen's env, receipt reading stays disabled.

## Solution
`ansible/plays/roles/docker_service/templates/finance/queen.env.j2` now sets:
- `OPENCODE_BASE_URL=https://code.lehel.xyz`
- `OPENCODE_API_KEY={{ opencode.api_key }}`

This reuses the existing key that job-search, devhub and dontforget use. opencode-authgate already accepts it, so the authgate needs no change. `QUEEN_OPENCODE_FREE_MODELS=false` (queen 0.22.2+) skips the free registry models and leaves only the paid `opencode-go:deepseek-v4.1-flash`: the free models took 100 s+ per attempt, which eats the 180 s reading budget before the fallback is reached.

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

## Follow-up: the key alone was not enough (same day)

The first real click ("Beleg auslesen", 09:22 UTC) failed: `opencode POST /api/session/ses_…/prompt failed: 400`. code.lehel.xyz runs OpenCode **V2**, which takes `{ text }` on the prompt endpoint, while queen 0.22.1 still sent the V1 `{ prompt: { text } }`. V2 also prepends `idle` entries to the session message list, so the poller's `data[0]` check would have timed out next. Fixed in `bumbleflies/queen` PR #148 → 0.22.2 (`QUEEN_OPENCODE_FREE_MODELS` comes from that release).

### Rollout of 0.22.2 + paid-only chain (PR #217, merged `8333112`)

- Test: deployed, `finance.queen` recreated on 0.22.2 with `QUEEN_OPENCODE_FREE_MODELS=false`; the shipped `opencodeFromEnv().modelChain()` is exactly `[opencode-go:deepseek-v4.1-flash]` and a live `ask()` answered in 17.7 s.
- Production: same deploy path (`user.docker.repo,user.docker.env.finance,user.docker.finance`), container healthy on 0.22.2, `/health` ok, `QUEEN_OPENCODE_FREE_MODELS=false` present.
- End-to-end with the shipped code (Drive → PDF text → prompt → strict parse, no DB write) on the Augustiner receipt of the failed transaction: 367 text chars, paid model, **8.9 s**, valid reading (`totalCents: 2520`, 19 %, account 6640).
- The transaction keeps its cached `failed` reading until it is read again: a click re-reads it (failed readings always retry), and the nightly reconcile reads it too. Because the receipt is 25.20 € against a 54.60 € transaction, the row will show the intended amount-mismatch hint.

Not yet exercised: an actual "Beleg auslesen" run on a receipt PDF (needs an upload in the UI).
