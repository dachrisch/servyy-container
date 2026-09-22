#!/bin/sh
# Dynamic per-repo session dispatch for claude-hub. Called (through the Bash
# tool) by the hub's own Claude session -- see skills/repo-task-dispatch/
# SKILL.md -- to start a NEW, independent Claude Code session for one repo
# and one task:
#
#   launch-session.sh <owner/repo-or-search-term> <task-title>
#
# Steps:
#   1. Resolve the target repo. An exact "owner/repo" is used as-is; anything
#      else is a search term, matched (case-insensitive substring) against the
#      nameWithOwner of the gh-dash-tagged repos of the dachrisch and
#      bumbleflies orgs. Zero or several matches print the candidates (one
#      owner/repo per line) on stdout and exit 1. This script never prompts:
#      the calling Claude relays the options to the user and re-invokes with
#      an exact owner/repo.
#   2. Ensure $HOME/dev/<owner>/<repo> is cloned / up to date, over HTTPS via
#      the git credential helper that startup.sh registers (same mechanism
#      and same git command sequence as provision-repos.sh).
#   3. Create a fresh worktree + branch at
#      $HOME/worktrees/<owner>-<repo>/<branch> and stamp it with a
#      .claude-hub-created marker (prune-sessions.sh ages worktrees by it).
#   4. Start a detached tmux session running `claude --remote-control` there.
#   5. Print a short summary: repo, branch, worktree path, tmux session name.
#
# stdout is reserved for the two things the caller parses -- the candidate
# list and the final summary. Progress and errors go to stderr.
set -eu

HOME="${HOME:-/root}"
DEV_DIR="$HOME/dev"
WORKTREES_DIR="$HOME/worktrees"
ORGS="dachrisch bumbleflies"
# Launched branches are "<BRANCH_PREFIX>-<slug>-<epoch>". Deliberately no '/'
# in the branch name: it doubles as the worktree directory name, and a slash
# would nest the worktree one level too deep for prune-sessions.sh's
# $HOME/worktrees/*/* scan. prune-sessions.sh only deletes branches carrying
# this prefix, so keep the two in sync.
BRANCH_PREFIX="claude-hub"

# This runs under the hub Claude's Bash tool (no tty). If the credential
# helper ever yields a bad PAT, fail instead of hanging on a username prompt.
GIT_TERMINAL_PROMPT=0
export GIT_TERMINAL_PROMPT

log() { echo "[launch-session] $*" >&2; }

usage() {
  echo "usage: launch-session.sh <owner/repo-or-search-term> <task-title>" >&2
  exit 1
}

if [ "$#" -lt 2 ] || [ -z "$1" ] || [ -z "$2" ]; then
  usage
fi
target="$1"
task_title="$2"

# tmux silently rewrites '.' and ':' (its target separators) in session names
# to '_', so a later `-t <name>` built from the un-rewritten name would miss
# the session. Sanitise up front instead: every character outside
# [A-Za-z0-9_-] becomes '-'. That is a superset of "replace '.' and ':'"; it
# also covers '/', spaces and anything else that could upset tmux's target
# parsing. KEEP IN SYNC with sanitize_session_name() in prune-sessions.sh --
# prune recomputes the name to kill the session.
sanitize_session_name() {
  printf '%s\n' "$1" | sed 's/[^A-Za-z0-9_-]/-/g'
}

# lowercase; every run of non-alphanumerics becomes one '-'; cut to 40 chars;
# then strip dashes from both ends (the cut can leave a trailing one).
slugify() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-' \
    | tr -s '-' | cut -c1-40 | sed 's/^-*//; s/-*$//'
}

# Wrap $1 in single quotes for embedding in a shell command line; an embedded
# single quote becomes '\'' so a task title can never break out of the quoting.
shell_quote() {
  printf "'%s'" "$(printf '%s\n' "$1" | sed "s/'/'\\\\''/g")"
}

# Default branch of an exact owner/repo, read from the remote's HEAD symref:
# one round trip, works before any clone exists, and authenticates through the
# same credential helper as every other git call here. Falls back to "master"
# only when the remote answers but advertises no HEAD symref (e.g. an empty
# repo), mirroring the fallback in provision-repos.sh's node snippet.
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

# Same discovery call as provision-repos.sh (GH_TOKEN=<org PAT> gh repo list
# <org> --topic gh-dash ... across both orgs, PAT picked by a case on the org
# name). Prints "<owner/repo><TAB><default-branch>" for every repo whose
# nameWithOwner contains the search term (case-insensitive). The default
# branch comes straight from the discovery JSON's defaultBranchRef.name.
discover_matches() {
  _term="$1"
  for _org in $ORGS; do
    case "$_org" in
      bumbleflies) _pat="${GITHUB_PAT_BUMBLEFLIES:-}" ;;
      dachrisch)   _pat="${GITHUB_PAT_DACHRISCH:-}" ;;
      *)           _pat="" ;;
    esac
    if _out=$(GH_TOKEN="$_pat" gh repo list "$_org" --topic gh-dash --json nameWithOwner,url,defaultBranchRef --limit 100 2>&1); then
      # The term travels in the environment, not argv: no shell/JS quoting
      # issues and no chance of node mistaking it for one of its own flags.
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

# ---------------------------------------------------------------- 1. resolve
# Exact "owner/repo" == the brief's ^[^/]+/[^/]+$ : exactly one '/', non-empty
# on both sides (written as a case so it is POSIX and newline-safe).
case "$target" in
  */*/* | /* | */) exact=0 ;;
  */*)             exact=1 ;;
  *)               exact=0 ;;
esac

if [ "$exact" -eq 1 ]; then
  # owner/repo end up in filesystem paths and a URL: accept only GitHub's
  # own alphabet, and refuse "." / ".." path segments.
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

owner="${owner_repo%%/*}"
repo="${owner_repo#*/}"

# ------------------------------------------------------- 2. clone or update
# Deliberately a copy of provision-repos.sh's per-repo block -- same HTTPS
# URL form, same command sequence (remote set-url, then fetch + checkout +
# ff-only pull of the default branch; or a --branch clone), so the shared
# clone behaves identically whichever script touched it last. Only the error
# policy differs: provision-repos.sh warns and moves on to the next repo in
# its batch; here the one target repo is the whole point, so failure is
# fatal. provision-repos.sh has no callable function to source, and
# refactoring it is out of scope. KEEP IN SYNC with it.
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

# ------------------------------------------------------ 3. branch + worktree
slug="$(slugify "$task_title")"
[ -n "$slug" ] || slug="task"
# Epoch seconds as the uniqueness suffix. Two launches with the same repo and
# title inside one second would collide, and `git worktree add -b` then fails
# loudly rather than silently reusing anything.
branch_name="${BRANCH_PREFIX}-${slug}-$(date -u +%s)"
worktree_dir="$WORKTREES_DIR/${owner}-${repo}/${branch_name}"

log "creating worktree $worktree_dir (branch $branch_name from origin/$default_branch)"
mkdir -p "$WORKTREES_DIR/${owner}-${repo}"
git -C "$dest" worktree add "$worktree_dir" -b "$branch_name" "origin/$default_branch" >&2 \
  || { log "ERROR: git worktree add failed for $worktree_dir"; exit 1; }

# Marker consumed by prune-sessions.sh. Its mtime (not its content) is what
# gets aged; the content is just the human-readable creation time.
date -u +%Y-%m-%dT%H:%M:%SZ > "$worktree_dir/.claude-hub-created"

# ------------------------------------------------------------- 4. tmux start
session_name="$(sanitize_session_name "${owner}-${repo}-${branch_name}")"

# TODO(verify): the exact behavior of `claude --remote-control '<name>'` --
# whether the value is just a display name for the session or can also seed an
# initial prompt, and how Remote Control registration actually gets confirmed
# -- has not been verified against a live installed CLI as part of this
# implementation (same open gap as the hub session in startup.sh). Check
# `claude --help` before relying on <task-title> to do more than name the
# session, at the first real deploy.
tmux new-session -d -s "$session_name" -c "$worktree_dir" \
  "claude --remote-control $(shell_quote "$task_title")" \
  || { log "ERROR: tmux new-session failed for $session_name (worktree left at $worktree_dir; prune-sessions.sh will reap it)"; exit 1; }

# ---------------------------------------------------------------- 5. summary
printf 'repo: %s\n' "$owner_repo"
printf 'branch: %s\n' "$branch_name"
printf 'worktree: %s\n' "$worktree_dir"
printf 'tmux session: %s\n' "$session_name"
