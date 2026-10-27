# Traefik error pages: keep app 404s, retry + auto-check when the service is down

**Date:** 2026-10-27
**Status:** ✅ **DEPLOYED** — servy + codey restarted, verified live.
Commits: `1f4e875` (feature), `b64c177` (single-file `world_readable_paths`),
`0e36e63` (opt-in survey follow-up).

## Problem

Two things made the branded pages useless in practice:

1. **A healthy service showed a "not found" page with no way back.** The
   entrypoint middleware `error-pages@file` caught status `404`, so a backend
   404 — i.e. the app answering, just without that route — was replaced by the
   branded page. The user was told the service could not find the page and had
   no link to the service itself.
2. **A down service left the user with a dead end.** The branded page had a
   retry anchor only for 5xx and it merely reloaded the same URL, so the user
   had to keep pressing it.

## Solution

### 1. Stop swallowing app 404s; make branding opt-in (`traefik/dynamic.yaml`)

`middlewares.error-pages` now lists `500-503` only. A backend 404 is the
service's own answer and is returned untouched. Services whose own 404 body is
not worth showing can opt in per router with the new
`middlewares.error-pages-404` (`status: ["404"]`), e.g.

```yaml
- traefik.http.routers.${SERVICE_NAME}.middlewares=crawler-ratelimit@file,error-pages-404@file
```

The catchall routers are unchanged: an unrouted/unhealthy host still gets a
branded 404 (that is the page a user sees while a container is unhealthy —
Traefik withdraws its routers in that state, see
`history/2026-10-22_hoefer-permissions-outage.md`).

### 2. Retry + availability poll (`traefik/error-pages.html`)

* The dispatch block moved **above** `<!DOCTYPE html>` so `$name`/`$slogan`/
  `$icon`/`$poll` are known in `<head>`; the requested host is lowercased and
  port-stripped before matching (`bumbleflies.de:8443` used to fall through).
* Every response carries `<meta name="x-error-page" content="traefik-error-page-v1">`.
  That marker is what the poll uses to decide "still the error page" vs "the
  app answered" — an app's own 404 also counts as *back*.
* `#retry` is always rendered. For mapped hosts the static href is
  `https://<host>/`; with JS it is rewritten to `location.href` and a click runs
  an immediate probe.
* Poll script: on hosts with no live route (catchall 404) and on any 5xx, a
  probe of the same URL runs every 20 s; the first response without the marker
  triggers `location.reload()`. It gives up after 20 min and says so. A
  `<noscript>` meta-refresh (30 s) covers JS-less clients — the previous page
  had no fallback at all.
* Wording: a 404 reaching this page now means "this host has no live route", so
  404 and 5xx share the downtime wording and the per-service slogan. The old
  "can't find that page" sentence for known hosts is gone (it was only correct
  while the middleware was stealing app 404s).
* Name map extended to every mapped prod host (bumbleflies, leaguesphere,
  bricksnbytes + office, passwords, search, code/opencode, hub, höfer, finance,
  finance-importer, queen, groceries, energy, jobs, dontforget, photoprism,
  portainer, monitor, git, traefik).

### 3. Opt-in 404 branding, decided per service

Surveyed every mapped prod host by probing its **backend directly** (container
IP + port, `Host:` header, `X-Forwarded-Proto: https`) so the app's own 404 body
was visible while the middleware still intercepted it in prod:

| Host | Own 404 | Decision |
|---|---|---|
| `xn--hfer-architekten-mwb.de`, `www.` | 153 B nginx `404 Not Found` | opt in (`achim-hoefer`, both routers) |
| `portainer.lehel.xyz` | 19 B `404 page not found` | opt in |
| `dontforget.lehel.xyz`, `dontforget.bumbleflies.de` | 90 B JSON `{"message":"Route GET:... not found"}` — even `/today` | opt in (both routers) |
| `www/stage/demo.leaguesphere.app` | designed LeagueSphere 404, 11–17 KB | pass through |
| `pass.lehel.xyz` | Vaultwarden `Page not found!`, 1.8 KB | pass through |
| `search.lehel.xyz` | SearXNG 404 page, 4.7 KB | pass through |
| `finance.lehel.xyz` | Firefly III 404 page | pass through |
| `finance-importer.lehel.xyz` | Laravel 404 page, 6.6 KB | pass through |
| `photoprism.lehel.xyz` | PhotoPrism 404 page | pass through |
| `groceries.lehel.xyz` | none for browsers (SPA answers 200); `/api/*` → 34 B JSON | **rejected** — branding a JSON API 404 would corrupt it for API clients |
| bumbleflies/live/edu/bricksnbytes/jobs/energy/queen | SPA 200 for browser paths; only missing *assets* 404 | left alone (nothing a visitor can hit) |

`code.lehel.xyz` / `h.code.lehel.xyz` were served by the catchall during the
survey (no container on servy at that moment), so they stayed on the catchall
page; `h.code.lehel.xyz` on codey renders DevHub's own 404 as intended.

### 4. Latent restart loop fixed (`ansible/plays/user.yml`, `docker_service`)

`error-pages` runs as uid 10001 and reads the bind-mounted `error-pages.html`.
The deploy checkout leaves tracked files at 0660 (umask 007), so the container
died in a restart loop with
`load HTML template: read template from file: open /error-pages.html: permission
denied` — and every catchall/5xx page silently fell back to Traefik's plain
status. Prod was only working because its file predated the umask change.

* `user.yml`: `world_readable_paths: [error-pages.html]` for the traefik
  `docker_service` role.
* `tasks/permissions.yml`: `state`/`recurse` now follow `item.stat.isdir`
  (`state: directory` failed the whole deploy on a file entry), with the
  converge/verify molecule scenario covering the single-file branch.

## Verification

### Template gate (local, before any deploy)

Re-implements upstream error-pages v4.2.4 exactly — the v3→v4 token shim plus
`text/template` with the upstream function subset (`/tmp/opencode/errgate`):

* 15/15 render cases pass: empty/unmapped host, mapped host, uppercase host,
  `host:port`, punycode, and 404/500/502/503 × mapped/unmapped.
* No leftover `{{ }}`, no `href="<!--`.
* Node behaviour test of the poll script with a virtual clock:
  `still-down-keeps-polling` (10 probes, 0 reloads, then "Automatic checks
  paused") and `service-back-navigates` (one probe → one reload).

### servyy-test.lxd (integration)

* App 404 passthrough: `h.code.lehel.xyz/...` → 10712 B DevHub Next.js 404, no
  marker, `RouterName=devhub@docker`; `/` still 200.
* Catchall mapped host (`pass.lehel.xyz`) → branded page, "Check Passwords
  again", poll present. Unknown host → generic + "Check again", no poll.
* **5xx path** with a throwaway container whose Traefik port pointed at a closed
  port: `502`, `<h3>…502 · Passwords</h3>`, retry link, poll present,
  `RouterName=errgate5xx@docker`. **This proves the errors middleware DOES
  forward the original Host** — correcting the claim in
  `history/2026-10-06_traefik-branded-error-pages.md`.
* **Opt-in 404 A/B** with a throwaway backend (its own Traefik API on :8080,
  which answers `404 page not found`):
  - without the label → `404`, 19 B `404 page not found` (passthrough)
  - with `error-pages-404@file` → `404`, branded, "· Passwords", poll
  - a `200` path → untouched
* **Browser end-to-end**: real rendered page served on `127.0.0.1:8099` behind
  a server that switches to an app document after 15 s. Chrome showed
  "ERROR 502 · PASSWORDS", "Checking again in 16s…", then navigated on its own
  to the app page without any user action (server log: probe at 21.0 s → reload
  at 21.1 s).

### Production rollout

1. `ansible-playbook servyy.yml -i production --tags user.docker.repo,user.docker.traefik`
   — repo pulled to `0e36e63` on both hosts, env rendered.
   (`--skip-tags opencode.vaultwarden` avoids the interactive `bw unlock` task
   in `plays/opencode_authgate.yml`, which fails without a TTY; it is unrelated
   to traefik.)
2. `world_readable_paths` applied → `error-pages.html` `0664` on both hosts.
3. `docker compose up -d --force-recreate` in `~/servyy-container/traefik` on
   **servy and codey** (bind-mounted config = new inode, so `up` alone is not
   enough — same caveat as the 2026-10-06 entry).
4. Labels deployed for `portainer` + `dontforget`.

Live results (servy unless noted):

| Check | Result |
|---|---|
| unknown host `:443` | 404 branded, "Check again", no poll |
| `code.lehel.xyz`, `h.code.lehel.xyz`, `monitor.lehel.xyz` (no live route) | 404 branded + name + poll |
| `pass.lehel.xyz`, `search.lehel.xyz`, `finance.lehel.xyz`, `photoprism.lehel.xyz`, `www/demo.leaguesphere.app` | their **own** 404 (no marker) |
| `portainer.lehel.xyz`, `dontforget.lehel.xyz`, `dontforget.bumbleflies.de` | branded 404 with name + poll; `/` still 200 |
| `h.code.lehel.xyz` on codey | DevHub's own 404 |
| all 21 mapped hosts `/` | unchanged codes (200/301/302/303/307) |
| containers | all healthy, no restarts |
| Traefik log since restart | only the known transient `middleware "error-pages@file" does not exist` for `acme-http@internal` at startup |

## Findings worth keeping

1. **The error-pages container always speaks HTML on the errors path.**
   Traefik's errors middleware builds a fresh request and drops the original
   `Accept`, so the 5xx page is HTML even for `curl` without
   `Accept: text/html` (the catchall path still negotiates and returns the
   219-byte plain-text template).
2. **Order matters when deploying.** A router that references a middleware name
   Traefik does not know is dropped entirely, so traefik must be deployed and
   restarted *before* any service that carries `error-pages-404@file`.
3. `SEND_SAME_HTTP_CODE=true` makes the error-pages app itself answer `200` for
   unknown paths, so it cannot be used as a stand-in "app with a real 404" in
   tests — use a second Traefik (API on `:8080`) or an nginx instead.
4. The comment markers used for conditional HTML (`<!-- {{ if … }} -->`) leave
   empty `<!-- -->` pairs in the output. Harmless, kept for readability.

## Rollback

`git revert` `0e36e63`/`b64c177`/`1f4e875`, redeploy
`--tags user.docker.repo,user.docker.traefik,user.docker.portainer,user.docker.dontforget`,
then `docker compose up -d --force-recreate` in `traefik/` on both hosts.
Reverting only `1f4e875` restores the swallowing behaviour for 404s (and drops
`error-pages-404@file`, which the portainer/dontforget labels reference — their
routers would then be dropped, so revert those labels too).
