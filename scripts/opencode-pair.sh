#!/usr/bin/env bash
# Print a one-time login link for an opencode instance (single use, 5 minutes).
#
# Usage:
#   ./opencode-pair.sh [ssh-target] [public-host]
#
# Defaults to codey.lehel.xyz / code.lehel.xyz — since the 2026-11-17 cutover
# codey IS the Oracle box, so the defaults are correct for the live instance.
# IdentitiesOnly matters there: without it the local agent offers enough keys to
# trip sshd's MaxAuthTries before reaching the authorized one.
#   SSH_OPTS='-o IdentitiesOnly=yes' ./opencode-pair.sh
#
# Don't use `opencode pair` here: it creates the code on its background service
# (127.0.0.1 only), not on the Traefik-facing server on :4096, so the browser
# always gets "This pairing link expired or was already used".
set -euo pipefail

SSH_TARGET=${1:-codey.lehel.xyz}
PUBLIC_HOST=${2:-code.lehel.xyz}

# Word-split on purpose: lets the caller pass several ssh flags through one var.
# shellcheck disable=SC2086
json=$(ssh ${SSH_OPTS:-} "$SSH_TARGET" \
  "docker exec opencode.web opencode api --server http://127.0.0.1:4096 POST /api/pair")
code=$(sed -nE 's/.*"code":"([^"]+)".*/\1/p' <<<"$json")

if [[ -z $code ]]; then
  echo "No pairing code in response: $json" >&2
  exit 1
fi

echo "https://${PUBLIC_HOST}/auth/connect/${code}"
