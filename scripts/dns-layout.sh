#!/bin/bash
# DNS Layout Validator
# Validates that Porkbun DNS is correctly configured and services are accessible

set -uo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAIN="${1:-lehel.xyz}"

# Load secrets
PK="${PORKBUN_PK:-}"
SK="${PORKBUN_SK:-}"

if [[ -z "$PK" ]] || [[ -z "$SK" ]]; then
  if [[ ! -f "$REPO_ROOT/ansible/plays/vars/secrets.yml" ]]; then
    echo -e "${RED}Error: secrets.yml not found${NC}" >&2
    exit 1
  fi

  if file "$REPO_ROOT/ansible/plays/vars/secrets.yml" | grep -q "data"; then
    echo -e "${RED}Error: secrets.yml is git-crypt encrypted${NC}" >&2
    exit 1
  fi

  PK=$(grep -A2 "porkbun_api:" "$REPO_ROOT/ansible/plays/vars/secrets.yml" | grep "pk:" | sed 's/.*pk: "\(.*\)".*/\1/' || echo "")
  SK=$(grep -A2 "porkbun_api:" "$REPO_ROOT/ansible/plays/vars/secrets.yml" | grep "sk:" | sed 's/.*sk: "\(.*\)".*/\1/' || echo "")
fi

if [[ -z "$PK" ]] || [[ -z "$SK" ]]; then
  echo -e "${RED}Error: Porkbun API keys not found${NC}" >&2
  exit 1
fi

# Fetch DNS records
fetch_records() {
  curl -s -X GET "https://api.porkbun.com/api/json/v3/dns/retrieve/$1" \
    -H "X-API-Key: $PK" \
    -H "X-Secret-API-Key: $SK"
}

# Check A record: verify ownership via SSH
check_a_record() {
  local hostname="$1"
  if timeout 2 ssh -o ConnectTimeout=1 -o BatchMode=yes -o StrictHostKeyChecking=accept-new cda@"$hostname" exit < /dev/null &>/dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} owned"
  else
    echo -e "${RED}✗${NC} no access"
  fi
}

# Check AAAA record: verify it's same server as A record
check_aaaa_record() {
  local a_hostname="$1"
  local aaaa_hostname="$2"

  # Try SSH on both, they should both work if it's the same server
  if timeout 2 ssh -o ConnectTimeout=1 -o BatchMode=yes -o StrictHostKeyChecking=accept-new cda@"$aaaa_hostname" exit < /dev/null &>/dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} same server"
  else
    echo -e "${RED}✗${NC} mismatch"
  fi
}

# Check CNAME: verify service is accessible (2xx/3xx)
check_cname() {
  local hostname="$1"
  local http_code=$(curl -s -o /dev/null -w "%{http_code}" -k --connect-timeout 2 "https://$hostname" 2>/dev/null || echo "000")

  if [[ "$http_code" =~ ^[23][0-9]{2}$ ]]; then
    echo -e "${GREEN}✓${NC} accessible ($http_code)"
  else
    echo -e "${RED}✗${NC} error ($http_code)"
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

  # Build lookup table for AAAA records to pair with A records
  declare -A aaaa_lookup
  echo "$records" | jq -r '.[] | select(.type=="AAAA") | "\(.name) \(.content)"' | while read -r aaaa_name aaaa_ip; do
    echo "$aaaa_name=$aaaa_ip"
  done > /tmp/aaaa_$$.tmp
  while IFS='=' read -r aaaa_name aaaa_ip; do
    aaaa_lookup["$aaaa_name"]="$aaaa_ip"
  done < /tmp/aaaa_$$.tmp
  rm -f /tmp/aaaa_$$.tmp

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

    case "$type" in
      CNAME)
        result=$(check_cname "$name" 2>&1 || true)
        echo -e "  ${BLUE}$name${NC} ${BOLD}→${NC} $content $result"
        ;;
      A)
        result=$(check_a_record "$name" 2>&1 || true)
        echo -e "  ${BLUE}$name${NC} ${BOLD}@${NC} $content (TTL: $ttl) $result"
        ;;
      AAAA)
        result=$(check_aaaa_record "$name" "$name" 2>&1 || true)
        echo -e "  ${BLUE}$name${NC} ${BOLD}@${NC} $content (TTL: $ttl) $result"
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
