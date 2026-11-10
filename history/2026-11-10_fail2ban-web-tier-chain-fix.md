# 2026-11-10 — fail2ban web-tier blocklist never blocked anything

## Why

An operator IP (`45.155.141.31`, a Greenfiber/CGNAT address) was banned by `sshd` +
`sshd-invalid-user` on codey and by `sshd` + `loki-blocklist` on servy, so SSH from that
line got `Connection refused` on both hosts while 80/443 stayed up. Unbanning was
trivial; chasing *why* turned up two defects bigger than the ban.

Trigger: the same source had simultaneously made ~52,600 requests against
`bumbleflies.de`, `live.bumbleflies.de`, `edu.bumbleflies.de`, `bricksnbytes.de` in
~12 minutes (≈80 req/s, 08:40–08:52 CET), with `interact.sh` / `oast.pro` OOB callbacks,
LFI (`/cgi-bin/loghandler.php?…file=/etc/passwd`), SQLi, Jenkins
`descriptorByName/AuditTrailPlugin` RCE and cloud-metadata SSRF probes — and it was
banned by the `loki-blocklist` jail 15 minutes in. The flood continued regardless.

## Finding 1 — the web-tier jail hooks a chain container traffic never traverses

`banaction = iptables-multiport` inserts the jail's jump into `INPUT` (fail2ban default).
Traefik runs in Docker with published ports, so its traffic is DNAT'd in `PREROUTING` and
then **forwarded**: it travels `FORWARD` → `DOCKER-USER` and never enters `INPUT`. `INPUT`
only sees host-local sockets (sshd, monit, postfix).

Measured on servy, 2026-11-10:

```
$ iptables -S | grep -c 'chain f2b-loki'      # 84 banned IPs
$ nft list chain inet filter f2b-loki-blocklist | grep -vc 'packets 0'
0                                             # every single rule at 0 packets
```

Live proof: with `217.217.227.124` banned by the running jail
(`-A f2b-loki-blocklist -s 217.217.227.124/32 -j REJECT`), a request from that exact
address to `https://bumbleflies.de/` still returned **200**. The ban was real, installed,
and consulted by nothing.

Proof of fix, isolated fail2ban instance on servy with the config shape below:

```
-A DOCKER-USER -p tcp -m multiport --dports 80,443 -j f2b-probe
-A f2b-probe -s 217.217.227.124/32 -j REJECT --reject-with icmp-port-unreachable
```

→ same request now returns `000` (blocked) while `ssh servy` from that IP keeps working
(SSH is `INPUT`, untouched).

## Finding 2 — correction: the port/banaction scoping was already fixed upstream

During triage `jail.local.j2` in the local clone still showed the pre-2026-10-30 block
(`port = http,https,ssh` + `banaction = iptables-allports`), which looked like the fix
existed only on the hosts. It did not: master carries
`2a0811b fix(fail2ban): make the Loki blocklist a web-only ban` (2026-10-30), and the clone
used for triage was 82 commits behind. **No port/banaction change is needed** — the hosts
and master agree. Recorded here because the wrong conclusion ("next deploy re-arms the
lockout") was stated before the fetch, and it would have justified a pointless edit.

What master still lacked is the chain: `2a0811b` scoped *which* ports get rejected, but
the rules still went into `INPUT`, so the scoped ban never applied either.

## Changes

| File | Change |
|---|---|
| `ansible/plays/roles/system/defaults/main.yml` | **new** — `fail2ban_web_tier_chain`: `DOCKER-USER` when `with_docker`, else `INPUT` |
| `ansible/plays/roles/system/templates/fail2ban/jail.local.j2` | `[loki-blocklist]` gains `chain = {{ fail2ban_web_tier_chain }}` + the why (ports/banaction were already scoped by `2a0811b`) |
| `ansible/plays/roles/system/tasks/fail2ban.yml` | create the `DOCKER-USER` chain if Docker has not (`iptables -N`); a missing chain makes the ban action fail with "No chain/target/match" and ban nothing |
| `ansible/plays/roles/system/molecule/with-docker/verify.yml` | renders the jail template and asserts web-port scoping + `chain = DOCKER-USER` (and `INPUT` without Docker) |

`chain` is the documented fail2ban jail option for this (jail.conf:
`action_ = %(banaction)s[…, chain="%(chain)s"]`, `chain = <known/chain>`).

## Verification

fail2ban runs in no molecule scenario (`with_fail2ban: false` everywhere), so the config is
guarded by rendering it in `molecule/with-docker` instead:

- All 8 rendered-config assertions pass (verified by re-rendering the template with
  jinja2 3.1.6 and applying the same checks): scoping, `chain = DOCKER-USER`,
  `chain = INPUT` for the no-Docker path, no `http,https,ssh` / `iptables-allports`.
- Rendered output vs the live `/etc/fail2ban/jail.local` on servy: **only** the
  `chain = DOCKER-USER` line differs — the template matches production, so deploying it
  cannot silently change anything else. (Same check against `origin/master` after the
  rebase: template differs from master only by the chain line and its comment block.)
- `yaml.safe_load()` OK on all three changed YAML files. No ansible/ansible-lint/molecule
  toolchain in the dev container, so lint runs in CI.
- Runtime behaviour of the resulting ruleset proven with the isolated instance above
  (`/tmp/f2bprobe`, its own socket, `dbfile = :memory:`, removed afterwards).

## To deploy

```bash
cd ansible
./servyy.sh --limit servy.lehel.xyz --tags system.fail2ban --check --diff
./servyy.sh --limit servy.lehel.xyz --tags system.fail2ban
./servyy.sh --limit codey.lehel.xyz --tags system.fail2ban
```

Then confirm the bans moved out of `INPUT` and into the forwarded path:

```bash
ssh servy.lehel.xyz "sudo iptables -S DOCKER-USER"
# -A DOCKER-USER -p tcp -m multiport --dports 80,443 -j f2b-loki-blocklist
ssh servy.lehel.xyz "sudo iptables -S f2b-loki-blocklist | head -3"
ssh servy.lehel.xyz "sudo fail2ban-client status loki-blocklist"
```

Existing bans are re-applied to the new chain by `actionstop`/`actionstart` on restart, so
the 80+ blocked IPs move with it; expect `packets` counters to start incrementing.

## Notes / follow-ups

- **IPv6 is not covered.** The base `iptables` action only writes v4 rules; Traefik also
  publishes on `[::]:443`. Out of scope here, but a v6 scanner is currently unthrottled.
- **Dead filter templates** are still shipped and deployed by the role
  (`traefik-access`, `traefik-bots`, `traefik-crawler-ratelimit`) although no jail
  references them since the Loki migration — cleanup candidate.
- **CGNAT means this recurs.** The address is a shared subscriber pool
  (`GF-FRA-CGN-POOL1-SUBSCRIBER`), so a neighbouring subscriber's scanner keeps getting
  the operator's IP banned. Mitigations belong outside fail2ban: dedicated public IPv4
  from the ISP, or SSH via WireGuard/Tailscale.
- The scan itself changed nothing: every 200 on an exploit path was the SPA catch-all
  (identical body sizes per host), no OOB callback was ever fetched.
