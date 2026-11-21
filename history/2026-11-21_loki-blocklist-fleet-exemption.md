# The Loki blocklist banned codey — Grafana's own query traffic tripped the crawler jail

**Date:** 2026-11-21
**Service:** fail2ban `loki-blocklist` on servy (and codey), consequence on the Forgejo runner
**Found by:** chasing a Grafana alert (`Forgejo Runner Offline`, `runner="codey"`) that had been
firing since 11:22 — the runner was up 20 h, so the alert looked wrong.

## What happened

`docker logs runny.runner` on codey, thousands of lines of:

```
level=error msg="failed to fetch task" error="unavailable: dial tcp 49.13.6.173:443: connect: connection refused"
```

49.13.6.173 is **servy's public IPv4**, and servy was listening on 443 (docker-proxy on `0.0.0.0:443`).
IPv6 to the same host worked (`curl -6 https://ci.lehel.xyz/api/health` → 303, `curl -4` → refused). The
reason was in servy's nftables:

```
chain f2b-loki-blocklist {
    ip saddr 138.2.180.191 counter packets 14886 bytes 901273 reject   # codey
```

`/var/log/fail2ban-loki.log`: `2026-11-21 05:33:11 138.2.180.191 traefik-aggressive-crawler attempts=274`.

Loki, for that IP over 24 h:

| RequestPath | Count |
|---|---|
| `/api/v1/query_range` | **50 947** |
| `/api/actions/runner.v1.RunnerService/FetchTask` | 21 763 |

That is **our own traffic**: Grafana on codey evaluates ~65 alert rules a minute against
`prometheus.lehel.xyz` (each rule one `query_range`), and every Forgejo runner long-polls its
instance. The crawler rule excludes SPA build assets (2026-11-11) but not authenticated API
polling, so a peer host is permanently over the "200 requests / 2 min" floor in bursts. The ban is
web-tier scoped (port 80/443, `DOCKER-USER`), so SSH stayed reachable — but **every Forgejo job on
that runner died**, and any IPv4 client on codey lost `ci`/`loki`/`prometheus` (Go/SRV-preferring
clients silently fell back to IPv6, which is why most of the stack looked fine).

Previous state of this lesson: `history/2026-11-10_fail2ban-web-tier-chain-fix.md` (a codey scan
banned all ports including SSH) and the "do not fix a lockout with `ignoreip`" note in
`jail.local.j2`. Both are about *scoping* the ban; neither covers "the peer is the client".

## Fix

`update-from-loki.sh` now drops **our own hosts' public IPv4s** before it writes a ban line:
`blocklist_exempt_ipv4` (`system/defaults/main.yml`) = this host's address + every inventory host
whose `ansible_host` is a literal IPv4, rendered into `EXEMPT_IPS`. The guard sits in `add_ips`,
after the private-IP skip, and logs `skipping fleet IP <ip> from <provider>`.

This is not the `ignoreip` anti-pattern the jail file warns about: the jail keeps working for real
offenders (nothing is whitelisted in fail2ban), a peer is still throttled by Traefik's rate limiter,
and the exemption is derived from the inventory rather than from whoever got locked out.

## Verification

```bash
ssh servy.lehel.xyz "sudo grep '^EXEMPT_IPS=' /usr/local/bin/blocklist/update-from-loki.sh"
# EXEMPT_IPS="49.13.6.173 138.2.180.191 …"    (servy + codey + alphavps)
ssh servy.lehel.xyz "sudo fail2ban-client status loki-blocklist"   # codey's IP must be absent
ssh codey.lehel.xyz "docker logs runny.runner --tail 20"           # no more 'connection refused'
molecule (system/with-docker) pins both the variable line and the skip guard.
```
