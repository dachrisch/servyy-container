# ADR: OpenCode V1 → V2 upgrade on codey

**Date:** 2026-10-22
**Status:** Accepted
**Branch:** `opencode-v2-upgrade` (merged to `master`)
**Plan:** `docs/plans/2026-10-21-opencode-v2-upgrade.md`

## Context

`opencode.web` on `codey.lehel.xyz` ran OpenCode **V1 1.19.3**, pulled from
`ghcr.io/anomalyco/opencode:latest`. Upstream never moved that tag to V2 — V2 ships only as
versioned image tags (`2.0.x`…`2.1.x`) and as the npm package `@opencode/cli`, so the container
could not upgrade by pulling. Meanwhile both local plugins had already been ported to the **V2
plugin API** and deployed into the V1 runtime (2026-10-18), where they were silently inert: the
server exposed no `session_*` tools at all.

V2's intentional breaking changes are the plugin API, the server API, and terminal config
(`tui.json` → `cli.json`). Every one of those touched this deployment.

## Decision

Pin the image to **`2.1.2`**, move the entrypoint to `opencode serve`, migrate the plugins'
configuration and the session pruner to V2, replace the V1-only memory plugin with the native
global `AGENTS.md` channel, and gate the cutover on a test-host run plus a pause of the
`dontforget` scheduler. Deploy through the existing Ansible role rather than by hand.

## Consequences

### Positive

- ✅ V1 1.19.3 → V2 2.1.2 on codey, verified running (`opencode v2.1.2`, healthy).
- ✅ Session messaging and superpowers work again: `/api/plugin` reports `session-messaging` and
  `superpowers` **active** (they were inert under V1).
- ✅ Sessions preserved: in-place DB migration left 116 `session_v2` rows, 116 legacy rows, and
  **zero** legacy-only sessions.
- ✅ The nightly pruner now targets the live tables and, worse, would have kept "succeeding"
  against the dead `session` table while the DB grew.
- ✅ Durable memory no longer depends on a dead npm package: a global `AGENTS.md` is deployed to
  every session from git.
- ✅ The API-key bridge (authgate → Basic auth) needed **no** change and was verified end to end.

### Negative / tradeoffs

- ⚠️ `opencode-working-memory` is gone (V1-only peer range). The native channel is curated, not
  auto-captured. The pre-vetted fallback is `@mathew-cf/opencode-memory`, which does not fit
  codey's 1.9 GB RAM without benchmarking.
- ⚠️ **V2 changed the prompt body** (`{"prompt":{"text"}}` → `{"text"}`), which breaks the three
  API consumers until their issues land: `dachrisch/dontforget#302`,
  `dachrisch/ai-job-search#202`, `dachrisch/devhub#306`. `dontforget`'s scheduler is paused
  (`SCHEDULER_ENABLED=false` in its env template) so retries cannot poison the shared model
  cooldowns; that line must be removed when #302 ships.
- ⚠️ The public root `https://code.lehel.xyz/` now returns the static V2 web shell `200` without
  auth (V1 answered 401). All API paths still 401; no data is exposed, but the shell is
  anonymous. Worth an edge rule if that matters.
- ⚠️ `docstash` MCP shows `needs_auth` until someone signs in once on the new runtime (`/mcps`).
- ⚠️ `devhub`'s per-session SSE stream (`/api/session/{id}/event`) is V1-only; its live progress
  view degrades to polling (tracked in #306).

### Implementation Details

**Files changed (branch, 11 commits):**

- `opencode/docker-compose.yml` — image pinned `2.1.2`; healthcheck now asserts liveness
  (`/health` 200) **and** the auth contract (unauth `/api/info` 401).
- `opencode/scripts/startup.sh` — `opencode serve --hostname 0.0.0.0 --port 4096`; deploys the
  global `AGENTS.md`; removes the stale in-volume `tui.json`.
- `opencode/scripts/AGENTS.md` (new) — the cross-session memory channel.
- `opencode/scripts/opencode.json.template` — V1-only plugin removed, `experimental.todo: true`.
- `opencode/scripts/tui.json` (deleted).
- `opencode/scripts/prune-sessions.py` — V2 schema (`session_v2`, `session_message`,
  `session_inbox`, `session_pending`, `instruction_*`), prunes by **inactivity**
  (`time_created` *and* `time_updated`), existence-gated legacy cleanup, explicit rollback,
  loud failure on a non-V2 schema.
- `opencode/scripts/test_prune_sessions.py` (new) — 17 tests; wired into CI
  (`.github/workflows/ci.yml`).
- `ansible/plays/roles/opencode/tasks/main.yml` — deploys `prune-sessions.py` and
  `provision-dev.sh` (both previously only arrived via the repo sync that tagged deploys skip),
  deploys `AGENTS.md`, removes the stale host `tui.json`.
- `ansible/plays/roles/docker_service/templates/dontforget/web.env.j2` — temporary
  `SCHEDULER_ENABLED=false` for the cutover.
- `.gitignore` — `__pycache__/`.

**Deployment:**

- Test host: `servyy-test.lxd` first (same procedure: backup, sync `opencode/`, compose pull/up).
- Production: online `sqlite3` backup (`/home/cda/oc.v1.pre-v2.db`, 167 MB,
  `pragma integrity_check` → ok — **not** `docker cp`, which yields a malformed copy of a live
  DB), image pre-pulled, then
  `./servyy.sh --limit codey.lehel.xyz --tags user.docker.opencode`.

**Verification (actual results):**

- codey: `opencode v2.1.2`, container healthy; `/health` 200, unauth `/api/info` 401, auth 200.
- `/api/plugin`: `session-messaging` and `superpowers` **active** (89 builtins alongside).
- `/api/mcp`: `circleci` and `chrome-devtools` **connected**, `docstash` `needs_auth`.
- `/api/model`: 146 models across `opencode`, `opencode-go`, `google`, `alibaba`, `alibaba-cn`,
  `bailian-payg` (the custom provider still works in V1 config shape).
- DB: 116 `session_v2` rows, 116 legacy, 0 legacy-only, 0 stale parents with live children.
- Pruner run manually: `no sessions idle for more than 168h, nothing to do`, exit 0 (codey's
  DB only holds the last 7 days — the V1 pruner had been working; the "~292 sessions" figure in
  the plan came from a laptop DB copy, not from codey).
- API bridge smoke through the public edge with `X-Api-Key`: model discovery 200 (146 models,
  19 free), session create 200, **old V1 prompt body → 400 `Missing key at ["text"]`**, new V2
  body → 200, model replied `PONG` with `finish: stop`, `GET …/message` newest-first = true,
  `DELETE` → 204.
- Test host: same checks, plus it surfaced that its `session-messaging.js` was a **stale V1
  file** (Oct 14) — V2 rejected it with "must export a default definition…". Copying the
  current V2 file made it `active`.

**Key learnings:**

1. `:latest` on ghcr never tracked V2 — the upgrade was impossible without pinning.
2. V2 has **no `web` subcommand**; `opencode web …` is parsed as a *directory*. `serve` is the
   foreground server.
3. V2 `/health` answers 200 **unauthenticated** (V1 answered 401), so the old healthcheck would
   have marked a healthy container unhealthy. The fix also restored an auth assertion the old
   probe provided by accident — via unauth `/api/info` → 401.
4. A live `docker cp` of the SQLite DB produces `database disk image is malformed`; the online
   `sqlite3` backup API does not.
5. V2 migrates a V1 DB in place and **keeps the legacy tables**, which is exactly why the old
   pruner kept "working" while pruning nothing live.
6. Deploying with `--tags user.docker.opencode` skips play 1's repo sync, so any file under
   `opencode/scripts/` that the role does not copy explicitly stays stale on the host. Two files
   were in that class (`prune-sessions.py`, `provision-dev.sh`).
7. V1 and V2 share only 40 of 162/121 API paths, and the prompt body is mutually exclusive
   (`additionalProperties: false` on both) — no dual-compatible request exists, so client and
   server cutovers must be coordinated.
8. Boot is slow by construction (package installs, chromium, dev-checkout provisioning):
   ~3 min on codey, ~14 min on the test host. `start_period: 20s` is cosmetic; the fixed `2m`
   watchtower health gate is the real constraint, so timings were left alone.

### Known issues

- The three API consumers 400 on the prompt call until #302/#202/#306 land; `dontforget`'s
  scheduler stays paused until then.
- `docstash` MCP needs a one-time sign-in on the new runtime.
- `devhub`'s live SSE view is polling-only under V2.
- The public web shell is served anonymously (API remains protected).
- The pruner does not consult `parent_id`; a stale parent with a live child would be pruned
  (query included in the plan's Phase 2 pre-flight, returns 0 today).
- `instruction_blob` rows are never garbage-collected.

## Related Decisions

- `history/2026-08-08_opencode-api-key-forwardauth.md` — the API-key bridge this upgrade had to
  preserve.
- `history/2026-10-14_session-messaging-plugin-canonical-setup-home.md` — the plugin that was
  inert until this upgrade.

## Alternatives Considered

### Keep V1 and pin `1.19.3`
Pros: no client work. Cons: the deployed plugins are V2-only, so session messaging stays broken;
V1 no longer receives fixes; the "latest" tag trap remains.
**Rejected.**

### `opencode-mem@2.33.0` as the memory replacement
Pros: feature parity (automatic capture). Cons: 0.5–2 GB RAM while its embedding model is loaded
and a 100 MB–2 GB model cache, against 1.9 GB total RAM and 2.7 GB free disk.
**Rejected**; the native `AGENTS.md` channel is the baseline, `@mathew-cf/opencode-memory` the
fallback.

### Lockstep cutover of the three API clients
Pros: one window. Cons: a 400 during the window can mark healthy models unhealthy in
`job-search`'s cooldown registry, turning a short outage into a long one.
**Rejected** in favour of pausing `dontforget`'s scheduler and tracking the clients as issues.
