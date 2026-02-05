#!/bin/bash
set -euo pipefail

# Automated Restic Password Sync to Vaultwarden
# This script derives the URL from the hostname and stores passwords in:
# infrastructure/<hostname>/restic-password-{home,root}

HOSTNAME=${1:? "Usage: $0 <hostname>"}
BW_BASE_URL="https://pass.${HOSTNAME}"

# Isolate Bitwarden config to avoid interfering with user's main profile
export BITWARDENCLI_APPDATA_DIR="${HOME}/.config/bw-infrastructure"
mkdir -p "$BITWARDENCLI_APPDATA_DIR"

# Dependencies check
command -v bw >/dev/null 2>&1 || { echo >&2 "Error: Bitwarden CLI (bw) is required but not installed."; exit 1; }
command -v jq >/dev/null 2>&1 || { echo >&2 "Error: jq is required but not installed."; exit 1; }

# SSL Trust for test environment (mkcert)
if [[ -f "/etc/ssl/mkcert/rootCA.pem" ]]; then
    export NODE_EXTRA_CA_CERTS="/etc/ssl/mkcert/rootCA.pem"
fi

echo "Configuring Bitwarden CLI for: ${BW_BASE_URL}"
bw config set baseUrl "$BW_BASE_URL" >/dev/null

# Authentication logic
if [[ -n "${BW_EMAIL:-}" && -n "${BW_PASSWORD:-}" ]]; then
    echo "Attempting non-interactive login..."
    # Attempt to login and get session key
    BW_SESSION=$(bw login "$BW_EMAIL" "$BW_PASSWORD" --raw || bw unlock "$BW_PASSWORD" --raw)
    export BW_SESSION
else
    # Interactive login
    if ! bw status --session "${BW_SESSION:-}" | jq -e '.status == "unlocked"' >/dev/null; then
        echo "Authentication required for Vaultwarden at ${BW_BASE_URL}"
        bw login
        BW_SESSION=$(bw unlock --raw)
        export BW_SESSION
    fi
fi

# 1. Ensure 'infrastructure' folder exists
FOLDER_NAME="infrastructure"
echo "Verifying folder: ${FOLDER_NAME}"
FOLDER_ID=$(bw list folders --session "$BW_SESSION" | jq -r ".[] | select(.name == \"$FOLDER_NAME\") | .id")

if [[ -z "$FOLDER_ID" ]]; then
    echo "Creating root folder: ${FOLDER_NAME}"
    FOLDER_ID=$(bw get template folder | jq --arg name "$FOLDER_NAME" '.name = $name' | bw encode | bw create folder --session "$BW_SESSION" | jq -r ".id")
fi

# 2. Sync passwords (home and root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"; pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

for type in home root; do
    # Check multiple possible locations for password files
    PASS_FILE=""
    for loc in "${PROJECT_ROOT}/ansible/plays/vars/.restic_password_${type}" "${PROJECT_ROOT}/ansible/vars/.restic_password_${type}"; do
        if [[ -f "$loc" ]]; then
            PASS_FILE="$loc"
            break
        fi
    done

    if [[ -z "$PASS_FILE" ]]; then
        echo "Warning: Restic password file for ${type} not found. Skipping."
        continue
    fi

    PASSWORD=$(cat "$PASS_FILE")
    ITEM_NAME="${HOSTNAME}/restic-password-${type}"
    
    echo "Syncing item: ${ITEM_NAME}"
    
    # Check if item exists in the infrastructure folder
    ITEM_ID=$(bw list items --search "$ITEM_NAME" --session "$BW_SESSION" | jq -r ".[] | select(.name == \"$ITEM_NAME\" and .folderId == \"$FOLDER_ID\") | .id")

    if [[ -n "$ITEM_ID" ]]; then
        # Update existing item
        bw get item "$ITEM_ID" --session "$BW_SESSION" \
            | jq --arg notes "$PASSWORD" '.notes = $notes' \
            | bw encode \
            | bw edit item "$ITEM_ID" --session "$BW_SESSION" >/dev/null
        echo "Successfully updated: ${ITEM_NAME}"
    else
        # Create new item
        bw get template item \
            | jq --arg name "$ITEM_NAME" --arg notes "$PASSWORD" --arg folderId "$FOLDER_ID" \
              '.type = 2 | .secureNote.type = 0 | .name = $name | .notes = $notes | .folderId = $folderId' \
            | bw encode \
            | bw create item --session "$BW_SESSION" >/dev/null
        echo "Successfully created: ${ITEM_NAME}"
    fi
done

echo "Sync complete. Locking session..."
bw lock >/dev/null
