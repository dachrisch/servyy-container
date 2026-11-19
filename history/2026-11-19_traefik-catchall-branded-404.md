# Traefik catch-all: branded 404s again, and no more `WriteHeader` panic

**Date:** 2026-11-19
**Branch:** `fix/traefik-catchall-branded-404`
**Services touched:** `traefik.traefik` (recreated, ~4 s of edge downtime),
`traefik.error-pages` (recreated, seconds), `traefik/dynamic.yaml`

Two defects, found while removing the `dontforget.bumbleflies.de` hostname. The
second one was invisible because the first one hid it.

## Defect 1 — the catch-all backend had been unreachable since 2026-11-11

`error-pages` lost its network alias during the `proxy` IPv6 cutover
(`history/2026-11-11_proxy-network-ipv6.md`, cutover step 4: "any container that keeps
a stale network-ID reference is fixed with `docker network connect proxy <name>`").
A plain `docker network connect` attaches the container **without aliases**, so
`http://error-pages:8080` — the `error-pages@file` service in `dynamic.yaml` — stopped
resolving for Traefik.

| Evidence (measured) | |
|---|---|
| `proxy` network created | 2026-11-10T22:22Z |
| `traefik.error-pages` created | 2026-11-01 (predates the network) |
| its aliases on `proxy` | `[]` — every other container carries `[container_name, service_name]` |
| from a container on `proxy` | `curl http://error-pages:8080/404` → *Could not resolve host* |
| same container, by name | `curl http://traefik.error-pages:8080/404` → 404 |
| Traefik access log | `RouterName=catchall-web@file`, `ServiceURL=http://error-pages:8080`, status **502** |

Impact: every unmatched hostname got Traefik's bare 502, and **every real 5xx from every
app** got the same bare 502 instead of the branded page (the entrypoint `error-pages@file`
errors middleware points at the same service). Nobody noticed because the image's
healthcheck is `httpcheck --port-env HTTP_PORT http://127.0.0.1:8080/healthz` — it probes
loopback *inside* the container, so the container reports `healthy` while being
unreachable on the network.

Fix: recreate the container from its own compose project, so compose creates the network
endpoint with the right aliases:

```bash
cd /home/cda/servyy-container/traefik
docker compose -p traefik up -d --force-recreate --no-deps error-pages
# aliases → ['traefik.error-pages', 'error-pages']
```

## Defect 2 — a numeric path below 100 panics `error-pages` (502 from the edge)

`error-pages` derives the rendered code from the **first path segment** (and from
`X-Code`), accepts any value `> 0 && <= 999`, and with `SEND_SAME_HTTP_CODE=true` mirrors
it via `w.WriteHeader(int(code))`. `net/http` only accepts 100–999, so any unmatched-host
request to `/1`, `/13`, `/99` panicked the handler:

```
http: panic serving …: invalid WriteHeader code 13
  …/handlers/error_page/handler.go:137
```

The panics in the log stopped at **2026-11-10 20:39Z** — precisely when defect 1 made the
requests stop arriving. The catch-all servers see scanner traffic daily (`/wp-login.php`,
`/robots.txt`, `/<number>`), so this was reachable, not theoretical.

Not fixed by narrowing the parser: upstream's own test calls `/1` a *valid lower bound*
(`handler_test.go`, `"code 1 is valid lower bound"`), and codes 1–99 render fine when
`SEND_SAME_HTTP_CODE=false`. Fix at the edge instead: never let the client's path reach
the backend.

```yaml
catchall-404:
  replacePath:
    path: /404.html
```
attached to both `catchall-web` and `catchall-websecure`. Every unmatched host now reaches
`error-pages` as `/404.html`, so the rendered code is a constant; no client-controlled
number can reach `WriteHeader`. The two `errors` middlewares (`query: /{status}.html`,
statuses 404 and 500-503) are untouched.

Reported upstream as **tarampampam/error-pages#435**
(https://github.com/tarampampam/error-pages/issues/435) — no PR; the suggested one-line
guard is in the issue. Not fixed in 4.2.7 or on `master`.

## Deploy

```bash
cd ansible
./servyy.sh --limit servy.lehel.xyz --tags user.repo.clone \
  -e docker_branch=fix/traefik-catchall-branded-404
```

**The clone deploy alone was a silent no-op** — this is the trap worth remembering:

- `dynamic.yaml` is bind-mounted as a **single file**; Ansible's `copy` is an atomic
  rename, so the running container keeps reading the **old inode**. `watch: true` never
  fires, and the file inside the container had `grep -c catchall-404` → `0` while the host
  file had it. Verified by comparing inodes (`663170` on the host vs `656143` in the
  container).
- `docker_service` does not recreate a container when only a bind-mounted file's content
  changed (compose compares config, not file contents), so `--tags user.docker.traefik`
  would not have helped either.

So the change goes live with a traefik recreate — a few seconds of edge downtime:

```bash
cd /home/cda/servyy-container/traefik
docker compose -p traefik up -d --force-recreate --no-deps reverse-proxy
```

Measured: `traefik.traefik` started 20:54:37Z, `healthy`; all four sampled sites answered
correctly within ~12 s (`bumbleflies.de` 200, `dontforget.lehel.xyz` 200, `offd.de` 200,
`leaguesphere.app` 301). The comment in `dynamic.yaml` that claimed "HOT-editable … reloads
in ~3 s" now carries the inode caveat and this check, so the next agent does not repeat it.

## Verification (all measured after the recreate)

| Check | Before | After |
|---|---|---|
| `curl -H 'Host: probe.invalid' http://127.0.0.1/` | 502, 11 B | **404, 63 668 B** branded |
| same with `/13`, `/1`, `/99`, `/wp-login.php` | 502 | **404, branded, identical body** |
| `--resolve probe.invalid:443:127.0.0.1 https://probe.invalid/13` | 502 | **404** (websecure catch-all + default cert) |
| `docker logs traefik.error-pages \| grep -c 'panic serving'` | 1 per numeric request | **0** |
| `https://dontforget.bumbleflies.de/` | 502 | **404** branded (`<title>404: Not Found</title>`) |
| `https://dontforget.lehel.xyz/today` | 404 | 404 — per-app `error-pages-404@file` untouched |
| `http://error-pages:8080/503.html` from a `proxy` container | resolve failure | **503** — the 5xx branding path works again |
| aliases on `traefik.error-pages` | `[]` | `[traefik.error-pages, error-pages]` |
| sampled public sites | 200/301 | unchanged |

End-to-end proof that the 5xx errors middleware works again: while the middleware was live
but defect 1 was not yet fixed, the panicking `/13` request produced a **branded** 502 page
(66 kB) instead of Traefik's 11-byte default — the errors middleware now reaches
`error-pages` and renders `/502.html`. `/503.html` answers 503 directly.

## Rollback

Revert the `dynamic.yaml` hunk and recreate traefik (same command as above). The container
recreate of `error-pages` needs no rollback — restoring the alias is the fix.

## Notes / follow-ups

- **`docker network connect` during any future network rebuild must pass `--alias`**, or the
  same silent unreachability returns. The IPv6 cutover entry keeps its text (it is a record
  of what was done); this entry is the correction.
- **A probe would have caught this in minutes.** Nothing watches the catch-all: the
  container healthcheck structurally cannot (loopback). Suggested next step, its own small
  branch: a `system_probe` metric (`curl -H 'Host: probe.invalid' http://127.0.0.1/`, expect
  404) plus an alert when it is not 404 — the same shape as the existing pushgateway
  thresholds.
- Upstream is not fixed: if `error-pages` ever moves to a release that clamps the status, the
  `replacePath` middleware can go, but it costs nothing to keep.
- The `dontforget.bumbleflies.de` removal (`chore/dontforget-drop-bumbleflies-host`) now
  lands on a branded 404 instead of the 502 recorded in its own history entry.

## Files

- `traefik/dynamic.yaml`
- `history/2026-11-19_traefik-catchall-branded-404.md` (this file)
