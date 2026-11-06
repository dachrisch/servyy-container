#!/usr/bin/env bash
# Print a one-time login link for https://code.lehel.xyz (single use, 5 minutes).
#
# Don't use `opencode pair` here: it creates the code on its background service
# (127.0.0.1 only), not on the Traefik-facing server on :4096, so the browser
# always gets "This pairing link expired or was already used".
set -euo pipefail

json=$(ssh codey.lehel.xyz \
  "docker exec opencode.web opencode api --server http://127.0.0.1:4096 POST /api/pair")
code=$(sed -nE 's/.*"code":"([^"]+)".*/\1/p' <<<"$json")

if [[ -z $code ]]; then
  echo "No pairing code in response: $json" >&2
  exit 1
fi

echo "https://code.lehel.xyz/auth/connect/$code"
