# 2026-11-11 — the web-tier jail bans IPv6, and its Loki queries stopped dropping addresses

Last layer of the 2026-11-10 fail2ban work. The layer below made v6 clients *visible*
(IPv6 on the `proxy` network, so published v6 ports are DNAT'd instead of proxied); this
one makes them *bannable*, and fixes two queries that could never produce a ban at all.

## Why the web tier had to stay v4-only until now

With `EnableIPv6: false` on `proxy`, `[::]:443` was served by docker-proxy, which
re-originates the connection — Traefik logged every v6 client as `172.18.0.1` (measured
2026-11-10 with a marked request). A v6 rule would have been dead weight that looked like
coverage, which is why the previous layer deliberately shipped v4-only.

With IPv6 on the network the packet is DNAT'd, so it traverses `FORWARD → DOCKER-USER` in
ip6tables exactly like v4. Verified on both hosts before writing the config:

```
ip6tables -S FORWARD     | grep -c DOCKER-USER   → 1
ip6tables -S DOCKER-USER                          → 2 rules
ip6tables -t nat -S      | grep -c DNAT           → 2
```

So the same chain name works for both families, and `loki-blocklist` now lists both
actions.

## The Loki queries: two of them could never ban anything

While adding v6 support, the patterns turned out to be broken for **v4 as well**. Three
defects, all in `update-blocklist-from-loki.sh.j2`:

1. `get_scanner_ips` and `get_error_ips` escaped their dots for **jq**, not for **Go RE2**.
   A `regexp` argument sits inside a shell single-quoted string, so Loki received `\\.` —
   which in RE2 is an escaped backslash followed by any character. The pattern extracted
   nothing, ever. (The bans that do fire come from the `ClientHost`-label queries, which
   never touch a regexp.)
2. Both now read Traefik's `ClientHost`, the bare host with no port — the same field the
   working queries use. Nothing to disambiguate for v6, and no risk of swallowing `:44321`.
3. `get_ssh_attackers` widened from `[0-9.]+` to `[0-9a-fA-F:.]+`, and the three jq guards
   from `^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$` to `^(…|[0-9a-fA-F:]+)$`. Previously a v6 address
   was dropped at the guard even when it was found.

## Changes

| File | Change |
|---|---|
| `ansible/plays/roles/system/templates/fail2ban/jail.local.j2` | `[loki-blocklist]` lists `iptables-multiport` **and** `ip6tables-multiport`, both in `{{ fail2ban_web_tier_chain }}` |
| `ansible/plays/roles/system/templates/fail2ban/update-blocklist-from-loki.sh.j2` | the three queries and three jq guards above |
| `ansible/tests/fail2ban/test_blocklist_regex.py` | **new** — extracts the patterns from the template and applies them to fixtures |
| `.github/workflows/ci.yml` | runs those tests in the custom-module job |
| `ansible/plays/roles/system/molecule/with-docker/verify.yml` | asserts both jails now render the v6 action |

The tests are the point: they read the *shipped template*, so a future edit is checked
against realistic lines — v4 and v6 must both capture the bare host, a timestamp or a
`host:port` must never pass, and a doubled backslash fails the build (that is exactly the
bug above).

## Verification

- `ansible/tests/fail2ban` → 6/6 pass; red before the fix (that is how defects 1 and 3 were
  found).
- Isolated fail2ban instance on servy, with a jail named for the test and `chain=DOCKER-USER`:
  a ban of `2001:db8::55` appears in `ip6tables -S f2b-lokitest` and the jump in
  `ip6tables -S DOCKER-USER`; stopping the instance removes both. Production untouched.
- Molecule assertions + `yamllint` / `ansible-lint` / `--syntax-check` locally; CI in full.

## To deploy

```bash
cd ansible
./servyy.sh --limit servy.lehel.xyz --tags system.fail2ban --check --diff
./servyy.sh --limit servy.lehel.xyz --tags system.fail2ban
./servyy.sh --limit codey.lehel.xyz --tags system.fail2ban
```

Then confirm the web tier can actually ban a v6 source (documentation prefix, then remove):

```bash
ssh servy.lehel.xyz "sudo fail2ban-client set loki-blocklist banip 2001:db8::55"
ssh servy.lehel.xyz "sudo ip6tables -S DOCKER-USER | head -2; sudo ip6tables -S f2b-loki-blocklist | head -2"
ssh servy.lehel.xyz "sudo fail2ban-client set loki-blocklist unbanip 2001:db8::55"
```

## Note on the first ban wave

Nothing should change immediately: the blocklist script runs every 2 minutes and bans what
Loki reports. A v6 scanner will now appear in the feed and be banned in `ip6tables`, where
before it was invisible. If the operator's own v6 line ever trips a rule, it is visible in
`fail2ban-client status loki-blocklist` and un-bannable the same way as v4.
