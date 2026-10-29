# traefik/ — routing, TLS and the branded error pages

The reverse proxy for every host (servy + codey). Deployed by
`ansible/plays/user.yml` via the `docker_service` role
(`--tags user.docker.traefik`). Design history:
`history/2026-10-06_traefik-branded-error-pages.md` (base),
`history/2026-10-27_traefik-error-page-retry.md` (current behaviour).

## Files

| File | Role |
|---|---|
| `traefik.yaml` | static config: entrypoints (`web`, `websecure`, `metrics`), Docker + file providers, ACME. Compose files render the env it substitutes. |
| `dynamic.yaml` | everything hot-editable: middlewares (`error-pages`, `error-pages-404`, `crawler-ratelimit`, `traefik-auth`, …), catchall routers, `error-pages` service. |
| `docker-compose.yml` | `traefik` + `error-pages` (the only containers in this project). |
| `error-pages.html` | custom error-page template, bind-mounted into `error-pages` as `/error-pages.html` (`HTML_TEMPLATE`). |

## Rules that bite

* **A service is only routable when it opts in.** `providers.docker.exposedByDefault` is
  `false` (since 2026-10-29): a compose service without `traefik.enable=true` gets no
  router at all and answers the catchall 404 while its container looks perfectly healthy.
  Add the label whenever you add a `traefik.http.routers.*` label. The old `true` setting
  published anything that merely *acquired* a router label, and logged a
  `Could not find network named "proxy"` warning per container per config event.
* **Never publish a port on all interfaces.** Docker writes its own FORWARD/nat rules and
  bypasses ufw, so `ports: - "8080:8080"` is internet-reachable the moment the container
  starts. Only this proxy may bind `0.0.0.0` (80/443); everything else publishes to
  `127.0.0.1` or is reached over the docker network. The deploy fails early if you forget
  (`roles/user/files/check_published_ports.py`), and the host `DOCKER-USER` firewall
  (#232) drops anything else arriving on the public interface.

* **Any change to `traefik.yaml`/`dynamic.yaml`/`error-pages.html` needs a
  project recreate, not just a deploy.** The config is a single-file bind
  mount; `git reset --hard` on the target replaces the inode, so the running
  container keeps the old file and `watch: true` never fires:
  `docker compose up -d --force-recreate` in `~/servyy-container/traefik` on
  **each** host that runs Traefik (servy and codey).
* **`error-pages` runs as uid 10001.** Its template must stay world-readable;
  that is why `plays/user.yml` declares `error-pages.html` in
  `world_readable_paths`. Without it the container restart-loops with
  `open /error-pages.html: permission denied` and every branded page silently
  degrades to Traefik's plain status.
* **404 is not intercepted globally.** `error-pages@file` covers `500-503`
  only, so a backend 404 reaches the user as the app rendered it. To brand a
  service whose own 404 is bare, add `error-pages-404@file` to that router's
  `middlewares` label — and deploy traefik *first*, because Traefik drops a
  router that references an unknown middleware.
* **The template is parsed with upstream's v3→v4 shim + `text/template`.**
  Identifiers inside `{{ }}` are rewritten (`host` → `.Host`, `$host` →
  `$.Host`, …), so never name a variable `host`, `code`, `message` or
  `description`, and never use those words inside action string literals.
  HTML comments outside `{{ }}` are safe. Validate any edit with the local
  render gate before deploying (`/tmp/opencode/errgate` as of 2026-10-27: 15
  host/status cases + a virtual-clock test of the poll script).
* `.Host` is only populated when `SHOW_DETAILS=true`, which stays true — the
  template renders no details table, so nothing about the request leaks.
* Catchall routers use `HostRegexp(`.+`)` with priority 1, so any real `Host(...)` rule
  outranks them. Traefik **3.7.7** made a bare `Host(`*`)` a real catch-all (on 3.6 it
  only matched single-label hosts such as `localhost`); we deliberately keep
  `HostRegexp` because it matches identically on 3.6 and 3.7, which keeps a rollback
  free of edge cases.

## Upgrading Traefik

The image tag is pinned in `docker-compose.yml` and **nothing bumps it automatically**
(there is no Renovate runner in this repo despite `renovate.json`), so check
`https://api.github.com/repos/traefik/traefik/releases` by hand and read
`docs/content/migrate/v3.md` on the target branch before changing the tag. Full worked
example: `history/2026-10-29_traefik-3.7-upgrade.md` (3.6.1 → 3.7.16).

1. **Rehearse the config first, off-host.** Run the repo's real `traefik.yaml` +
   `dynamic.yaml` in a throwaway container on the target image with **the docker
   provider removed from the static copy and no `traefik.env`** — otherwise the
   instance discovers the live containers and can place real ACME orders. Compare
   startup warnings and a probe set (catchall page + branded marker, unknown-host
   TLS, encoded-character paths, `CONNECT`) against the running version.
2. **Back up the ACME store**: `traefik-certificates/acme.json` (re-issuable, but LE
   rate limits are real).
3. **Deploy test host first** (`servyy-test.lxd`: `cd ~/servyy-container/traefik &&
   docker compose up -d --force-recreate`), verify, then servy, then codey.
4. **Verify**: image tag, `traefik version`, `docker logs | grep -cE
   'aliasHeadersStrategy|trustForwardHeader'` → 0, the branded-page marker on an
   unknown host, and the **router inventory** before/after (grep the
   `traefik.http.routers.*` labels of every container — the count and the md5 of the
   sorted set must not change).
5. **Config and image move together; a rollback is the whole commit.** Traefik parses
   its *static* configuration strictly: an option the running image does not know is a
   **fatal startup error**, not a warning. `traefik:3.6.1` + a `traefik.yaml` carrying
   `aliasHeadersStrategy` exits with `command traefik error: field not found, node:
   aliasHeadersStrategy` (measured 2026-10-29). So: `git revert` the commit (config and
   tag together), pull, `up -d --force-recreate` — and deploy in the same order, with
   the image **pre-pulled**, because the container sits in watchtower's `prod` scope: new
   config on disk + a recreate that still starts the old image = dead proxy.
   Never mix a behaviour change (header strategy `delete`, `encodedCharacters`
   hardening) into a version bump — a failure then has two possible causes.

Config is a single-file bind mount: `up -d` alone will **not** pick up a changed
`traefik.yaml`/`dynamic.yaml`. Since 3.6.19 an empty `dashboard-auth.htpasswd` unmounts the
dashboard router (404 instead of 401) with only a log line, so `user.yml` post_tasks
slurp the rendered file and **assert it holds exactly one `user:hash` line** on every
deploy of the traefik service — no manual check needed, but do not tag those tasks away.

The dashboard hostname is **per host**: `traefik.lehel.xyz` on servy (the role default
`{{ service_dir }}.{{ domain }}`) and `traefik.code.lehel.xyz` on codey, via
`traefik_service_host` in `ansible/production`. codey also runs with `domain: lehel.xyz`,
and the `*.lehel.xyz` wildcard resolves to servy — without the override both hosts claim
the same dashboard name and codey's copy is simply unreachable.

## Checking a change by hand

```bash
# after deploying + recreating, on the host itself:
curl -sk --resolve nope.invalid:443:127.0.0.1 -H 'Accept: text/html' https://nope.invalid/
curl -sk --resolve search.lehel.xyz:443:127.0.0.1 -H 'Accept: text/html' https://search.lehel.xyz/nope
docker logs --since 5m traefik.traefik 2>&1 | grep -i error
```

A branded page carries `<meta name="x-error-page" content="traefik-error-page-v1">`
and a poll script; an app's own page carries neither. The transient
`middleware "error-pages@file" does not exist` error for `acme-http@internal`
at startup is known and harmless. Access logs are enabled — every request
line has `RouterName`/`ServiceAddr`, which is the quickest way to see which
router actually answered.
