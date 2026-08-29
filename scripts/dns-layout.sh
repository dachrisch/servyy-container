#!/bin/bash
# DNS Layout Viewer
# Displays Porkbun domain configuration in user-friendly CLI format

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Porkbun API credentials from secrets
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAIN="${1:-lehel.xyz}"

# Load secrets - support env vars or secrets.yml
PK="${PORKBUN_PK:-}"
SK="${PORKBUN_SK:-}"

# If not in env, try to load from secrets.yml (must be decrypted)
if [[ -z "$PK" ]] || [[ -z "$SK" ]]; then
  if [[ ! -f "$REPO_ROOT/ansible/plays/vars/secrets.yml" ]]; then
    echo -e "${RED}Error: secrets.yml not found${NC}" >&2
    exit 1
  fi

  # Check if file is encrypted (binary)
  if file "$REPO_ROOT/ansible/plays/vars/secrets.yml" | grep -q "data"; then
    echo -e "${RED}Error: secrets.yml is git-crypt encrypted${NC}" >&2
    echo -e "${YELLOW}Please decrypt with: git-crypt unlock${NC}" >&2
    echo -e "${YELLOW}Or set env vars: export PORKBUN_PK='...' PORKBUN_SK='...'${NC}" >&2
    exit 1
  fi

  # Extract Porkbun keys using yq or grep
  if command -v yq &> /dev/null; then
    PK=$(yq eval '.porkbun_api.pk' "$REPO_ROOT/ansible/plays/vars/secrets.yml" 2>/dev/null || echo "")
    SK=$(yq eval '.porkbun_api.sk' "$REPO_ROOT/ansible/plays/vars/secrets.yml" 2>/dev/null || echo "")
  else
    # Fallback to grep
    PK=$(grep -A1 "porkbun_api:" "$REPO_ROOT/ansible/plays/vars/secrets.yml" | grep "pk:" | awk '{print $2}' | tr -d '"' || echo "")
    SK=$(grep -A2 "porkbun_api:" "$REPO_ROOT/ansible/plays/vars/secrets.yml" | grep "sk:" | awk '{print $2}' | tr -d '"' || echo "")
  fi
fi

if [[ -z "$PK" ]] || [[ -z "$SK" ]]; then
  echo -e "${RED}Error: Porkbun API keys not found${NC}" >&2
  echo -e "${YELLOW}Set env vars or ensure git-crypt is unlocked${NC}" >&2
  exit 1
fi

# Fetch DNS records
fetch_records() {
  local domain="$1"
  curl -s -X GET "https://api.porkbun.com/api/json/v3/dns/retrieve/$domain" \
    -H "X-API-Key: $PK" \
    -H "X-Secret-API-Key: $SK"
}

# Parse and display records
display_layout() {
  local domain="$1"
  local data
  data=$(fetch_records "$domain")

  if ! echo "$data" | jq . &>/dev/null; then
    echo -e "${RED}Error: Invalid response from Porkbun${NC}" >&2
    return 1
  fi

  local status
  status=$(echo "$data" | jq -r '.status' 2>/dev/null)
  if [[ "$status" != "SUCCESS" ]]; then
    echo -e "${RED}Error: API returned status: $status${NC}" >&2
    return 1
  fi

  # Extract records
  local records
  records=$(echo "$data" | jq -c '.records | sort_by(.name, .type)' 2>/dev/null)

  echo
  echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${BOLD}Porkbun Domain Layout: ${YELLOW}$domain${NC}"
  echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo

  # Group by type
  local current_type=""
  local count=0

  echo "$records" | jq -r '.[] | "\(.name)\t\(.type)\t\(.content)\t\(.ttl)"' | while IFS=$'\t' read -r name type content ttl; do
    if [[ "$type" != "$current_type" ]]; then
      if [[ -n "$current_type" ]]; then
        echo
      fi
      echo -e "${BOLD}${GREEN}▸ $type Records${NC}"
      current_type="$type"
    fi

    # Format content based on type
    case "$type" in
      CNAME)
        echo -e "  ${BLUE}$name${NC} ${BOLD}→${NC} $content"
        ;;
      A)
        echo -e "  ${BLUE}$name${NC} ${BOLD}@${NC} $content (TTL: $ttl)"
        ;;
      AAAA)
        echo -e "  ${BLUE}$name${NC} ${BOLD}@${NC} $content (TTL: $ttl)"
        ;;
      ALIAS)
        echo -e "  ${BLUE}$name${NC} ${BOLD}⇒${NC} $content"
        ;;
      NS)
        echo -e "  ${BLUE}$name${NC} ${BOLD}»${NC} $content"
        ;;
      TXT)
        local short_content="${content:0:50}"
        [[ ${#content} -gt 50 ]] && short_content="${short_content}..."
        echo -e "  ${BLUE}$name${NC} ${BOLD}≈${NC} $short_content"
        ;;
      MX)
        echo -e "  ${BLUE}$name${NC} ${BOLD}✉${NC} $content"
        ;;
      *)
        echo -e "  ${BLUE}$name${NC} ${BOLD}·${NC} $content"
        ;;
    esac
    count=$((count + 1))
  done

  echo
  echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "Total Records: ${BOLD}$(echo "$records" | jq 'length')${NC}"
  echo

  # Show relationships
  echo -e "${BOLD}${YELLOW}Service Routing:${NC}"

  local has_cnames=false
  echo "$records" | jq -r '.[] | select(.type=="CNAME") | "\(.name) → \(.content)"' | while read -r line; do
    if [[ -n "$line" ]]; then
      has_cnames=true
      echo -e "  ${CYAN}$line${NC}"
    fi
  done

  if ! $has_cnames; then
    echo -e "  ${YELLOW}(No CNAME records)${NC}"
  fi
}

# Main
if [[ "${1:-}" == "-h" ]] || [[ "${1:-}" == "--help" ]]; then
  echo "Usage: dns-layout.sh [domain]"
  echo ""
  echo "Display Porkbun DNS records in user-friendly format"
  echo ""
  echo "Examples:"
  echo "  dns-layout.sh lehel.xyz"
  echo "  dns-layout.sh"
  exit 0
fi

display_layout "$DOMAIN"
