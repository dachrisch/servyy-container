# höfer-architekten.de — registrar transfer GoDaddy → Porkbun

**Date:** 2026-10-22
**Domain:** `höfer-architekten.de` (`xn--hfer-architekten-mwb.de`), TLD `.de`
**Related service:** `achim-hoefer` (static site on `servy.lehel.xyz`)

## Summary

Moved the domain from GoDaddy to Porkbun — registrar, DNS delegation and TLS
challenge method — and fixed a two-day-old site outage that was discovered
during the move (it was unrelated to the transfer).

- Registrar: GoDaddy → Porkbun (`dachrisch` account)
- Nameservers: `ns51/ns52.domaincontrol.com` → `curitiba/fortaleza/maceio/salvador.ns.porkbun.com`
- DNS zone: recreated at Porkbun, byte-identical records, imported and verified
  *before* the delegation changed, so there was no resolution gap
- Cert resolver: `_prod` router switched from `letsencrypthttpresolver` to
  `letsencryptdnsresolver` (DNS-01 is possible now that the zone is in the same
  Porkbun account the Traefik keys belong to)

## Reason

GoDaddy terminated the hosting product while the auth code was being issued and
the domain was expiring the same day. Transferring was cheaper and simpler than
staying: the domain already served content from `servy` and the rest of the
estate (including `lehel.xyz`) is managed at Porkbun through the API.

Transfer cost: **$5.10** (Porkbun, adds one year). GoDaddy was paid nothing.

## Detailed Changes

### 1. Transfer

- Auth code issued by GoDaddy (registry `AUTHINFO`, valid at DENIC; not recorded
  here — it is a bearer credential and was void once the transfer completed).
- Submitted through the Porkbun API with `authCode`, `cost: 510`,
  `holdForDnsSetup: true` and an idempotency key. `holdForDnsSetup` parks the
  transfer at `PENDINGDNS` so the zone can be built before the domain moves —
  the no-downtime path.
- `POST /domain/prepareTransfer` → zone created.
- `POST /dns/import` → records loaded, then `POST /domain/startTransfer` released it.
- Transfer order `12228589`, transfer id `907014`, status `DONE`.

### 2. DNS zone at Porkbun

Captured from the live GoDaddy nameservers with `/dns/scan` (a GoDaddy API
token was not available; the public zone was also checked directly with `dig`).
The zone is small and has **no mail**: no MX, no SPF/DKIM/DMARC, no CAA, no DNSSEC.

| name | type | content |
|---|---|---|
| `@` | A | `49.13.6.173` |
| `@` | AAAA | `2a01:4f8:c013:f6f4::1` |
| `www` | CNAME | `xn--hfer-architekten-mwb.de` |

The AAAA record was caught only by the scan — a plain `dig A` misses it, and
losing it would have silently dropped the IPv6 path to the site.

### 3. Nameservers

`POST /domain/updateNs` to the four Porkbun nameservers immediately after the
transfer showed `PENDINGDONENOTICE` (registry-complete), so GoDaddy stopped
being authoritative as early as possible. DENIC delegation and public resolvers
confirmed the change within minutes.

### 4. Cert resolver

`achim-hoefer/docker-compose.yml`, `_prod` router:

```diff
-traefik.http.routers.${SERVICE_NAME}_prod.tls.certresolver=letsencrypthttpresolver
+traefik.http.routers.${SERVICE_NAME}_prod.tls.certresolver=letsencryptdnsresolver
```

The domain is now inside the Porkbun account the Traefik API keys belong to, so
DNS-01 works. Before the move it failed with `INVALID_DOMAIN` — same reason
noted in `ansible/production` for `bumbleflies.de`.

## Outage found in passing (not caused by the transfer)

`https://höfer-architekten.de/` returned Traefik's branded **404** from
`catchall-websecure@file` — i.e. no router matched, requests never reached
nginx. First occurrence in the access log: `2026-10-20T15:47:20Z`, 785 requests,
about two days before this work started.

Two independent causes:

1. **Routers not bound to `websecure`.** The container's three routers existed
   in Traefik but were attached to the wrong entrypoint, so nothing matched the
   domain. `docker compose up -d --force-recreate` (via the ansible deploy)
   made Traefik rebuild its configuration; the per-entrypoint router
   `websecure-achim-hoefer_prod@docker` appeared and traffic flowed again.
2. **nginx `403` on its own healthcheck.** `serve/*.html` were `660 cda:docker`
   — unreadable by the nginx worker (uid 101) — so the container had failed its
   healthcheck 135 consecutive times. `chmod -R a+rX serve/` fixed it;
   container now reports `healthy`.

No file content was modified, only permissions.

## Verification

```
https://höfer-architekten.de/                    200  25984 bytes  <title>Höfer Architekten - Website</title>
https://www.höfer-architekten.de/                200
https://höfer-architekten.de/impressum.html      200
router    websecure-achim-hoefer_prod@docker → www-achim-hoefer@docker
container achim-hoefer.www                       Up (healthy)
```

- Porkbun: transfer `DONE`, domain `ACTIVE`, expires `2027-10-22`, auto-renew on,
  lock off, WHOIS privacy off (not offered for `.de`), balance `$0.00`.
- DENIC RDAP and `1.1.1.1` / `8.8.8.8` both answer with the Porkbun nameservers.
- `A` + `AAAA` + `www CNAME` resolve identically before and after the cutover.
- Porkbun zone was queried directly on `maceio`/`fortaleza` before release and
  returned the same answers as GoDaddy, which is what makes this a zero-gap
  cutover rather than a hoped-for one.

## Impact Assessment

- The site never stopped resolving; the 404s were the pre-existing outage.
- `.de` transfers carry no 60-day ICANN lock and need no registrant change, so
  nothing else about the domain moved.
- Expiry moved from 2026-10-22 to 2027-10-22 (a year was bought by the transfer,
  not lost from the remaining term).
- Any future DNS edits for this domain must go through the Porkbun API/UI — the
  GoDaddy zone is gone from the path.

## Rollback Procedure

Not practically reversible: an outbound `.de` transfer back to GoDaddy needs a
fresh `AUTHINFO` from Porkbun and another year's fee. If DNS has to move again,
the zone above is the complete content to recreate.

For the cert-resolver change alone: revert the one label to
`letsencrypthttpresolver` and redeploy. Existing certificates stay valid until
renewal, so there is no urgency either way.

## Next Steps

- [ ] Rotate the Traefik dashboard basic-auth credential — it was found to be
      weak during this investigation. Needs a new hash in
      `traefik/docker-compose.yml` plus a redeploy.
- [ ] Reconcile the site's deploy path: the container on `servy` was recreated
      on 2026-10-20 with no corresponding commit, which is why the site could
      sit broken for two days while UptimeRobot kept getting HTTP responses
      from the error page.
- [ ] Point the uptime check at content, not just reachability — the error page
      returned a well-formed response the whole time.
