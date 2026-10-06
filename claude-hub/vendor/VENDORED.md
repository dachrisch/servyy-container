# Vendored from `june-hub`

Source: `june-hub` plugin v0.2.1, `june-claude-marketplace @ a505eee` (JUNE GmbH), obtained as a
snapshot zip (`june-hub-0.2.1.zip`) on 2026-09-26. See
`history/2026-09-26_claude-hub-worktree-dispatch-rework.md` for why and how this is used.

## What's vendored

Copied from the zip, preserving relative directory depth so existing relative `import`
statements resolve unchanged, flattened directly under `claude-hub/vendor/` (no
third-party-branded subdirectory):

```
scripts/lib/hub-config.mjs
scripts/lib/proc.mjs
scripts/lib/memory.mjs
scripts/lib/launcher-install.mjs
scripts/launcher/hub.mjs
skills/spinup-session/scripts/spinup-session.mjs
skills/session-reaper/scripts/session-reaper.mjs
skills/session-reaper/scripts/transcript.mjs
skills/session-reaper/scripts/file-learning.mjs
```

Mounted read-only at `/opt/vendor` in the `claude-hub` container, invoked by absolute path — not
installed as an actual Claude Code plugin (no `--plugin-dir`, no marketplace). The plugin
packaging (`hooks/hooks.json`'s `SessionStart` prereq-nag hook, `.claude-plugin/`, `INSTALL.md`'s
marketplace flow) is built for an interactive human periodically starting fresh sessions, not a
single always-on headless service, and is skipped entirely.

**Not vendored** (genuinely unused, not a workaround): `scripts/lib/selftest.mjs` (test-only,
never referenced by a SKILL.md), `skills/session-reaper/scripts/install-schedule.mjs` (installs a
systemd **user** timer / LaunchAgent / Task Scheduler entry — none of which fits a root/system,
no-login-session, containerized deployment; this repo's own host-side `system` role timers
(`claude-hub-reaper.timer`, `claude-hub-force-cleanup.timer`) replace it), the Python test
suite/Poetry packaging, `.codex-plugin/`, `hooks/`, `.claude-plugin/`, `skills/hub-setup/`,
`README.md`/`INSTALL.md`.

## Rename patch

Unlike a typical vendoring pass, this is **not** a byte-for-byte copy. Every `june-hub`/`JUNE_HUB`
identifier inside these files was renamed in place to this project's own naming convention
(`CLAUDE_HUB_*` env vars, `claude-hub-*` names) — nothing was restructured or skipped to route
around it. Re-vendoring a future june-hub release means re-applying this exact substitution table
to the new files, then re-running `node --check` on all of them and re-verifying on
`servyy-test.lxd` per this repo's test-first workflow before touching production:

| File | Original | Renamed to |
|---|---|---|
| `scripts/lib/hub-config.mjs` | env var `JUNE_HUB_CONFIG` | `CLAUDE_HUB_CONFIG` |
| | default config filename `'june-hub.json'` | `'claude-hub.json'` |
| | `SETUP_HINT` string ("run the june-hub:hub-setup skill...") | "claude-hub's startup.sh writes ~/.claude/claude-hub.json at container boot" |
| | `repoMap` default dir segment `'june-hub'` | `'claude-hub'` (moot in practice — we always set `repoMap: null`) |
| `scripts/lib/proc.mjs` | comment "shared by every june-hub script" | "shared by every claude-hub vendored script" |
| | test-only env var `JUNE_HUB_FAST` | `CLAUDE_HUB_FAST` (never set by us either way) |
| `scripts/lib/launcher-install.mjs` | launcher dir segment `'june-hub'` in `launcherPath()` | `'claude-hub'` → installs to `~/.claude/claude-hub/hub.mjs` |
| | header comment | reworded |
| `scripts/launcher/hub.mjs` | header comments, `~/.claude/june-hub/hub.mjs` | `~/.claude/claude-hub/hub.mjs` |
| | marketplace-scan base dir segment `'june-hub'` | `'claude-hub'` (this whole scan is dead code in our deployment either way — we never install this as a real Claude Code plugin, so `candidates()` never finds anything; kept renamed for consistency, not hand-stripped) |
| | env var `JUNE_HUB_PLUGIN_ROOT` | `CLAUDE_HUB_VENDOR_ROOT` |
| | error message ("...run /plugin install june-hub@...") | rewritten to point at the `/opt/vendor` mount and `CLAUDE_HUB_VENDOR_ROOT` |

We set both `CLAUDE_HUB_VENDOR_ROOT=/opt/vendor` and `CLAUDE_HUB_CONFIG=/root/.claude/claude-hub.json`
as static `environment:` entries in `claude-hub/docker-compose.yml`, so every renamed lookup
resolves deterministically without depending on the (now-dead-anyway) marketplace-scanning
fallback.

## Local bug fixes (behavior, not renames)

Genuine deviations from the vendored source, beyond the rename patch above — kept here so a
future re-vendoring pass re-applies them too, not just the rename table.

| File | Fix | Why |
|---|---|---|
| `skills/spinup-session/scripts/spinup-session.mjs` | Adding a worktree for a git-crypt-enabled source repo now passes `--no-checkout` to `git worktree add`, copies `<source-git-dir>/git-crypt` into the new worktree's own git-dir, then does an explicit `checkout HEAD -- .` | git-crypt's unlocked key lives under the repo's own git-dir (`.git/git-crypt/keys/...`); a linked worktree gets its own git-dir (`.git/worktrees/<name>/`) with no such key, so plain `git worktree add`'s immediate checkout fails on the first encrypted path (`git-crypt: Unable to open key file`) and dispatch into any git-crypt repo (servyy-container included) came back `spinup-blocked`. See `history/2026-09-26_claude-hub-gitcrypt-worktree-fix.md`. |
| `skills/spinup-session/scripts/spinup-session.mjs` | Task-session `CLAUDE.md` close-request rule finds the hub by name ending in `hub` **or** by cwd being the infra repo checkout (`<checkoutRoot>/<INFRA_REPO>`, same default as `startup.sh`/`provision-repos.sh`) | `--remote-control 'hub'` alone left the messaging name (`ListAgents`/`SendMessage`) auto-generated (e.g. `servyy-container-4f`), so task sessions never found the hub by name. The cwd fallback matches the reaper's hub recognition. See issue #159. |
| `skills/session-reaper/scripts/session-reaper.mjs` | `--action revive` also revives `stopped` sessions with no parked ledger entry via a plain `claude respawn` fallback (`respawn-stopped`); only fails `not_in_ledger` when `claude agents` does not know the id either | A finished task session goes `stopped` (Remote Control disconnected) about a minute after its turn ends -- the CLI daemon retires settled or blocked workers after 60 s whenever free memory is below 1 GB (always true on 2 GB codey; see history/2026-09-29_claude-hub-ssh-rewrite-and-bg-retire.md), not via the reaper, so `revive` previously refused it with `not_in_ledger`. See issue #159. |
| `skills/session-reaper/scripts/session-reaper.mjs` | `revive`'s parked-entry lookup now checks the id's true latest ledger event (`entry = last?.event === 'parked' ? last : null`, reusing the already-computed `last`) instead of scanning for the last-ever `parked` event; the new `respawn-stopped` fallback also refuses (`not_revivable`) an id whose agent isn't `kind: 'background'` or is the hub, via a shared `isHubAgent()` helper now used by both `close` and `revive` | Review of PR #161 found the original lookup could return a stale `parked` record for an id later `revived`, routing a since-re-stopped session back into the entry-based path with a stale `resumeSessionId`/`loops` instead of the new fallback; the fallback also had no hub-safety check, unlike `close`'s equivalent guard. |
| `skills/session-reaper/scripts/session-reaper.mjs` | `close` now asks each repo's *source* repo whether it still registers the workspace path as a worktree on the recorded branch (new `registeredWorktree()` helper), before trusting any `git status`/`rev-list` run inside the path itself. A mismatch is reported as `corrupted` instead of `dirty_worktree`, and close removes that one repo's directory with a plain `rm -rf` instead of `git worktree remove` | `git worktree add <path>` names the admin dir (`<source-git-dir>/worktrees/<name>`) from `path`'s plain basename, which is just the repo name and repeats across every task on that repo. If an old workspace's admin-dir entry is ever pruned while its directory survives, a later, unrelated spinup on the same repo can get that exact name back; the old directory's `.git` file then resolves into the new worktree's index/HEAD, and `git status` there reports the wrong branch and hundreds of bogus "dirty" files. The old `close` trusted that output, refused with `dirty_worktree`, and a forced retry would have run `git worktree remove` against the *new* job's registration. Reproduced by hand on servyy-test.lxd (free a worktree's admin-dir entry, spin up a second task on the same repo, confirm the first workspace now reads the second one's branch) — see history/2026-10-06_claude-hub-reaper-fixes.md. |
| `skills/session-reaper/scripts/session-reaper.mjs` | `close` on a `cwd` that no longer exists at all now stops the agent and ledgers the close instead of failing `not_a_spinup_workspace` | A workspace hand-removed after being refused under the bug above (or by any other means) left its `claude agents` entry permanently stuck `blocked`/zombied — `close` always required reading `.spinup.json` from a directory that was already gone. |
| `skills/session-reaper/scripts/session-reaper.mjs` | `close`'s no-upstream fallback now checks whether `origin/<branch>` exists before computing "unpushed" commits; if it does, it diffs against that instead of the task's base branch, and only keeps the `no_upstream` framing when nothing on origin matches either | The old fallback always diffed against `base`, so a branch that was pushed but never got local tracking configured (`git push` without `--set-upstream`) was reported as having unpushed commits that were, in fact, already on `origin/<branch>`. |
| `skills/session-reaper/scripts/session-reaper.mjs` | `close` now walks up from each removed repo's directory, `rmdir`-ing now-empty parents up to (not past) the workspace root, instead of only ever checking the workspace root itself | Every repo lives at `<workspace>/<owner>/<repo>`; removing `<repo>` alone never emptied `<workspace>` (the `<owner>/` directory was always still there), so the final "remove the workspace if it's empty" check never fired and `<owner>/` directories piled up under old workspace roots indefinitely. |

## Why `scripts/launcher/hub.mjs` is vendored despite not being our normal invocation path

Our own systemd-timer-driven calls (`claude-hub-reaper.timer`, `claude-hub-force-cleanup.timer`)
invoke `session-reaper.mjs` directly by its fixed absolute path under `/opt/vendor` — they don't
go through `hub.mjs` at all, since there's no plugin-cache-version-drift problem to solve for a
single vendored copy.

`hub.mjs` is still vendored because `session-reaper.mjs` itself unconditionally runs, on every
real `--action run` (not `list`/`revive`/`close`/`--dry-run`):
```js
if (!existsSync(launcherPath())) installLauncher();
```
`installLauncher()` needs `scripts/launcher/hub.mjs` to exist as its copy source — without it,
the first real reaper run throws (`readFileSync` on a missing file). It copies that file to
`launcherPath()` (`~/.claude/claude-hub/hub.mjs`, after the rename above) the first time it's
missing. `launcherPath()` is also what the reaper's ledger uses to build its suggested
`revive`/`respawn`/`spinup` commands (`session-reaper.mjs`'s internal `reviveCmd`/`spawnCmd`
helpers) — so with the rename applied, those suggested commands are correct and directly runnable
(e.g. `node ~/.claude/claude-hub/hub.mjs reaper --action revive --id <id>`), rather than
referencing a launcher file that doesn't exist on our system.

## Left in, but inert

Windows/macOS-specific code paths inside the vendored files (e.g. `proc.mjs`'s cross-platform
process helpers, `session-reaper.mjs`'s state-dir resolution for non-Linux, `hub.mjs`'s
now-dead marketplace-scanning fallback) are **not** hand-stripped, so that re-vendoring a future
june-hub release stays a mechanical rename-table application rather than a divergent, hand-pruned
fork.
