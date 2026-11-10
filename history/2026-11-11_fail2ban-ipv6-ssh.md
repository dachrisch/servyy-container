# 2026-11-11 — the SSH jails detect IPv6 attackers and never banned them

Third layer of the 2026-11-10 fail2ban work. The two layers below fixed *which* chain the
web-tier rules land in and *which* journal events the SSH jails can see. This one fixes the
family they ban in.

## Why

`iptables-multiport` writes **v4 rules only**. A v6 source is matched by the filter, counted
by the jail, and then the ban does nothing — the rule is inserted into `f2b-<jail>` in the
`ip` tables while the attacker keeps connecting over `ip6tables`.

The filter side needed no change, which was verified rather than assumed — the custom
filter matched real captured v6 journal lines:

```
$ printf 'servy sshd-session[1]: Invalid user  from 2001:470:1:fb5:…:2c8f port 49120\n
          servy sshd-session[1]: Failed password for invalid user x from 2001:db8::13 port 22 ssh2\n' \
    > /tmp/v6test.log
$ fail2ban-regex /tmp/v6test.log sshd-custom.conf
Lines: 2 lines, 0 ignored, 2 matched, 0 missed
```

Volume at the time was low — 3 v6 vs 1044 v4 `Invalid user`/`Failed password` lines in the
current journal window — but the gap is structural: it stays silent exactly as long as the
per-family blindness lasts.

## Changes

| File | Change |
|---|---|
| `ansible/plays/roles/system/templates/fail2ban/action.d/ip6tables-multiport.conf.j2` | **new** — the v6 twin action (`ip6tables`, `icmp6-port-unreachable`), inheriting the rest of `iptables.conf` |
| `ansible/plays/roles/system/tasks/fail2ban.yml` | deploys that action to `/etc/fail2ban/action.d/` |
| `ansible/plays/roles/system/templates/fail2ban/jail.local.j2` | `[DEFAULT]` spells the action out instead of `%(action_)s` and lists **both** action names; `[loki-blocklist]` gets an explicit v4-only action instead of the jail-level `chain` option |
| `ansible/plays/roles/system/molecule/with-docker/verify.yml` | asserts the v6 action exists exactly once and that `loki-blocklist` has none; web-tier chain assertions follow the chain into the action parameter |
| `CLAUDE.md` | one more command: check the v6 ruleset |

## The first attempt took fail2ban down on both hosts

The first shape used the documented-looking trick of instantiating the *same* action twice
with `family=inet6` (which `iptables.conf` supports via its `[Init?family=inet6]` section):

```
action = iptables-multiport[port="%(port)s", protocol="%(protocol)s", chain="%(chain)s"]
         iptables-multiport[port="%(port)s", protocol="%(protocol)s", chain="%(chain)s", family="inet6"]
```

It deployed cleanly, `fail2ban-client -t` said `OK: configuration test is successful` — and
the service then **failed to start on both hosts**:

```
fail2ban.transmitter ERROR Command ['server-stream', …] has failed.
    Received ValueError('Action iptables-multiport already exists')
```

fail2ban identifies actions by name and refuses two of one name inside a jail. The check
runs when the server starts, so the config test cannot see it. Both hosts were left with no
bans at all for ~2 minutes until the previous `jail.local` was redeployed (9 + 1 + 82 bans
re-applied from the database, chains intact).

Two lessons, both now encoded above:

- **`fail2ban-client -t` is not a deploy gate.** It parses; it does not start jails.
- **A second instance needs a second action *name*.** Hence the role-owned
  `ip6tables-multiport` action file instead of a duplicate instance.

## Why the web-tier jail deliberately stays v4

An inet6 twin here would be theatre. Measured 2026-11-10: the `proxy` Docker network has
`EnableIPv6: false`, so `[::]:443` is served by **docker-proxy**, which re-originates the
connection. Traefik therefore records every v6 client as the bridge gateway — proved with a
marked request:

```
curl -6 https://bumbleflies.de/__v6probe?x=1
traefik: {"ClientAddr":"172.18.0.1","RequestPath":"/__v6probe?x=1"}
```

No log-based jail can identify a v6 attacker while that is true, and the blocklist script's
three Loki queries are v4-only regexes anyway. The v6 web action belongs with the network
change that makes v6 clients visible — which is the next layer, not this one.

## Verification

- **Isolated fail2ban instance on servy** (the check that would have caught the first
  attempt): a scratch config dir with one uniquely named jail, started with
  `fail2ban-server -c /tmp/f2bt -s /tmp/f2bt/f2b.sock -b start`. The server came up, and a
  ban per family produced the right rule in the right table:

  ```
  ip6tables -S f2b-sshdtest  → -s 2001:db8::55/128 -j REJECT --reject-with icmp6-port-unreachable
  iptables  -S f2b-sshdtest  → -s 192.0.2.55/32   -j REJECT --reject-with icmp-port-unreachable
  ```

  The instance was then stopped, its chains were gone, and the production jails were
  untouched (9 bans still installed). This is the gate for future changes to the action set.
- Molecule: rendered-config assertions (see table).
- `yamllint`, `ansible-lint`, `ansible-playbook --syntax-check` locally; molecule in CI.

## To deploy

```bash
cd ansible
./servyy.sh --limit servy.lehel.xyz --tags system.fail2ban --check --diff
./servyy.sh --limit servy.lehel.xyz --tags system.fail2ban
./servyy.sh --limit codey.lehel.xyz --tags system.fail2ban
```

Then prove both families actually write rules, on each host — documentation-prefix
addresses, then remove them:

```bash
ssh servy.lehel.xyz "sudo fail2ban-client set sshd banip 2001:db8::55; sudo ip6tables -S f2b-sshd | head -2"
ssh servy.lehel.xyz "sudo fail2ban-client set sshd banip 192.0.2.55;  sudo iptables  -S f2b-sshd | head -2"
ssh servy.lehel.xyz "sudo fail2ban-client set sshd unbanip 2001:db8::55; sudo fail2ban-client set sshd unbanip 192.0.2.55"
```

`2001:db8::/32` and `192.0.2.0/24` are reserved for documentation, so banning them is
inert. Confirm `ssh` from the operator line still works afterwards.

## Follow-ups

- **The v6 web surface is a network problem, not a fail2ban one.** Until `proxy` carries
  IPv6 (and therefore DNATs instead of proxying), v6 clients are invisible; the fix is
  `enable_ipv6` + an IPAM subnet on that network, after which the web-tier v6 action
  belongs in `ip6tables DOCKER-USER` — symmetric with v4, in the forward path.
- **The blocklist script is v4-only** in all three Loki queries
  (`from (?P<ip>[0-9.]+) port`, and two `(?P<ip>[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)`). Even
  with v6 clients visible, the script would drop them. Widening it needs fixture-based
  tests, because the traefik regex can easily over-match timestamps and ports.
