#!/bin/sh
# Git credential helper (https://git-scm.com/docs/git-credential#IOFMT) for
# claude-hub. Registered by startup.sh as an absolute-path helper for
# https://github.com. Only implements the 'get' operation: it picks a PAT
# based on the repo owner in the request's 'path' field and answers with a
# username=x-access-token / password=<pat> pair (the GitHub App / fine-
# grained PAT convention for HTTPS git auth). Silently no-ops for 'store'
# and 'erase' -- git may invoke this helper with either, but there is
# nothing to persist since the PATs already live in the environment
# (rendered into claude-hub.env by Ansible), not a credential cache.
set -eu

op="${1:-}"

if [ "$op" != "get" ]; then
  exit 0
fi

host=""
path=""

# Read key=value lines from stdin until EOF or a blank line, per the git
# credential helper protocol.
while IFS='=' read -r key value; do
  [ -z "$key" ] && break
  case "$key" in
    host) host="$value" ;;
    path) path="$value" ;;
  esac
done

# Safe-by-construction, not just safe-by-registration: only ever answer for
# github.com, even if this helper were ever invoked for some other host
# (e.g. a misconfigured global credential.helper, rather than the
# github.com-scoped one startup.sh registers).
[ "$host" = "github.com" ] || exit 0

# path looks like "owner/repo.git" or "owner/repo"; owner is the first
# path segment.
owner="${path%%/*}"

case "$owner" in
  dachrisch)   pat="${GITHUB_PAT_DACHRISCH:-}" ;;
  bumbleflies) pat="${GITHUB_PAT_BUMBLEFLIES:-}" ;;
  # Unknown/missing owner: fall through to dachrisch's PAT, since dachrisch
  # is the primary personal org this credential helper mostly serves.
  *)           pat="${GITHUB_PAT_DACHRISCH:-}" ;;
esac

printf 'username=x-access-token\n'
printf 'password=%s\n' "$pat"
