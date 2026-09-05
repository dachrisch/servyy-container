#!/bin/sh
# Idempotent provisioning of /root/dev checkouts + credentials for OpenCode.
# Discovers repos tagged with 'gh-dash' topic across dachrisch + bumbleflies orgs.
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

Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/id_github
  StrictHostKeyChecking accept-new
EOF
  chmod 600 "$SSH_DIR/config"
  # The .ssh dir is a bind mount from the docker host, where these files are
  # owned by the host user (e.g. cda/uid 1000). The container runs as root
  # (uid 0), and OpenSSH refuses to use a config/private key not owned by root,
  # which silently breaks every git-over-SSH clone/pull. Re-own them to root.
  chown root:root "$SSH_DIR/config"
  if [ -f "$SSH_DIR/id_github" ]; then
    chown root:root "$SSH_DIR/id_github"
    chmod 600 "$SSH_DIR/id_github"
  fi
  if [ -f "$SSH_DIR/id_servy" ]; then
    chown root:root "$SSH_DIR/id_servy"
    chmod 600 "$SSH_DIR/id_servy"
  fi
  log "ssh key + config written"
fi

# 2. GitHub SSH setup (use SSH_KEY_PATH if provided, otherwise assume mounted)
if [ -n "${SSH_KEY_PATH:-}" ]; then
  export GIT_SSH_COMMAND="ssh -i ${SSH_KEY_PATH} -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$SSH_DIR/known_hosts"
  log "GIT_SSH_COMMAND set to use $SSH_KEY_PATH"
fi

git config --global --add safe.directory '*'
git config --global user.name  "${GIT_AUTHOR_NAME:-opencode}"
git config --global user.email "${GIT_AUTHOR_EMAIL:-opencode@servy.lehel.xyz}"
# Use SSH for all github.com URLs (not HTTPS) to avoid credential issues
git config --global url."git@github.com:".insteadOf "https://github.com/"

# 2b. Seed Antigravity (Google) OAuth credential for OpenCode.
if [ -n "${OPENCODE_AUTH_GOOGLE_B64:-}" ]; then
  AUTH_DIR="$HOME/.local/share/opencode"; export AUTH_DIR
  result="$(python3 "$(dirname "$0")/seed_auth.py")" \
    && log "opencode google auth $result" \
    || log "WARN: opencode google auth seed failed (continuing)"
fi

# 3. Decode git-crypt key (used for repos flagged with the gh-dash-crypt topic)
CRYPT_KEY=""
if [ -n "${GIT_CRYPT_KEY_B64:-}" ]; then
  CRYPT_KEY="$(mktemp)"
  echo "$GIT_CRYPT_KEY_B64" | base64 -d > "$CRYPT_KEY"
fi

# 4. Ensure dev dir exists for discovery-based provisioning
mkdir -p "$DEV_DIR"

# 5. Discovery-based provisioning: search for repos with 'gh-dash' topic
# Searches across dachrisch + bumbleflies orgs. A repo additionally tagged
# 'gh-dash-crypt' is git-crypt encrypted and gets unlocked with CRYPT_KEY.
# ORGS is also used below (step 6) to identify orphaned clones -- keep both
# uses in sync by only listing orgs here.
ORGS="dachrisch bumbleflies"

if [ -x /usr/bin/gh.real ]; then
  log "discovering repos with 'gh-dash' topic..."

  for target in $ORGS; do
    log "  checking $target..."

    # Call gh.real directly with the org's own PAT. The gh wrapper instead
    # picks a token by inspecting the CWD's git remote, which doesn't exist
    # yet for this org-level listing call and silently defaults to the
    # dachrisch PAT -- rejected by orgs (e.g. bumbleflies) that forbid
    # long-lived fine-grained PATs, which then made this loop silently
    # find zero repos for that org.
    case "$target" in
      bumbleflies) target_pat="${GITHUB_PAT_BUMBLEFLIES:-}" ;;
      dachrisch)   target_pat="${GITHUB_PAT_DACHRISCH:-}" ;;
      *)           target_pat="" ;;
    esac

    if output=$(GH_TOKEN="$target_pat" /usr/bin/gh.real repo list "$target" --topic gh-dash --json nameWithOwner,url,defaultBranchRef --limit 100 2>&1); then
      repos="$output"
    else
      log "WARN: repo list failed for $target: $output"
      repos="[]"
    fi

    # Repos additionally tagged 'gh-dash-crypt' are git-crypt encrypted.
    # `gh repo list --json` cannot return topics, so query the crypt subset
    # separately and intersect it against the full gh-dash list below.
    if crypt_output=$(GH_TOKEN="$target_pat" /usr/bin/gh.real repo list "$target" --topic gh-dash-crypt --json nameWithOwner --limit 100 2>/dev/null); then
      crypt_repos="$crypt_output"
    else
      crypt_repos="[]"
    fi

    echo "$repos" | python3 -c '
import json,sys
repos = json.load(sys.stdin)
crypt_repos = json.loads(sys.argv[1])
crypt_set = {r["nameWithOwner"] for r in crypt_repos}
for r in repos:
    owner_repo = r["nameWithOwner"]
    branch = r.get("defaultBranchRef", {}).get("name", "master")
    # Use SSH URL: git@github.com:owner/repo.git
    ssh_url = f"git@github.com:{owner_repo}.git"
    crypt = "1" if owner_repo in crypt_set else "0"
    # Path: owner/repo (e.g. dachrisch/servyy-container)
    print("\t".join([owner_repo, ssh_url, branch, crypt]))
' "$crypt_repos" | while IFS="$(printf '\t')" read -r dir repo branch crypt; do
      dest="$DEV_DIR/$dir"
      if [ -d "$dest/.git" ]; then
        log "updating $dir"
        git -C "$dest" remote set-url origin "$repo"
        git -C "$dest" fetch --quiet origin "$branch" \
          && git -C "$dest" checkout --quiet "$branch" \
          && git -C "$dest" pull --quiet --ff-only origin "$branch" \
          || log "WARN: update failed for $dir (continuing)"
      else
        log "cloning $dir from $repo"
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
  done
fi

# 6. Clean up orphaned flat-layout clones. An earlier discovery generation
# cloned repos directly to $DEV_DIR/$repo instead of today's
# $DEV_DIR/$owner/$repo; nothing ever removed those when the layout changed,
# so they just sit there accumulating (never updated, never reclaimed).
# Anything at the top level that isn't a known org directory is stale.
log "checking for orphaned flat-layout clones..."
for entry in "$DEV_DIR"/*; do
  [ -e "$entry" ] || continue
  name=$(basename "$entry")
  is_org=0
  for org in $ORGS; do
    [ "$name" = "$org" ] && is_org=1 && break
  done
  [ "$is_org" = 1 ] && continue
  if [ -d "$entry/.git" ]; then
    log "removing orphaned flat clone: $name"
    rm -rf "$entry"
  fi
done

[ -n "$CRYPT_KEY" ] && rm -f "$CRYPT_KEY"
log "done"
