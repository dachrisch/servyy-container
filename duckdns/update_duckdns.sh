#!/bin/sh

# Check if the correct number of arguments are provided
if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <inventory_hostname> <duck_token>"
  exit 1
fi

# Assign arguments to variables
inventory_hostname=$1
duck_token=$2

# Get the IPv6 address
ipv6=$(curl -s ifconfig.me/ip)

# Update DuckDNS and store the response
response=$(curl -s "https://www.duckdns.org/update?domains=${inventory_hostname}&token=${duck_token}&ip=&ipv6=${ipv6}")

# Check if the response is "OK"
if [ "$response" = "OK" ]; then
  echo "DuckDNS update successful."
else
  echo "DuckDNS update failed. Response: $response"
  exit 1
fi
