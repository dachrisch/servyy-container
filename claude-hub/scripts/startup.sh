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
apk update && apk add --no-cache git tmux github-cli git-crypt

echo "[startup] installing @anthropic-ai/claude-code..."
# 2. Claude Code CLI. Idempotent (npm just no-ops if already at this version).
#    /root/.npm cache lives on the persistent claude_hub_root volume, so
#    repeat boots after the first are fast.
npm install -g @anthropic-ai/claude-code

echo "[startup] configuring git identity..."
# 3. Git identity for commits made from inside this container.
git config --global user.name "claude-hub"
git config --global user.email "claude-hub@codey.lehel.xyz"
git config --global --add safe.directory '*'

echo "[startup] registering github credential helper..."
# 4. Install the credential helper from the read-only /scripts mount to a
#    writable, executable path, then register it for github.com HTTPS auth.
#    An absolute path passed to credential.helper is invoked directly by git
#    (argv[0] = the path, "get"/"store"/"erase" appended as an argument);
#    only a "!"-prefixed value is run through a shell. Since this is a plain
#    absolute path (no "!"), no prefix is needed. Confirmed against git's
#    documented credential.helper resolution rules.
cp /scripts/gh-cred-helper.sh /usr/local/bin/gh-cred-helper.sh
chmod +x /usr/local/bin/gh-cred-helper.sh
git config --global credential.https://github.com.helper '/usr/local/bin/gh-cred-helper.sh'

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

echo "[startup] provisioning repo checkouts..."
# 6. Provision dev checkouts (infra repo + gh-dash-tagged repos). Best-effort.
sh /scripts/provision-repos.sh || echo "[startup] provision-repos.sh reported issues (continuing)"

echo "[startup] starting hub session..."
# 7. Start (or resume) the persistent "hub" tmux session, then keep the
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
if ! tmux has-session -t hub 2>/dev/null; then
  tmux new-session -d -s hub -c "$HUB_DIR" \
    "claude --continue --remote-control 'hub' || claude --remote-control 'hub'"
fi
exec tail -f /dev/null
