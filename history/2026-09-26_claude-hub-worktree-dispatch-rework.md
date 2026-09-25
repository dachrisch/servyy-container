# claude-hub: Rework Dispatch & Lifecycle (Worktree Sessions, Reaper)

**Date:** 2026-09-26
**Author:** Claude (via user dachrisch)
**Type:** Feature / Refactor
**Status:** 🚧 Implemented, static checks passed; pending Molecule/servyy-test.lxd verification and production deploy

## Summary

`claude-hub`'s dispatch mechanism (`launch-session.sh`: tmux + a bare mtime
marker file) and lifecycle mechanism (`prune-sessions.sh`: blind age-based
worktree deletion) have been reworked to build on ideas from **june-hub**, a
more mature Claude Code plugin for the same problem (a hub routing work to
background task sessions in git worktrees), that the user obtained as a
snapshot (`june-hub-0.2.1.zip`, `june-claude-marketplace @ a505eee`, JUNE
GmbH).

This is a **fusion**, not a wholesale swap and not a plugin install: kept
from current claude-hub — Docker packaging, boot-time provisioning with no
human required after a restart, the shared `claude_shared_dev_checkouts`
volume convention with `opencode`, the per-org GitHub credential helper, live
`gh-dash`-topic repo discovery across `dachrisch`/`bumbleflies`. Adopted from
june-hub — deterministic worktree/branch/session creation
(`spinup-session.mjs`), the `EnterWorktree`-disallow trick, workspace
`TASK.md`/`CLAUDE.md`/`.spinup.json` bookkeeping, and a ledger-based
`session-reaper` that parks/revives/closes sessions safely instead of
blindly deleting them.

**Every "june-hub"/"JUNE_HUB" identifier is renamed** to this project's own
convention (`CLAUDE_HUB_*` env vars, `claude-hub-*` names) — not routed
around with an env-var override or a skipped line. See
`claude-hub/vendor/VENDORED.md` for the full rename table.

## Design decisions (settled with the user)

1. **Repo discovery**: kept live `gh-dash`-topic auto-discovery — did not
   adopt june-hub's hand-curated `repo-map.md` model.
2. **Vendoring**: the relevant `.mjs` scripts are vendored (and renamed, see
   below) flat under `claude-hub/vendor/`, mounted read-only at
   `/opt/vendor`, invoked by absolute path. Not installed as an actual
   Claude Code plugin — the plugin packaging (`hooks.json`'s `SessionStart`
   nag hook, marketplace mechanics) is built for an interactive human, not a
   headless service.
3. **Disk-growth backstop**: june-hub's park/close model never auto-deletes
   (only a task session's own `close-request` + explicit user OK does). That
   removes the old 14-day blind-deletion backstop, so a new, infra-specific
   **force-cleanup** script was added on top (see below) — the user's
   explicit ask, after weighing "pure park/close, monitor manually" against
   adding a long-tail safety net and choosing the latter.

## Vendoring and the rename patch

Vendored, flat under `claude-hub/vendor/`:
```
scripts/lib/{hub-config,proc,memory,launcher-install}.mjs
scripts/launcher/hub.mjs
skills/spinup-session/scripts/spinup-session.mjs
skills/session-reaper/scripts/{session-reaper,transcript,file-learning}.mjs
```
Not vendored (genuinely unused): `scripts/lib/selftest.mjs` (test-only),
`install-schedule.mjs` (installs a systemd **user** timer/LaunchAgent/Task
Scheduler entry — none of which fits a root/system, no-login-session,
containerized deployment; replaced by this repo's own host-side `system`
role timers), the Python test suite/Poetry packaging, `.codex-plugin/`,
`hooks/`, `.claude-plugin/`, `skills/hub-setup/`.

Every `june-hub`/`JUNE_HUB` identifier inside the vendored files was renamed
in place — a pure substitution, nothing restructured or skipped (full table
in `claude-hub/vendor/VENDORED.md`): `JUNE_HUB_CONFIG` → `CLAUDE_HUB_CONFIG`,
default config filename `june-hub.json` → `claude-hub.json`,
`JUNE_HUB_FAST` → `CLAUDE_HUB_FAST`, `JUNE_HUB_PLUGIN_ROOT` →
`CLAUDE_HUB_VENDOR_ROOT`, every `'june-hub'` path segment (launcher install
dir, marketplace-scan base dir) → `'claude-hub'`, and the `SETUP_HINT`/error
strings rewritten to describe this deployment instead of an interactive
`hub-setup` skill or a marketplace install. Verified end-to-end against the
real vendored code (not just eyeballed): `validateConfig()` accepts the
generated config, `resolveSettings()` resolves it correctly with
`CLAUDE_HUB_CONFIG` pointed at a test file, and `launcherPath()` resolves to
`~/.claude/claude-hub/hub.mjs` with zero "june" anywhere in the result.

`scripts/launcher/hub.mjs` is vendored (it wasn't, in an earlier pass of this
same work) because `session-reaper.mjs` unconditionally runs
`if (!existsSync(launcherPath())) installLauncher();` on every real
`--action run`, which needs that file as its copy source — and, renamed, it
makes the reaper's ledger-suggested `revive`/`respawn` commands correct and
directly runnable instead of referencing a file that doesn't exist here.

## Target architecture

`claude-hub` stays one always-on `node:24-alpine` Docker service
(`claude-hub.hub`) on `codey.lehel.xyz`, boot-provisioned by `startup.sh`:

- **Hub session** — unchanged: a tmux-wrapped, foreground
  `claude --continue --remote-control 'hub'` process. Kept foreground/tmux
  (not `--bg`) deliberately: guarantees
  `docker exec -it claude-hub.hub tmux attach -t hub` keeps working
  regardless of how well-verified native `claude --bg`/`attach` turn out to
  be, and it satisfies `session-reaper.mjs`'s first rule
  (`kind !== 'background' → skip`) as defense in depth alongside the
  name-based `hub` protection.
- **Dispatch** — new `claude-hub/scripts/spinup-repo.sh`: reuses
  `launch-session.sh`'s exact resolve/clone logic (gh-dash search across
  both orgs, clone/update `$HOME/dev/<owner>/<repo>` — now supporting one
  *or more* repos per task, comma/space-separated), then hands off to
  vendored `spinup-session.mjs`, which owns everything deterministic from
  there: workspace layout, git worktrees, branch, session name, and starting
  a native `claude --bg --remote-control ... --disallowedTools=EnterWorktree`
  job in `$HOME/worktrees/<slug>/<owner>/<repo>`.
- **Lifecycle** — vendored `session-reaper.mjs`, run every 15 minutes by a
  host-side systemd timer → `docker exec` (`claude-hub-reaper.timer`):
  parks idle/never-prompted/cleared sessions (reversible via revive), and
  closes only on a task session's own `close-request`, relayed by the hub,
  after the user's explicit OK (new `session-fleet` skill).
- **Force-cleanup backstop** (new, infra-specific) —
  `claude-hub/scripts/force-cleanup-stale.sh`, on its own weekly timer
  (`claude-hub-force-cleanup.timer`), force-closes (via
  `session-reaper.mjs --action close`, never hand-rolled deletion) sessions
  parked longer than `CLAUDE_HUB_FORCE_CLEANUP_DAYS` (default 75 days). A
  dirty worktree still always blocks it and every branch is still always
  kept (only the worktree directory is torn down) — this is a deliberate,
  narrow override of `session-reaper`'s own "never close on a timeout"
  guardrail for this one long-tail case.

## Known, accepted gaps

- **cwd-based hub-protection mismatch**: june-hub's `samePath(cwd,
  checkoutRoot)` reaper rule assumes the hub's cwd *is* the checkout root;
  ours anchors two levels deeper (`$HOME/dev/dachrisch/servyy-container` vs.
  checkoutRoot `$HOME/dev`), by design, to support the multi-org gh-dash
  layout. This rule simply never fires for us — the name-based `hub` rule
  and the `kind !== 'background'` rule both still protect the hub
  independently, so this is a documented no-op, not a bug to chase.
- **Force-cleanup overrides a stated guardrail**: `session-reaper`'s own
  design says a `close-request` should never be acted on without the user's
  live OK. The weekly force-cleanup script does exactly that, for sessions
  parked far past a long threshold — an explicit, narrow, infra-specific
  exception the user asked for, not an oversight.
- **Native `claude --bg`/`claude agents`/`claude attach` behavior is still
  unverified against a live installed CLI** (same open gap as before this
  change, inherited from the original `claude-hub` design doc) — this is the
  single biggest risk item for the `servyy-test.lxd` pass below.

## Files Changed

**Modified:** `claude-hub/docker-compose.yml` (vendor mount +
`CLAUDE_HUB_VENDOR_ROOT`/`CLAUDE_HUB_CONFIG` env vars),
`claude-hub/scripts/startup.sh` (writes `/root/.claude/claude-hub.json`
non-interactively), `claude-hub/skills/repo-task-dispatch/SKILL.md`
(rewritten around `spinup-repo.sh`'s JSON-event contract),
`ansible/plays/roles/docker_service/templates/claude-hub/.env.j2` (new
`CLAUDE_HUB_*` vars, dropped `CLAUDE_HUB_PRUNE_DAYS`),
`ansible/plays/vars/default.yml` (`claude_hub_prune` →
`claude_hub_reaper` + new `claude_hub_force_cleanup`),
`ansible/plays/roles/system/tasks/main.yml` (import swap), `CLAUDE.md`
(claude-hub row), `ansible/plays/roles/docker_service/molecule/default/verify.yml`
and `ansible/plays/roles/system/molecule/with-docker/{converge,verify}.yml`.

**Removed:** `claude-hub/scripts/launch-session.sh` (superseded by
`spinup-repo.sh` + vendored `spinup-session.mjs`),
`claude-hub/scripts/prune-sessions.sh` (superseded by vendored
`session-reaper.mjs` + `force-cleanup-stale.sh`),
`ansible/plays/roles/system/tasks/claude_hub_prune.yml` and its three
templates (renamed/rewritten; the new `claude_hub_reaper.yml` explicitly
tears down the old systemd units first, since a template rename doesn't
delete a previously-rendered file).

**New:** `claude-hub/scripts/spinup-repo.sh`,
`claude-hub/scripts/force-cleanup-stale.sh`, `claude-hub/vendor/` (the
vendored+renamed `.mjs` files and `VENDORED.md`),
`claude-hub/skills/session-fleet/SKILL.md`,
`ansible/plays/roles/system/tasks/{claude_hub_reaper,claude_hub_force_cleanup}.yml`
and their systemd templates (`claude-hub-reaper.{sh,service,timer}.j2`,
`claude-hub-force-cleanup.{sh,service,timer}.j2`).

## Testing

Done so far (all static, no live Docker/CLI needed):
- `ansible-playbook servyy.yml -i production --syntax-check` — clean.
- `ansible-lint --profile production` (whole repo) — 0 failures/warnings.
- `sh -n` + `shellcheck -s sh` on `startup.sh`, `spinup-repo.sh`,
  `force-cleanup-stale.sh` — clean.
- `node --check` on every vendored + new `.mjs` file — clean.
- The generated `claude-hub.json` shape validated directly against the
  vendored `validateConfig()`/`resolveSettings()` — valid, resolves
  correctly, `CLAUDE_HUB_CONFIG` override honored.
- `launcherPath()` resolves to `~/.claude/claude-hub/hub.mjs` (zero "june"
  anywhere) when exercised directly against the vendored code.

**Not yet done** (this sandboxed session has no Docker access):
- `molecule test` in `ansible/plays/roles/docker_service` and
  `ansible/plays/roles/system` (both scenarios updated, neither yet run
  live).
- Full `servyy-test.lxd` deployment and the live-CLI verification list from
  the plan (`claude agents --json --all` behavior, a real `spinup-repo.sh`
  dispatch, `--disallowedTools=EnterWorktree` actually suppressing the
  approval prompt, the raw `claude attach`/`claude logs` operator commands,
  a real reaper timer tick, an end-to-end `close-request` round trip, and a
  force-cleanup dry run against a deliberately-aged parked session).
- Production deploy to `codey.lehel.xyz` — requires the above to pass first,
  then explicit user approval, per this repo's mandatory workflow.

## Future Enhancements

- Once `servyy-test.lxd` verification resolves the native `claude --bg`
  behavior question, consider whether the hub session itself could also
  move off tmux — deferred deliberately in this pass since it's the one
  guaranteed-working escape hatch.
- The pre-existing OAuth-credential backup gap (`/var/lib/docker` excluded
  from restic) and the never-verified `claude --remote-control` registration
  behavior are unchanged by this work — still open, out of scope here.
