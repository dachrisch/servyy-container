# Centralize dev checkouts on codey_dev_checkouts + reclaim disk (2026-09-27)

## Problem

Follow-up to the same-day disk investigation: `opencode.web` had no live
`/root/dev` mount at runtime (inspect listed it, `/proc/self/mountinfo` did
not), and the shared checkouts volume still carried the `claude_`-prefixed
name from before opencode shared it. Two stores, confusing ownership, and
`opencode_root` had regrown to 5.9G of caches.

## Solution

1. **Renamed shared volume `claude_shared_dev_checkouts` → `codey_dev_checkouts`**
   (neutral name — both claude-hub and opencode use it):
   - `opencode/docker-compose.yml` (`name:` + comment)
   - `claude-hub/docker-compose.yml` (external `name:`)
   - `ansible/plays/user.yml` (`ensure_volumes` in both the opencode-owner
     and claude-hub-referrer stanzas)
   - Docs: `CLAUDE.md` service table, `opencode/skills/opencode-deployment/SKILL.md`
     (no longer claims git clones live in `opencode_root`)
2. **Orphan-cleanup parity**: `claude-hub/scripts/provision-repos.sh` gained the
   flat-layout (`$DEV_DIR/<repo>` vs `$DEV_DIR/<owner>/<repo>`) sweep from
   opencode's `provision-dev.sh`, so either boot keeps the `owner/repo`
   convention devhub expects (`OPENCODE_WORKSPACE_ROOT=/root/dev`).
3. **Migration on codey**: `docker volume create codey_dev_checkouts` +
   `cp -a` from old volume (verified byte-identical via `diff -r`), then
   redeploy. Both containers' `/proc/self/mountinfo` confirm the same
   `_data` path; identical `rev-parse HEAD` from both containers proves one store.
4. **Manual reclaim**: `npm cache clean --force` (.npm 1.9G→252M),
   `prune-sessions.py` (217 sessions, 12 snapshot repos), deleted dead plugin
   caches (`opencode-antigravity-auth`, `opencode-mem*`, 1.4G→64M, live
   `opencode-working-memory@1.6.9` kept), removed old volume,
   `docker image prune -a --filter until=168h` (0B — nothing eligible).

## Results

- `df -h /`: 3.2G → **7.7G free** (89% → 72%)
- `opencode_root`: 5.9G → **3.0G**; shared store: single **2.1G** volume
  (was effectively 2×2.1G during migration, now one)
- Layout verified from both containers: only `dachrisch/` + `bumbleflies/`
  at top level, 14 repos all `owner/repo` with `.git`
- `code.lehel.xyz` → 401 (auth-gated normal); all containers healthy

## Deployment notes / gotchas

- **Test-first**: validated on `servyy-test.lxd`
  (`./servyy-test.sh --tags user.docker.opencode,user.docker.claude-hub`,
  ok=56/failed=0) before prod. Commit `5949f6f`, pushed `master`.
- **claude-hub has no compose-copy role**: the `opencode` ansible role copies
  `docker-compose.yml` from the controller working tree (uncommitted OK), but
  claude-hub deploys only via the git checkout (`user.docker.repo` tag). The
  hub migration therefore required commit+push first — first deploy only moved
  opencode, hub followed after `user.docker.repo,user.docker.claude-hub`.
- Left for later: `.local` (1.6G, fresh session data) and `.cache/puppeteer`
  (652M) + `uv` (214M) untouched — regenerable but in active use patterns;
  the Ofelia-on-codey scheduling gap (see `2026-09-05_opencode-volume-cleanup.md`)
  still means prune jobs never run automatically here.
