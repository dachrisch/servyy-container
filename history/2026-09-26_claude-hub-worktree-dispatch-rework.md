# claude-hub: Rework Dispatch & Lifecycle (Worktree Sessions, Reaper)

**Date:** 2026-09-26
**Author:** Claude (via user dachrisch)
**Type:** Feature / Refactor
**Status:** ✅ Merged (PR #143, all 22 CI checks green including both Molecule scenarios) and
deployed to production `codey.lehel.xyz` — container healthy, hub session resumed on its existing
persistent volume (no fresh login needed), Bash tool and both new systemd timers confirmed
working live.

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

## Two bugs found and fixed during live `servyy-test.lxd` verification

Both root-caused live (not guessed), both fixed on this same branch since they blocked finishing
this branch's own verification.

**1. Workspace trust blocked every fresh dispatch (new, caused by this rework).**
`claude --bg`'s first-run workspace-trust check fires for every brand-new task workspace, because
`spinup-session.mjs` creates a new directory per task by design. Trust turned out to be a literal
per-directory entry in `~/.claude.json`'s `projects` map (`hasTrustDialogAccepted: true`), keyed by
the exact workspace-root path used as `cwd` in the `--bg` call — not inherited from the source
repo, not shared between sibling worktrees of the same repo (confirmed both ways experimentally).
Fix: `spinup-repo.sh` now calls `spinup-session.mjs --no-start` first to build the workspace and
learn its path, seeds that one trust entry via a small `node -e` (merging into `~/.claude.json`,
never overwriting it), then calls `spinup-session.mjs` again for real. Safe to automate:
`spinup-repo.sh` already fully owns everything under `/root/worktrees`.

**2. The 2026-09-25 `SHELL` fix (commit `a8270b1`) no longer works — pre-existing, not caused by
this rework.** Confirmed live on both the hub session and a dispatched session: the Bash tool
failed with `No suitable shell found...` even though `SHELL=/bin/sh` was genuinely present in the
process's own OS environment (checked via `/proc/<pid>/environ`, not a misdiagnosis). Root cause,
extracted directly from the installed CLI binary's strings (`strings .../bin/claude.exe | grep -B5
-A15 'No suitable shell found'`): this CLI version (`2.1.283`) scans `/bin` and `/usr/bin` for an
actual **`bash` or `zsh`** binary (or honors an explicit `CLAUDE_CODE_SHELL` override, itself
validated as a path whose name contains "bash" or "zsh") — plain POSIX-compliance was never
actually sufficient; `/bin/sh` on `node:24-alpine` is BusyBox `ash`, which this check rejects
regardless of `$SHELL`. Since `startup.sh` runs an unpinned `npm install -g
@anthropic-ai/claude-code` on every boot, this container always runs whatever's newest, and a
tightened check in a newer release silently broke the September fix with zero local change. Fix:
`apk add bash` in `startup.sh`, `docker-compose.yml` switched to `CLAUDE_CODE_SHELL=/bin/bash` +
`SHELL=/bin/bash`. Verified live in both the hub session and a fresh dispatched session after
redeploy — Bash tool works in both.

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
- **Native `claude --bg`/`claude agents` behavior** — the single biggest risk
  item going into the `servyy-test.lxd` pass, inherited as an open
  `TODO(verify)` from the original `claude-hub` design doc — is now
  confirmed working live (see Testing below), including a real
  `--disallowedTools` deny-list flag surviving into the running job and a
  real `close-request`/`SendMessage` round trip between sessions.

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

**Static** (no live Docker/CLI needed):
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

**Live on `servyy-test.lxd`** — deployed via `./servyy-test.sh --tags
user.docker.repo,user.docker.claude-hub,system.docker.claude_hub_reaper,system.docker.claude_hub_force_cleanup`
(branch auto-selected via the existing `docker.local_dir` HEAD lookup in
`includes/repository.yml` — no `-e branch=` needed):
- Full boot sequence completes correctly end to end, including the new
  `claude-hub.json` write step and gh-dash repo provisioning.
- `claude agents --json` works without auth (`[]` on an empty fleet).
- Vendored `session-reaper.mjs` runs correctly for real: `list --all`,
  `run --dry-run`, and a real automatic 15-minute timer tick that completed
  cleanly with no errors.
- Both new systemd timers (`claude-hub-reaper.timer`,
  `claude-hub-force-cleanup.timer`) created, enabled, correctly scheduled;
  old `claude-hub-prune.*` units fully torn down, no orphans.
- After the two bugs above were fixed and redeployed: a **full, real,
  end-to-end round trip** — `spinup-repo.sh` dispatch (gh-dash resolution +
  clone + automated workspace-trust pre-seeding) → `session-ready` on the
  first try → dispatched session runs real Bash-tool commands in its
  worktree → sends a `close-request` to the hub via `SendMessage` → hub
  dry-runs the close, asks for the user's OK, closes for real → worktree
  removed, branch (`claude/smoke-test-three`) and its commits kept, `reopen`
  command correctly references the renamed `~/.claude/claude-hub/hub.mjs`
  launcher. Repeated for a second dispatched session with the same result.
- `EnterWorktree` was never even invoked by either dispatched session (the
  `CLAUDE.md`/prompt instructions were sufficient on their own) — the
  `--disallowedTools=EnterWorktree` deny-list is there as the backstop for
  when that doesn't hold, not exercised as the primary mechanism in this
  pass.
- Real-world wrinkle, not a bug: Claude Code's own "auto mode" permission
  gate categorizes `session-reaper.mjs --action close` as risky enough to
  require an explicit manual run or a standing permission rule, even after
  the user approves the close in conversation — the hub's own suggested
  workaround (`! <command>` or a permission rule) handles this correctly;
  documented here so it isn't mistaken for a `session-fleet` skill bug.

**CI** (GitHub Actions, on PR #143): all 22 checks passed, including
`Molecule Test (docker_service/default)` and `Molecule Test (system/with-docker)` —
the two scenarios this session couldn't run locally (no Docker access).

**Production (`codey.lehel.xyz`)**, deployed via `./servyy.sh --tags
user.docker.repo,user.docker.claude-hub,system.docker.claude_hub_reaper,system.docker.claude_hub_force_cleanup
--limit codey.lehel.xyz` after explicit user approval:
- Both new systemd timers deployed, enabled, correctly scheduled; old
  `claude-hub-prune.*` units fully absent.
- Container healthy after the boot sequence completed (package installs,
  CLI install, `claude-hub.json` write, gh-dash provisioning, hub session
  start).
- Hub session resumed its existing conversation on the pre-existing
  `claude_hub_root` volume (same session id as before this change) — no
  fresh OAuth login needed in production, unlike the fresh `servyy-test.lxd`
  volume.
- Bash tool confirmed working (`bash -c 'echo ...'` via `docker exec`, and
  the `CLAUDE_CODE_SHELL`/`SHELL`/`CLAUDE_HUB_VENDOR_ROOT`/`CLAUDE_HUB_CONFIG`
  env vars all present and correct).

**Not exercised specifically on production** (already validated on
`servyy-test.lxd`, not worth repeating live against the real fleet): a real
task dispatch, the `close-request` round trip, and a force-cleanup dry run
against a deliberately-aged parked session. The raw `docker exec ... claude
attach`/`claude logs` operator commands were exercised via their
`session-reaper.mjs --action list --all` equivalent instead.

## Future Enhancements

- Once `servyy-test.lxd` verification resolves the native `claude --bg`
  behavior question, consider whether the hub session itself could also
  move off tmux — deferred deliberately in this pass since it's the one
  guaranteed-working escape hatch.
- The pre-existing OAuth-credential backup gap (`/var/lib/docker` excluded
  from restic) and the never-verified `claude --remote-control` registration
  behavior are unchanged by this work — still open, out of scope here.
