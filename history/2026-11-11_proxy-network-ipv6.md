# 2026-11-11 — the `proxy` network carries IPv6 so v6 clients stop being invisible

Fourth layer of the 2026-11-10 fail2ban work, and the first one that is not a fail2ban
change: the SSH jails can now ban v6 sources, but the **web** tier could not, because it
never sees them.

## The finding that forced this

`proxy` was created with `EnableIPv6: false`. A published port therefore has no ip6tables
DNAT rule, so `[::]:443` is handled by **docker-proxy**, which terminates the v6 connection
and re-opens it from the bridge — the client address is rewritten to the gateway. Proved
with a marked request on 2026-11-10:

```
$ curl -6 https://bumbleflies.de/__v6probe?x=1        # from servy, over its own v6
$ docker logs traefik.traefik | grep __v6probe
"ClientAddr":"172.18.0.1"   "RequestPath":"/__v6probe?x=1"
```

Consequences, all of which this layer removes:

- Traefik, Loki and the blocklist script see `172.18.0.1` for every v6 client, so no
  log-based jail can ever identify a v6 attacker;
- a v6 `loki-blocklist` rule would have been dead weight that looked like coverage
  (which is why the layer below deliberately shipped v4-only);
- v6 visitors were served, but unthrottled — a v6 scanner had a free path.

## Changes

| File | Change |
|---|---|
| `ansible/plays/vars/default.yml` | `docker_proxy_ipv6_subnet` (`fd00:c0de:1::/64`) and `docker_proxy_ipv4_subnet` (`172.18.0.0/16`) |
| `ansible/plays/roles/user/tasks/docker_setup.yml` | the `proxy` network is created with `enable_ipv6: true` and both subnets pinned |
| `ansible/plays/roles/user/molecule/default/verify.yml` | guards the task definition: `enable_ipv6`, both subnet vars |
| `CLAUDE.md` | one command to check the network's family |

**Why a private ULA and not a slice of servy's routed `2a01:4f8:c013:f6f4::/64`:** inbound
v6 is DNAT'd, and DNAT rewrites the destination, so the container does not need a globally
routable address. A ULA needs no NDP proxying, no routing change at Hetzner, and works
identically on codey, whose `2a01:8740:1:fa3::/64` is on-link on `eth0` rather than routed
to the host.

**Why the v4 pool is pinned:** it is already `172.18.0.0/16` on both hosts and is
referenced by allowlists (`portainer-agent` permits `172.18.0.0/16` for its master).
Leaving it implicit would let Docker pick a different pool when the network is recreated.

**Why `userland-proxy` is left alone:** it is not the cause. Docker installs DNAT rules for
external traffic and the userland proxy only catches what DNAT misses (host-local
connections). The proxy handled our v6 traffic purely because there was no v6 DNAT rule to
match. Turning the proxy off would have restarted dockerd on both hosts — a far bigger
event — for no benefit. If the acceptance test below ever fails, that is the next thing to
try, on its own.

## Cutover (Docker cannot change a network in place)

Measured before the change: `proxy` carried **30 of 53** containers on servy and **6 of 9**
on codey, `172.18.0.0/16`, `EnableIPv6: false` on both.

1. Baseline: site status codes, `docker network inspect proxy > /tmp/proxy.bak`.
2. Stop the containers attached to `proxy`.
3. `docker network rm proxy`, then create it via
   `./servyy.sh --limit <host> --tags user.docker.create.network` (the task above).
4. Start the same containers again. `docker start` reattaches by network name; any
   container that keeps a stale network-ID reference is fixed with
   `docker network connect proxy <name>`.
5. Acceptance: `curl -6 https://bumbleflies.de/__v6probe` from servy must appear in
   Traefik's log with the **real** v6 client, not `172.18.0.1`. That is the entire point.
6. Sanity: every public site back to its baseline code, `docker ps` all up, cert resolver
   untouched, `monit summary` all OK.

Rollback: stop the same containers, `docker network rm proxy`, recreate without
`enable_ipv6`, start them. No daemon restart is involved in either direction.

## Follow-up

With clients visible, the web tier gets its v6 jail (`ip6tables DOCKER-USER`, the forward
path) **and** the blocklist script's three Loki regexes widened — they are v4-only today,
so even a visible v6 attacker would be dropped before it reached fail2ban.
