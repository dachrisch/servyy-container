#!/bin/bash
# DNS Layout Viewer
# Displays Porkbun domain configuration in user-friendly CLI format

set -uo pipefail  # removed -e to allow validation failures without exiting

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

  # Extract Porkbun keys using grep (yq parsing YAML is unreliable for this use case)
  PK=$(grep -A2 "porkbun_api:" "$REPO_ROOT/ansible/plays/vars/secrets.yml" | grep "pk:" | sed 's/.*pk: "\(.*\)".*/\1/' || echo "")
  SK=$(grep -A2 "porkbun_api:" "$REPO_ROOT/ansible/plays/vars/secrets.yml" | grep "sk:" | sed 's/.*sk: "\(.*\)".*/\1/' || echo "")
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

# Validate server connectivity and ownership
validate_server() {
  local hostname="$1"

  # Quick ping check
  if ! ping -c 1 -W 1 "$hostname" &>/dev/null; then
    echo -e "${RED}✗${NC} unreachable"
    return 1
  fi

  # SSH access check (short timeout)
  local ssh_ok=0
  if timeout 2 ssh -o ConnectTimeout=1 -o BatchMode=yes -o StrictHostKeyChecking=accept-new cda@"$hostname" exit &>/dev/null 2>&1; then
    ssh_ok=1
  fi

  # HTTP status check
  local http_code
  http_code=$(curl -s -o /dev/null -w "%{http_code}" -k --connect-timeout 1 "https://$hostname" 2>/dev/null || echo "000")

  # Determine status
  if [[ $ssh_ok -eq 1 ]]; then
    if [[ "$http_code" =~ ^[23][0-9]{2}$ ]]; then
      echo -e "${GREEN}✓${NC} owned (HTTP $http_code)"
    else
      echo -e "${GREEN}✓${NC} owned (HTTP $http_code)"
    fi
  else
    echo -e "${RED}✗${NC} no SSH access"
  fi
}

# Get hostname from IP (resolve CNAME or use direct hostname)
get_hostname_for_record() {
  local name="$1"
  local type="$2"

  # For A/AAAA records, validate the hostname itself
  # For CNAME records, skip validation (they're aliases)
  if [[ "$type" == "A" ]] || [[ "$type" == "AAAA" ]]; then
    echo "$name"
  fi
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

  # Extract records sorted by type, then name
  local records
  records=$(echo "$data" | jq -c '.records | sort_by(.type, .name)' 2>/dev/null)

  echo
  echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${BOLD}Porkbun Domain Layout: ${YELLOW}$domain${NC}"
  echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo

  # Group by type - capture records data to avoid subshell issues
  local records_data
  records_data=$(echo "$records" | jq -r '.[] | "\(.name)\t\(.type)\t\(.content)\t\(.ttl)"')

  local current_type=""
  local count=0

  while IFS=$'\t' read -r name type content ttl; do
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
        echo -e "  ${BLUE}$name${NC} ${BOLD}@${NC} $content (TTL: $ttl) [IPv6]"
        ;;
      ALIAS)
        echo -e "  ${BLUE}$name${NC} ${BOLD}⇒${NC} $content"
        ;;
      NS)
        echo -e "  ${BLUE}$name${NC} ${BOLD}»${NC} $content"
        ;;
      TXT)
        short_content="${content:0:50}"
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
  done <<< "$records_data"

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

  # Server Validation
  echo
  echo -e "${BOLD}${YELLOW}Server Health:${NC}"
  echo "$records" | jq -r '.[] | select(.type=="A") | .name' | sort -u | while read -r hostname; do
    result=$(validate_server "$hostname" 2>/dev/null || echo -e "${RED}✗${NC} error")
    echo -e "  ${BLUE}$hostname${NC} $result"
  done
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
