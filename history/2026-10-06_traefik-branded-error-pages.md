# Branded Traefik error pages (404 + 500-503)

## Problem
Requests to non-existent Traefik routes (unknown `Host`) got Traefik's plain
`404 page not found` (19 bytes, no branding). Failed backends (502/503) were
equally bare. Ask: a better error page than the default 404.

## Solution
Off-the-shelf `ghcr.io/tarampampam/error-pages:4.2.4` (ghost theme), hosted
as a new container inside the existing traefik compose project (no new
Ansible role, no `user.yml` change):

- `traefik/docker-compose.yml`: new `error-pages` service (port 8080,
  `traefik.enable=false`, `SEND_SAME_HTTP_CODE=true` so direct-backend hits
  keep the right status, `SHOW_DETAILS=false`, JSON warn-level logs for Loki).
- `traefik/dynamic.yaml`: `middlewares.error-pages` (`errors`, status
  `404,500-503`, query `/{status}.html` — 401/403/422 deliberately excluded
  so app auth flows keep their own responses); `routers.catchall-web` /
  `catchall-websecure` (`HostRegexp(`.+`)`, priority 1; websecure variant has
  bare `tls: {}` with NO certResolver so unknown hosts get the default cert
  and never trigger LE issuance); `services.error-pages`
  (`http://error-pages:8080` via proxy-network Docker DNS).
- `traefik/traefik.yaml`: `error-pages@file` prepended to `web` + `websecure`
  entrypoints, so every router gets coverage without editing ~15 service
  compose files. `metrics` entrypoint left bare (raw Prometheus scrapes).

Commits (master, pushed): `a7e0825` (feature), `94f405b` (catchall rule fix).

## Verification (servyy-test.lxd, all passing)
Deploy: `./servyy-test.sh --tags user.docker.traefik,user.docker.repo
-e '{"services_enabled":{"traefik":true},"git_servyy_reachable":"no"}'`
(the `-e` override is needed because traefik is not in the testing
inventory's `services_enabled`; nothing in the repo was changed for this).

- Unknown host `:80` → 404 + ghost page (`<title>404: Not Found</title>`,
  61 KB), `RouterName: catchall-web@file` in access log.
- Unknown host `:443` → 404 + ghost page via `catchall-websecure@file`
  (default cert, `-k` needed as expected without wildcard cert).
- Known host + missing asset (backend 404) → 404 status preserved, ghost
  body swapped in by entrypoint middleware. Known host `/` → 200, app page
  byte-identical behavior (SPA fallback still 200s, correctly untouched).
- Direct `http://error-pages:8080/502.html` → status 502 + `502: Bad
  Gateway`; `/500.html` → 500.
- Logs: zero `error-pages`-related errors (the predicted entrypoint
  startup-race quirk did not manifest); remaining ERRs are pre-existing
  test-host noise (queen empty `Host(``)`, missing `opencode@docker`,
  ACME attempts for `.lxd` names).
- Static checks: `ansible-playbook servyy.yml --syntax-check -i testing`
  passes; yamllint shows zero new findings vs pre-change baseline
  (remaining warnings/errors are pre-existing).

## Operational findings (important for rollout)
1. **Restart required, not just `compose up`.** `docker compose up`
   (`state: present`) does not recreate containers when bind-mounted config
   content changes, and the file provider (`watch: true`) did NOT pick up a
   git-checkout file replacement within minutes (likely inode replacement
   defeats fsnotify on the single-file mount). After ANY change to
   `traefik/*.yaml`, restart the project:
   `ansible <host> -i production -m community.docker.docker_compose_v2
   -a "project_src=<remote_dir>/traefik state=restarted"`.
   `dynamic.yaml`-only edits normally hot-reload, but restart is the reliable
   path — this matches the existing `restart traefik` handler precedent in
   the testing role.
2. **Bare `Host(`*`)` does not match on Traefik 3.6** (silently — no error,
   just never fires). `HostRegexp(`.+`)` with priority 1 is the working
   catchall pattern. Fixed in `94f405b` after live testing proved it.
3. Test host now runs traefik+error-pages (previously absent there) — left
   running intentionally; stop via compose if unwanted. Pre-existing
   test-host ACME spam for `.lxd` names is unrelated to this change.

## Follow-up fix: dead homepage link (`f909a70`, verified on test)
The ghost theme's "Go to homepage" defaulted to `/`, which loops into
another 404 on unknown hosts (servy has no apex service, so no lehel URL
works as a universal homepage). Fix: `HOMEPAGE_URL=https://bumbleflies.de`
(org site, alive independent of serving host) + `ADD_LINK` service
directory (Search/Git/Code/Photos/Passwords, all absolute). Verified
rendered hrefs + screenshot on servyy-test. Rollout note: env change
recreates the error-pages container via compose automatically — no
Traefik restart needed for this one.
Superseded same day (`b1e8e82`): service directory links removed again —
internal services stay unlisted per owner request. Final state: only
"Go to homepage" → https://bumbleflies.de. Verified rendered single href
+ screenshot on servyy-test.
Superseded same day (`4e18e58`): generic homepage link hidden via empty
`HOMEPAGE_URL` (verified honored-empty in upstream flag parsing); two
custom links instead — "Buzz back home" → bumbleflies.de and "Fly with us
on GitHub" → github.com/bumbleflies (org URL confirmed from bumbleflies.de
footer). Verified rendered hrefs + screenshot on servyy-test. Note: custom
labels carry the theme's auto-translate flag, so DE browsers will translate
the wordplay (meaning survives).

## Per-service pages (`bf9a20a`, `cc23a2c`, `7e79053`, verified on test)
New `traefik/error-pages.html`: fork of the ghost theme with a host-based
dispatch chain (bumbleflies → leaguesphere → bricksnbytes → password →
search → opencode → hub, in that priority order; everything else falls back
to generic ghost). Each known service gets its own inline SVG illustration
(zero external dependencies), slogan, and name in the heading. Wording is
status-aware: 5xx → "{Name} is down"-style + slogan + "Try {Name} again"
(same-host retry link, 5xx only); 404 on a known host → "{Name} can't find
that page" (service is up, never claim downtime); unknown host → generic.
Wired via read-only volume mount + `HTML_TEMPLATE` env (no new containers,
no Traefik changes; compose auto-recreates on deploy).

Hard-won findings:
- Upstream parses templates with text/template + a naive v3-token shim
  that rewrites bare words ANYWHERE (even `$host` → `$.Host`, breaking
  assignment). Fix: `$reqHost` + case-normalized `$h` compare. A local Go
  harness replicating the exact shim + engine now gates the template and
  reproduces upstream errors byte-for-byte (it caught this pre-deploy).
- `.Host` is only populated when showDetails=true (upstream handler code),
  so `SHOW_DETAILS=true` is required for dispatch — but our fork renders
  NO details table, so nothing (client IP, headers) leaks into the page.
- Host matching is case-normalized (`lower`); Try-again href is escaped and
  only renders for exact-match hosts (injection-proof by construction).
- 5xx test without stopping backends: the error container renders
  `/{code}.html` honoring any Host header — full 7-services × statuses
  matrix verified live via direct hits (slogans, icons, Try links, XSS
  probe with malicious Host, empty-host and unmapped-host fallbacks, zero
  template leakage). End-to-end also proven through Traefik: catchall with
  mapped host renders the service branch; middleware 502 path renders
  branded pages with status preserved (one controlled ~2 min stop of
  bumbleflies.www on test for the true 502 path; backend restored healthy).
- Env/volume-only changes need `compose ... recreate=always` to take
  effect (content changes are invisible to plain `up`) — same restart
  caveat as the base change.

## Production rollout — DONE (servy + codey, verified live)
Deploy: `./servyy.sh --tags user.docker.traefik,user.docker.repo` (failed=0
both hosts), then project restart on both hosts (static entrypoint
middlewares only load on start — same caveat as test). Verified: unknown
hosts on :80/:443 → branded 404 on both hosts; search.lehel.xyz → 200;
code.lehel.xyz → 401 (authgate normal, untouched — 401 not in middleware
scope); middleware 404s → branded pages with status preserved; containers
healthy; checkouts current.

Correction to the design assumption: the errors-middleware path does NOT
forward the original Host (verified live: known-host backend 404 rendered
the generic variant despite mapped host; consistent with upstream v1 code
copying headers but not Host). Per-service dispatch therefore fires on the
catchall-direct path only (original Host preserved through normal routing).
Down-service (middleware) pages render generic-but-branded. True
per-service DOWN pages would need an identity header plumbed per router
(headers middleware setting X-Service-Name + template branching on
.ServiceName) — i.e. label edits across services. Parked unless requested.

Known upstream issue observed on prod: error-pages v4.2.4 panics
(per-connection, recovered, process stays healthy) with `invalid
WriteHeader code 1` when the catchall routes scanner-style numeric paths
(e.g. `/1.php` on unknown hosts → parsed as status 1, below valid HTTP
range). Impact: log spam + reset conn for the scanner; legit pages
unaffected (full correct bodies delivered in the same window). Middleware
path can never trigger it (status list is all ≥100). Options: live with it
+ report upstream, or exclude numeric paths in the catchall rule (needs
rule-syntax verification on test first).
Rollback if ever needed: `git revert` the traefik commits, redeploy the
same tags on both hosts, restart the traefik projects.

## Follow-ups (not done, optional)
- Wildcard cert (`*.lehel.xyz`) so unknown HTTPS hosts skip the cert
  warning before the branded 404.
- Consider a `restart traefik` notify/handler for mounted-config changes
  (currently a manual step — pre-existing gap, not introduced here).
- Per-service DOWN pages via identity header (see correction above).
- Upstream report for the WriteHeader(1) panic on numeric paths.
