#!/bin/sh
# Idempotent provisioning of $HOME/dev checkouts for claude-hub: the infra
# repo itself, plus repos discovered via the 'gh-dash' topic across the
# dachrisch + bumbleflies orgs (same discovery shape as opencode's
# provision-dev.sh). Everything is cloned over HTTPS using the
# gh-cred-helper.sh credential helper registered by startup.sh -- no SSH,
# no known_hosts, no key material handled directly in this script.
# Runs on every container boot from startup.sh. Safe to re-run.
set -eu

HOME="${HOME:-/root}"
DEV_DIR="$HOME/dev"
INFRA_REPO="${INFRA_REPO:-dachrisch/servyy-container}"

# This runs unattended from startup.sh (no tty). If the credential helper
# ever yields a bad PAT, fail instead of hanging on a username/password
# prompt -- a stall here is worse than in launch-session.sh's interactive
# dispatch, since it blocks the whole entrypoint from ever starting the hub
# session.
GIT_TERMINAL_PROMPT=0
export GIT_TERMINAL_PROMPT

log() { echo "[provision-repos] $*"; }

mkdir -p "$DEV_DIR"

# 1. Clone/update the infra repo itself over HTTPS. Auth is handled
#    transparently by the credential helper git invokes (registered in
#    startup.sh) -- no PAT handling needed directly here.
infra_dest="$DEV_DIR/$INFRA_REPO"
infra_url="https://github.com/$INFRA_REPO.git"
if [ -d "$infra_dest/.git" ]; then
  log "updating infra repo ($INFRA_REPO)"
  git -C "$infra_dest" remote set-url origin "$infra_url"
  git -C "$infra_dest" fetch --quiet origin \
    && git -C "$infra_dest" pull --quiet --ff-only \
    || log "WARN: update failed for $INFRA_REPO (continuing)"
else
  log "cloning infra repo ($INFRA_REPO)"
  git clone --quiet "$infra_url" "$infra_dest" \
    || log "WARN: clone failed for $INFRA_REPO (continuing)"
fi

# 2. Decode git-crypt key (used for repos flagged with the gh-dash-crypt topic).
# trap ... EXIT (same pattern prune-sessions.sh uses for its tmpfile) so the
# decoded key material is removed even on an early exit under `set -eu`, not
# just on the happy-path cleanup at the bottom of this script.
CRYPT_KEY=""
trap 'rm -f "$CRYPT_KEY"' EXIT
if [ -n "${GIT_CRYPT_KEY_B64:-}" ]; then
  CRYPT_KEY="$(mktemp)"
  echo "$GIT_CRYPT_KEY_B64" | base64 -d > "$CRYPT_KEY"
fi

# 3. Discovery-based provisioning: search for repos with the 'gh-dash' topic
# across dachrisch + bumbleflies orgs. A repo additionally tagged
# 'gh-dash-crypt' is git-crypt encrypted and gets unlocked with CRYPT_KEY.
ORGS="dachrisch bumbleflies"

log "discovering repos with 'gh-dash' topic..."
for target in $ORGS; do
  log "  checking $target..."

  case "$target" in
    bumbleflies) target_pat="${GITHUB_PAT_BUMBLEFLIES:-}" ;;
    dachrisch)   target_pat="${GITHUB_PAT_DACHRISCH:-}" ;;
    *)           target_pat="" ;;
  esac

  if output=$(GH_TOKEN="$target_pat" gh repo list "$target" --topic gh-dash --json nameWithOwner,url,defaultBranchRef --limit 100 2>&1); then
    repos="$output"
  else
    log "WARN: repo list failed for $target: $output"
    repos="[]"
  fi

  # Repos additionally tagged 'gh-dash-crypt' are git-crypt encrypted.
  # `gh repo list --json` cannot return topics, so query the crypt subset
  # separately and intersect it against the full gh-dash list below.
  if crypt_output=$(GH_TOKEN="$target_pat" gh repo list "$target" --topic gh-dash-crypt --json nameWithOwner --limit 100 2>/dev/null); then
    crypt_repos="$crypt_output"
  else
    crypt_repos="[]"
  fi

  # No python3 in this image (node:22-alpine + only what startup.sh apk-adds);
  # use node (already installed for the Claude Code CLI) to intersect the
  # two JSON lists instead.
  echo "$repos" | node -e '
const fs = require("fs");
const repos = JSON.parse(fs.readFileSync(0, "utf8"));
const cryptRepos = JSON.parse(process.argv[1] || "[]");
const cryptSet = new Set(cryptRepos.map(function (r) { return r.nameWithOwner; }));
repos.forEach(function (r) {
  const ownerRepo = r.nameWithOwner;
  const branch = (r.defaultBranchRef && r.defaultBranchRef.name) || "master";
  const crypt = cryptSet.has(ownerRepo) ? "1" : "0";
  console.log([ownerRepo, branch, crypt].join("\t"));
});
' "$crypt_repos" | while IFS="$(printf '\t')" read -r dir branch crypt; do
    dest="$DEV_DIR/$dir"
    repo_url="https://github.com/$dir.git"
    if [ -d "$dest/.git" ]; then
      log "updating $dir"
      git -C "$dest" remote set-url origin "$repo_url"
      git -C "$dest" fetch --quiet origin "$branch" \
        && git -C "$dest" checkout --quiet "$branch" \
        && git -C "$dest" pull --quiet --ff-only origin "$branch" \
        || log "WARN: update failed for $dir (continuing)"
    else
      log "cloning $dir from $repo_url"
      git clone --quiet --branch "$branch" "$repo_url" "$dest" \
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

log "done"
