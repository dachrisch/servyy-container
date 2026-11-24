# hetzner/ — Hetzner firewall rules from a dynamic client IP

Keeps the `dns-filtered-fw` firewall in sync with the current public IPv4/IPv6 of the
machine running the script. The firewall only allows DNS from known client networks;
when the client IP changes, DNS stops resolving and the rules must be updated.

## Files

- `main.py` — CLI (`fire`) around the `hcloud` Python SDK. A `SerializableRule` maps
  `hcloud.firewalls.FirewallRule` slots to JSON so rules can be saved, merged and
  re-applied. Rules carry direction, protocol, source/destination IPs, port and
  description. Default firewall name: `dns-filtered-fw`.
- `update_firewall.sh` — the operational entry point. Fetches the IPv4 from
  `ipinfo.io`, the IPv6 from `ifconfig.me` (3 retries, truncated to a `/64`), and the
  router IPv6 from `<wifi-ssid>.fritz.box`; then tests DNS against `88.198.151.84`
  and `2a01:4f8:1c1e:d9fb::1`. If DNS fails it backs up the current rules to a temp
  dir and merges a new inbound tcp/udp port-53 rule for the three addresses.
- `requirements.txt` — `hcloud`, `fire`, `dataclasses-json`.

## Rules

- Always back up the rule set (`python main.py firewall save <dir>`) before merging.
- The script aborts if any of the three addresses cannot be resolved — do not replace a
  missing address with `::/64` or an empty string to force it through.
- This is a host-side client script, not a deployed service. It is not managed by the
  `docker_service` role.

## Reference

- [Root AGENTS.md](../AGENTS.md) — DNS architecture and Porkbun credentials (separate
  from the Hetzner API credentials).
