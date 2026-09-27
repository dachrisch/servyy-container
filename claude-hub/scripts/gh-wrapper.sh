#!/bin/sh
# Wrapper for the GitHub CLI (`gh`) that selects the correct per-org PAT
# before handing off to the real binary. Installed by startup.sh at
# /usr/local/bin/gh, which precedes the apk-installed /usr/bin/gh on PATH --
# so the real binary is never renamed, just shadowed.
#
# Mirrors gh-cred-helper.sh's dachrisch/bumbleflies PAT split (git push/pull
# auth), but for the `gh` CLI itself, which only reads GH_TOKEN/GITHUB_TOKEN
# and has no equivalent to git's credential-helper protocol. See
# ansible/plays/roles/opencode/templates/bin/gh-wrapper.sh.j2 for the sibling
# implementation on the opencode side (deliberately not shared: opencode's
# version doesn't need repo-argument parsing or to preserve a caller-set
# GH_TOKEN, and is templated by Ansible rather than a plain bind-mounted
# script like this one).
set -eu

REAL_GH=/usr/bin/gh

# A caller that already set GH_TOKEN knows what it's doing (e.g. testing
# against a different token, or a repo outside dachrisch/bumbleflies) --
# never override it. Checked before everything else below, including the
# owner-agnostic subcommand skip.
if [ -n "${GH_TOKEN:-}" ]; then
  exec "$REAL_GH" "$@"
fi

# Owner-agnostic subcommands (and the bare --version/--help/-h flags) have
# no repo context at all -- gh itself doesn't need one for these, so don't
# force owner detection to run for them, and don't export any PAT: gh's own
# stored `gh auth login` credentials (if any) apply as normal, unaffected by
# this wrapper. Found via servyy-test verification: `gh auth status` has no
# -R, no positional repo, and (in claude-hub's checkoutRoot, not any single
# repo's worktree) no git origin remote either -- the general owner-
# detection gate below always came up empty for it, hard-failing a command
# that has nothing to do with any particular repo.
case "${1:-}" in
  auth | help | config | alias | extension | version | --version | --help | -h)
    exec "$REAL_GH" "$@"
    ;;
esac

owner=""

# 1. Prefer an explicit -R/--repo owner/repo on the command line: it's
#    authoritative regardless of the caller's cwd. Supports the two forms
#    `gh` itself documents: `-R value` / `--repo value` (space-separated)
#    and `--repo=value`. Deliberately not supported: the attached
#    shorthand form `-Rvalue` and an explicit [HOST/] prefix -- gh always
#    targets github.com here, and dispatched sessions don't use that form.
prev=""
for arg in "$@"; do
  case "$prev" in
    -R | --repo)
      owner="${arg%%/*}"
      break
      ;;
  esac
  case "$arg" in
    --repo=*)
      owner="${arg#--repo=}"
      owner="${owner%%/*}"
      break
      ;;
  esac
  prev="$arg"
done

# 2. Otherwise, a bare `owner/repo` positional argument: several
#    subcommands (`gh repo view`, `gh repo clone`, `gh repo list <owner>`,
#    ...) take the target as a positional rather than via -R/--repo. Take
#    the first non-flag argument that has the owner/repo shape (exactly one
#    '/', no further slashes -- so it can't be mistaken for a path).
if [ -z "$owner" ]; then
  for arg in "$@"; do
    case "$arg" in
      -*) ;;
      */*/*) ;;
      ?*/?*)
        owner="${arg%%/*}"
        break
        ;;
    esac
  done
fi

# 3. Otherwise, fall back to the cwd's git checkout: same origin remote
#    `gh` itself would infer a target repo from. Handles the three URL
#    shapes git actually produces for a github.com remote (SCP-like
#    `git@`, `https://`/`http://`, and explicit `ssh://`).
if [ -z "$owner" ]; then
  origin_url=$(git config --get remote.origin.url 2>/dev/null || true)
  case "$origin_url" in
    git@github.com:*)
      owner="${origin_url#git@github.com:}"
      owner="${owner%%/*}"
      ;;
    https://github.com/* | http://github.com/*)
      owner="${origin_url#*github.com/}"
      owner="${owner%%/*}"
      ;;
    ssh://git@github.com/*)
      owner="${origin_url#ssh://git@github.com/}"
      owner="${owner%%/*}"
      ;;
    *)
      owner=""
      ;;
  esac
fi

if [ -z "$owner" ]; then
  echo "gh-wrapper: could not determine the repo owner (pass -R owner/repo, an owner/repo argument, or run inside a git checkout with a github.com 'origin' remote) -- refusing to guess a GitHub token" >&2
  exit 1
fi

case "$owner" in
  bumbleflies) token="${GITHUB_PAT_BUMBLEFLIES:-}" ;;
  # Everything else (dachrisch, or any other owner) defaults to the
  # dachrisch PAT, matching gh-cred-helper.sh's convention.
  *) token="${GITHUB_PAT_DACHRISCH:-}" ;;
esac

export GH_TOKEN="$token"
exec "$REAL_GH" "$@"
