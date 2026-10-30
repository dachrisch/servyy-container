# Baseline security headers at the Traefik entrypoints

**Date:** 2026-10-29 (deployed 2026-10-30)
**Status:** ✅ **Deployed** — merged as PR #244 and rolled out to `servyy-test.lxd` (rehearsal),
`servy.lehel.xyz` and `codey.lehel.xyz` on 2026-10-30. It shipped *after* the Traefik 3.7.16
upgrade (`2026-10-29_traefik-3.7-upgrade.md`) had already landed on both hosts, so it got its own
`--force-recreate` rather than riding along with that rollout.
**Relates to:** `2026-10-29_traefik-3.7-upgrade.md`, `2026-10-29_exposure-triage.md`,
`2026-10-06_traefik-branded-error-pages.md`

## Context

The monthly security audit (`/var/log/security-audit/2026-10-29/`) put **29 of 30 public hostnames at
humble grade D**, and testssl added MEDIUM findings that are header-level rather than TLS-level
(HSTS max-age 30 days on leaguesphere, duplicate `X-Frame-Options`/`X-Content-Type-Options`/
`Referrer-Policy` on firefly, missing HSTS on 22 hosts).

Every one of those 30 hosts is a Traefik router, and Traefik has no global middleware — the only
place that can cover all routers without touching ~30 compose files is the **entrypoint middleware
list**, which the repo already uses for `error-pages@file`.

### Live header survey (2026-10-29, before the change)

| host | XFO | HSTS | nosniff | referrer-policy | Server | X-Powered-By |
|---|---|---|---|---|---|---|
| photoprism | DENY (+CSP `frame-ancestors 'none'`) | – | – | – | – | – |
| portainer | – | – | nosniff | – | – | – |
| energy | SAMEORIGIN | 1y +subDomains | nosniff | no-referrer | – | – |
| finance (firefly) | **deny + SAMEORIGIN** | 1y +subDomains | **nosniff ×2** | **no-referrer + strict-origin-when-cross-origin** | nginx | – |
| leaguesphere.app | DENY | 30d +subDomains | nosniff | strict-origin-when-cross-origin | nginx/1.30.6 | "LeagueSphere and match-day coffee" |
| m.leaguesphere.app (moodle) | sameorigin | – | – | – | nginx/1.30.6 | **PHP/8.3.36** |
| git | – | – | – | – | **nginx/1.14.0 (Ubuntu)** | – |
| search | – | – | nosniff | no-referrer | granian | – |
| pass (vaultwarden) | SAMEORIGIN | – | nosniff | same-origin | Rocket | – |
| monitor (grafana) | deny | – | nosniff | – | – | – |

So the fleet is split: six apps already ship a careful policy, the rest ship one header or none, and
firefly emits duplicates because two layers both set them.

## Decision

One `security-headers@file` middleware in `traefik/dynamic.yaml`, attached **first** (outermost) in
the `web` and `websecure` entrypoint middleware lists in `traefik/traefik.yaml`, so it also covers
the branded error pages.

Set: `Strict-Transport-Security` (1 year, `includeSubDomains`, no `preload`),
`X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, and
`customResponseHeaders` deleting `Server` and `X-Powered-By`.

Nothing here depends on the Traefik version: the `headers` middleware's field set is unchanged between
3.6 and 3.7, and the change is written against the post-3.7 config (each entrypoint now also declares
`aliasHeadersStrategy: keep`, which is orthogonal — that guards *request* header aliasing, this governs
*response* headers).

**The constraint that shaped the list:** Traefik's headers middleware runs after the router and uses
`Header().Set()`, and the docs are explicit that custom headers overwrite identical ones. An
entrypoint middleware is therefore *unconditional* — a backend cannot opt out and cannot keep a
stricter value. So every header in the list had to be **equal-or-stronger than what is live today**:

| header | chosen value | why it is safe |
|---|---|---|
| HSTS | 1y, includeSubDomains | energy/finance already send 1y+subDomains; leaguesphere's 30d is raised |
| nosniff | `nosniff` | every host that sets it already uses this exact value |
| Referrer-Policy | `no-referrer` | strictest practical; the loosest current value is `strict-origin-when-cross-origin`, so nobody is weakened |
| X-Frame-Options | `DENY` | current values are DENY or SAMEORIGIN only, so DENY is stronger-or-equal everywhere, and it collapses firefly's duplicate pair |
| Server / X-Powered-By | removed | pure fingerprinting loss (nginx/1.14.0, PHP/8.3.36, Rocket, granian) |

### Deliberately NOT set globally

* **Content-Security-Policy** — photoprism, portainer, firefly, vaultwarden, energy and pass ship
  longer, stricter policies; a blanket CSP would overwrite them and break apps whose inline
  scripts/`nonce` sources a global policy cannot express. CSP stays per-app.
* **Permissions-Policy** — portainer/firefly/vaultwarden disable 20-30 features each; a short global
  list would silently re-enable the rest for them. (Also a footgun: disabling
  `publickey-credentials-get` would break passkeys on `pass.lehel.xyz`.)
* **COOP / CORP / COEP** — same overwrite problem, plus real breakage for cross-origin subresources.
* **`X-XSS-Protection`** — deprecated, and its legacy filter mode was itself an XSS vector; sending
  no header is the correct value. (`browserXssFilter` left at its `false` default.)
* **`stsPreload`** — submitting to the browser preload list is an irreversible, fleet-wide commitment
  and needs its own decision.

## Consequences

### Positive

- ~25 hosts that sent no HSTS/nosniff/referrer-policy now send all of them, in one place, no
  per-service labels
- `Server`/`X-Powered-By` version disclosure disappears fleet-wide, including PHP/8.3.36 on the
  public Moodle
- firefly's duplicate `X-Frame-Options`/`X-Content-Type-Options`/`Referrer-Policy` collapse to one
  header per name (three testssl MEDIUMs), because `Set` replaces rather than appends
- New services inherit the baseline automatically — no label discipline required

### Negative / Tradeoffs

- **No opt-out.** A backend that wants a different XFO/HSTS/referrer value cannot have one while the
  middleware is on the entrypoint; the fix would be to move it to per-router labels or relax the
  shared value. Accepted because every chosen value is already equal-or-stronger than production.
- **Moodle framing risk.** `m.leaguesphere.app` sends `X-Frame-Options: sameorigin` today and now
  becomes `DENY`. If a Moodle view frames same-origin content, switch the middleware to
  `customFrameOptionsValue: SAMEORIGIN` (documented inline in `dynamic.yaml`).
- **Not hot-reloadable in practice.** `dynamic.yaml` is a single-file bind mount, so a
  `git reset --hard` on the target replaces the inode and `watch: true` never fires — the change needs
  `docker compose up -d --force-recreate` in `~/servyy-container/traefik` on **both** servy and codey
  (the rule in `traefik/AGENTS.md`).
- Header value is a single shared decision: changing e.g. HSTS max-age later means editing the
  middleware, not one service.

## Verification

Done here:

- rebased onto `origin/master` after the 3.7.16 upgrade landed; the middleware block was re-applied to
  the post-3.7 `dynamic.yaml` and the entrypoint lists to the `aliasHeadersStrategy`-bearing
  `traefik.yaml` (the first push of this branch conflicted on both encrypted files, which is why it is
  a force-push)
- `python3 -c "yaml.safe_load(...)"` on both files — parses, `security-headers`/`http` keys land where
  expected, entrypoint middleware lists are `[security-headers@file, error-pages@file]`
- every `headers:` field name checked against the Traefik v3 reference (`stsSeconds`,
  `stsIncludeSubdomains`, `forceSTSHeader`, `contentTypeNosniff`, `referrerPolicy`, `frameDeny`,
  `customResponseHeaders`) and against the entrypoint `http.middlewares` docs — the
  json.schemastore traefik-v3 schema does **not** cover dynamic middleware config, so it could not be
  used
- `yamllint -c .yamllint.yml` on both files: no new findings (the one long line in `dynamic.yaml` is
  the pre-existing `opencode-apikey-code` rule; `traefik.yaml`'s three findings are pre-existing)
- `git-crypt` round-trip: both files are `*.yaml` → encrypted; the staged blobs are ciphertext
  (`\0GITCRYPT\0`) and `git cat-file --filters :<path>` reproduces the edited plaintext byte for byte

NOT done at authoring time (no Traefik runtime was reachable from that container): the
`--force-recreate` and the real `curl -I` per host. Both are done below.

## Deployment (2026-10-30)

1. **PR #244** merged to `master` as `649cf69` (merge commit, all 28 CI checks green).
2. **Rehearsal on `servyy-test.lxd`** — that box runs its own `traefik` compose project outside the
   `testing` inventory, so the rehearsal is the production procedure verbatim: `git pull` +
   `docker compose up -d --force-recreate` in `~/servyy-container/traefik`. Result: `healthy`, zero
   `level=error` lines, headers present on both `web` and `websecure` (HSTS only on TLS, as designed
   by `forceSTSHeader: false`), branded catchall 404 still carrying
   `x-error-page: traefik-error-page-v1`.
3. **Production** — `./servyy.sh --tags "user.docker.repo,user.docker.traefik"` on `servy` and
   `codey` (repo sync **must** be in the tag list: the config only exists on the host after
   `user.docker.repo` runs, and `user.docker.traefik` alone leaves the checkout on the old commit),
   then `docker compose up -d --force-recreate` in `~/servyy-container/traefik` on **each** host, per
   `traefik/AGENTS.md`. Both came back `running healthy` on `traefik:3.7.16` with zero
   `level=error` lines; the dashboard routers still answer `401 WWW-Authenticate: Basic`.

Post-deploy sample (public URLs, through real DNS):

| host | status | HSTS | nosniff | referrer-policy | XFO | Server / X-Powered-By |
|---|---|---|---|---|---|---|
| git.lehel.xyz | 200 | 1y +subDomains | ✅ | no-referrer | DENY | **gone** (was `nginx/1.14.0`) |
| m.leaguesphere.app | 200 | 1y +subDomains | ✅ | no-referrer | DENY | **gone** (was `nginx` + `PHP/8.3.36`) |
| leaguesphere.app | 301 | 1y +subDomains | ✅ | no-referrer | DENY | **gone** |
| photoprism.lehel.xyz | 307 | 1y +subDomains | ✅ | no-referrer | DENY | **gone** |
| finance.lehel.xyz | 302 | 1y +subDomains | ✅ | no-referrer | DENY | **gone** (was `nginx`) |
| pass.lehel.xyz | 200 | 1y +subDomains | ✅ | no-referrer | DENY | **gone** (was `Rocket`) |
| portainer.lehel.xyz | 200 | 1y +subDomains | ✅ | no-referrer | DENY | **gone** |
| search.lehel.xyz | 200 | 1y +subDomains | ✅ | no-referrer | DENY | **gone** (was `granian`) |
| h.code.lehel.xyz (codey) | 200 | 1y +subDomains | ✅ | no-referrer | DENY | **gone** |
| traefik[.code].lehel.xyz | 401 | 1y +subDomains | ✅ | no-referrer | DENY | **gone** |

firefly (`finance.lehel.xyz`) no longer emits the duplicate `X-Frame-Options`,
`X-Content-Type-Options` and `Referrer-Policy` pairs — one of each, as intended.

Still to watch: `m.leaguesphere.app` framing (Moodle moved `SAMEORIGIN` → `DENY`; if a view turns
out to frame same-origin content, switch the middleware to `customFrameOptionsValue: SAMEORIGIN`)
and the next security-audit run for the humble grade movement.

### Post-deploy check (one line per host)

```bash
for h in git.lehel.xyz m.leaguesphere.app photoprism.lehel.xyz finance.lehel.xyz; do
  echo "== $h"; curl -sI "https://$h/" | grep -iE 'strict-transport|x-frame|x-content-type|referrer-policy|^server|powered-by'
done
```

Expect: HSTS `max-age=31536000; includeSubDomains`, `X-Frame-Options: DENY` once per response,
`nosniff`, `Referrer-Policy: no-referrer`, and no `Server`/`X-Powered-By`. Then re-check
`m.leaguesphere.app` in a browser (login + any iframe-bearing activity) and confirm the audit's
humble grades move from D to B on the next run.

## Rollback

Remove `security-headers@file` from the two entrypoint `middlewares` lists in `traefik/traefik.yaml`
(leave the middleware definition in `dynamic.yaml` — an unreferenced middleware is inert), then
`--force-recreate` Traefik on both hosts. Or, for a single header, flip it off inside the middleware
(`frameDeny: false`, `referrerPolicy: ""`, …).
