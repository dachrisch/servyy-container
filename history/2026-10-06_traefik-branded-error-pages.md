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

## Production rollout (needs explicit approval, NOT done)
1. Code is on master already (`94f405b`); no merge needed.
2. `cd ansible && ./servyy.sh --tags user.docker.traefik,user.docker.repo`
   (refreshes the remote checkout, recreates/starts error-pages).
3. Restart the traefik project on each host running it (servy + codey —
   verify via inventory) with the ad-hoc restart command above
   (static entrypoint middlewares only load on start).
4. Verify: unknown host → branded 404 (with correct status); known hosts →
   200; `docker logs traefik.traefik` clean; watch http-errors dashboard
   (catchall appears as new `error-pages@file` service label).
5. Rollback: `git revert 94f405b a7e0825`, redeploy same tags, restart.

## Follow-ups (not done, optional)
- Wildcard cert (`*.lehel.xyz`) so unknown HTTPS hosts skip the cert
  warning before the branded 404.
- Consider a `restart traefik` notify/handler for mounted-config changes
  (currently a manual step — pre-existing gap, not introduced here).
- Live 502 test (stop a backend briefly) — skipped on purpose; the 502
  render path is proven via direct `/502.html` + identical middleware code
  path as the proven 404 case.
