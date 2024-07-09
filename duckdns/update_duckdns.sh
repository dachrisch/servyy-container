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

# Build the URL based on whether the IPv6 address is empty or not
url="https://www.duckdns.org/update?domains=${inventory_hostname}&token=${duck_token}"

if [ -n "$ipv6" ]; then
  url="${url}&ipv6=${ipv6}"
else
  echo "only updating IPv4 (no IPv6 address found)"
fi

# Update DuckDNS and store the response
response=$(curl -s "$url")

# Check if the response is "OK"
if [ "$response" = "OK" ]; then
  echo "DuckDNS update successful."
else
  echo "DuckDNS update failed. Response: $response"
  exit 1
fi
