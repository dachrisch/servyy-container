#!/bin/zsh

set -e
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
pushd "$SCRIPT_DIR" || exit

ipv4=$(curl -s https://ipinfo.io/ip)/32
ipv6=$(curl -s ifconfig.me/ip | cut -d':' -f -4)::/64
network=$(iwgetid -r)

if [[ $ipv4 == "/32" ]]; then
  echo "could not obtain ipv4: $ipv4"
  exit 1
fi

if [[ $ipv4 == "::/64" ]]; then
  echo "could not obtain ipv6: $ipv6"
  exit 1
fi

backup_dir=$(mktemp -d)
python main.py firewall save "$backup_dir"
echo "updating firewall with ipv4=$ipv4 and ipv6=$ipv6"
python main.py firewall merge_update "$backup_dir"/dns-filtered-fw_rules.json "Allow DNS from $network" in "('tcp', 'udp')" --port='53' "['$ipv4', '$ipv6']"

echo "checking that DNS is resolving"
nslookup google.com 88.198.151.84
nslookup google.com 2a01:4f8:1c1e:d9fb::1
