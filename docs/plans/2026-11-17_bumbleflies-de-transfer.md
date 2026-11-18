# bumbleflies.de — registry transfer GoDaddy → Porkbun

**Status:** **done** 2026-11-18 — superseded by
[`history/2026-11-18_bumbleflies-de-transfer.md`](../../history/2026-11-18_bumbleflies-de-transfer.md).
Kept for the pre-transfer recon and the captured old zone.
**Owner:** Christian
**Started:** 2026-11-17
**Blocker (cleared):** GoDaddy support ticket **1026409** — `.de` `AUTHINFO` arrived 2026-11-18 11:26

---

## Why

The domain is the last one in the estate still registered outside Porkbun, and
that single fact is what keeps DNS-01 unavailable for the services on it:

- `bumbleflies/docker-compose.yml` — apex `_prod` router falls back to
  `letsencrypthttpresolver`; `bnb`, `edu`, `live` routers likewise.
- `waggle/docker-compose.yml`, `dontforget/docker-compose.yml`,
  `bnb-office`, `finance`/`queen` — all carry comments explaining HTTP-01 is
  forced because `bumbleflies.de` is not in the Porkbun account.

Moving the registration makes the whole wildcard tree eligible for DNS-01 and
lets renewal stop depending on the HTTP-01 path staying reachable.

## Verified baseline (2026-11-17, all read-only)

| Fact | Value |
|---|---|
| Porkbun account | `dachrisch`, key scopes `["full"]`, `credentialsValid: true` |
| In account? | **no** — `GET /domain/get/bumbleflies.de` → `DOMAIN_NOT_FOUND` |
| Transfer price | **$5.10** (`additional.transfer.price`, → `cost: 510`) |
| Renewal price | $4.07 (what the following year costs) |
| Balance | **$0.00** → top-up of 510¢ needed before the transfer |
| Registry expiry | **2026-12-10** (23 days at time of writing; `.de` transfer adds a year → 2027-12-10) |
| WHOIS status | `clientTransferProhibited` → **domain still locked at GoDaddy** |
| DNSSEC | **unsigned** (no DS, no DNSKEY) — no landmine |
| CAA | none — will not block Let's Encrypt later |
| Nameservers | `ns49.domaincontrol.com`, `ns50.domaincontrol.com` |
| Registrar | `GoDaddy.com, LLC`, IANA 146, registered 2021-12-10 |
| Registrant country | DE; WHOIS privacy is not offered for `.de` |
| Other Porkbun domains | `lehel.xyz`, `xn--hfer-architekten-mwb.de` (both `ACTIVE`, `apiAccess: 1`) |

The 48 h window and the 2026-12-10 expiry are compatible — `.de` transfers
settle in hours once `AUTHINFO` is in, but **do not let this slip past
2026-12-10**, an expired domain cannot transfer and GoDaddy would charge its own
renewal.

## The zone that must be rebuilt (captured 2026-11-17 from the live GoDaddy NS)

`*.bumbleflies.de` is a **wildcard**, which is why most subdomains resolve
without an explicit record and why a scan is the wrong tool here: `/dns/scan`
would see the wildcard answer at every well-known name, import each as an
explicit A record, and still not create the wildcard itself. The records below
are the complete, hand-verified set (`dig` against `ns49/ns50.domaincontrol.com`,
every type probed: A, AAAA, CNAME, MX, TXT, NS, SRV, CAA, DS).

| name | type | content | prio |
|---|---|---|---|
| `bumbleflies.de` | A | `49.13.6.173` | |
| `bumbleflies.de` | AAAA | `2a01:4f8:c013:f6f4::1` | |
| `*.bumbleflies.de` | A | `49.13.6.173` | |
| `*.bumbleflies.de` | AAAA | `2a01:4f8:c013:f6f4::1` | |
| `www.bumbleflies.de` | CNAME | `bumbleflies.de` | |
| `events.bumbleflies.de` | CNAME | `bumbleevent.cname.pretix.eu` | |
| `openchat.bumbleflies.de` | CNAME | `bumbleevent.cname.pretix.eu` | |
| `trainings.bumbleflies.de` | CNAME | `bumbletrain.cname.pretix.eu` | |
| `bumbleflies.de` | MX | `aspmx.l.google.com` | 1 |
| `bumbleflies.de` | MX | `alt1.aspmx.l.google.com` | 5 |
| `bumbleflies.de` | MX | `alt2.aspmx.l.google.com` | 5 |
| `bumbleflies.de` | MX | `alt3.aspmx.l.google.com` | 10 |
| `bumbleflies.de` | MX | `alt4.aspmx.l.google.com` | 10 |
| `bumbleflies.de` | TXT | `v=spf1 include:dc-aa8e722993._spfm.bumbleflies.de ~all` | |
| `bumbleflies.de` | TXT | `google-site-verification=G5RqH1_i49CYADSb7nlaISxBsF2H8WD6PhX8WdFcVmk` | |
| `bumbleflies.de` | TXT | `google-site-verification=THjy-QfFquPcuyRO1OkHYDBau827MmS_f7ntqTN1RTk` | |
| `bumbleflies.de` | TXT | `openai-domain-verification=dv-hBP0DKmrOXOPby3qdhcvQimf` | |
| `dc-aa8e722993._spfm.bumbleflies.de` | TXT | `v=spf1 include:_spf.google.com ~all` | |

TTL `600` throughout (GoDaddy SOA minimum is 600).

**Mail is live on this domain** (Google Workspace MX, SPF, a Google-managed
`_spfm` include). There is **no DMARC and no DKIM selector** published today —
that is the current state, not an omission to fix silently during the move.

Nothing else exists: no `_dmarc`, no `mta-sts`, no `_acme-challenge`, no CAA, no
DS. Historic names from certificate transparency (`beta`, `archive`, `social`,
`ibs`, `dontforget`, `queen`, …) all resolve **only** via the wildcard and need
no record of their own.

## Steps when the code arrives

1. **Unlock first.** WHOIS still shows `clientTransferProhibited`. If
   `AUTHINFO` arrives without the lock being lifted, DENIC will reject the
   transfer — confirm in the ticket reply (or the GoDaddy panel) that the domain
   is unlocked.
2. **Top up exactly 510¢** (`POST /account/topup {"amount":510}`). Credit, not a
   card charge at purchase time; balance is currently `$0.00`. If it returns
   `NO_PAYMENT_METHOD`, the card has to be added at
   <https://porkbun.com/account/credit> — not doable over the API.
3. **Start the transfer held** — `POST /domain/transfer/bumbleflies.de` with
   `{"cost":510,"holdForDnsSetup":true,"authCode":"…"}` and one
   `Idempotency-Key` for the operation. The auth code must be read with
   `read -rs` into an env var: never argv, never a file, never the history entry.
   Verify `held: 1` via `GET /domain/getTransferSetup/bumbleflies.de`.
4. **Build the zone** — `POST /domain/prepareTransfer/bumbleflies.de`, then
   create the 18 records above explicitly (`POST /dns/create/…`, name **relative**
   — `""` for the apex, `"*"` for the wildcard, MX priority in `prio`). Do **not**
   run `/dns/import`, and do not pass FQDNs: they get stored with the suffix
   doubled.
5. **Preflight** — `GET /dns/preflight/bumbleflies.de?intent=move-nameservers`
   must have empty `blockers[]` *and* `warnings[]`.
6. **Prove parity** — compare `dig @<porkbun-ns>` against the old zone for A,
   AAAA, MX, TXT, CNAME, on apex and every name in the table. The wildcard needs
   its own check (`dig @ns zzz.bumbleflies.de`). Order-insensitive comparison;
   RRsets are unordered.
7. **Release** — `POST /domain/startTransfer/bumbleflies.de {}`. A
   `TRANSFER_ZONE_EMPTY` here means the zone is still empty; fix it rather than
   forcing.
8. **Repoint NS** once status reaches `PENDINGTRANSFER`/`DONE`:
   `curitiba`, `fortaleza`, `maceio`, `salvador`.ns.porkbun.com.
   Verify at the registry **and** two public resolvers.
9. **Verify the service** — apex and `www` over IPv4 **and** IPv6; `events`,
   `trainings` still reach pretix; mail still answers (`dig MX`).
10. **Switch cert resolvers** to `letsencryptdnsresolver` for the bumbleflies
    routers (`bumbleflies/docker-compose.yml` lines 21, 62, 85, 110) and prove
    the Traefik API key can write a TXT record in *this* zone before relying on
    it — a broken DNS-01 path surfaces 30 days before expiry, not at deploy.
11. **Lock down** — `apiAccess: 1` (a domain that arrives without it refuses
    `/domain/renew` with `API_ACCESS_DISABLED`), `autoRenew` on, registrar lock
    on (`.de` carries no 60-day lock).
12. **Write `history/2026-11-??_bumbleflies-de-transfer.md`** with the cost,
    transfer/order IDs, the final record set and the verification output — then
    retire this plan.

## Known risks

| Risk | Handling |
|---|---|
| Wildcard lost in a scan/import | Create the 18 records explicitly; the wildcard check is part of the parity test |
| Losing AAAA → site silently drops to IPv4 | Both `@` and `*` AAAA are in the table and probed |
| Mail outage | MX + SPF + `_spfm` copied verbatim; `_spfm` is easy to miss, it is the SPF target of the apex include |
| Expiry 2026-12-10 overtakes the transfer | Force the issue with GoDaddy if the code slips past ~2026-12-01 |
| `clientTransferProhibited` left on | Check the ticket reply; WHOIS again before submitting |
| DNS-01 works at cutover but fails at renewal | Explicit Traefik-key TXT write/delete probe (step 10) |
