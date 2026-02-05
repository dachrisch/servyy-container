#!/bin/bash
set -euo pipefail

# Automated Restic Password Sync to Vaultwarden
# This script derives the URL from the hostname and stores passwords in:
# infrastructure/<hostname>/restic-password-{home,root}

HOSTNAME=${1:? "Usage: $0 <hostname>"}
# Use VAULTWARDEN_URL if provided, else derive it
BW_BASE_URL="${VAULTWARDEN_URL:-https://pass.${HOSTNAME}}"

# Isolate Bitwarden config to avoid interfering with user's main profile
export BITWARDENCLI_APPDATA_DIR="${HOME}/.config/bw-infrastructure"
mkdir -p "$BITWARDENCLI_APPDATA_DIR"

# Dependencies check
command -v bw >/dev/null 2>&1 || { echo >&2 "Error: Bitwarden CLI (bw) is required but not installed."; exit 1; }
command -v jq >/dev/null 2>&1 || { echo >&2 "Error: jq is required but not installed."; exit 1; }

# SSL Trust for test environment (mkcert)
# Check multiple possible locations for the CA certificate
CA_FOUND=false
for ca_loc in "/etc/ssl/mkcert/rootCA.pem" "/usr/local/share/ca-certificates/servyy-test-ca.crt" "/tmp/servyy-test-ca.pem"; do
    if [[ -f "$ca_loc" ]]; then
        export NODE_EXTRA_CA_CERTS="$ca_loc"
        echo "Using CA certificate: $ca_loc"
        CA_FOUND=true
        break
    fi
done

# Fallback for test environment if CA is not found or trust fails
if [[ "$HOSTNAME" == *"test.lxd" ]]; then
    if [ "$CA_FOUND" = false ]; then
        echo "Warning: CA certificate not found for test environment. Disabling SSL verification."
        export NODE_TLS_REJECT_UNAUTHORIZED=0
    fi
    # If we still get verification errors, the user can set this manually
fi

# Check if server is reachable (5 second timeout)
if ! curl -s --connect-timeout 5 -k "${BW_BASE_URL}/api/config" > /dev/null; then
    echo "Error: Vaultwarden at ${BW_BASE_URL} is unreachable." >&2
    exit 1
fi

echo "Configuring Bitwarden CLI for: ${BW_BASE_URL}"
bw config server "$BW_BASE_URL" > /dev/null

# Authentication logic
# 1. Try to use existing session if provided or cached
if [[ -z "${BW_SESSION:-}" && -f "${BITWARDENCLI_APPDATA_DIR}/session" ]]; then
    BW_SESSION=$(cat "${BITWARDENCLI_APPDATA_DIR}/session")
    export BW_SESSION
fi

# Function to perform login/unlock
do_auth() {
    local email="${1:-}"
    local password="${2:-}"
    local session=""

    if [[ -n "$email" && -n "$password" ]]; then
        # Try login, if already logged in try unlock
        session=$(bw login "$email" "$password" --raw 2>/dev/null || bw unlock "$password" --raw 2>/dev/null)
    elif [[ -n "$password" ]]; then
        session=$(bw unlock "$password" --raw 2>/dev/null)
    fi
    echo "$session"
}

# 2. Check if we are unlocked
IS_UNLOCKED=$(bw status | jq -r '.status' || echo "error")

if [[ "$IS_UNLOCKED" != "unlocked" ]]; then
    if [[ -n "${BW_EMAIL:-}" && -n "${BW_PASSWORD:-}" ]]; then
        echo "Attempting non-interactive login..."
        BW_SESSION=$(do_auth "$BW_EMAIL" "$BW_PASSWORD")
        
        # If it failed and we are in test environment, try disabling TLS verification
        if [[ ( -z "${BW_SESSION}" || "$BW_SESSION" == "null" ) && "$HOSTNAME" == *"test.lxd" ]]; then
            echo "Authentication failed. Retrying with SSL verification disabled for test environment..."
            export NODE_TLS_REJECT_UNAUTHORIZED=0
            BW_SESSION=$(do_auth "$BW_EMAIL" "$BW_PASSWORD")
        fi
        
        if [[ -z "${BW_SESSION}" || "$BW_SESSION" == "null" ]]; then
            echo "Error: Authentication failed for user ${BW_EMAIL}" >&2
            exit 1
        fi
        
        export BW_SESSION
        echo "$BW_SESSION" > "${BITWARDENCLI_APPDATA_DIR}/session"
    else
        # Interactive login
        echo "Authentication required for Vaultwarden at ${BW_BASE_URL}"
        bw login
        BW_SESSION=$(bw unlock --raw)
        
        if [[ -z "${BW_SESSION}" || "$BW_SESSION" == "null" ]]; then
            echo "Error: Authentication failed" >&2
            exit 1
        fi
        
        export BW_SESSION
        echo "$BW_SESSION" > "${BITWARDENCLI_APPDATA_DIR}/session"
    fi
fi

# 1. Ensure 'infrastructure' folder exists
FOLDER_NAME="infrastructure"
echo "Verifying folder: ${FOLDER_NAME}"
# bw list folders might return empty if nothing exists yet
FOLDERS_JSON=$(bw list folders)
FOLDER_ID=$(echo "$FOLDERS_JSON" | jq -r ".[] | select(.name == \"$FOLDER_NAME\") | .id")

if [[ -z "$FOLDER_ID" || "$FOLDER_ID" == "null" ]]; then
    echo "Creating root folder: ${FOLDER_NAME}"
    FOLDER_ID=$(bw get template folder | jq --arg name "$FOLDER_NAME" '.name = $name' | bw encode | bw create folder | jq -r ".id")
    if [[ -z "$FOLDER_ID" || "$FOLDER_ID" == "null" ]]; then
        echo "Error: Failed to create folder ${FOLDER_NAME}" >&2
        exit 1
    fi
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
    # Filter by exact name and folderId
    ITEMS_JSON=$(bw list items --search "$ITEM_NAME")
    ITEM_ID=$(echo "$ITEMS_JSON" | jq -r ".[] | select(.name == \"$ITEM_NAME\" and .folderId == \"$FOLDER_ID\") | .id" | head -n 1)

    if [[ -n "$ITEM_ID" && "$ITEM_ID" != "null" ]]; then
        # Update existing item
        bw get item "$ITEM_ID" \
            | jq --arg notes "$PASSWORD" '.notes = $notes' \
            | bw encode \
            | bw edit item "$ITEM_ID" > /dev/null
        echo "Successfully updated: ${ITEM_NAME}"
    else
        # Create new item
        bw get template item \
            | jq --arg name "$ITEM_NAME" --arg notes "$PASSWORD" --arg folderId "$FOLDER_ID" \
              '.type = 2 | .secureNote.type = 0 | .name = $name | .notes = $notes | .folderId = $folderId' \
            | bw encode \
            | bw create item > /dev/null
        echo "Successfully created: ${ITEM_NAME}"
    fi
done

echo "Sync complete."
# We don't lock here to allow session reuse across hosts in same run
