# OmniRoute Free-First Tier for Codey OpenCode Server

**Date:** 2026-10-13
**Status:** Approved design (not yet implemented)
**Relates to:** history/2026-09-26_opencode-working-memory.md, history/2026-06-29_opencode-antigravity-auth.md
**Upstream:** https://www.omniroute.online/ (MIT, `diegosouzapw/OmniRoute`), Cheaper Inference marketplace (out of scope)

## Goal

Work for free, nearly unlimited, by default. Paid providers stay available
for heavy stuff only, picked explicitly per session by the user.

- Default session models route over pooled free quotas first.
- `bailian-payg/*` and `opencode-go/*` remain selectable for heavy work.
- No background LLM calls are added (the 403 failure class from
  `history/2026-09-26_opencode-working-memory.md` must not return).

## Pool eligibility (decided)

- INCLUDE: official API-key free tiers with published budgets
  (e.g. Mistral ~1B/mo, LLM7, Nara, Gemini CLI, Cerebras, NVIDIA NIM).
- INCLUDE: keyless free-forever routes (e.g. Pollinations, OpenCode Free,
  Felo-class). Bigger pool, weaker SLAs — accepted.
- EXCLUDE: OAuth / subscription-seat / web-cookie routes
  (Claude Code, Codex, Copilot seats, web sessions). Max quota but
  account/ToS risk — rejected.
- EXCLUDE: hosted Cheaper Inference gateway (paid account + data egress;
  contradicts the free/local constraint that rejected cloud memory in
  Alt E of the working-memory decision).

## Architecture

OmniRoute runs as a **sidecar container inside the existing `opencode`
compose project** on `codey.lehel.xyz` — not a new top-level service.

- Image: pinned `diegosouzapw/omniroute`, `restart: unless-stopped`,
  `com.centurylinklabs.watchtower.scope=prod` like its neighbor.
- Listens only on `localhost:20128` inside the compose network
  (OpenAI-compatible `/v1`, local `/dashboard` for debugging).
- No new Traefik router, no public dashboard in v1 (no auth surface).
- State on a new named volume (upstream local-first: SQLite on disk,
  AES-256-GCM encrypted credentials, no OmniRoute account).
- `opencode.web` keeps port 4096 and its Traefik routing untouched.
- One new provider entry in the rendered `opencode.json` using the generic
  `@ai-sdk/openai-compatible` shape already used for `bailian-payg`
  (preferred over the native `@omniroute/opencode-provider` npm plugin
  to avoid a new dependency inside the Alpine container until proven).
- Model surface: 2–3 explicit aliases (`omniroute-auto` → `auto`,
  `omniroute-cheap` → `auto/cheap`, optionally `omniroute-coding` →
  `auto/coding`) — not the full 352-provider catalog, so
  `opencode models` stays legible and user choice is real.
- Secrets stay Ansible-native: new keys in git-crypt `secrets.yml`
  (`opencode.*`), rendered via `docker_service/templates/opencode/.env.j2`
  (0600); `startup.sh` `envsubst` allowlist grows by the new var names only
  (the allowlist exists to protect `$schema`).
- Deliberately out of scope: MCP server (110 tools), A2A server, semantic
  cache dependency, Cheaper Inference hosted path.

## Components & data flow

Files carrying the change (all inside existing patterns):

1. `opencode/docker-compose.yml` — new `omniroute` service
   (`container_name: opencode.omniroute`, shared `proxy` network for DNS
   only, no Traefik labels, named state volume, healthcheck against
   `:20128/v1/models`).
2. `opencode/scripts/opencode.json.template` — new `provider.omniroute`
   block (`baseURL: http://localhost:20128/v1`,
   `apiKey: $OMNIROUTE_API_KEY`) + the 2–3 named models above.
3. `opencode/scripts/startup.sh` — extend `envsubst` allowlist
   (`$OMNIROUTE_API_KEY` + per-provider free keys).
4. Ansible — `docker_service/templates/opencode/.env.j2` renders new vars;
   `opencode/tasks/main.yml` deploys compose + template under the existing
   `user.docker.opencode` tag with the existing restart notify.

Runtime flow per request on a free model: session → local `:20128/v1` →
combo scores keyless pool first, then official-free keys (reset-window
aware), standard compression profile on eligible tool/context payloads →
response. On 429/quota/dead-key the 3-layer isolation (provider breaker →
connection cooldown → model lockout) fails over in ms inside the gateway.
Paid endpoints are touched only when the user explicitly picks a
`bailian-*` / `opencode-go/*` model — a free outage can never silently
burn money.

## Failure handling

- Free↔paid boundary is user-explicit; gateway fallback never crosses it.
- Keyless backends are opaque: rely on cooldown/lockout, expect latency
  spikes, size the soak accordingly.
- Resource guards: pinned image, `unless-stopped`, volume observed via
  dashboard usage/quota analytics during soak; existing Ofelia
  `prune-sessions` untouched.
- Rollback: remove provider block + sidecar, redeploy
  `--tags user.docker.opencode` — single-tag revert.

## Testing & rollout (mandatory path)

1. `user.yml --syntax-check`, template JSON parses, `sh -n` on scripts.
2. Molecule `docker_service` fixtures with `test-` keys + `verify.yml`
   greps (new env vars present, mode 0600, no OAuth/cookie vars).
3. Live `servyy-test.lxd` deploy (`servyy.yml -i testing
   --tags user.docker.opencode`): `:20128/v1/models` lists, `opencode
   models` shows the `omniroute-*` entries, free-model inference smoke
   passes, paid-model control probe passes.
4. Scoped prod deploy on `codey`, same smokes.
5. One-week soak: dashboard shows free-pool drain before any paid tokens,
   zero 403-class regressions, memory still extraction-at-compaction.

## Alternatives considered

- **B: standalone `omniroute` service project** (own compose + Traefik +
  authgate dashboard) shared by opencode + claude-hub + devhub. More
  reuse, new lifecycle/monitoring/secrets surface. Deferred — revisit only
  if hub/devhub want the same pool.
- **C: hosted Cheaper Inference for heavy overflow.** Zero ops but paid +
  egress. Rejected as default; at most a future fallback, not this design.

## Pre-requisites / notes

- Worktree quirk (pre-existing, untouched):
  `ansible/plays/roles/user/defaults/main.yaml` is truncated to 0 bytes;
  left alone, excluded from any commit.
- Auto-stash `auto-stash before master checkout 2026-10-13` (and 3 older
  master stashes) still held; consume or drop deliberately, not as part
  of this change.
