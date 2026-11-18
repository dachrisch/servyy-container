# bumbleflies.de — registrar transfer GoDaddy → Porkbun

**Date:** 2026-11-18
**Domain:** `bumbleflies.de`, TLD `.de`
**Related services:** the whole wildcard tree — `bumbleflies` (www), `bnb-office`,
`bumbleflies` edu/live, `waggle`, `dontforget`, `finance`/`queen`, plus the
pretix hosts `events`/`openchat`/`trainings`

## Summary

Moved the last domain in the estate that was registered outside Porkbun. The
registration, the DNS delegation and (potentially) the TLS challenge method all
moved, with **no resolution gap**: the zone was rebuilt and proven identical on
Porkbun's own nameservers *before* the delegation changed.

- Registrar: **GoDaddy → Porkbun** (`dachrisch` account)
- Nameservers: `ns49/ns50.domaincontrol.com` → `curitiba/fortaleza/maceio/salvador.ns.porkbun.com`
- Expiry: 2026-12-10 → **2027-11-18** (the transfer bought a year; the remaining
  23 days of the old term were folded in, not lost)
- Cost: **$5.10** (Porkbun credit, top-up order `12610613`; transfer order
  `12610616`, transfer id `930774`). GoDaddy was paid nothing.

## Reason

Consolidation, and the DNS-01 blocker. `ansible/production` and four compose
files carried comments explaining that DNS-01 could not issue for
`bumbleflies.de` because the zone was not in the Porkbun account the Traefik API
keys belong to (`INVALID_DOMAIN`). The GoDaddy ticket (Incident `1026409`,
`cctldtransferaway@godaddy.com`) supplied the `.de` `AUTHINFO` within the
promised 48 h.

## Detailed Changes

### 1. Before the transfer (recon)

Read-only, nothing charged. Recorded in `docs/plans/2026-11-17_bumbleflies-de-transfer.md`,
which this entry supersedes.

| Fact | Value |
|---|---|
| In account before | no (`DOMAIN_NOT_FOUND`) |
| Transfer price | $5.10 (`additional.transfer.price` → `cost: 510`) |
| Balance before | $0.00 → topped up to 510¢ |
| Registry expiry | 2026-12-10 |
| WHOIS status | `clientTransferProhibited` (GoDaddy lock / "protection") |
| DNSSEC | unsigned — no DS, so a delegation change could not break validation |
| CAA | none |

The zone was captured with `dig` against the GoDaddy nameservers, **every record
type probed** (A, AAAA, CNAME, MX, TXT, NS, SRV, CAA, DS), not with
`/dns/scan`: `*.bumbleflies.de` is a wildcard, so a scan would have answered the
wildcard at every well-known name, imported each as an explicit record, and
still not created the wildcard itself.

### 2. Transfer, held before delegation

A `dryRun` transfer (no charge) returned `wouldSucceed: true`, then the real
call:

```
POST /domain/transfer/bumbleflies.de
{"cost": 510, "holdForDnsSetup": true, "authCode": "…"}
Idempotency-Key: <uuid, one per operation>
```

`holdForDnsSetup` parked it at `PENDINGDNS`, so the zone could be built while
GoDaddy was still authoritative. The auth code was passed through stdin, never
argv, never a file, and is not recorded here.

Status progression, all inside ~10 minutes: `PENDINGWHOIS` → `PENDINGSUBMIT` →
`PROCSUBMIT` → `PENDINGINSERT` → `PENDINGDONENOTICE` → **`DONE`**.

### 3. DNS zone at Porkbun (18 records, byte-identical to GoDaddy)

```
A      bumbleflies.de                     49.13.6.173
AAAA   bumbleflies.de                     2a01:4f8:c013:f6f4::1
A      *.bumbleflies.de                   49.13.6.173
AAAA   *.bumbleflies.de                   2a01:4f8:c013:f6f4::1
CNAME  www.bumbleflies.de                 bumbleflies.de
CNAME  events.bumbleflies.de              bumbleevent.cname.pretix.eu
CNAME  openchat.bumbleflies.de            bumbleevent.cname.pretix.eu
CNAME  trainings.bumbleflies.de           bumbletrain.cname.pretix.eu
MX     @ aspmx.l.google.com               1
MX     @ alt1.aspmx.l.google.com          5
MX     @ alt2.aspmx.l.google.com          5
MX     @ alt3.aspmx.l.google.com          10
MX     @ alt4.aspmx.l.google.com          10
TXT    @ v=spf1 include:dc-aa8e722993._spfm.bumbleflies.de ~all
TXT    @ google-site-verification=G5RqH1_i49CYADSb7nlaISxBsF2H8WD6PhX8WdFcVmk
TXT    @ google-site-verification=THjy-QfFquPcuyRO1OkHYDBau827MmS_f7ntqTN1RTk
TXT    @ openai-domain-verification=dv-hBP0DKmrOXOPby3qdhcvQimf
TXT    dc-aa8e722993._spfm  v=spf1 include:_spf.google.com ~all
```

TTL 600 throughout. Mail is live on this domain (Google Workspace MX + SPF); the
`_spfm` TXT is the SPF target of the apex include and is the easiest one to drop.

**`/dns/create` takes a relative name** — `""` for the apex, `"*"` for the
wildcard, never the domain itself. The first pass passed FQDNs, which Porkbun
stored as `www.bumbleflies.de.bumbleflies.de`; `/dns/preflight` caught it
("Nothing answers at the apex", "wildcard-shadowed") before anything was
released. All 22 records were deleted by id and recreated correctly. **Use
preflight as the check, not the retrieve output** — retrieve returns FQDNs, so
the mistake reads back looking almost right.

### 4. Release and delegation

- `POST /domain/prepareTransfer` created the zone; the four Porkbun NS records
  are created automatically (a 22-record zone, not 18).
- `GET /dns/preflight?intent=move-nameservers` → **no blockers**. Two warnings,
  both expected: `nameservers-ours` (still delegated to GoDaddy, by definition,
  while held) and `wildcard-shadowed` on `dc-aa8e722993._spfm` — a TXT-only name
  under RFC 4592 so the wildcard no longer answers it for addresses, which is
  harmless for an SPF target and was equally true at GoDaddy.
- Parity was proven **authoritative-to-authoritative** (`@ns49.domaincontrol.com`
  vs `@maceio.ns.porkbun.com`, `+norecurse`): 27 comparisons, all identical,
  including the wildcard and every MX. Comparing against a *recursive* resolver
  instead produces phantom diffs on CNAME'd names, because it chases the CNAME
  while an authoritative answer does not.
- `POST /domain/startTransfer` released it; delegation was repointed with
  `POST /domain/updateNs` as soon as the domain was in the account.

## Verification

```
DENIC a.nic.de (authoritative for .de)  curitiba/fortaleza/maceio/salvador.ns.porkbun.com
1.1.1.1 / 8.8.8.8 / 9.9.9.9            same four (within ~10 min of the change)
apex A / AAAA                          49.13.6.173 / 2a01:4f8:c013:f6f4::1
apex MX                                5 Google targets, priorities preserved
apex TXT                               4 records, identical strings
wildcard probe (rnd-probe.bumbleflies.de)  49.13.6.173 / 2a01:4f8:c013:f6f4::1
www / events / openchat / trainings    CNAMEs intact, pretix answers 200
https://bumbleflies.de/                200 (72,639 bytes)
https://www.bumbleflies.de/            301
```

- Site verified over **IPv4 and IPv6** from `codey` (both 200) — *not* from the
  workstation or `servyy-test`, which cannot reach `49.13.6.173:443` over IPv4
  at all. That path failure is pre-existing, affects `lehel.xyz` identically,
  and is unrelated to this move (see Next Steps).
- Porkbun: domain `ACTIVE`, `autoRenew: 1`, `apiAccess: 1`, `securityLock: 0`,
  `whoisPrivacy: 0` (not offered for `.de`), expiry `2027-11-18`.
- **DNS-01 proven, not assumed:** a `_acme-challenge-check` TXT was created and
  deleted in this zone using the *Traefik* key pair
  (`traefik.porkbun_api_key` in `vars/secrets.yml`, deliberately a different key
  from `porkbun_api`). `domain/get`, `dns/create` and `dns/delete` all
  `SUCCESS`; zone left as found.

## Impact Assessment

- No resolution gap: A, AAAA, MX, TXT and the wildcard answered identically from
  both nameserver pairs throughout, so mail and the whole subdomain tree were
  never served from an empty zone.
- `.de` carries no 60-day transfer lock and needs no registrant change.
- The four services that were forced onto HTTP-01 because of this domain are now
  *eligible* for DNS-01 — see Next Steps; nothing was switched as part of the
  transfer itself.

## Rollback Procedure

Not practically reversible: an outbound `.de` transfer needs a fresh `AUTHINFO`
from Porkbun and another year's fee. The record set above is the complete zone
content to recreate anywhere else.

For the delegation alone: `POST /domain/updateNs` back to the GoDaddy pair —
but GoDaddy no longer holds a zone for the domain, so that would blackhole it.

## Next Steps

- [ ] **Switch the `bumbleflies.de` routers to `letsencryptdnsresolver`** —
      `bumbleflies/docker-compose.yml` lines 21 (`_prod`, the apex), 62 (bnb),
      85 (edu), 110 (live). HTTP-01 still works today, so this is an improvement
      rather than a fix, and it needs a deploy to take effect.
- [ ] **Correct the now-false comments** in `waggle/docker-compose.yml`,
      `dontforget/docker-compose.yml`, `bnb-office/docker-compose.yml`,
      `finance/docker-compose.yml` and `ansible/production`, all of which say DNS-01
      is impossible because "bumbleflies.de is at Strato/GoDaddy".
- [ ] **The IPv4 path to `49.13.6.173:443` from the workstation and
      `servyy-test`** fails while IPv6 succeeds and `codey` reaches it fine on
      both. Looks like a fail2ban ban or a firewall rule on that source range,
      and it silently hides IPv4-only breakage from local testing. Unrelated to
      this transfer, worth its own investigation.
- [ ] `securityLock: 0` — confirm whether Porkbun offers a registrar lock for
      `.de`; the previous `.de` transfer also ended with the lock off.
