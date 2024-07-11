#!/bin/zsh

set -e
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
pushd "$SCRIPT_DIR" || exit

# Function to validate IPv6 address
is_valid_ipv6() {
    local ip=$1
    if [[ $ip =~ ^([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$ ]]; then
        return 0
    else
        return 1
    fi
}

# Function to get a valid IPv6 address
get_ipv6() {
    for i in {1..3}; do
        ipv6=$(curl -s ifconfig.me/ip )

        if is_valid_ipv6 "$ipv6"; then
            echo "$(echo $ipv6 | cut -d':' -f -4)::/64"
            return 0
        else
            echo "Invalid IPv6 address: $ipv6. Retrying ($i/3)..." >&2
            sleep $(( i ** 2 ))
        fi
    done

    echo "Failed to obtain a valid IPv6 address after 3 attempts." >&2
    echo '::/64'
    return 1
}

ipv4=$(curl -s https://ipinfo.io/ip)/32
ipv6=$(get_ipv6)
network=$(iwgetid -r)
ipv6_router=$(dig "$network".fritz.box AAAA +short|grep -v "^fd" | cut -d':' -f -2)::/32

if [[ $ipv4 == "/32" ]]; then
  echo "could not obtain ipv4: $ipv4"
  exit 1
fi

if [[ $ipv4 == "::/64" ]]; then
  echo "could not obtain ipv6: $ipv6"
  exit 1
fi

if [[ $ipv6_router == "::/64" ]]; then
  echo "could not obtain ipv6 for router: $ipv6_router"
  exit 1
fi

echo "updating firewall with ipv4=$ipv4, ipv6=$ipv6 and ipv6_router=$ipv6_router"

echo "checking that DNS is resolving"
if ! nslookup google.com 88.198.151.84 > /dev/null || ! nslookup google.com 2a01:4f8:1c1e:d9fb::1 > /dev/null; then
  echo "Firewall update needed."

  backup_dir=$(mktemp -d)
  echo "Backing up firewall rules to [$backup_dir]"
  python main.py firewall save "$backup_dir"

  python main.py firewall merge_update "$backup_dir"/dns-filtered-fw_rules.json "Allow DNS from $network" in "('tcp', 'udp')" --port='53' "['$ipv4', '$ipv6', '$ipv6_router']"
else
  echo "Firewall already up to date."
fi
