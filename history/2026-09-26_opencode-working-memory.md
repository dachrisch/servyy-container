# Replace opencode-mem with opencode-working-memory; remove Antigravity

**Date:** 2026-09-26
**Status:** Accepted
**Relates to:** history/2026-06-29_opencode-antigravity-auth.md, history/2026-09-26_opencode-server-skills.md

## Context

The opencode server's memory system (`opencode-mem` plugin) never stored a
single project memory. Two independent failure modes, both structural:

1. Auto-capture issues background structured-output calls through the
   `opencode` free-tier provider, which rejects them with
   `403 "OpenCode's free tier can only be used from within OpenCode"`.
   Pinning capture to `google` (Antigravity OAuth) fixed the 403 — and then
   Antigravity itself died, closing that escape hatch.
2. Local vector embeddings (ONNX) cannot load in the Alpine container
   (`ld-linux-x86-64.so.2` missing) — broken since at least Sep 10. Without
   embeddings nothing can be vector-stored or searched.

Separately, the Antigravity auth stack (plugin + model defs + OAuth seeder)
was dead weight after the upstream shutdown.

## Decision

- Replace `opencode-mem` with `opencode-working-memory@1.6.9` (pinned, MIT,
  0 deps). It extracts memory inside OpenCode's built-in compaction request
  — zero extra API calls — so the 403 failure class is structurally
  impossible on any session model. No embeddings, no vector DB, no cloud.
- Remove the entire Antigravity stack: plugin entry, `google` provider
  model defs, `seed_auth.py`, `provision-dev.sh` step 2b, `OPENCODE_AUTH_GOOGLE_B64`
  (template + secrets), molecule fixtures.
- Add `opencode/scripts/tui.json` (same pinned plugin) for the `/memory`
  inspector menu (best-effort: we run `web` mode, the menu is TUI-native).

## Consequences

### Positive
- ✅ Memory has no background LLM calls, no native ML runtime, no API keys,
  no billing, no data egress — every opencode-mem failure mode is gone
- ✅ Store initializes per workspace; `memory-diag` works keyless
- ✅ Dead Antigravity wiring (incl. an OAuth refresh token in secrets)
  fully removed; `opencode models` shows no `antigravity` entries
- ✅ Stale host files (`opencode-mem.jsonc`, `seed_auth.py`) cleaned by
  idempotent `absent` tasks; container config cleans itself at boot

### Negative / Tradeoffs
- ⚠️ No semantic search (keyword/context injection only) and no auto-capture
  outside compaction — memory appears after compaction cycles, not instantly
- ⚠️ Sessions pinned to `google/antigravity-*` models stop working; users
  switch to `opencode-go` / `bailian-payg`
- ⚠️ Upstream caveat inherited: concurrent sessions on the same workspace
  can race on store files; other compaction plugins may conflict (none
  observed with `superpowers.js`)

### Implementation Details

**Files Modified:**
- `opencode/scripts/opencode.json.template` (MODIFY: plugin swap, google block delete)
- `opencode/scripts/tui.json` (NEW)
- `opencode/scripts/startup.sh` (MODIFY: tui deploy + legacy `opencode-mem.jsonc` cleanup)
- `opencode/scripts/provision-dev.sh` (MODIFY: drop step 2b)
- `opencode/scripts/seed_auth.py` (DELETE), `opencode/scripts/opencode-mem.jsonc` (DELETE)
- `ansible/plays/roles/opencode/tasks/main.yml` (MODIFY: tui deploy + 2 absent cleanups)
- `ansible/plays/roles/docker_service/templates/opencode/.env.j2` (MODIFY)
- `ansible/plays/vars/secrets.yml` (MODIFY: still encrypted, 11907→11063 bytes)
- `ansible/plays/roles/docker_service/molecule/default/{converge,verify}.yml` (MODIFY)

**Testing & Verification:**
- ✅ `user.yml --syntax-check`, `sh -n` on both scripts, template JSON parses
- ✅ Molecule scenario unrunnable on controller (no Docker daemon) — fixtures validated by lint + live test deploy instead
- ✅ Test (`servyy-test.lxd`, `servyy.yml -i testing --tags user.docker.opencode`): ok=52/failed=0; plugin 1.6.9 installed; store initialized; env clean
- ✅ Prod (`codey.lehel.xyz`, `./servyy.sh` scoped): ok=52/failed=0; `healthy`; 0 ERROR lines since boot; `opencode-go/glm-5.3-flash` inference smoke passed; `memory-diag` OK
- ✅ Extraction-at-compaction e2e pending normal-use soak (trivial 1-turn probe correctly stores nothing — extraction happens at compaction)

**Key Learnings:**
1. **Test-env gaps are documented, not discovered:** `unhealthy` on test is expected (no server password); no provider keys on test by design — session tests belong to prod soak (`history/2026-09-26_opencode-server-skills.md`).
2. **Deploy from clean `origin/master`:** local branch had diverged; implement + deploy only from master worktree.
3. **Pre-existing tree quirk (untouched):** `ansible/plays/roles/user/defaults/main.yaml` is truncated to 0 bytes in the worktree (mtime predates this work); left alone, excluded from the commit.
4. **`opencode run` segfault in-container was transient** (memory pressure); retry succeeded.
5. **yamllint flags dotenv `.j2` templates** identically before/after — pre-existing noise, not a regression.

### Known Issues & Limitations
- Read-path (compaction → injection → new session) awaits a real compaction cycle; verify with `memory-diag status` then.
- Dead Google OAuth grant should be revoked at myaccount.google.com (credential already non-functional).
- Old `~/.opencode-mem/` data and container `auth.json` Google block remain until volume recreation (nothing reads them).

## Related Decisions
- history/2026-06-29_opencode-antigravity-auth.md (stack removed here)
- history/2026-09-26_opencode-server-skills.md (plugin/skill deploy patterns + test-gap docs reused)

## Alternatives Considered

### Alt A: opencode-localmemory
Pros: Markdown storage, same plugin shape, verified zero-secret
Cons: 12 dl/wk single maintainer, agent-driven only, no auto-capture
**Rejected** — less mature than the pick, same automation gap

### Alt B: MCP knowledge-graph server (@modelcontextprotocol/server-memory)
Pros: Official, zero creds, exits the plugin system
Cons: Single global graph (no project isolation), substring search, per-session spawn cost
**Rejected** — weaker isolation, still needs a usage skill for automation

### Alt C: @wszqkzqk/openmemory
Pros: Layered Markdown, staleness via git-hash, companion skill
Cons: 1 star; writes `.openmemory/` into shared checkouts; GPL-3.0
**Rejected** — repo pollution on shared volumes

### Alt D: opencode-plugin-git-memory
Pros: Version-controlled memory on orphan branch
Cons: 2 dl/wk; creates `memory/` branch in every touched repo — most invasive for shared checkouts
**Rejected**

### Alt E: opencode-supermemory (cloud)
Pros: Most mature (1.6k stars), full auto-capture + semantic search
Cons: Paid account, data egress to third-party cloud, new Ansible secrets
**Rejected** — violates free/local constraints

### Alt F: gcompat fix + keep opencode-mem on google provider
Pros: Smallest diff
Cons: Keeps background-LLM fragility; google path died with Antigravity anyway
**Rejected** — superseded by events during planning
