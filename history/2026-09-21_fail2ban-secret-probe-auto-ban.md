# Fail2ban Auto-Ban Learns Secret-Probe Scanners

**Date:** 2026-09-21
**Author:** opencode (via user dachrisch)
**Type:** Security Fix
**Status:** 🟡 Patched in repo, NOT yet deployed to production

## Summary

The hourly Loki blocklist (`update-blocklist-from-loki.sh`, `system` role) was blind to a
distributed secret-harvesting campaign hammering `energy.lehel.xyz` (single IP
`34.46.20.161` burned ~25% CPU with 400+ exploit probes; campaign-wide 15,591
secret-probe hits/24h from 50+ IPs, mostly 34.x Google Cloud range). Two gaps fixed
in `ansible/plays/roles/system/templates/fail2ban/update-blocklist-from-loki.sh.j2`:

1. **New `get_secret_probe_ips()`** — flags IPs requesting paths that are never
   legitimate (`[.]env`, `proc/self/environ`, `proc/self/cmdline`,
   `serviceaccount/token`, `[.]git/config`, `wp-config[.]php`,
   `terminal-xhr[.]php`, `[.]aws/credentials`), threshold >= 5 hits/24h.
   This catches the observed attacker class regardless of user-agent spoofing
   (it rotated GPTBot/ClaudeBot/DeepSeekBot/... UAs, evading all UA-list queries)
   and regardless of burst timing (it evaded the 1m/2m rate windows sampled hourly).
2. **Fixed `get_error_ips()` 4xx pattern** — old pattern `" 4[0-9][0-9] ` only matches
   plain-text access logs; Traefik JSON logs (`"DownstreamStatus":404`) never matched,
   so the query returned **zero series** on Traefik traffic. Now also matches
   `"DownstreamStatus":4xx`. Threshold unchanged (100/24h).

## Why the old queries missed it (verified live against servy Loki)

- Scanner-UA query: only lists `nikto|sqlmap|nmap|masscan|zgrab|nuclei|dirbuster` —
  spoofed AI-bot UAs don't match.
- Malicious-bot query: same problem (`nmap|masscan|...|havij|sqlninja`).
- Rate queries (10+/1m, 20+/2m): mechanically functional (return `vector`), but the
  hourly sampler lands between bursts (0.2 rps average, ~7 rps spikes).
- 4xx query: `result: []` on `{container="traefik.traefik"}` — proven blind; fixed
  pattern returns 50 IPs (top: 4573 4xx/24h).

## Verification (no molecule: fail2ban is `with_fail2ban: false` in all scenarios)

- `bash -n` passes on the rendered script (checked on servy; no bash/shellcheck
  in the dev container).
- Both new/changed queries executed verbatim (bash-expanded template text) against
  servy Loki: secret query → 50 series incl. `34.46.20.161 = 414`; fixed 4xx query →
  50 series. Both would have banned the attacker (`>= 5`, `>= 100`).
- `ansible-playbook --syntax-check` and molecule could not run here (no Ansible
  toolchain in container); no YAML was modified (only the `.j2` shell template).

## Immediate mitigation (already done, expires)

- `34.46.20.161` manually banned via `fail2ban-client set loki-blocklist banip`
  (24h `iptables-allports`). Energy CPU dropped 25% → 0.15% instantly.
- job-search containers were found fully removed (not just stopped); volumes
  `job-search_mongodb_data` / `job-search_redis_data` intact. Unclear who ran `down`.

## To deploy

Run the system fail2ban tasks against servy (script + timer only, no fail2ban
restart triggered by the `.sh` template change), then confirm the next hourly run
logs `Querying Loki for secret-probing scanner IPs...` and bans the backlog, e.g.:

```sh
# from ansible/ (example - confirm inventory/tags before running)
ansible-playbook servyy.yml -i production --limit servy.lehel.xyz --tags system.fail2ban.scripts,system.fail2ban.timer
ssh servy.lehel.xyz "grep -c secret-probe /var/log/fail2ban-loki.log; sudo fail2ban-client status loki-blocklist"
```

## Files Changed

- `ansible/plays/roles/system/templates/fail2ban/update-blocklist-from-loki.sh.j2` —
  new `get_secret_probe_ips()` + main-loop wiring, fixed 4xx alternation pattern.
