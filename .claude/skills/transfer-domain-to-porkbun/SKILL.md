---
name: transfer-domain-to-porkbun
description: Use when moving a domain registration from another registrar into Porkbun (e.g. "transfer leaguesphere.app to Porkbun", "move bumbleflies.de off GoDaddy", "get this domain off Strato/Namecheap"), especially when the site must stay up during the move. Covers cost and funding, the holdForDnsSetup no-downtime path (scan → import → verify → release), nameserver repoint, then the repo-side wiring (cert resolver, verification, history entry).
---

# Transfer a domain registration into Porkbun

## When this applies

A domain lives at some other registrar and has to move to Porkbun — because it
is expiring, because the old registrar is being abandoned, or because the whole
estate is consolidated at Porkbun. Upcoming case: `leaguesphere.app`.
`bumbleflies.de` was moved 2026-11-18 (see
`history/2026-11-18_bumbleflies-de-transfer.md`); `lehel.xyz` and
`höfer-architekten.de` are already there.

This is **not** the same as changing nameservers. A transfer moves the
registration; the DNS zone is a separate object that Porkbun only creates when
you ask for it. EPP carries **no zone data**, so the moment the losing registrar
stops answering, everything it published is gone. That is the single most
important fact in this skill and the reason for the `PENDINGDNS` hold.

Landing page for the API: <https://porkbun.com/llms/domain> ·
`/llms/dns` · full reference `https://porkbun.com/llms-full.txt`

## Ground rules

- **Never guess or brute-force a credential.** Auth codes, registrar logins and
  anything behind 2FA belong to the human. If a login is needed, stop and ask.
  Use the API for everything the API can do; use the browser for the rest.
- **The auth code is a bearer credential.** Never put it in the shell argv
  (`curl -d '{"authCode":"…"}'` lands in `~/.zsh_history` and `ps`), never in a
  file, never in a commit message, never in the history entry. Read it with
  `read -rs` into an env var, or paste it into a python heredoc via stdin.
- **Verify the zone before you release the hold.** `startTransfer` moves the
  delegation; once it does, there is no second chance to read the old zone.
- **Fund with account credit.** A saved card is *not* charged by a purchase —
  the balance has to be there first (`INSUFFICIENT_FUNDS` otherwise).
- ~$5–15 of someone's money moves here. Quote the cost to the user and get a
  yes before `domain/transfer`, before `account/topup`, and before
  `startTransfer` if the zone differs from what was planned.

## Prerequisites

- Porkbun account (currently `dachrisch`) with **verified email and phone**,
  and an API key with `purchase` + `domains` + `dns` + `funding` scopes
  (`/ping` prints `scopes`).
- A saved payment method on the website if `account/topup` is to be used. It
  cannot be added over the API (`NO_PAYMENT_METHOD`).
- Losing registrar: domain **unlocked**, registrant email reachable (they send
  the approval/notice there), and an **auth code / EPP code** in hand. `.de`
  calls it `AUTHINFO`; some registrars only reveal it after a support request.
- Domain not expiring mid-transfer if avoidable — an expired domain usually
  cannot transfer, and renewal at the old registrar costs more than the
  transfer fee. (Last time the domain expired the same day and it still worked;
  do not plan on that.)
- The domain must **not** already be in the account (check first, below).

## Step 0 — credentials and a helper

Run from the repo root (`~/dev/infrastructure/container`). Keys come from
`ansible/plays/vars/secrets.yml` (git-crypt). They never appear in argv, only in
the environment of the helper:

```bash
load_porkbun() {   # load_porkbun [account]  — default: dachrisch (the paying one)
  local account="${1:-dachrisch}"
  read -r PB_PK PB_SK < <(python3 - "$account" <<'PY'
import sys, yaml
acc = ((yaml.safe_load(open("ansible/plays/vars/secrets.yml")).get("porkbun") or {})
       .get(sys.argv[1]) or {})
print(acc.get("pk", ""), acc.get("sk", ""))
PY
  )
  export PB_PK PB_SK
}

# Secrets live under `porkbun.<account>`, one block per Porkbun account keyed by
# the name /ping reports. `dachrisch` owns lehel.xyz and the höfer domain and is
# the account that pays; `bumbledomain` owns bumbleflies.de only and must never
# be used for purchases. Pick the account whose domain you are working on — the
# wrong one returns DOMAIN_NOT_FOUND / INVALID_DOMAIN.

pb() {  # pb METHOD PATH [JSON_BODY]
  python3 - "$@" <<'PY'
import json, os, sys, urllib.request, urllib.error
method, path = sys.argv[1], sys.argv[2]
body = sys.argv[3].encode() if len(sys.argv) > 3 else None
h = {"X-API-Key": os.environ["PB_PK"], "X-Secret-API-Key": os.environ["PB_SK"],
     "Content-Type": "application/json"}
if os.environ.get("PB_IDEM"):
    h["Idempotency-Key"] = os.environ["PB_IDEM"]
req = urllib.request.Request("https://api.porkbun.com/api/json/v3" + path,
                             data=body, method=method, headers=h)
try:
    print(json.dumps(json.load(urllib.request.urlopen(req)), indent=1))
except urllib.error.HTTPError as e:
    print(e.code, json.dumps(json.loads(e.read() or b"{}"), indent=1))
PY
}
```

Sanity check: `pb GET /ping` → `credentialsValid: true`, the account name, and
the scopes. If the key is IP-restricted, `yourIp` shows what Porkbun sees.

Traefik has a **second** key in `traefik/docker-compose.yml`, same account,
used by lego for DNS-01. Do not use it for purchases.

## Step 1 — recon (read-only, nothing is charged)

```bash
D=bumbleflies.de            # or the punycode form for an IDN

pb POST /domain/checkDomain/$D   # availability + pricing, incl. the transfer price
pb GET  /domain/get/$D           # 404 DOMAIN_NOT_FOUND = not in the account (expected)
pb GET  /account/balance
```

`checkDomain` is the cheapest way to get the exact cost and to see whether the
domain is already here:

- `response.additional.transfer.price` → dollars (`"5.10"`)
- `response.inYourAccount` → `true` means someone already transferred it; stop.
- `response.avail: "no"` is normal for a domain you own elsewhere.

Convert to the integer cents the API wants: `$5.10` → `cost: 510`.

Then look at the zone the domain publishes **now** (this is your ground truth
for the import — `/dns/scan` cannot run until the domain is in the account):

```bash
dig +short NS $D
dig +short A $D; dig +short AAAA $D
dig +short MX $D; dig +short TXT $D; dig +short CAA $D
dig +short DS $D        # DNSSEC: non-empty = a landmine, see below
```

- **A and AAAA both.** `dig A` alone silently misses IPv6; losing AAAA takes
  the domain off IPv6 with no visible symptom.
- **DS records** mean the zone is signed. Pointing new nameservers at an
  unsigned Porkbun zone makes every validating resolver refuse the domain
  (SERVFAIL, not degradation). Remove DNSSEC at the old registrar, wait out the
  DS TTL, then transfer.
- **CAA** records copied verbatim can block Let's Encrypt later. Note them.
- **MX/SPF/DKIM** mean someone's mail depends on this zone. A scan will find the
  obvious ones but not every DKIM selector — get an exact export (below).

## Step 2 — fund the exact amount

```bash
pb GET  /account/balance                    # cents
pb POST /account/topup '{"amount":510}'     # 500–50000 cents, one-off
```

Rules that bite: the charge is the top-up, not the purchase; supplying `amount`
does **not** change the account's stored top-up setting (good, on purpose);
top-ups are capped at 5/day, 20/month and by the monthly API spend ceiling.

If no card is saved: ask the user to add credit at
<https://porkbun.com/account/credit> — do not work around it.

## Step 3 — start the transfer **held** at `PENDINGDNS`

```bash
read -rs PB_AUTH                   # paste the code: no echo, no history, no argv
export PB_AUTH
export PB_IDEM=$(python3 -c 'import uuid;print(uuid.uuid4())')   # one per operation
BODY=$(python3 -c 'import json,os;print(json.dumps({"cost":510,"holdForDnsSetup":True,"authCode":os.environ["PB_AUTH"]}))')
pb POST /domain/transfer/$D "$BODY"
unset PB_AUTH BODY                 # nothing left in the environment afterwards
```

Read the auth code with `read -rs` (no echo, no history) rather than typing it
into the command. `holdForDnsSetup: true` charges the transfer but
parks it at `PENDINGDNS` so the zone can be built **before** the domain moves —
the no-downtime path. Nothing releases a held transfer on a timer; it waits for
you indefinitely.

The idempotency key makes retries safe: same key + same body within 24h replays
the original response instead of buying twice. A retry with a *different* body
returns `409 IDEMPOTENCY_KEY_MISMATCH`.

Verify the hold before continuing:

```bash
pb GET /domain/getTransferSetup/$D
# -> held: 1, zoneReady: 0, recordCount: 0, delegation: {...}, dnssec: 0,
#    nextStep: {...}, porkbunNameservers: [...]
```

`TRANSFER_HOLD_NOT_AVAILABLE` (nothing charged) means the TLD does not support
it — `.uk` and Handshake. `.uk` and manage-only TLDs cannot be transferred over
the API at all; use the website.

## Step 4 — build the zone before the domain moves

### 4a. Create the zone

```bash
pb POST /domain/prepareTransfer/$D    # -> zoneReady, recordCount, porkbunNameservers
```

### 4b. Load the records — exact export first, scan second

If the old registrar has an API or a zone export, **that** is authoritative;
read it with your own credentials (they never reach Porkbun) and POST the
records. Otherwise let the scan do it:

```bash
pb GET  /dns/scan/$D          # read-only; ~90 lookups, metered 20/hour
pb POST /dns/import/$D '{}'   # omit "records" = import whatever the scan found
```

`/dns/import` is idempotent (`skipped`, not `failed`, for existing records) and
takes up to 500 records, so it is safe to re-run. NS and SOA entries are
ignored — they describe the delegation, not the zone.

The scan probes a fixed set of well-known names. It cannot enumerate a zone
(AXFR is refused everywhere), so it **is not exhaustive**: subdomains nobody
thinks about, extra DKIM selectors and verification TXT records are exactly what
it misses. Diff the import against your step-1 `dig` output and add what is
missing by hand:

```bash
pb POST /dns/create/$D '{"name":"www","type":"CNAME","content":"example.com","ttl":600}'
```

**`name` is relative to the domain** — `www`, not `www.example.com`. The apex is
`""` and the wildcard is `"*"`. Passing an FQDN does not error: it stores
`www.example.com.example.com` and the zone then looks plausible while resolving
nothing. `/dns/retrieve` returns FQDNs, so that reads back looking almost right —
**`/dns/preflight` in 4c is the check**, not the retrieve output. A wrong-name
zone announces itself with "Nothing answers at the apex" and
`wildcard-shadowed`. Fix by deleting by id (`/dns/delete/$D/<id>`) and
recreating; the four Porkbun NS records are created by `prepareTransfer` and
must be left alone.

**A wildcard zone breaks the scan.** If step 1 showed a `*.domain` record, do not
run `/dns/import` at all: the scan answers through the wildcard at every
well-known name, imports each answer as an explicit record, and never creates the
wildcard — so every future subdomain silently stops resolving. Create the
records by hand from the step-1 `dig` inventory instead.

Watch `warnings` on every DNS write: a write to a zone that is not (yet)
delegated to Porkbun succeeds and does nothing visible. That warning is normal
during a held transfer and a red flag afterwards.

### 4c. Check the zone is safe

```bash
pb GET '/dns/preflight/'$D'?intent=move-nameservers'
# -> safe, blockers[], warnings[], checks[]
```

Read `blockers` first — `dnssec-active`, `cname-exclusivity`, `spf-duplicate`,
`mx-undeliverable`. `safe` is only true with both lists empty. This runs here,
not in step 1, because it needs the domain in the account with a zone.

### 4d. Prove parity on Porkbun's own nameservers

The whole point of the hold: Porkbun's nameservers can be queried directly
before anything public changes.

```bash
OLD=ns49.domaincontrol.com      # the losing registrar's NS, from step 1
NEW=maceio.ns.porkbun.com       # from prepareTransfer / getTransferSetup
q() { dig +norecurse +noall +answer "$2" "$3" @"$1" | awk '{print $4,$5,$6,$NF}' | sort -u | tr '\n' ' '; }
for t in A AAAA MX TXT CNAME; do
  echo "$t: old=$(q $OLD $t $D)"; echo "$t: new=$(q $NEW $t $D)"
done
```

Compare **authoritative to authoritative**, with `+norecurse` — never against a
recursive resolver. `dig +short A www.$D` through a resolver follows the CNAME
and prints the target's addresses, while `dig +short A www.$D @$NEW` prints only
the CNAME, so every CNAME'd name shows a phantom difference and a correct zone
looks broken. Repeat for each subdomain, and probe the wildcard separately
(`dig +short A zzz-anything.$D @…`) since no explicit-record comparison can
cover it.

The two columns must match (order-insensitive — an RRset is unordered). Do not
release until they do. This is the difference between a zero-gap cutover and
hoping.

## Step 5 — release the transfer

```bash
pb POST /domain/startTransfer/$D '{}'
```

`TRANSFER_ZONE_EMPTY` means the zone has no records and the release would move
the domain to an empty zone — that is the outage the hold exists to prevent.
Fix the zone; only pass `{"force": true}` if the domain genuinely needs no DNS
at Porkbun. Supports `dryRun`.

## Step 6 — follow it

```bash
pb GET /domain/getTransfer/$D      # transfer.status + statusDescription
pb GET /domain/getTransferSetup/$D # progress while still pending
```

`transfer.status` enum (from the OpenAPI spec): `INIT`, `NEW`, `PENDINGAUTH`,
`PENDINGSUBMIT`, `PENDINGTRANSFER`, `PENDINGDNS`, `DONE`, `CANCELED`.
`statusDescription` is the human-readable state and is the field to read out
loud. The website shows finer registry phases than the API status — e.g.
`PENDINGDONENOTICE` ("registry has accepted, delegation can move") — so if the
user is watching the UI and quoting a label the API never returns, that is why.

A status ending `_ERROR:<n>` is terminal; `<n>` is the registry result code
seen in the description. Also terminal-ish and worth recognizing:
`PENDINGSUBMIT_BADAUTHCODE` can mean the *losing registrar* refused to release
rather than a typo (a terminated hosting product will do that), so retrying the
same code is pointless — confirm with them first.

Transfers take days, so do not block on it:

```bash
while :; do s=$(pb GET /domain/getTransfer/$D | python3 -c 'import json,sys;print(json.load(sys.stdin)["transfer"]["status"])'); echo "$s"; [ "$s" = DONE ] && break; sleep 900; done
```

## Step 7 — repoint the nameservers

Two moments are defensible:

- **Right after `PENDINGTRANSFER` → the losing registrar has accepted**, so the
  delegation is the only thing still pointing at them. Moving early shortens
  the window where two zoos disagree.
- **Right after `DONE`**, if you want to keep the old zone live as long as
  possible.

```bash
pb GET  /domain/getNs/$D    # what the registry says today
pb POST /domain/updateNs/$D '{"ns":["curitiba.ns.porkbun.com","fortaleza.ns.porkbun.com","maceio.ns.porkbun.com","salvador.ns.porkbun.com"]}'
```

Nameservers are an **unordered set** — `/domain/getNs` will not echo your order
back and that is not drift. Compare as sets.

## Step 8 — verify the domain, then the service

```bash
dig +short NS $D @1.1.1.1
dig +short NS $D @8.8.8.8        # both must show Porkbun, not the old pair
dig +short A $D; dig +short AAAA $D; dig +short www.$D
curl -sS -o /dev/null -w '%{http_code}\n' https://$D/
```

- The old nameservers should stop answering authoritatively. `dig @old-ns $D`
  returning nothing/timeout is the signal the handover is complete.
- Querying one resolver is not verification. `.de` changed at DENIC and at both
  public resolvers within minutes; other TLDs and other resolvers can lag by
  the old TTL.
- If the site 404s through Traefik's branded error page, the router is not
  matching — that is a routing problem, not DNS. Check
  `docker logs traefik.traefik | grep RequestHost` for the `RouterName` that
  actually served the request.

## Step 9 — repo wiring: certs, and the thing that breaks in 60 days

Once the zone is in the account the Traefik keys belong to, **DNS-01 is
available** and is the right resolver for a domain whose HTTP-01 path might be
blocked by a proxy or a redirect. It failed with `INVALID_DOMAIN` before the
move — that is expected, not a bug.

**Account scoping is the whole precondition, and it can be undone later.** The
keys in `vars/secrets.yml` only see one Porkbun account. If the domain is moved
to another account or subaccount afterwards (done for `bumbleflies.de` the same
day), every `/dns/*` call returns `INVALID_DOMAIN` again and DNS-01 stops
working for it — while the site keeps serving, because the zone stays on the
same nameservers. Check with `GET /domain/get/$D` before promising anyone that
DNS-01 will work, and expect a fresh API key from that account if it must.

```yaml
# <service>/docker-compose.yml
- traefik.http.routers.${SERVICE_NAME}_prod.tls.certresolver=letsencryptdnsresolver
```

Do not trust that the switch works — prove the Traefik key can write to *this*
zone, or the renewal fails silently months later:

```bash
# with the traefik key pair from traefik/docker-compose.yml
pb GET  /domain/get/$D                            # SUCCESS = key sees the domain
pb POST /dns/create/$D '{"name":"_acme-challenge-check","type":"TXT","content":"dns01-probe","ttl":600}'
pb POST /dns/delete/$D/<id>                       # leave the zone as you found it
```

A cert already in `acme.json` keeps serving until renewal, so a broken DNS-01
path shows up **30 days before expiry**, not at deploy time. That probe is the
only cheap early warning.

**The label alone changes nothing, and forcing it is a maintenance-window job.**
Traefik serves any certificate in its local store and only calls a resolver when
nothing matches the SNI; renewal follows the *store* entry's resolver, not the
router's label. So after flipping the label the old HTTP-01 cert keeps being
served and keeps renewing over HTTP-01 — a cosmetic switch. To make it real you
must delete that domain's entries from `acme.json` (back it up first) and restart
Traefik, which immediately serves Traefik's **default self-signed certificate**
for those hostnames until issuance completes. Only do that deliberately, with a
rollback ready:

```bash
# on the host; ACME lives in the traefik certificates volume
sudo cp -a $ACME ${ACME}.bak-$(date +%Y%m%d)   # restore copies over it
docker stop traefik.traefik
# remove entries whose domain.main is the host(s) being moved, then:
docker start traefik.traefik
docker logs -f traefik.traefik | grep dns01:
```

Verified DNS-01 issuance has still failed *after* all four Porkbun nameservers
and the public resolvers serve the challenge TXT: lego sits on "waiting for
record propagation" for its full timeout, and the hostnames stay self-signed.
In that case restore the backup, restart Traefik, revert the label, and diagnose
off live traffic. Two suspects worth checking first: a **wildcard** `*` record in
the zone (it makes every name exist, changing NODATA/CNAME answers during the
propagation check — no other zone in this estate has one), and a stale negative
or delegation cache somewhere in lego's resolution path.

Deploy through the normal ansible path (`--limit servy.lehel.xyz --tags
user.docker.<service>`), see `manage-service`. **The deploy does not pull** —
`servyy.sh` only runs the playbook against the checkout at
`/home/cda/servyy-container` on the host, so `git push`, then `git pull` there,
then deploy. Skipping the pull deploys the old file and reports success.

## Step 10 — lock it down and write it up

```bash
pb GET /domain/get/$D
# status ACTIVE, autoRenew 1, securityLock 0/1, whoisPrivacy, apiAccess 1
```

- **`apiAccess: 1`** — a domain that arrived without API access will refuse
  `/domain/renew` with `API_ACCESS_DISABLED`. Turn it on in the website
  (per-domain toggle) or future renewals have to be hand-driven.
- **Auto-renew on**, registrar lock on (unless the next move is imminent).
- WHOIS privacy is not offered for `.de` and some other ccTLDs; the API will
  just report `whoisPrivacy: 0`.
- Write `history/YYYY-MM-DD_<domain>-transfer.md` per
  `infrastructure-history-tracking`: cost, order/transfer IDs, the exact record
  set, what the verification showed, and what is left undone. Never the auth
  code, never a key.

## Resuming a stuck transfer

State lives at Porkbun, not in your notes:

```bash
pb GET  /domain/getTransferSetup/$D                      # where it is, what to do next
pb POST /domain/updateTransferAuthCode/$D '{"authCode":"…"}'   # repair a bad code in place
pb POST /domain/cancelTransfer/$D '{}'                   # withdraw + refund
```

`updateTransferAuthCode` validates the new code against the registry before
storing it (`INVALID_AUTH_CODE` if wrong), so a bad paste fails immediately
instead of days later. `cancelTransfer` withdraws at the registry, **verifies**
the withdrawal, and only then refunds; if the registry will not confirm, it
returns `TRANSFER_STATE_UNCONFIRMED` and refunds nothing — deliberately.

## Failure modes

| Symptom | Meaning | Do |
|---|---|---|
| `INVALID_DOMAIN` on `/dns/*` | domain not in the account (or key is for another account — the response names it) | finish the transfer first; `/dns/scan` only works once held |
| `INSUFFICIENT_FUNDS` | credit, not the card | `account/topup` for `cost` or check `topUpAvailable` |
| `COST_MISMATCH` | `cost` is not the current price | re-quote: `checkDomain`, or `dryRun` with `cost: 0` |
| `TRANSFER_HOLD_NOT_AVAILABLE` | TLD does not support the hold | resend without `holdForDnsSetup` (nothing was charged) |
| `TRANSFER_ZONE_EMPTY` | release onto an empty zone | import the records first |
| `TRANSFER_NOT_FOUND` | nothing pending for that domain | check `listTransfers`; the record is per-domain |
| `NO_PAYMENT_METHOD` | no saved card | user adds credit on the website |
| `TOPUP_LIMIT_EXCEEDED` | 5/day, 20/month, monthly ceiling | wait, or the user adds credit manually |
| `DOMAIN_NOT_FOUND` | domain not in this account | wrong key/account, or the transfer never landed |

## TLD notes

- **`.de`** — no WHOIS privacy, no 60-day transfer lock, registrant is not part
  of a transfer. Auth code is `AUTHINFO`. A transfer adds a year to the term.
  Punycode: `höfer-architekten.de` → `xn--hfer-architekten-mwb.de`; always use
  the punycode form in API paths and Traefik `Host()` rules.
  **At GoDaddy the `AUTHINFO` only comes from a support ticket** to
  `cctldtransferaway@godaddy.com` (incident number, ~48 h). While that ticket is
  open, WHOIS keeps showing `clientTransferProhibited` — their reply's boilerplate
  about removing "protection" is generic, and the lock did **not** block the
  transfer in practice (2026-11-18). Do not burn the 48 h waiting for the flag to
  clear; submit and read the status.
- **`.uk`** — no API transfer, no `holdForDnsSetup`. Website only.
- **`.in`** — registries refuse registrant contacts on temporary/encrypted email
  providers (`REGISTRANT_EMAIL_NOT_ACCEPTED`, nothing charged).
- **gTLDs** — a 60-day lock on transferring it out again after the move, and the
  losing registrar's "transfer lock" must be off first.

## Checklist

- [ ] `/ping` shows the right account and scope; cost quoted to the user and agreed
- [ ] `checkDomain` shows `inYourAccount: false` and `additional.transfer.price`
- [ ] old zone captured: NS, A, **AAAA**, MX, TXT/SPF/DKIM, CAA, DS
- [ ] DNSSEC is off (or explicitly planned for) — otherwise the domain goes dark
- [ ] balance covers the transfer exactly; top-up confirmed
- [ ] transfer started with `holdForDnsSetup` + one `Idempotency-Key`
- [ ] `getTransferSetup` shows `held: 1`
- [ ] `prepareTransfer`, records imported, missing ones added by hand
- [ ] `/dns/preflight?intent=move-nameservers` has no blockers
- [ ] `dig @porkbun-ns` matches the old zone for every record type
- [ ] `startTransfer` accepted (no `TRANSFER_ZONE_EMPTY`)
- [ ] nameservers repointed, confirmed at the registry and two public resolvers
- [ ] site answers 200 on apex and www, over IPv4 **and** IPv6
- [ ] cert resolver decision made explicitly: either proven DNS-01 in a maintenance
      window (label **and** re-issued cert), or honestly left on HTTP-01
- [ ] deploy pulled the new file on the host (`servyy.sh` does not `git pull`)
- [ ] `autoRenew`, `securityLock`, `apiAccess` all set; history entry written
