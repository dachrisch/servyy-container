# Exposure triage: host edge filter, Traefik metrics, Renovate forks, vaultwarden CVEs

**Date:** 2026-10-29
**Status:** ✅ Edge filter deployed to `servy.lehel.xyz`; 8082 unpublish committed (deploys with the next Traefik rollout); findings recorded
**Relates to:** `2026-10-28_auditd-rules.md`, `2026-10-28_security-audit-trivy-empty-results.md`

## Context

After the audit became trustworthy, the question was where the fleet has *real* exposure rather
than paper findings. Four things came out of it.

## 1. No host-level firewall — the provider was the only filter

`ufw` is **inactive** and the `DOCKER-USER` iptables chain was **empty**. Docker writes its own
`FORWARD`/`nat` rules and bypasses ufw entirely, so every `ports:` entry binds `0.0.0.0` and is
internet-facing unless something upstream blocks it. Evidence of the gap:

- Traefik's **metrics endpoint was published on `0.0.0.0:8082`** (`/metrics` → 200) — the whole
  router/service topology, unauthenticated
- Postfix listened on `0.0.0.0:25`
- Both happen to be filtered by the Hetzner firewall, not by the host

Nothing forbade either. A new `ports:` line in any compose file was one provider-rule change
away from being public.

### Decision

`tasks/firewall.yml` (system role) deploys `/usr/local/sbin/docker-user-firewall.sh` plus a
oneshot unit that re-runs it after every Docker start (Docker recreates `DOCKER-USER` on
restart). The script maintains its own `HOST-EDGE` chain, hooked first from `DOCKER-USER`, so
foreign rules there are never flushed:

```
-A HOST-EDGE -i eth0 -m conntrack --ctstate RELATED,ESTABLISHED -j RETURN
-A HOST-EDGE -i eth0 -p tcp -m multiport --dports 22,80,443 -j RETURN
-A HOST-EDGE -i eth0 -j DROP
```

Only traffic arriving on the **public interface** is filtered, so container egress and
Docker-network-to-network traffic (in-interface `br-*`) are untouched. IPv6 gets the same
treatment. Ports are a var (`edge_allowed_tcp_ports`).

The script refuses to run when there is no default route (rather than guessing an interface) and
fails loudly when `DOCKER-USER` does not exist yet (Docker down). `KEEP`-style contract test:
`tests/test_docker_edge_filter.sh`, 14 checks, including a guard that the DROP is last and the
allow-list is exactly what the var says.

### Verification (the interesting part)

A test container published on `9999` was blocked from outside — but `iptables -Z` on the chain
showed the **DROP counter at 0**, i.e. the packets never reached the host: the provider firewall
dropped them first. That proves nothing about our rules.

So the test was inverted: temporarily set `edge_allowed_tcp_ports: [22, 443]` (removing 80) and
retry from outside:

| probe | result |
|---|---|
| `http://<public-ip>/` with 80 not allowed | timeout, and **`DROP` counter 10 packets / 540 bytes** |
| `https://monitor.lehel.xyz/` with 443 allowed | 302, as before |

That is the chain doing the blocking, in the live path. Restored immediately; HTTP answered 404
(the branded catch-all) again.

## 2. Traefik metrics port

`traefik/docker-compose.yml` no longer publishes `8082`: Prometheus scrapes
`traefik.traefik:8082` over the docker network, so the publish only added an endpoint. Recorded
in the compose file with that reason.

**Not deployed from here**: the `docker_service` run for Traefik asserts
`traefik_dashboard_password | length >= 16`, and the seed file
`plays/vars/.traefik_dashboard_password` is absent in this checkout (it is operator-local and
untracked). That assertion is protective — it prevents rendering a broken htpasswd — so it was
not bypassed. The publish disappears with the next Traefik rollout; until then the port is
still bound but dropped by `HOST-EDGE` (and by the provider firewall before that).

## 3. Renovate is not running on a fork (not a Pillow-specific miss)

The `leaguesphere` backend carries `Pillow==12.3.0`; 13.0.0 (published 2026-10-16) fixes four
critical CVEs, and no Renovate PR existed.

- `dachrisch/leaguesphere` is a **fork** (`fork: true`, parent `chris0chris/league-manager`)
- its Dependency Dashboard (#295) was last updated **2026-08-30**; the non-fork repos in the
  same account updated 2026-10-27/28/29
- the dashboard *does* list `Pillow ==12.3.0` (pep621 manager) but with **no
  `→ [Updates: …]`** annotation, unlike Django which shows `==6.0.8 → ==6.1`
- `renovate.json` was edited 2026-09-22 — three weeks *after* the last run, so that edit never
  took effect either

Mend's hosted Renovate **skips forks** unless `forkProcessing: "enabled"` is set, and this
repo's `renovate.json` does not set it. So the repo has had no dependency updates at all since
August, Pillow being one of many.

**Remedy:** add `"forkProcessing": "enabled"` to `leaguesphere/renovate.json` (or enable the
repo in the Mend portal) and confirm the dashboard updates and a Pillow 13 major-bump PR
appears. Worth deciding whether that repo should remain a fork at all.

## 4. vaultwarden's 4 criticals are not reachable

| | |
|---|---|
| CVEs | `CVE-2026-44172` (MariaDB server SQL injection via `big5` charset), `CVE-2026-49261` (MariaDB server RCE via `wsrep_notify_cmd`) |
| packages | `libmariadb3`, `mariadb-common` 1:11.8.6 (Debian 13 base of the image) |
| vaultwarden backend | container `pass.pass`, **no `DATABASE_URL`** → SQLite |
| verdict | **not reachable** — both are server-side MariaDB features (server charset handling, galera replication); the image only ships the *client* library for optional MySQL support, and no MariaDB server runs behind vaultwarden |

Nothing to patch: no fixed version exists (Debian), and Watchtower will pick one up on the next
image rebuild. Keeping them visible in the report is the right call — they are real CVEs in the
image, just not reachable from Vaultwarden's code path.

## Consequences

### Positive

- A published port no longer becomes internet-facing by accident; the host has its own say
- Two endpoints (metrics, SMTP) that were only saved by the provider firewall are now covered
- The Renovate silence has a cause and a one-line remedy
- Four "critical" CVEs are dismissed with evidence instead of sitting as unexplained backlog

### Negative / Tradeoffs

- New iptables state that must be re-applied after Docker restarts (systemd unit does it)
- Container-based molecule scenarios skip the task (`virtualization_type == docker`), so it is
  host-verified plus contract-tested, not converge-tested
- The Traefik restart is still pending an operator with the dashboard-password seed

### Known Issues / Open Findings

- `edge_allowed_tcp_ports` is global; a host that needs another published port needs the var
  extended, otherwise the port is silently dropped (and the audit will not notice — no check
  watches for "published but unreachable" yet)
- The remaining public exposure is application-level: 18 `pillow` criticals in
  `leaguesphere/backend`, plus unfixed criticals in `vaultwarden`, `photoprism` and
  `bumblecode/ibs`
