# Public IPv4 instead of CGNAT — ISP request (2026-11-19)

**Date:** 2026-11-19
**Repo:** `servyy-container` (`/home/cda/dev/infrastructure/container`)
**Status:** open — blocked on the provider's reply to a request sent 2026-11-18
**Host:** `servy.lehel.xyz` (that is where the bans land) — no host change is
planned, this is about the operator's home uplink
**Related:** [`history/2026-11-18_bumbleflies-de-transfer.md`](2026-11-18_bumbleflies-de-transfer.md)

> **Why this sits in `history/` and not `docs/plans/`:** `docs/plans/` is being
> retired ([#307](https://github.com/dachrisch/servyy-container/pull/307)) —
> the rule is that plans are deleted when the job is done and anything still
> needed moves into history. This is the incident record *plus* the one open
> decision, so it belongs here rather than in a directory that is going away.

## Goal

Get a **non-shared public IPv4** for the household uplink, so that a stranger's
abuse from the same NAT pool can no longer block the household from 80/443 —
and stop the recurring "IPv4 is broken" investigations, which cost an afternoon
on 2026-11-18 and turned out to be a ban, not a network fault.

Decision taken 2026-11-18: **keep HTTP-01** for the whole estate (DNS-01 buys
nothing here and stalled on its propagation check) and ask the ISP for a
non-shared address instead of working around the bans.

The only missing input is the ISP's reply. Everything needed to act on it is
below.

## Findings (verified 2026-11-18 / 2026-11-19)

| Fact | Evidence |
|---|---|
| The uplink is behind CGNAT | the public IPv4 reverse-resolves to `cgn-<addr>.ip-pool.greenfiber.de`; the household has no dedicated /32 |
| The address rotates without warning | `.31` (11-10), `.17` (11-11), `.217` (11-18), `.14` (11-19) — a fresh assignment re-appears in the pool's abuse within days |
| Who bans it | `loki-blocklist`, the Traefik web-abuse jail: `port = http,https`, jumped from the FORWARD/DOCKER-USER chain so container traffic actually traverses it |
| What triggers it | `traefik-aggressive-crawler` (5857 attempts), `traefik-rate-limit` (5738), `traefik-rate-flood` (268) at 09:35 on 2026-11-18 — from a neighbour on the shared address, not from this household |
| SSH is unaffected **by design** | the jail is scoped to http/https; the reasoning is in `ansible/plays/roles/system/templates/fail2ban/jail.local.j2` (~line 100) and `history/2026-10-30…`: an all-ports web ban once locked the operator out |
| Ban length is not fixed at 1 h | observed `3600` s on 2026-11-18 but `86400` s on 2026-11-10 for the same pool → 1 h base with `bantime.increment` escalating to `bantime.maxtime = 86400` |
| Evidence retention is short | fail2ban keeps ~10 days in `fail2ban.sqlite3` and 4 weekly rotations of `fail2ban.log`, so "it happens all the time" cannot be re-proved beyond ~4 weeks |
| Nothing in this repo depends on the WAN address | no DNS record, cert resolver or firewall rule references it; DNS, TLS and Traefik are unaffected by the bans |

State re-checked on 2026-11-19: assignment rotated to `.14`, no active ban,
`https://bumbleflies.de/` answers 200 over IPv4 **and** IPv6.

## The request (sent 2026-11-18)

To **Greenfiber** (`kontakt@greenfiber.de`, the open-access fibre operator), by
email, on behalf of the contract holder:

1. whether a public/own IPv4 is bookable (their product list shows it as a paid option);
2. monthly and one-off cost;
3. genuine dual-stack (public IPv4 **and** IPv6) versus DS-Lite;
4. static or dynamic — **a dynamic, non-shared address is sufficient**, do not buy static;
5. whether it changes the tariff or extends the contract term;
6. who may order it (the contract is in a household member's name, so a
   Vollmacht or a confirmation from them is likely required).

## When the reply arrives

Judge it in this order:

- **Dual-stack, not DS-Lite.** DS-Lite still has no inbound IPv4 — that is not an
  answer to the problem, whatever else the reply says.
- **Not a business tariff.** No hosting was requested and none is needed; a
  Geschäftskunde upsell is a wrong answer, not a price.
- **Term impact stated explicitly.** Any extension belongs to the contract
  holder and needs their consent before anything is booked.
- **Price.** Weigh a monthly fee plus a term extension against a self-clearing
  ban roughly once a week, with IPv6 unaffected throughout. That is a real
  decision, not an automatic yes.

### If yes

- Order it. Expect a new public IPv4 on the line, possibly dynamic.
- **Nothing in this repo changes**: no DNS record, no certificate resolver, no
  firewall rule depends on the WAN address.
- Verify afterwards: `curl -4 -sS https://ifconfig.me` returns one address that
  does **not** reverse-resolve into a `cgn-*.ip-pool.*` range, and inbound IPv4
  to the estate works from a foreign network.
- Update this plan's status and write a short `history/` entry.

### If no, or the price is silly

1. **Do nothing.** Bans self-clear and IPv6 keeps working — this is the current,
   stable state. Revisit if it starts happening daily again.
2. **Escalate at the ISP.** Their fibre is an **open-access** network, so another
   provider on the same glass may sell what they will not. That makes "not
   possible" a product answer, not a technical limit.
3. **Last resort, and against repo policy:** a jail-scoped `ignoreip` for the pool
   in `jail.local.j2`. That file explicitly forbids it ("fix the scope, not the
   target"), and on a shared address it would also stop throttling the
   neighbours. It needs a deliberate policy change plus the molecule assertion
   updated — not a quick edit.

## Re-checking the evidence later

```bash
# is the household blocked right now?
ssh servy.lehel.xyz 'sudo fail2ban-client status loki-blocklist'
ssh servy.lehel.xyz 'sudo nft list ruleset | grep -c "45\.155\.141\."'

# has the assignment rotated? (it does, without warning)
curl -4 -sS https://ifconfig.me

# what triggered it
ssh servy.lehel.xyz 'sudo grep -a "<address>" /var/log/fail2ban-loki.log | tail -3'

# unban (legitimate: the household is not the offender)
ssh servy.lehel.xyz 'sudo fail2ban-client set loki-blocklist unbanip <address>'
```

## Open detail

`fail2ban-client get loki-blocklist bantime` reports `86400` while the observed
ban record for 2026-11-18 was `3600`. That is consistent with a 1 h base plus
`bantime.increment` capped by `bantime.maxtime`, but it means a repeat offender
can still be blocked for 24 h. Confirm which value is in force before telling
anyone "it is only an hour".

## Constraints on this note

- The repo is **public**. The contract holder's name, customer number, address,
  phone and email are deliberately not recorded here and must not be added.
  The provider's name is recorded because it is a vendor, like the others in
  this repo, and the reply is useless without knowing who to chase.
- The operator is not the contract holder, so any booking may need a Vollmacht.
