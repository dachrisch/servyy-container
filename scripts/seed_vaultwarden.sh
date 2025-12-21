#!/bin/bash
#
# seed_vaultwarden.sh - ONE-TIME migration script
# Populates Vaultwarden with infrastructure secrets from git-crypt encrypted files
#
# IMPORTANT:
# - Verify all passwords exist in git-crypt BEFORE running this script
# - This script is NOT used in disaster recovery (Vaultwarden restored from backup)
# - All items organized under "servyy" collection/organization
#
# Usage: ./seed_vaultwarden.sh [test|prod]
#

set -euo pipefail

ENVIRONMENT="${1:-test}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANSIBLE_DIR="$(cd "$SCRIPT_DIR/../ansible" 2>/dev/null && pwd || echo "$SCRIPT_DIR")"
SECRETS_FILE="${SECRETS_FILE:-$ANSIBLE_DIR/plays/vars/secrets.yml}"
VW_SECRETS_FILE="${VW_SECRETS_FILE:-$ANSIBLE_DIR/plays/vars/secret_vaultwarden.yaml}"
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
[[ -f "$SECRETS_FILE" ]] || { log_error "Secrets file not found: $SECRETS_FILE"; exit 1; }
[[ -f "$VW_SECRETS_FILE" ]] || { log_error "Vaultwarden config not found: $VW_SECRETS_FILE"; exit 1; }

log_info "Starting Vaultwarden seed for environment: $ENVIRONMENT"
log_info "Reading secrets from: $SECRETS_FILE"

# Read Vaultwarden configuration
VW_SERVER_URL=$(yq -r ".vaultwarden.${ENVIRONMENT}.server_url" "$VW_SECRETS_FILE")
VW_CLIENT_ID=$(yq -r ".vaultwarden.${ENVIRONMENT}.api_client_id" "$VW_SECRETS_FILE")
VW_CLIENT_SECRET=$(yq -r ".vaultwarden.${ENVIRONMENT}.api_client_secret" "$VW_SECRETS_FILE")
VW_MASTER_PASSWORD=$(yq -r ".vaultwarden.${ENVIRONMENT}.master_password" "$VW_SECRETS_FILE")

if [[ "$VW_MASTER_PASSWORD" == "null" ]] || [[ -z "$VW_MASTER_PASSWORD" ]]; then
    log_error "Master password not found for environment: $ENVIRONMENT"
    log_error "For production, you must manually enter the master password in this script or provide it interactively."
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

# Helper function to validate file content
validate_file_content() {
    local file_path="$1"
    local description="$2"

    if [[ ! -f "$file_path" ]]; then
        log_warn "Skipping $description - file not found: $file_path"
        return 1
    fi

    local content=$(cat "$file_path")
    if [[ -z "$content" ]]; then
        log_warn "Skipping $description - file is empty: $file_path"
        return 1
    fi

    return 0
}

# Helper function to create or update item
create_or_update_item() {
    local item_name="$1"
    local item_type="$2"  # 1=login, 2=secure_note
    local username="${3:-}"
    local password="${4:-}"
    local notes="${5:-}"
    shift 5
    local fields=("$@")  # Array of "name:value" pairs for custom fields

    log_info "Creating/updating item: $item_name"

    # Check if item exists
    existing_id=$(bw list items --search "$item_name" --session "$BW_SESSION" 2>/dev/null | jq -r --arg name "$item_name" '.[] | select(.name == $name) | .id' | head -1)

    # Build JSON
    if [[ "$item_type" == "1" ]]; then
        # Login item
        item_json=$(jq -n \
            --arg name "$item_name" \
            --arg username "$username" \
            --arg password "$password" \
            '{
                type: 1,
                name: $name,
                login: {
                    username: $username,
                    password: $password
                },
                fields: []
            }')
    else
        # Secure note
        item_json=$(jq -n \
            --arg name "$item_name" \
            --arg notes "$notes" \
            '{
                type: 2,
                name: $name,
                secureNote: {type: 0},
                notes: $notes,
                fields: []
            }')
    fi

    # Add custom fields
    for field in "${fields[@]}"; do
        IFS=':' read -r fname fvalue <<< "$field"
        item_json=$(echo "$item_json" | jq --arg name "$fname" --arg value "$fvalue" '.fields += [{name: $name, value: $value, type: 0}]')
    done

    # Create or update
    if [[ -n "$existing_id" ]]; then
        log_warn "Item '$item_name' already exists (ID: $existing_id), skipping..."
    else
        echo "$item_json" | bw encode | bw create item --session "$BW_SESSION" >/dev/null
        log_info "✓ Created: $item_name"
    fi
}

# =============================================================================
# MIGRATE SECRETS
# =============================================================================

log_info "Starting secret migration..."

# Item name prefix for organization
ITEM_PREFIX="servy/servy-${ENVIRONMENT}"
log_info "Using item prefix: $ITEM_PREFIX"

# Infrastructure secrets
log_info "=== Infrastructure Secrets ==="

# Storage Box credentials (username/password only - SSH key stays in bootstrap)
STORAGEBOX_USER=$(yq -r '.storagebox_credentials.user' "$SECRETS_FILE")
STORAGEBOX_PASSWORD=$(yq -r '.storagebox_credentials.password' "$SECRETS_FILE")
STORAGEBOX_HOST=$(yq -r '.storagebox_credentials.host' "$SECRETS_FILE")
create_or_update_item \
    "${ITEM_PREFIX}/infrastructure/${ENVIRONMENT}/storagebox/credentials" \
    "1" \
    "$STORAGEBOX_USER" \
    "$STORAGEBOX_PASSWORD" \
    "" \
    "host:$STORAGEBOX_HOST" \
    "ansible_var:storagebox_credentials.password"

# Restic root password (home password stays in bootstrap!)
# Try multiple possible locations for the password file
RESTIC_PASSWORD_FILE=""
for path in "$ANSIBLE_DIR/plays/vars/.restic_password_root" "$ANSIBLE_DIR/.restic_password_root" ".restic_password_root"; do
    if [[ -f "$path" ]]; then
        RESTIC_PASSWORD_FILE="$path"
        break
    fi
done

if [[ -n "$RESTIC_PASSWORD_FILE" ]] && validate_file_content "$RESTIC_PASSWORD_FILE" "restic root password"; then
    RESTIC_PASSWORD_ROOT=$(cat "$RESTIC_PASSWORD_FILE")
    create_or_update_item \
        "${ITEM_PREFIX}/infrastructure/${ENVIRONMENT}/restic/root_password" \
        "1" \
        "restic" \
        "$RESTIC_PASSWORD_ROOT" \
        "" \
        "ansible_var:restic_password_root" \
        "environment:$ENVIRONMENT"
fi

# Shell/Git credentials (optional - for private repos)
SHELL_KEY=$(yq -r '.shell.key_file' "$SECRETS_FILE" 2>/dev/null || echo "")
if [[ "$SHELL_KEY" != "null" ]] && [[ -n "$SHELL_KEY" ]]; then
    # Try multiple possible locations
    SHELL_KEY_PATH=""
    for path in "$ANSIBLE_DIR/plays/vars/$SHELL_KEY" "$ANSIBLE_DIR/$SHELL_KEY" "$SHELL_KEY"; do
        if [[ -f "$path" ]]; then
            SHELL_KEY_PATH="$path"
            break
        fi
    done

    if [[ -n "$SHELL_KEY_PATH" ]] && validate_file_content "$SHELL_KEY_PATH" "shell key"; then
        SHELL_KEY_CONTENT=$(cat "$SHELL_KEY_PATH")
        create_or_update_item \
            "${ITEM_PREFIX}/infrastructure/${ENVIRONMENT}/shell/key" \
            "2" \
            "" \
            "" \
            "$SHELL_KEY_CONTENT" \
            "ansible_var:shell.key_file"
    else
        log_info "Shell key not found - repo likely public, skipping"
    fi
fi

# Docker container key (optional - for private repos)
DOCKER_KEY=$(yq -r '.docker.key_file' "$SECRETS_FILE" 2>/dev/null || echo "")
if [[ "$DOCKER_KEY" != "null" ]] && [[ -n "$DOCKER_KEY" ]]; then
    # Try multiple possible locations
    DOCKER_KEY_PATH=""
    for path in "$ANSIBLE_DIR/plays/vars/$DOCKER_KEY" "$ANSIBLE_DIR/$DOCKER_KEY" "$DOCKER_KEY"; do
        if [[ -f "$path" ]]; then
            DOCKER_KEY_PATH="$path"
            break
        fi
    done

    if [[ -n "$DOCKER_KEY_PATH" ]] && validate_file_content "$DOCKER_KEY_PATH" "docker key"; then
        DOCKER_KEY_CONTENT=$(cat "$DOCKER_KEY_PATH")
        create_or_update_item \
            "${ITEM_PREFIX}/infrastructure/${ENVIRONMENT}/docker/key" \
            "2" \
            "" \
            "" \
            "$DOCKER_KEY_CONTENT" \
            "ansible_var:docker.key_file"
    else
        log_info "Docker key not found - repo likely public, skipping"
    fi
fi

# Ubuntu Pro token
UBUNTU_PRO_TOKEN=$(yq -r '.ubuntu_pro_token' "$SECRETS_FILE" 2>/dev/null || echo "")
if [[ "$UBUNTU_PRO_TOKEN" != "null" ]] && [[ -n "$UBUNTU_PRO_TOKEN" ]]; then
    create_or_update_item \
        "${ITEM_PREFIX}/infrastructure/${ENVIRONMENT}/ubuntu_pro/token" \
        "1" \
        "ubuntu_pro" \
        "$UBUNTU_PRO_TOKEN" \
        "" \
        "ansible_var:ubuntu_pro_token"
fi

# Social credentials
SOCIAL_USER=$(yq -r '.social.user' "$SECRETS_FILE" 2>/dev/null || echo "")
SOCIAL_PASSWORD=$(yq -r '.social.password' "$SECRETS_FILE" 2>/dev/null || echo "")
SOCIAL_EMAIL=$(yq -r '.social.email' "$SECRETS_FILE" 2>/dev/null || echo "")
if [[ "$SOCIAL_USER" != "null" ]] && [[ -n "$SOCIAL_USER" ]]; then
    create_or_update_item \
        "${ITEM_PREFIX}/services/${ENVIRONMENT}/social/credentials" \
        "1" \
        "$SOCIAL_USER" \
        "$SOCIAL_PASSWORD" \
        "" \
        "email:$SOCIAL_EMAIL" \
        "ansible_var:social.password"
fi

# Git repository credentials
GIT_USERNAME=$(yq -r '.servyy_git_repo.username' "$SECRETS_FILE" 2>/dev/null || echo "")
GIT_PASSWORD=$(yq -r '.servyy_git_repo.password' "$SECRETS_FILE" 2>/dev/null || echo "")
GIT_HOSTNAME=$(yq -r '.servyy_git_repo.hostname' "$SECRETS_FILE" 2>/dev/null || echo "")
if [[ "$GIT_USERNAME" != "null" ]] && [[ -n "$GIT_USERNAME" ]]; then
    create_or_update_item \
        "${ITEM_PREFIX}/services/${ENVIRONMENT}/git/credentials" \
        "1" \
        "$GIT_USERNAME" \
        "$GIT_PASSWORD" \
        "" \
        "hostname:$GIT_HOSTNAME" \
        "ansible_var:servyy_git_repo.password"
fi

log_info ""
log_info "=== Application Secrets ==="

# LeagueSphere secrets (if they exist)
LS_SECRET_FILE="$ANSIBLE_DIR/plays/vars/secret_leaguesphere.yaml"
if [[ -f "$LS_SECRET_FILE" ]]; then
    log_info "Found LeagueSphere secrets file: $LS_SECRET_FILE"
    log_warn "LeagueSphere secret migration should be implemented based on actual file structure"
    log_warn "Check the file and add migration code in this script"
fi

# TODO: Add more service secrets as needed
# - Traefik (Porkbun API key, basic auth)
# - Vaultwarden (admin token, SMTP)
# - Other Docker services

log_info ""
log_info "=== Migration Complete ==="
log_info "Summary:"
bw list items --session "$BW_SESSION" | jq -r '.[] | .name' | sort | while read -r name; do
    echo "  - $name"
done

log_info ""
log_info "✓ Seed complete! Vaultwarden now contains infrastructure secrets."
log_warn "NEXT STEPS:"
log_warn "1. Review created items in Vaultwarden web UI"
log_warn "2. Add any missing service secrets to this script and re-run"
log_warn "3. Test the lookup plugin with actual deployment"
log_warn "4. After validation, archive old secret files (secrets.yml, etc.)"

# Logout
bw logout >/dev/null 2>&1 || true
