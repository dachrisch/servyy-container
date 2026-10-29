# 2026-10-29 — Exposure guards: nothing internal public, now or later

## Why

Before making the compose files reviewable (they were git-crypt ciphertext, which is
why Renovate cannot bump image tags inside them — `traefik:3.6.1` sat through ~24 patch
releases unnoticed), the precondition was: **prove nothing internal is reachable from
the internet today, and put guards in place so it cannot become reachable later.** Both
repos are **public**.

Trigger: the follow-up work on the Traefik upgrade (`history/2026-10-29_traefik-3.7-upgrade.md`)
raised that decision; this entry is the audit and the guards.

## Audit — what is reachable today (2026-10-29)

| Check | Result |
|---|---|
| `docker ps` published ports | only `traefik.traefik` binds `0.0.0.0:80/443`; everything else is `127.0.0.1`-bound (stage mysql `33062`, db-tunnels `33063/33064`, pushgateway-bridge `9091`) |
| Host listeners (`ss -tlnp`) | `:80`, `:443` (docker-proxy), `:25` (postfix) — nothing else on all interfaces |
| **Port scan from outside** | **22, 80, 443 only** on both hosts; 25, 3000, 3306, 3100, 8082, 9090, 9091, 2342 all refused |
| `*.servy.lehel.xyz` style names | DNS wildcard is **single-level** (`*.lehel.xyz` → servy), so `monitor.servy.lehel.xyz`, `traefik.servy.lehel.xyz`, `pass.servy.lehel.xyz` do **not resolve publicly** — the `*_local_qualified` routers are genuinely internal |
| Monitor backends | loki / prometheus / pushgateway / cadvisor sit on the un-published `metrics` entrypoint or bare internal names — unreachable |
| Public hostnames | every one is an intended-public app behind its own auth (401/302/200 as appropriate) |

Two findings worth keeping:

* `https://monitor.lehel.xyz/metrics` answered **200** with Grafana's Prometheus metrics
  (Go runtime, Grafana internals). Grafana serves `/metrics` unauthenticated by design and
  we do not scrape Grafana, so this was pure exposure.
* `monitor/docker-compose.yml` declared `ports: - 9100:9100` (node-exporter) and
  `ports: - "8080:8080"` (cadvisor). The *running* containers had no published ports (an
  older creation), so nothing was reachable yet — but the **next** recreate would have put
  both on `0.0.0.0`. That is exactly the "later" case this task exists for.

## Blocking finding before any unencryption

`photoprism/docker-compose.yml` carried **four inline literals** — the PhotoPrism admin
password, its DB password, `MARIADB_PASSWORD` and `MARIADB_ROOT_PASSWORD` — safe only
because that file is ciphertext. I checked 20 historical commits of the file: **every one
is ciphertext**, so the values were never published, and no rotation was required.

## Changes

1. **Photoprism secrets moved to an encrypted env file.**
   New `templates/photoprism/photoprism.env.j2` rendered to `photoprism.env`
   (`*.env` stays git-crypt encrypted, `env_file`-consumed by both the app and its
   MariaDB), values sourced from a new `photoprism:` block in `plays/vars/secrets.yml`.
   The compose file now carries only comments where the literals were. Values unchanged →
   the existing MariaDB users keep working; one recreate to pick the file up.
2. **`providers.docker.exposedByDefault: false`** in `traefik/traefik.yaml`, with
   `traefik.enable=true` added to all **14** routed services that relied on the default
   (13 here + the three `www` services in the LeagueSphere repo, PR #2135's sibling).
   This is the structural guard: a container is only routable when its compose service
   says so. Side effect: the ~1 100 `Could not find network named "proxy"` warnings per
   log rotation disappear (follow-up 7 of the Traefik entry).
3. **No more published monitor ports**: node-exporter and cadvisor are scraped over the
   docker network, so their `ports:` entries were removed rather than rebound.
4. **Grafana metrics off** (`GF_METRICS_ENABLED=false` in the rendered `grafana.env`).
5. **Deploy-time guard**: `ansible/plays/roles/user/files/check_published_ports.py`, wired
   into `roles/user/tasks/main.yml` right after the repo sync. It parses every compose
   file in the checkout and fails the deploy when any service publishes a port on every
   interface, except `traefik` `80`/`443`. It also catches the long form and the
   container-only form (`- 8080`), which publishes a *random* host port on all
   interfaces. Verified against a synthetic bad tree (exit 1) and against this repo
   (exit 0, 24 compose files). It runs on the target because CI only sees ciphertext.
6. **Host firewall** (`system.firewall`, merged earlier in #232): a `DOCKER-USER` chain
   that allows `22`, `80`, `443` on the public interface and DROPs the rest, so even a
   mistaken `ports:` entry is not reachable while the deploy guard is being fixed.

## Order of operations (and why)

The label rollout and the `exposedByDefault` flip are the same change: flipping first
would 404 every service that still lacked the label. So: recreate the app containers
(with labels) → then recreate Traefik. The host firewall is deployed independently and
has no effect on 80/443.

## Verification

* `check_published_ports.py` on the prod checkout: **0 offenders** after the
  node-exporter/cadvisor removal.
* Every public host still answers (the sweep from the Traefik entry re-run).
* `https://monitor.lehel.xyz/metrics` → **404** (or 401) after the Grafana recreate.
* Traefik log: no `Could not find network named "proxy"` lines, and the API service list
  shrinks to the routed set.
* Exposure re-scan from outside: still only 22/80/443; and the new `DOCKER-USER` chain
  present on both hosts (`iptables -C DOCKER-USER -j HOST-EDGE`).

## Then, and only then

Remove the `docker-compose.yml` encryption rule from `.gitattributes` (and the matching
requirement in `.github/scripts/validate-git-crypt.sh`), so the compose files become
readable — which is what lets the already-installed Renovate app finally bump the image
tags. `*.yaml` (config), `*.env`, `*.conf`, `secrets.*` and `secret_*` stay encrypted.
