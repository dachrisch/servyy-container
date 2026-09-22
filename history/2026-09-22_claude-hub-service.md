# claude-hub: Headless Claude Code Dispatcher Service

**Date:** 2026-09-22
**Author:** Claude (via user dachrisch)
**Type:** New Feature
**Status:** Implemented on `claude/claude-hub`, pending test-environment verification and explicit production approval

## Summary

Added `claude-hub`, a new Docker service on `codey.lehel.xyz` that runs a
persistent, headless Claude Code process (the "hub" session) inside a tmux
session. The hub session, reachable via claude.ai/code Remote Control, can
dynamically spin up brand-new, independent Remote-Control-visible Claude Code
sessions for any `gh-dash`-tagged repo across the `dachrisch` and
`bumbleflies` GitHub orgs — each in its own isolated git worktree — in
response to a chat request like "start work on the leagues-finance bug".

## Problem / Goal

There was no way to dispatch a Claude Code session against an arbitrary repo
from a chat interface without first being at a terminal with that repo
checked out. The goal: a single long-running "hub" session, itself
Remote-Control-visible, that can discover a target repo by name/topic, set up
an isolated worktree for it, and launch a fully independent session for that
one task — without the hub's own context, conversation, or terminal being
reused for the work.

## Solution

### Architecture

- `claude-hub/docker-compose.yml` — `node:22-alpine` base image, boot-time
  provisioning (no custom Dockerfile, matching this repo's convention),
  `restart: unless-stopped`, `traefik.enable=false` and **no** `proxy`
  network membership (belt-and-suspenders: this repo's Traefik has
  `exposedByDefault: true`, so omitting the network entirely is what
  actually keeps this container off any public route).
- `claude-hub/scripts/startup.sh` — entrypoint: installs `git tmux
  github-cli git-crypt` via apk, installs `@anthropic-ai/claude-code` via
  npm (both idempotent, cached on the persistent `claude_hub_root` volume),
  configures git identity + the HTTPS credential helper, seeds
  `~/.claude/settings.json` with `remoteControlAtStartup: true`, runs
  `provision-repos.sh` (best-effort), then starts (or resumes) the `hub`
  tmux session anchored at `$HOME/dev/$INFRA_REPO` and keeps the container
  alive with `tail -f /dev/null`.
- `claude-hub/scripts/provision-repos.sh` — clones/updates the infra repo
  itself plus every `gh-dash`-tagged repo across both orgs (git-crypt
  repos additionally tagged `gh-dash-crypt` get auto-unlocked), same
  discovery shape as `opencode/scripts/provision-dev.sh`.
- `claude-hub/scripts/gh-cred-helper.sh` — git credential helper; routes
  `dachrisch`/`bumbleflies` PATs by repo owner, safe-by-construction to
  `github.com` only.
- `claude-hub/scripts/launch-session.sh` — the dispatch entry point, called
  from inside the hub session's own Bash tool: resolves an exact
  `owner/repo` or a search term against the gh-dash-tagged repo list,
  clones/updates it, creates a fresh worktree + branch under
  `$HOME/worktrees/<owner>-<repo>/<branch>`, stamps a
  `.claude-hub-created` marker, and starts a detached tmux session running
  `claude --remote-control`.
- `claude-hub/scripts/prune-sessions.sh` — daily cleanup of worktrees whose
  marker is older than `CLAUDE_HUB_PRUNE_DAYS` (default 14), run via a new
  systemd timer (`ansible/plays/roles/system/tasks/claude_hub_prune.yml`,
  `claude-hub-prune.timer` at 04:30, after the nightly restic backup
  window).
- `claude-hub/skills/repo-task-dispatch/SKILL.md` — the Claude Code skill
  (mounted read-only at `/root/.claude/skills`) that teaches the hub session
  how to call `launch-session.sh` and relay its output.
- Ansible wiring: `docker_service` role invocation in `ansible/plays/user.yml`
  (`claude-hub.env` rendered from `ansible/plays/roles/docker_service/templates/claude-hub/.env.j2`),
  `claude-hub: true` under `codey.lehel.xyz` in `ansible/production`.
- Molecule coverage extended in `ansible/plays/roles/docker_service/molecule/default/`
  and `ansible/plays/roles/system/molecule/with-docker/`.

### Integration fix wave (this pass)

A whole-branch code review after the 5-task implementation surfaced several
integration-level gaps, fixed in this pass:

1. **`ansible/testing` didn't enable `claude-hub`** — the test-first deploy
   step could never exercise the service. Added `claude-hub: true` to
   `servyy-test.lxd`'s `services_enabled` in `ansible/testing`.
2. **`SKILL.md` frontmatter used OpenCode's convention** (`triggers:`,
   `delegates_to:`, `reads:`), which Claude Code does not read — it matches
   skills purely on `name` + `description`. Rewritten to plain `name:` +
   a specific, action-oriented `description:` folding in the old trigger
   phrases as natural language.
3. **`startup.sh`'s hub anchor directory wasn't checked** before the `tmux
   new-session -c "$HUB_DIR"` call. If `provision-repos.sh`'s best-effort
   infra-repo clone failed silently, tmux would either fall back to `$HOME`
   (a workspace-trust failure) or the whole entrypoint would die under
   `set -e`, looping the expensive `apk`/`npm install` every
   `restart: unless-stopped` cycle with no running container to debug from.
   Added a non-fatal `[ -d "$HUB_DIR/.git" ]` check that logs a clear
   `ERROR:` line, and made the `tmux new-session` call itself non-fatal.
4. **`prune-sessions.sh` had no liveness check** — it pruned purely by the
   age of the `.claude-hub-created` marker, which is never refreshed, so an
   actively-worked-on session past `CLAUDE_HUB_PRUNE_DAYS` would have its
   tmux session killed and its worktree force-removed with no warning.
   Added a `tmux has-session -t "<name>"` check that skips pruning (and
   logs why) when the session is still alive.
5. Documentation: this file, plus a `claude-hub` row in `CLAUDE.md`'s
   "Key Services" and "Common Per-Server Configurations" tables.
6. Minor cleanups: corrected a stale comment in `launch-session.sh` about
   what `prune-sessions.sh` actually matches on; `safe.directory` now uses
   `--replace-all` instead of `--add` (was growing `.gitconfig` on every
   boot); `provision-repos.sh`'s git-crypt key tempfile now has an
   EXIT trap (matching `prune-sessions.sh`'s pattern) instead of only
   cleaning up on the happy path; `provision-repos.sh` now sets
   `GIT_TERMINAL_PROMPT=0` like `launch-session.sh` does; `gh-cred-helper.sh`
   now hard-checks `host = github.com` after parsing instead of relying only
   on how it's registered; `launch-session.sh` now adds
   `.claude-hub-created` to the worktree's (shared, per-clone)
   `info/exclude` so it doesn't show up as untracked in every spawned
   session's `git status`.

## ⚠️ Required Manual Step After First Production Deploy

**The Claude OAuth login credential has zero backup coverage** (per the
plan's Risk section: `/var/lib/docker` is explicitly excluded from both the
root and home restic backups, and `claude_hub_root`'s volume contents,
including the login, aren't captured by anything else today). Losing the
volume means redoing this step from scratch — there is no automated
recovery path, so **this must be rediscoverable by a future operator**.

After the **first** production deploy of `claude-hub`, once
`provision-repos.sh` has had a chance to anchor the hub session in a real
git directory (workspace trust does not persist for a bare `$HOME`), log in
interactively:

```bash
ssh codey.lehel.xyz "docker exec -it claude-hub.hub tmux attach -t hub"
```

Inside the attached session, run:

```
/login
```

**Use the full-scope login flow, not `/login setup-token`** (setup-token
issues a short-lived scoped token, not a persistent session credential).
Open the printed URL on any device with a browser, complete the OAuth
consent, and paste the resulting code back into the session. Detach without
killing it (`Ctrl-b d`).

Confirm the hub session then appears in the claude.ai/code session list
(Remote Control) before considering the deploy complete. This step must be
repeated any time the `claude_hub_root` volume is lost or recreated.

## Task 6: Shared dev checkouts with opencode

The final whole-branch review (Important finding #5) flagged that
`claude-hub`'s `provision-repos.sh` independently clones the entire
`gh-dash`-tagged repo set of both orgs into its own private
`claude_hub_root` volume — duplicating exactly what `opencode` (already
running on the same `codey.lehel.xyz` host, same disk) clones into its own
private `opencode_root` volume, with no orphan cleanup on either side (this
was the "Future Enhancements" / "Known Issues" duplication noted above).
Fixed by having both containers mount the **same physical Docker volume** at
`/root/dev`:

- `opencode/docker-compose.yml` now defines a second top-level volume with a
  fixed, explicit name (`shared_dev_checkouts`, Docker volume name
  `claude_shared_dev_checkouts`) and mounts it at `/root/dev` on the
  `opencode` service, *in addition to* the existing `opencode_root:/root`
  mount. Docker mounts the more-specific `/root/dev` path from the second
  volume on top of the less-specific `/root` from the first — standard,
  supported layered-mount behavior.
- `claude-hub/docker-compose.yml` references the same volume as
  `external: true` (same fixed name) and mounts it at `/root/dev` on the
  `hub` service, *in addition to* the existing `claude_hub_root:/root`
  mount. `claude-hub`'s worktree working directories
  (`$HOME/worktrees/<owner>-<repo>/<branch>`) are **not** on the shared
  volume — only the base `$HOME/dev/<owner>/<repo>` clones are shared; the
  worktrees stay private to `claude_hub_root`.
- **No script changes needed.** Both `provision-repos.sh` and
  `provision-dev.sh` already resolve their clone directory as `$HOME/dev`
  (opencode's script allows a `DEV_DIR` override but defaults to the same
  `$HOME/dev`, and nothing sets that override), use the same
  `$DEV_DIR/<owner>/<repo>` layout, the same `dachrisch bumbleflies` org
  list and `gh-dash` topic, and the same clone-if-missing /
  fetch+checkout+ff-only-pull-if-present idempotent logic. Both containers
  also already run as root (uid 0) inside their images, so there's no
  ownership/permission mismatch between the two writers. Whichever
  container boots first does the real clone/update; the other's
  provisioning script just finds an already-current checkout and no-ops
  through it. `launch-session.sh`'s `$DEV_DIR` and `startup.sh`'s
  `$HUB_DIR` (`$HOME/dev/$INFRA_REPO`) anchor are likewise unaffected — they
  only read/write under `$HOME/dev` without caring whether it's backed by a
  private or shared volume.
- **Ordering dependency:** `opencode` must be deployed before or together
  with `claude-hub` on a given host for the `external: true` volume
  reference to resolve (Compose fails to start `claude-hub` otherwise,
  since the external volume must already exist). This is already true
  today — `opencode` is enabled on every host `claude-hub` is
  (`codey.lehel.xyz`), and the `docker_service` role invocation for
  `opencode` in `ansible/plays/user.yml` already runs earlier in that
  file's task list than the one for `claude-hub`.
- **Migration tradeoff:** on `opencode`'s *first* redeploy after this
  change, its previously-private `/root/dev` (inside the `opencode_root`
  volume) becomes orphaned/unused — Docker doesn't delete unused volume
  data, it just stops being mounted there. This is harmless: the new
  `shared_dev_checkouts` volume starts empty and `provision-dev.sh` simply
  re-clones into it on the next boot. No data loss, since these are all
  just re-creatable git clones; the only cost is one extra clone pass and
  the old data sitting unused inside `opencode_root` until that volume is
  itself pruned/removed.

## Files Changed

**Feature (prior commits on this branch):**
- `claude-hub/docker-compose.yml`, `claude-hub/.gitignore`
- `claude-hub/scripts/{startup.sh,provision-repos.sh,gh-cred-helper.sh,launch-session.sh,prune-sessions.sh}`
- `claude-hub/skills/repo-task-dispatch/SKILL.md`
- `ansible/plays/roles/docker_service/templates/claude-hub/.env.j2`
- `ansible/plays/user.yml`, `ansible/production`, `ansible/plays/vars/default.yml`
- `ansible/plays/roles/system/tasks/{claude_hub_prune.yml,main.yml}`
- `ansible/plays/roles/system/templates/claude-hub-prune.{sh,service,timer}.j2`
- Molecule: `ansible/plays/roles/docker_service/molecule/default/{converge.yml,verify.yml}`,
  `ansible/plays/roles/system/molecule/with-docker/{converge.yml,verify.yml}`

**This fix wave:**
- `ansible/testing` — added `claude-hub: true`
- `claude-hub/skills/repo-task-dispatch/SKILL.md` — frontmatter rewrite
- `claude-hub/scripts/startup.sh` — `HUB_DIR` existence check, non-fatal
  tmux call, `safe.directory --replace-all`
- `claude-hub/scripts/prune-sessions.sh` — tmux liveness check before pruning
- `claude-hub/scripts/provision-repos.sh` — `GIT_CRYPT_KEY_B64` tempfile
  EXIT trap, `GIT_TERMINAL_PROMPT=0`
- `claude-hub/scripts/gh-cred-helper.sh` — hard `host = github.com` check
- `claude-hub/scripts/launch-session.sh` — corrected prune-sessions.sh
  comment, `.claude-hub-created` added to worktree's shared `info/exclude`
- `CLAUDE.md` — Key Services + Common Per-Server Configurations rows
- `history/2026-09-22_claude-hub-service.md` — this document

**Task 6 (shared dev checkouts):**
- `opencode/docker-compose.yml` — added `shared_dev_checkouts` volume
  (fixed name `claude_shared_dev_checkouts`), mounted at `/root/dev`
- `claude-hub/docker-compose.yml` — added `shared_dev_checkouts` volume
  (`external: true`, same fixed name), mounted at `/root/dev`
- `CLAUDE.md` — extended the `claude-hub` row with the shared-checkout note
- `history/2026-09-22_claude-hub-service.md` — this section

## Testing

```bash
# Syntax
cd ansible && ansible-playbook servyy.yml --syntax-check
cd ansible && ansible-playbook servyy.yml -i production --syntax-check
cd ansible && ansible-lint --profile production

# Shell scripts
shellcheck claude-hub/scripts/*.sh
sh -n claude-hub/scripts/*.sh

# SKILL.md frontmatter is valid YAML (checked with PyYAML; no live Claude
# Code CLI available in this environment to verify actual skill-matching
# behavior against the new description)
```

Per repo policy, deployment to `servyy-test.lxd` (`./setup_test_container.sh`
then `./servyy-test.sh --limit servyy-test.lxd`) and container/tmux/session
verification there is still required before production, followed by explicit
user approval before `./servyy.sh --limit codey.lehel.xyz`. Neither was run
as part of this fix-wave pass — this workstation's `docker`/`tmux` were
off-limits for this pass (see guardrails); the actual test-environment
deploy and the one-time `/login` step above remain to be done by whoever
carries out the rollout in the plan's "Rollout" section.

## Known Issues / Not Verified

- `claude --remote-control '<name>'`'s exact behavior (display name vs.
  something else, how registration is confirmed) has not been verified
  against a live installed CLI — flagged with `TODO(verify)` comments in
  `startup.sh` and `launch-session.sh` for whoever does the first real
  deploy.
- The tmux liveness check added to `prune-sessions.sh` in this pass has not
  been exercised against a live container (tmux is off-limits on this
  workstation per the hard guardrails for this task).
- `provision-repos.sh`'s "claude-hub duplicates opencode's clone set with no
  orphan pruning" finding was explicitly deferred (monitoring
  recommendation, not a code change for this pass) — `du -sh` on
  `claude_hub_root` should be checked after the first couple of weeks in
  production, same as was done for opencode. **Resolved by Task 6** (see
  above): both containers now share one checkout set via the
  `claude_shared_dev_checkouts` volume, so this is no longer a duplication
  concern — though orphan pruning of stale `<owner>/<repo>` checkouts that
  fall out of the `gh-dash` topic (tracked separately, see "Future
  Enhancements" below) still applies to the now-shared volume.
- Task 6's compose changes were verified with `docker-compose config`
  (standalone binary; no live Docker daemon on this workstation) and
  `ansible-playbook servyy.yml --syntax-check` only — not deployed to
  `servyy-test.lxd`. The actual cross-container resolution of the
  `external: true` volume reference, and confirmation that both containers
  converge on one checkout set at runtime, remain to be verified at the
  first real test/production deploy.

## Future Enhancements

- Backup coverage for the OAuth login credential (accepted as a v1 risk;
  see plan's Risk section) if re-login proves more disruptive than expected.
- Orphan-clone pruning for `$HOME/dev/<owner>/<repo>` checkouts that fall
  out of the `gh-dash` topic (deferred from this review pass).
