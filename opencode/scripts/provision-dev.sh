#!/bin/sh
# Idempotent provisioning of /root/dev checkouts + credentials for OpenCode.
# Runs on every container boot from startup.sh. Safe to re-run.
set -eu

HOME="${HOME:-/root}"
DEV_DIR="${DEV_DIR:-$HOME/dev}"
SSH_DIR="$HOME/.ssh"

log() { echo "[provision-dev] $*"; }

# 1. SSH key + config for servy.lehel.xyz (reached over the docker bridge)
if [ -n "${SERVY_SSH_KEY_B64:-}" ]; then
  mkdir -p "$SSH_DIR"; chmod 700 "$SSH_DIR"
  echo "$SERVY_SSH_KEY_B64" | base64 -d > "$SSH_DIR/id_servy"
  chmod 600 "$SSH_DIR/id_servy"
  cat > "$SSH_DIR/config" <<EOF
Host servy.lehel.xyz lehel.xyz
  HostName host.docker.internal
  User cda
  IdentityFile ~/.ssh/id_servy
  StrictHostKeyChecking accept-new
EOF
  chmod 600 "$SSH_DIR/config"
  log "ssh key + config written"
fi

# 2. GitHub HTTPS credentials (read+write via PAT)
if [ -n "${GITHUB_PAT:-}" ]; then
  git config --global credential.helper store
  printf 'https://x-access-token:%s@github.com\n' "$GITHUB_PAT" > "$HOME/.git-credentials"
  chmod 600 "$HOME/.git-credentials"
  log "github credential helper configured"
fi
git config --global --add safe.directory '*'
git config --global user.name  "${GIT_AUTHOR_NAME:-opencode}"
git config --global user.email "${GIT_AUTHOR_EMAIL:-opencode@servy.lehel.xyz}"

# 2b. Seed Antigravity (Google) OAuth credential for OpenCode.
# Merge the baked-in {"google": {...}} into auth.json without clobbering a
# credential opencode may have refreshed on a previous boot (persisted volume).
if [ -n "${OPENCODE_AUTH_GOOGLE_B64:-}" ]; then
  AUTH_DIR="$HOME/.local/share/opencode"; export AUTH_DIR
  result="$(python3 "$(dirname "$0")/seed_auth.py")" \
    && log "opencode google auth $result" \
    || log "WARN: opencode google auth seed failed (continuing)"
fi

# 3. Decode git-crypt key (used for repos flagged crypt=true)
CRYPT_KEY=""
if [ -n "${GIT_CRYPT_KEY_B64:-}" ]; then
  CRYPT_KEY="$(mktemp)"
  echo "$GIT_CRYPT_KEY_B64" | base64 -d > "$CRYPT_KEY"
fi

# 4. Clone/pull each declared repo
mkdir -p "$DEV_DIR"
if [ -n "${DEV_REPOS_B64:-}" ]; then
  echo "$DEV_REPOS_B64" | base64 -d | python3 -c '
import json,sys
for r in json.load(sys.stdin):
    print("\t".join([r["dir"], r["repo"], r.get("branch","master"), "1" if r.get("crypt") else "0"]))
' | while IFS="$(printf '\t')" read -r dir repo branch crypt; do
    dest="$DEV_DIR/$dir"
    if [ -d "$dest/.git" ]; then
      log "updating $dir"
      git -C "$dest" remote set-url origin "$repo"
      git -C "$dest" fetch --quiet origin "$branch" \
        && git -C "$dest" checkout --quiet "$branch" \
        && git -C "$dest" pull --quiet --ff-only origin "$branch" \
        || log "WARN: update failed for $dir (continuing)"
    else
      log "cloning $dir"
      git clone --quiet --branch "$branch" "$repo" "$dest" \
        || { log "ERROR: clone failed for $dir"; continue; }
    fi
    if [ "$crypt" = "1" ] && [ -n "$CRYPT_KEY" ]; then
      if git -C "$dest" config --local --get filter.git-crypt.smudge >/dev/null 2>&1; then
        log "$dir already git-crypt unlocked"
      else
        ( cd "$dest" && git-crypt unlock "$CRYPT_KEY" ) \
          && log "git-crypt unlocked $dir" \
          || log "WARN: git-crypt unlock failed for $dir"
      fi
    fi
  done
fi

[ -n "$CRYPT_KEY" ] && rm -f "$CRYPT_KEY"
log "done"
