#!/bin/sh
# Boot-time provisioning for the claude-hub container: installs tooling,
# configures git identity + credentials, seeds Claude settings, provisions
# repo checkouts, then starts (or resumes) the long-running "hub" tmux
# session that holds the persistent headless Claude Code process.
#
# Runs on every container boot (entrypoint). Must be idempotent.
set -e

echo "[startup] installing system packages..."
# 1. System packages. node/npm already ship in the node:22-alpine base image.
# bash: required by the Claude Code CLI's Bash tool, which scans /bin and /usr/bin for an actual
# bash/zsh binary rather than accepting any POSIX shell -- see docker-compose.yml's SHELL/
# CLAUDE_CODE_SHELL comment and history/2026-09-26_claude-hub-worktree-dispatch-rework.md.
apk update && apk add --no-cache git tmux github-cli git-crypt bash

echo "[startup] installing @anthropic-ai/claude-code..."
# 2. Claude Code CLI. Idempotent (npm just no-ops if already at this version).
#    /root/.npm cache lives on the persistent claude_hub_root volume, so
#    repeat boots after the first are fast.
npm install -g @anthropic-ai/claude-code

echo "[startup] configuring git identity..."
# 3. Git identity for commits made from inside this container.
git config --global user.name "claude-hub"
git config --global user.email "claude-hub@codey.lehel.xyz"
git config --global --replace-all safe.directory '*'

echo "[startup] registering github credential helper..."
# 4. Install the credential helper from the read-only /scripts mount to a
#    writable, executable path, then register it for github.com HTTPS auth.
#    Every form of credential.helper (bare name, absolute path, or
#    "!"-prefixed) is executed via a shell (sh -c) per gitcredentials(7);
#    the forms differ only in what string is built for that shell command,
#    not in whether a shell runs. A plain absolute path like this one is
#    used as-is with no "!" needed -- confirmed against git's documented
#    credential.helper resolution rules.
cp /scripts/gh-cred-helper.sh /usr/local/bin/gh-cred-helper.sh
chmod +x /usr/local/bin/gh-cred-helper.sh
git config --global credential.https://github.com.helper '/usr/local/bin/gh-cred-helper.sh'
# credential.useHttpPath defaults to false, which makes git strip the
# "path" attribute (the owner/repo.git part) from every credential
# request sent to an HTTP(S) helper -- without this, gh-cred-helper.sh's
# owner="${path%%/*}" routing always sees an empty path and always falls
# into its default case. Must be set for per-org PAT selection to work.
git config --global credential.useHttpPath true

echo "[startup] seeding ~/.claude/settings.json..."
# 5. Idempotently merge {"remoteControlAtStartup": true} into
#    ~/.claude/settings.json, preserving any other keys already present.
#    Best-effort: never let a JSON parse failure abort startup.
mkdir -p "$HOME/.claude"
node -e '
const fs = require("fs");
const path = process.env.HOME + "/.claude/settings.json";
let settings = {};
try {
  settings = JSON.parse(fs.readFileSync(path, "utf8"));
} catch (e) {
  settings = {};
}
settings.remoteControlAtStartup = true;
fs.writeFileSync(path, JSON.stringify(settings, null, 2) + "\n");
' || true

echo "[startup] writing ~/.claude/claude-hub.json..."
# 6. Non-interactively write the config the vendored dispatch/lifecycle scripts read (see
#    claude-hub/vendor/VENDORED.md) -- the equivalent of running june-hub's own interactive
#    hub-setup skill, but generated from Ansible-templated env vars every boot instead. Always
#    fully overwritten (unlike the settings.json merge above): nothing else ever writes this
#    file, so there is nothing to preserve, and it must stay in sync with the current env vars.
#    Best-effort: never let a JSON build failure abort startup.
mkdir -p "$HOME/.claude"
CLAUDE_HUB_SESSION_PREFIX="${CLAUDE_HUB_SESSION_PREFIX:-[codey]}" \
CLAUDE_HUB_OWNER="${CLAUDE_HUB_OWNER:-the user}" \
CLAUDE_HUB_NO_PR_REPOS="${CLAUDE_HUB_NO_PR_REPOS:-}" \
CLAUDE_HUB_REPO_NOTES_JSON="${CLAUDE_HUB_REPO_NOTES_JSON:-{}}" \
node -e '
const fs = require("fs");
const path = (process.env.CLAUDE_HUB_CONFIG || (process.env.HOME + "/.claude/claude-hub.json"));
const noPrRepos = (process.env.CLAUDE_HUB_NO_PR_REPOS || "")
  .split(",").map((s) => s.trim()).filter(Boolean);
let repoNotes = {};
try { repoNotes = JSON.parse(process.env.CLAUDE_HUB_REPO_NOTES_JSON || "{}"); } catch (e) { repoNotes = {}; }
const config = {
  version: 1,
  checkoutRoot: "/root/dev",
  workspaceRoot: "/root/worktrees",
  sessionPrefix: process.env.CLAUDE_HUB_SESSION_PREFIX,
  owner: process.env.CLAUDE_HUB_OWNER,
  repoMap: null,
  noPrRepos,
  repoNotes,
  contextDirs: [],
  reaper: {},
};
fs.writeFileSync(path, JSON.stringify(config, null, 2) + "\n");
' || echo "[startup] failed to write claude-hub.json (continuing)"

echo "[startup] provisioning repo checkouts..."
# 7. Provision dev checkouts (infra repo + gh-dash-tagged repos). Best-effort.
sh /scripts/provision-repos.sh || echo "[startup] provision-repos.sh reported issues (continuing)"

echo "[startup] starting hub session..."
# 8. Start (or resume) the persistent "hub" tmux session, then keep the
#    container alive. Guarded by `tmux has-session` so a restart that
#    somehow finds tmux already running (unlikely -- tmux dies with the
#    container -- but kept for defensive idempotency) doesn't spawn a
#    duplicate hub session.
#
# TODO(verify): the exact behavior of `claude --remote-control '<name>'` --
# whether the value is a display name vs. something else, and how Remote
# Control registration actually gets confirmed -- has not been verified
# against a live installed CLI as part of this implementation. Check
# `claude --help` before relying on this at the first real deploy.
HUB_DIR="$HOME/dev/${INFRA_REPO:-dachrisch/servyy-container}"
# provision-repos.sh (step 6 above) is best-effort and can fail silently to
# clone/anchor $HUB_DIR. Without this check, `tmux new-session -c "$HUB_DIR"`
# on a missing directory either falls back to $HOME (the workspace-trust
# failure mode) or, worse, dies here under `set -e` -- which would loop the
# expensive apk/npm install every `restart: unless-stopped` cycle with no
# running container to `docker exec` into and debug. Log and continue either
# way; this check must never itself be fatal.
if [ ! -d "$HUB_DIR/.git" ]; then
  echo "[startup] ERROR: $HUB_DIR is not a git checkout -- provision-repos.sh likely failed to clone/update it; hub session will still be started anchored there so an operator can docker exec in and fix it"
fi
if ! tmux has-session -t hub 2>/dev/null; then
  tmux new-session -d -s hub -c "$HUB_DIR" \
    "claude --continue --remote-control 'hub' || claude --remote-control 'hub'" \
    || echo "[startup] ERROR: hub session failed to start"
fi
exec tail -f /dev/null
