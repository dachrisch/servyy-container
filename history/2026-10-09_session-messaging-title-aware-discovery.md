# 2026-10-09 — Session messaging: discover unregistered sessions + title-aware send

## Goal (user directive)

A `devhub-whole-board-scope` session could not reach a peer session titled
"Opencode command/web missing from agent interface": `session_list` returned
only its own (registered) session and `session_check` was empty, so it had no
name and no raw ID to address and correctly refused to guess one. Make such a
target discoverable and addressable.

## Root cause

`session_list()` (`opencode/plugins/session-messaging.js`) already fetched every
session via `client.session.list()` but rendered **only** registry entries. Any
session that never ran `session_register` — including the target — was dropped,
even though the API returns its `id` and `title`. There was no path from the
tools to an unregistered session's ID, and `session_send` only accepted a
registered name or a raw ID.

## Changes

### `opencode/plugins/session-messaging.js`

- **`session_list`** now takes `context` and appends an **"Unregistered live
  sessions"** section: live, top-level sessions (`!parentID`) that are not in
  the registry and are not the caller's own `context.sessionID`, sorted by
  `time.updated` and capped at 20, rendered as `- (unregistered) <id> "<title>" [dir]`.
  Registered-name lines are unchanged; the "no registered sessions" fallback no
  longer suppresses the unregistered section.
- **`session_send`** resolves `to` in order: registered name → raw session ID →
  **live title**. New helpers:
  - `looksLikeSessionID()` — `ses_*` or UUID shape (raw-ID passthrough).
  - `matchSessionsByTitle()` — pure, tiered match (exact → case-insensitive →
    substring), excludes subagents and the caller's own session.
  - `resolveTargetLive()` — async; on a title miss throws listing available live
    sessions, and on **multiple** matches throws with the candidate IDs
    (ambiguity is never auto-resolved).
  - `resolveTarget()` now returns `null` when `to` is neither a registry name nor
    a raw ID, so the caller can fall through to the title lookup.
- Updated the `session_list` / `session_send` descriptions and the `to` arg help.

### setup-home (canonical skill, different repo)

`agent-config/skills/server/session-messaging/SKILL.md`: documents that
`session_list` surfaces unregistered peers by title+ID, that `session_send`'s
`to` accepts name / raw ID / title (explicit name or ID preferred; ambiguous
titles error), and adds the "assumed unreachable because unregistered" mistake.

## Verification

Local:
- `node --check opencode/plugins/session-messaging.js` → OK.
- Pure-helper assertions (`looksLikeSessionID`, `resolveTarget`,
  `matchSessionsByTitle`) pass, including tier precedence and subagent/self exclusion.
- Stubbed-`client` integration run of the real plugin: `session_list` lists the
  registered peer + the unregistered target and excludes subagent/self;
  `session_send` resolves by title, registered name, and raw ID; `ask` omits
  `noReply`, `notify` sets it; ambiguous title and unknown target both throw with
  candidates. All assertions pass.

servyy-test (`servyy-test.sh --tags user.docker.opencode`):
- Play recap `ok=52 changed=13 failed=0`.
- New plugin present in the container (`resolveTargetLive` / `Unregistered live
  sessions`), canonical skill landed flat at
  `/root/.config/opencode/skills/session-messaging/SKILL.md`.
- Container restarted and reached `healthy`; in-container `/health` → 401 (as the
  healthcheck expects). No plugin load/import errors in `docker logs` (only the
  pre-existing, unrelated `xdg-open` warnings).

## Remaining

- Live two-session manual test on the test host (register one container session,
  confirm the other appears in `session_list` and is reachable by title) was not
  performed; the stubbed-client run exercises the same code paths.
- Not deployed to production (`codey.lehel.xyz`).

## Notes / limits

- Scope is still same-instance only (`opencode.web` on codey): host-side and
  container-side opencode sessions use separate registries/DBs and remain
  mutually unreachable.
- Titles are non-unique and drift as sessions evolve, so title matching is a
  convenience layer; an explicit name/ID always wins and ambiguity never silently
  resolves.
