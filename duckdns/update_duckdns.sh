#!/bin/sh

# Check if the correct number of arguments are provided
if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <inventory_hostname> <duck_token>"
  exit 1
fi

# Assign arguments to variables
inventory_hostname=$1
duck_token=$2

# Get the IP address (could be IPv4 or IPv6)
ip=$(curl -s ifconfig.me/ip)

# Regular expression to match a valid IPv6 address
ipv6_regex='^[0-9a-fA-F:]+$'

# Build the URL based on whether the IP address is a valid IPv6 address
url="https://www.duckdns.org/update?domains=${inventory_hostname}&token=${duck_token}"

if echo "$ip" | grep -Eq "$ipv6_regex" && echo "$ip" | grep -q ":"; then
  url="${url}&ipv6=${ip}"
else
  echo "Invalid IPv6 address. Only updating IPv4"
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
