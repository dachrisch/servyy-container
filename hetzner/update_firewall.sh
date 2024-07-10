#!/bin/zsh

set -e
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
pushd "$SCRIPT_DIR" || exit

ipv4=$(curl -s https://ipinfo.io/ip)/32
ipv6=$(curl -s ifconfig.me/ip | cut -d':' -f -4)::/64
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

echo "checking that DNS is resolving"
if ! nslookup google.com 88.198.151.84 > /dev/null && ! nslookup google.com 2a01:4f8:1c1e:d9fb::1 > /dev/null; then
  echo "Firewall update needed."

  backup_dir=$(mktemp -d)
  echo "Backing up firewall rules to [$backup_dir]"
  python main.py firewall save "$backup_dir"

  echo "updating firewall with ipv4=$ipv4, ipv6=$ipv6 and ipv6_router=$ipv6_router"
  python main.py firewall merge_update "$backup_dir"/dns-filtered-fw_rules.json "Allow DNS from $network" in "('tcp', 'udp')" --port='53' "['$ipv4', '$ipv6', '$ipv6_router']"
else
  echo "Firewall already up to date."
fi
