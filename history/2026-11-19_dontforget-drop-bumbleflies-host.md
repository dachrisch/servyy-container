# dontforget: drop the `dontforget.bumbleflies.de` hostname

**Date:** 2026-11-19
**Branch:** `chore/dontforget-drop-bumbleflies-host`
**Services touched:** `dontforget.web` (recreated, no database involvement)

## Why

`dontforget` carried a second public hostname, `dontforget.bumbleflies.de`, from the
period when Google Calendar refused to subscribe to the `webcal://` feeds published
on `dontforget.lehel.xyz` without ever fetching them. The second name existed to
isolate *domain* reputation from *IP* reputation: `bumbleflies.de` resolves to the
same host through its `*.bumbleflies.de` wildcard, so only the name changed.

Owner decision, 2026-11-19: the app is served on its own domain only. A personal
app answering under a customer's domain was the wrong default to leave in place
once the diagnostic had served its purpose, and the second name cost a separate
HTTP-01 certificate and two extra routers on every deploy.

## What changed

| File | Change |
|---|---|
| `dontforget/docker-compose.yml` | Removed the `-bf` and `-bf-http` routers (7 label keys + 16 lines of rationale). The calendar `-http` redirect router and its `-https-redirect` middleware **stay** — they are what makes `webcal://` work on the main hostname and are unrelated to the second name. A short comment records why the second name existed and that it is gone. |
| `ansible/plays/roles/docker_service/templates/dontforget/.env.j2` | Stopped rendering `BUMBLEFLIES_HOST` and `BUMBLEFLIES_CERTRESOLVER`. `dontforget_bumbleflies_host` was never set by any inventory host, so both were always the template default. |
| `.claude/skills/servyy-branch-deploy/SKILL.md` | The preview-`.env` recipe no longer lists `BUMBLEFLIES_HOST` (a preview instance must not export a variable no service reads). |
| `architecture/landscape.yaml` | `dontforget` domains → `[dontforget.lehel.xyz]`; the hand-written edge tile `60 hostnames` → `59` (the poster's stat tile computes from the map). |

**No DNS change.** `bumbleflies.de` publishes only `bumbleflies.de` and
`*.bumbleflies.de` A/AAAA records (checked against the Porkbun API, `bumbledomain`
account) — `dontforget` never had a record of its own. The name therefore still
resolves to servy; with no router claiming it, it now falls to Traefik's catch-all.

## Deploy

```bash
cd ansible
./servyy.sh --limit servy.lehel.xyz \
  --tags user.repo.clone,user.docker.dontforget \
  -e docker_branch=chore/dontforget-drop-bumbleflies-host
```

`user.repo.clone` is required: the compose file that runs is the host's clone, not
this checkout (the same trap WP-12 hit). `restic-backup-home` re-uploads the app
directory every hour, so the changed compose file is backed up without any extra step.

Measured: ok=172, changed=3, failed=0; `dontforget.web` recreated at **19:52:41Z**,
`running`, healthy. `db-private.mongo` was not touched (`ENV` renders only `.env` +
`web.env`), and no other container on the private tier was recreated.

## Verification

| Check | Result |
|---|---|
| `docker inspect dontforget.web` → routers | only `dontforget` and `dontforget-http`, both `Host(\`dontforget.lehel.xyz\`)` |
| `… \| grep -c '\-bf'` | `0` |
| `docker exec dontforget.web printenv \| grep -ci bumble` | `0` |
| `https://dontforget.lehel.xyz/` | `200` |
| `http://dontforget.lehel.xyz/` | `302 → https://dontforget.lehel.xyz/` (calendar/webcal hop intact; `redirectscheme` is 302 by default, not 301) |
| `https://dontforget.lehel.xyz/today` | `404` from the branded `error-pages-404@file` middleware — the SPA's own "not found" behaviour is unchanged |
| `https://dontforget.bumbleflies.de/` | `502`, Traefik access log `RouterName=catchall-websecure@file`, `ServiceName=error-pages@file` — the name no longer reaches the app. See the finding below for why this is not a `404`. |
| `https://bumbleflies.de/` | `200` (the wildcard host itself is untouched) |
| `grep -rn BUMBLEFLIES_HOST` | only the explanatory comment in `.env.j2` |
| `python3 architecture/render.py --verify` | `ok: 28 services, 4 tiers agree with the repository, 23 with rendered domains`; domain count 60 → 59 |

## Finding (pre-existing, not caused by this change): the catch-all answers 502, not 404

`https://dontforget.bumbleflies.de/` returns `502 Bad Gateway` with the security
headers of the file provider. The access log names `catchall-websecure@file` →
`error-pages@file`, and `traefik.error-pages` is **healthy** but panics per request:

```
http: panic serving …: invalid WriteHeader code 1
  …/internal/httpserver/handlers/error_page.New.func2
```

The panics in its log start **2026-11-10 07:24Z**, nine days before this change, so
every unmatched-but-certified hostname has been getting a 502 since then. The
branded-404 *middleware* (`error-pages-404@file`, used by the apps' own routers) is
unaffected and still answers `404` — measured on `dontforget.lehel.xyz/today` and
`portainer.lehel.xyz/<garbage>`. Scope discipline: not fixed here, it is its own
defect in the catch-all service and needs a look at how the code is handed to
`error-pages` v4. Once this hostname's certificate expires it will fail TLS like any
other unknown name (e.g. `foo.servy.lehel.xyz` → curl exit 60).

**Fixed the same day** in `history/2026-11-19_traefik-catchall-branded-404.md`
(branch `fix/traefik-catchall-branded-404`): the cause was not the panic but a lost
network alias on `traefik.error-pages`, and the catch-all now rewrites every request
to `/404.html` so a numeric path can no longer reach `WriteHeader`. This hostname and
every other unmatched one now render the branded 404 instead of a 502.

## Notes for later

- The certificate for `dontforget.bumbleflies.de` stays in the traefik `acme.json`
  volume until it expires. **Do not hand-edit `acme.json`** to remove it — that file
  holds 46 certificates across two resolvers and a bad edit takes the edge down.
- Calendar feeds that were subscribed under the old name must be re-subscribed on
  `dontforget.lehel.xyz`. Nothing in the app changes.
- servyy-test still runs the previous compose until its next deploy; its `-bf`
  routers pointed at `.invalid` fallbacks there (TLS is off), so behaviour on test
  is unchanged either way.
- Rollback: revert this commit and re-run the same deploy — a recreate, no data.

## Files

- `dontforget/docker-compose.yml`
- `ansible/plays/roles/docker_service/templates/dontforget/.env.j2`
- `.claude/skills/servyy-branch-deploy/SKILL.md`
- `architecture/landscape.yaml`
- `history/2026-11-19_dontforget-drop-bumbleflies-host.md` (this file)
