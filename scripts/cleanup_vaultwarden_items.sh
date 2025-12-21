#!/bin/bash
#
# cleanup_vaultwarden_items.sh - Delete invalid items from Vaultwarden
# Run this before re-seeding with the fixed seed script
#
# Usage: ./cleanup_vaultwarden_items.sh [test|prod]
#

set -euo pipefail

ENVIRONMENT="${1:-test}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANSIBLE_DIR="$(cd "$SCRIPT_DIR/../ansible" 2>/dev/null && pwd || echo "$SCRIPT_DIR")"
VW_SECRETS_FILE="${VW_SECRETS_FILE:-$ANSIBLE_DIR/plays/vars/bootstrap_secrets.yml}"
MKCERT_CA="${MKCERT_CA:-/etc/ssl/mkcert/rootCA.pem}"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check dependencies
command -v bw >/dev/null 2>&1 || { log_error "bitwarden CLI (bw) is required but not installed. Aborting."; exit 1; }
command -v jq >/dev/null 2>&1 || { log_error "jq is required but not installed. Aborting."; exit 1; }
command -v yq >/dev/null 2>&1 || { log_error "yq is required but not installed. Aborting."; exit 1; }

# Check files exist
[[ -f "$VW_SECRETS_FILE" ]] || { log_error "Vaultwarden config not found: $VW_SECRETS_FILE"; exit 1; }

log_info "Vaultwarden cleanup for environment: $ENVIRONMENT"

# Read Vaultwarden configuration
VW_SERVER_URL=$(yq -r ".vaultwarden.${ENVIRONMENT}.server_url" "$VW_SECRETS_FILE")
VW_CLIENT_ID=$(yq -r ".vaultwarden.${ENVIRONMENT}.api_client_id" "$VW_SECRETS_FILE")
VW_CLIENT_SECRET=$(yq -r ".vaultwarden.${ENVIRONMENT}.api_client_secret" "$VW_SECRETS_FILE")
VW_MASTER_PASSWORD=$(yq -r ".vaultwarden.${ENVIRONMENT}.master_password" "$VW_SECRETS_FILE")

if [[ "$VW_MASTER_PASSWORD" == "null" ]] || [[ -z "$VW_MASTER_PASSWORD" ]]; then
    log_error "Master password not found for environment: $ENVIRONMENT"
    exit 1
fi

log_info "Vaultwarden server: $VW_SERVER_URL"

# Set up environment for bw CLI
export NODE_EXTRA_CA_CERTS="$MKCERT_CA"
export BW_CLIENTID="$VW_CLIENT_ID"
export BW_CLIENTSECRET="$VW_CLIENT_SECRET"
export BW_PASSWORD="$VW_MASTER_PASSWORD"

# Configure bw server
log_info "Configuring Bitwarden CLI..."
bw config server "$VW_SERVER_URL" >/dev/null

# Login with API key
log_info "Logging in with API key..."
bw login --apikey 2>&1 | grep -v "You are already logged in" || true

# Unlock vault and get session
log_info "Unlocking vault..."
BW_SESSION=$(bw unlock --passwordenv BW_PASSWORD --raw)
export BW_SESSION

log_info "Session established: ${BW_SESSION:0:20}..."

# List all items
log_info "Listing all items..."
ALL_ITEMS=$(bw list items --session "$BW_SESSION")

# Find items with "NOT_FOUND" content
log_info "Searching for invalid items..."

INVALID_ITEMS=$(echo "$ALL_ITEMS" | jq -r '.[] | select(.notes == "NOT_FOUND" or (.notes // "" | contains("NOT_FOUND"))) | "\(.id):\(.name)"')

if [[ -z "$INVALID_ITEMS" ]]; then
    log_info "No invalid items found with 'NOT_FOUND' content."
else
    log_warn "Found invalid items:"
    echo "$INVALID_ITEMS"

    echo ""
    read -p "Do you want to delete these items? (yes/no): " confirm

    if [[ "$confirm" == "yes" ]]; then
        echo "$INVALID_ITEMS" | while IFS=: read -r item_id item_name; do
            log_info "Deleting: $item_name (ID: $item_id)"
            bw delete item "$item_id" --session "$BW_SESSION" >/dev/null
            log_info "✓ Deleted: $item_name"
        done
    else
        log_warn "Deletion cancelled by user"
    fi
fi

# Also find and delete items NOT in servyy folder (cleanup old flat structure)
log_info ""
log_info "Checking for items not in servyy folder..."
FOLDER_ID=$(bw list folders --session "$BW_SESSION" | jq -r --arg path "servy/servy-${ENVIRONMENT}" '.[] | select(.name == $path) | .id')

if [[ -n "$FOLDER_ID" ]]; then
    log_info "Found servyy folder ID: $FOLDER_ID"
    # List items not in the servyy folder
    ITEMS_NOT_IN_FOLDER=$(echo "$ALL_ITEMS" | jq -r --arg fid "$FOLDER_ID" '.[] | select((.folderId // "") != $fid) | "\(.id):\(.name)"')

    if [[ -n "$ITEMS_NOT_IN_FOLDER" ]]; then
        log_warn "Found items not in servy/servy-${ENVIRONMENT} folder:"
        echo "$ITEMS_NOT_IN_FOLDER"

        echo ""
        read -p "Do you want to delete these items? (yes/no): " confirm_folder

        if [[ "$confirm_folder" == "yes" ]]; then
            echo "$ITEMS_NOT_IN_FOLDER" | while IFS=: read -r item_id item_name; do
                log_info "Deleting: $item_name (ID: $item_id)"
                bw delete item "$item_id" --session "$BW_SESSION" >/dev/null
                log_info "✓ Deleted: $item_name"
            done
        else
            log_warn "Deletion cancelled by user"
        fi
    else
        log_info "All items are already in the servyy folder."
    fi
else
    log_warn "servy/servy-${ENVIRONMENT} folder not found yet (will be created by seed script)"
fi

# Logout
bw logout >/dev/null 2>&1 || true

log_info ""
log_info "✓ Cleanup complete!"
log_info "You can now run seed_vaultwarden.sh to recreate items with proper organization."
