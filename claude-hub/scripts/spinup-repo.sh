#!/bin/sh
# Dynamic per-repo session dispatch for claude-hub. Called (through the Bash tool) by the hub's
# own Claude session -- see skills/repo-task-dispatch/SKILL.md -- to start a NEW, independent,
# worktree-isolated Claude Code background session for one or more repos and one task.
#
#   spinup-repo.sh <targets> <desc> [ticket] [task-file]
#
# <targets> is one or more comma/space-separated "owner/repo-or-search-term" values -- a task
# that touches more than one repo gets them all in the same workspace.
#
# Steps:
#   1. Resolve each target. An exact "owner/repo" is used as-is; anything else is a search term,
#      matched (case-insensitive substring) against the nameWithOwner of the gh-dash-tagged repos
#      of the dachrisch and bumbleflies orgs. Any target with zero or several matches prints its
#      candidates (one owner/repo per line) on stdout and exits 1 before anything is cloned or
#      started -- this script never prompts: the calling Claude relays the options to the user and
#      re-invokes with an exact owner/repo for that target.
#   2. Ensure $HOME/dev/<owner>/<repo> is cloned / up to date for every resolved target, over
#      HTTPS via the git credential helper that startup.sh registers (same mechanism and same git
#      command sequence as provision-repos.sh -- KEEP IN SYNC).
#   3. Hand off to the vendored spinup-session.mjs (see claude-hub/vendor/VENDORED.md), which owns
#      everything deterministic from here: workspace layout, branch, session name, worktree
#      creation, starting the background Remote Control session. Its single JSON event
#      (session-ready / session-exists / workspace-ready / spinup-planned / spinup-blocked) is
#      passed straight through on stdout.
#
# stdout is reserved for the two things the caller parses -- a target's candidate list (step 1)
# and spinup-session.mjs's JSON event (step 3). Progress and errors go to stderr.
set -eu

HOME="${HOME:-/root}"
DEV_DIR="$HOME/dev"
ORGS="dachrisch bumbleflies"
VENDOR_ROOT="${CLAUDE_HUB_VENDOR_ROOT:-/opt/vendor}"

# This runs under the hub Claude's Bash tool (no tty). If the credential helper ever yields a bad
# PAT, fail instead of hanging on a username prompt.
GIT_TERMINAL_PROMPT=0
export GIT_TERMINAL_PROMPT

log() { echo "[spinup-repo] $*" >&2; }

usage() {
  echo "usage: spinup-repo.sh <targets> <desc> [ticket] [task-file]" >&2
  echo "  <targets>: one or more comma/space-separated owner/repo-or-search-term values" >&2
  exit 1
}

if [ "$#" -lt 2 ] || [ -z "$1" ] || [ -z "$2" ]; then
  usage
fi
targets_raw="$1"
desc="$2"
ticket="${3:-}"
task_file="${4:-}"

# Default branch of an exact owner/repo, read from the remote's HEAD symref: one round trip,
# works before any clone exists, authenticates through the same credential helper as every other
# git call here. Falls back to "master" only when the remote answers but advertises no HEAD
# symref (e.g. an empty repo), mirroring the fallback in provision-repos.sh's node snippet.
resolve_default_branch() {
  _url="https://github.com/$1.git"
  if ! _out="$(git ls-remote --symref "$_url" HEAD 2>&1)"; then
    log "ERROR: cannot query $_url: $_out"
    return 1
  fi
  _branch="$(printf '%s\n' "$_out" \
    | awk '$1 == "ref:" { sub("^refs/heads/", "", $2); print $2; exit }')"
  if [ -z "$_branch" ]; then
    log "WARN: $1 advertises no HEAD symref; assuming master"
    _branch="master"
  fi
  printf '%s\n' "$_branch"
}

# Same discovery call as provision-repos.sh (GH_TOKEN=<org PAT> gh repo list <org> --topic
# gh-dash ... across both orgs, PAT picked by a case on the org name). Prints
# "<owner/repo><TAB><default-branch>" for every repo whose nameWithOwner contains the search term
# (case-insensitive). The default branch comes straight from the discovery JSON's
# defaultBranchRef.name.
discover_matches() {
  _term="$1"
  for _org in $ORGS; do
    case "$_org" in
      bumbleflies) _pat="${GITHUB_PAT_BUMBLEFLIES:-}" ;;
      dachrisch)   _pat="${GITHUB_PAT_DACHRISCH:-}" ;;
      *)           _pat="" ;;
    esac
    if _out=$(GH_TOKEN="$_pat" gh repo list "$_org" --topic gh-dash --json nameWithOwner,url,defaultBranchRef --limit 100 2>&1); then
      # The term travels in the environment, not argv: no shell/JS quoting issues and no chance of
      # node mistaking it for one of its own flags.
      printf '%s\n' "$_out" | SEARCH_TERM="$_term" node -e '
const fs = require("fs");
const term = (process.env.SEARCH_TERM || "").toLowerCase();
const repos = JSON.parse(fs.readFileSync(0, "utf8"));
repos.forEach(function (r) {
  if (r.nameWithOwner.toLowerCase().indexOf(term) === -1) { return; }
  const branch = (r.defaultBranchRef && r.defaultBranchRef.name) || "master";
  console.log([r.nameWithOwner, branch].join("\t"));
});
' || log "WARN: could not parse repo list for $_org"
    else
      log "WARN: repo list failed for $_org: $_out"
    fi
  done
  return 0
}

# ------------------------------------------------------------- 1. resolve every target
resolved=""
old_ifs="$IFS"
IFS=', '
# shellcheck disable=SC2086 # deliberate: splitting targets_raw on IFS (comma/space) is the point
set -- $targets_raw
IFS="$old_ifs"
for target in "$@"; do
  [ -n "$target" ] || continue

  # Exact "owner/repo" == the brief's ^[^/]+/[^/]+$ : exactly one '/', non-empty on both sides
  # (written as a case so it is POSIX and newline-safe).
  case "$target" in
    */*/* | /* | */) exact=0 ;;
    */*)             exact=1 ;;
    *)               exact=0 ;;
  esac

  if [ "$exact" -eq 1 ]; then
    # owner/repo end up in filesystem paths and a URL: accept only GitHub's own alphabet, and
    # refuse "." / ".." path segments.
    case "$target" in
      *[!A-Za-z0-9._/-]*) log "ERROR: '$target' is not a valid owner/repo"; exit 1 ;;
    esac
    case "${target%%/*}:${target#*/}" in
      .:* | ..:* | *:. | *:..) log "ERROR: '$target' is not a valid owner/repo"; exit 1 ;;
    esac
    owner_repo="$target"
    default_branch="$(resolve_default_branch "$owner_repo")" || exit 1
  else
    matches="$(discover_matches "$target")"
    match_count="$(printf '%s' "$matches" | grep -c . || true)"
    case "$match_count" in
      0)
        log "no gh-dash repo matches '$target' (re-run with an exact owner/repo)"
        exit 1
        ;;
      1)
        owner_repo="$(printf '%s\n' "$matches" | cut -f1)"
        default_branch="$(printf '%s\n' "$matches" | cut -f2)"
        ;;
      *)
        printf '%s\n' "$matches" | cut -f1
        log "'$target' matches $match_count repos (candidates on stdout); re-run with an exact owner/repo"
        exit 1
        ;;
    esac
  fi

  # --------------------------------------------------------- 2. clone or update
  # Deliberately a copy of provision-repos.sh's per-repo block -- same HTTPS URL form, same
  # command sequence (remote set-url, then fetch + checkout + ff-only pull of the default branch;
  # or a --branch clone), so the shared clone behaves identically whichever script touched it
  # last. Only the error policy differs: provision-repos.sh warns and moves on to the next repo in
  # its batch; here every target repo is required, so failure is fatal. KEEP IN SYNC with it.
  mkdir -p "$DEV_DIR"
  dest="$DEV_DIR/$owner_repo"
  repo_url="https://github.com/$owner_repo.git"
  if [ -d "$dest/.git" ]; then
    log "updating $owner_repo"
    git -C "$dest" remote set-url origin "$repo_url"
    if ! { git -C "$dest" fetch --quiet origin "$default_branch" \
        && git -C "$dest" checkout --quiet "$default_branch" \
        && git -C "$dest" pull --quiet --ff-only origin "$default_branch"; }; then
      log "ERROR: update failed for $owner_repo"
      exit 1
    fi
  else
    log "cloning $owner_repo from $repo_url"
    git clone --quiet --branch "$default_branch" "$repo_url" "$dest" >&2 \
      || { log "ERROR: clone failed for $owner_repo"; exit 1; }
  fi

  resolved="${resolved:+$resolved,}$owner_repo"
done

if [ -z "$resolved" ]; then
  log "ERROR: no targets given"
  exit 1
fi

# ------------------------------------------------------- 3. hand off to spinup-session.mjs
# spinup-session.mjs owns everything deterministic from here: workspace directory, worktrees,
# branch, session name. Never re-implement any of that here.
set -- --repos "$resolved" --desc "$desc" --root "$DEV_DIR"
[ -n "$ticket" ] && set -- "$@" --ticket "$ticket"
[ -n "$task_file" ] && set -- "$@" --task-file "$task_file"

SPINUP="$VENDOR_ROOT/skills/spinup-session/scripts/spinup-session.mjs"

# Build the workspace first, without starting anything (--no-start): claude --bg's first-run
# workspace-trust check blocks on every brand-new workspace directory otherwise, and nothing here
# is interactive to answer it. Confirmed live -- see
# history/2026-09-26_claude-hub-worktree-dispatch-rework.md. Calling spinup-session.mjs a second
# time below (without --no-start) is safe: an existing worktree/TASK.md/CLAUDE.md is its own
# ordinary "already built" case, not a special one we have to handle here.
build_out="$(node "$SPINUP" "$@" --no-start)" || { printf '%s\n' "$build_out"; exit 1; }

workspace="$(printf '%s\n' "$build_out" | node -e '
const fs = require("fs");
let d;
try { d = JSON.parse(fs.readFileSync(0, "utf8")); } catch { process.exit(1); }
if (d.event !== "workspace-ready" || !d.workspace) process.exit(1);
process.stdout.write(d.workspace);
')"

if [ -z "$workspace" ]; then
  # Not workspace-ready (e.g. spinup-blocked from a bad repo/branch/base) -- relay --no-start's
  # own output verbatim; there is no workspace here to seed trust for.
  printf '%s\n' "$build_out"
  exit 1
fi

log "pre-trusting workspace $workspace"
# ~/.claude.json is the Claude Code CLI's own state file (projects, trust, etc.) -- distinct from
# our CLAUDE_HUB_CONFIG-pointed claude-hub.json. Merge in one entry; never overwrite the file,
# it holds real state (auth, other projects) the CLI itself owns.
CLAUDE_HUB_SEED_WORKSPACE="$workspace" node -e '
const fs = require("fs");
const path = (process.env.HOME || "/root") + "/.claude.json";
let d = {};
try { d = JSON.parse(fs.readFileSync(path, "utf8")); } catch { d = {}; }
d.projects = d.projects || {};
const ws = process.env.CLAUDE_HUB_SEED_WORKSPACE;
d.projects[ws] = { ...(d.projects[ws] || {}), hasTrustDialogAccepted: true };
fs.writeFileSync(path, JSON.stringify(d, null, 2));
'

exec node "$SPINUP" "$@"
