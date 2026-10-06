# 2026-10-06 — opencode: API-key clients may list models

**Status:** 🔁 #170 targeted the wrong router; corrected in the follow-up (see Correction below)

## Problem
job-search calls opencode with `X-Api-Key`. The `opencode_apikey` router only matched
`POST /api/session` and `/api/session/ses_*`, so `GET /api/model` returned 401. job-search
could not discover which models are servable and kept using its pinned default
`mimo-v2.5-free` after the registry marked it `deprecated`. In production, searches failed
with `HTTP 429 FreeUsageLimitError`, and there was no fallback.

## Solution
`opencode/docker-compose.yml`: the `${SERVICE_NAME}_apikey` router rule now also matches
`Path(/api/model) && Method(GET)`. It uses the same `opencode-apikey-auth@file` forwardAuth
middleware, so the key is still validated by `opencode-authgate` before Basic auth is injected.
Every other path and method stays blocked for API-key clients.

Consumer: job-search (`packages/api/src/ai/opencode.ts`) discovers active cost-0 models the
same way devhub does, with `opencode-go:deepseek-v4.1-flash` as a paid fallback.

## Files changed
- `opencode/docker-compose.yml`

## Deployment
servyy-test: `./servyy-test.sh --tags "user.repo,user.docker.opencode"` → `failed=0`.

Verification on servyy-test (`--resolve opencode.servyy-test.lxd:443:10.185.182.250`,
because the local DNS entry points at a stale `.233`):

| Request | Result |
|---|---|
| `GET /api/model`, no key | 401 (unchanged) |
| `GET /api/config` + key | 401 (still blocked) |
| `POST /api/model` + key | 401 (method still blocked) |
| `GET /api/session` + key | 401 (listing still blocked) |
| `GET /api/model` + key | routed to `opencode_apikey@docker` (Traefik access log), then **500** |

The 500 comes from a gap that already existed: **servyy-test has no `opencode-authgate`**
(it is missing from `ansible/testing`), so the forwardAuth target
`opencode-authgate.authgate:80` does not resolve. This affects every API-key route on
test, including session calls, not just this change. The key check can therefore only
be verified on production.

Production (pending approval):
```bash
./servyy.sh --tags "user.repo,user.docker.opencode" --limit <codey host>
K=<job-search OPENCODE_API_KEY>
curl -s -o /dev/null -w '%{http_code}\n' -H "X-Api-Key: $K" https://code.lehel.xyz/api/model   # 200
curl -s -o /dev/null -w '%{http_code}\n' https://code.lehel.xyz/api/model                       # 401
curl -s -o /dev/null -w '%{http_code}\n' -H 'X-Api-Key: wrong' https://code.lehel.xyz/api/model # 401
curl -s -o /dev/null -w '%{http_code}\n' -H "X-Api-Key: $K" https://code.lehel.xyz/api/config  # 401
```

## Known issues / follow-ups
- Add `opencode-authgate: true` to `ansible/testing`, so API-key routes can be tested on servyy-test.
- The local DNS entry for `opencode.servyy-test.lxd` resolves to `10.185.182.233` rather than servyy-test (`.250`).
- servyy-test's job-search `api.env` points `OPENCODE_BASE_URL` at production `code.lehel.xyz`.

## Correction (same day)
#170 changed the wrong router and had no effect for job-search. It edited the
`opencode_apikey@docker` router in `opencode/docker-compose.yml`, which matches
`Host(${SERVICE_HOST})` = `opencode.lehel.xyz`. That hostname is retired: its DNS points
at servy, not codey. The public endpoint `code.lehel.xyz` is served by the file-provider
router `opencode-apikey-code` in `traefik/dynamic.yaml`. After the #170 deploy to codey,
Traefik's access log showed `GET /api/model` with a key still landing on `opencode_root@docker` → 401.

The follow-up fix:
- removes the stale `${SERVICE_NAME}_apikey` router labels from `opencode/docker-compose.yml`
  (no consumer uses `opencode.lehel.xyz`: checked repos under `~/dev`, the `*.env` files and
  container envs on servy and codey; only opencode's own `SERVICE_HOST` still names it)
- adds `(Path(/api/model) && Method(GET))` to `opencode-apikey-code` in `traefik/dynamic.yaml`

Lesson: before changing routing, find the router that actually receives the traffic
(Traefik access log `RouterName`), not the one that looks right in compose.

Still open: opencode's plain `${SERVICE_NAME}` router also matches the retired
`opencode.lehel.xyz` through `SERVICE_HOST`. It is left untouched here.
