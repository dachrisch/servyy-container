# 2026-10-30 — The Loki blocklist can no longer take SSH down

**Date:** 2026-10-30
**Status:** ✅ Merged (PR #252) and deployed to `servy.lehel.xyz` + `codey.lehel.xyz`
**Relates to:** `2026-10-29_exposure-guards.md`, `2026-10-29_traefik-3.7-upgrade.md`
(the blocklist's Traefik log source), PR #249 (same session, unrelated)

## Symptom

A codey session reported "SSH to servy still blocked (codey works) — IPv6 route gone + 22
refused, almost certainly fail2ban's sshd jail from my audit burst". Both halves of that
diagnosis were wrong, in ways that cost real time, so they are recorded here.

## Root cause

`loki-blocklist` is fed from `/var/log/fail2ban-loki.log`, which
`/usr/local/bin/blocklist/update-from-loki.sh` fills by querying Loki for Traefik abuse
signatures. Its config was:

```
[loki-blocklist]
port = http,https,ssh          # ← decoration
banaction = iptables-allports  # ← ignores `port` entirely
maxretry = 1
bantime = 86400
```

`iptables-allports` bans the address on **every** port regardless of `port`, so one trigger
took out SSH along with the web tier:

```
2026-10-30 09:00:53  217.217.227.124  traefik-rate-limit          attempts=12
2026-10-30 09:00:54  217.217.227.124  traefik-aggressive-crawler  attempts=21

-A f2b-loki-blocklist -s 217.217.227.124/32 -j REJECT --reject-with icmp-port-unreachable
```

`217.217.227.124` is codey's egress. The session's own audit sweep banned its own host and
then cut its route back in.

## Why it read as something else

- **"fail2ban's sshd jail"** — the sshd jails never banned that IP. `fail2ban.log` has zero
  ban entries for it in `sshd` or `sshd-invalid-user`; both reported it as free. Only
  `loki-blocklist` had it.
- **"IPv6 route gone"** — the REJECT rule is **IPv4-only** (there are no `ip6tables` rules
  for that jail), and `servy.lehel.xyz` resolves IPv6-first. So HTTPS from codey still
  answered **200** while IPv4 SSH was refused, which looks like a broken IPv6 route rather
  than a source-IP ban. Inside the container it was worse: the container has **no IPv6 at
  all**, so it hit `Network unreachable` on AAAA and `REJECT` on the A fallback.
- Symptom shape: `REJECT --reject-with icmp-port-unreachable` reads as "connection
  refused", not as a firewall drop, which points at sshd rather than at a ban.

## Decision

Scope the jail to the web tier instead of exempting the victim:

```
[loki-blocklist]
port = http,https
banaction = iptables-multiport
```

fail2ban applies the port scope on the **INPUT jump**, not on the per-IP rule — worth
knowing, because the ban rule still reads `-I f2b-loki-blocklist 1 -s <ip> -j REJECT` and
looks all-ports until you see what feeds that chain:

```
-A INPUT -p tcp -m multiport --dports 80,443 -j f2b-loki-blocklist
```

So a hostile source is still throttled off 80/443 for 24 h and SSH is out of reach of this
jail entirely.

**Rejected: whitelisting codey's IP in `ignoreip`.** That was the first version of the PR
(#252, force-pushed away). It disables the jail for that source altogether — on a jail whose
purpose is stopping web abuse — and leaves the next burst unbounded. It also fixes one IP
rather than the class: the same lockout would hit an operator laptop, a new host, or a
provider-assigned address change. The template now carries a comment saying so, because
"add it to ignoreip" is the obvious move and it is what the previous two lockouts invited.

## Verification (both hosts)

- `jail.local` rendered with `port = http,https`, `banaction = iptables-multiport`;
  `fail2ban-client get loki-blocklist actions` → `iptables-multiport`
- `iptables-save` → `-A INPUT -p tcp -m multiport --dports 80,443 -j f2b-loki-blocklist`,
  and **no** INPUT jump into that chain without `--dports`
- sshd chains untouched: `-A INPUT -p tcp -m multiport --dports 22 -j f2b-sshd`
- test ban of `203.0.113.66` (RFC 5737) installs and removes exactly one rule, and the
  INPUT jump is the only path into the chain
- codey → servy from inside the container: `CONTAINER-SSH-OK`
- 83 pre-existing bans survived the fail2ban restart on servy and were re-applied under the
  new action

## Side finding — codey's copy of this jail is inert (not fixed here)

On codey the jail is enabled, restarted, and its feed file is being written, but:

- `Currently banned: 0  Total banned: 0`
- no `f2b-loki-blocklist` chain exists at all — the action never installed its INPUT jump
- the feed contains **no ban-shaped lines since 2026-08-28**, only the script's own
  `[blocklist] Querying Loki …` progress output (codey's copy: 0 matching lines vs 30 489 on
  servy)

So codey's web tier has had no Loki-driven blocking for two months. The queries select
`{job="docker", container="traefik.traefik"}`, which matches both hosts' Traefik — the most
likely cause is that codey's Traefik logs never reach the Loki instance the script queries
(or arrive under different labels). Worth its own investigation: it is a public host
(devhub, h.code, the dashboard).
