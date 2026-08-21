# 2026-08-21 — Deploy Platzler-Heid (platzler-heid)

## Status

**Created and deployed a new service** for [Platzler-Heid] — the Festzelt Availability
dashboard, an Express server that scrapes table reservation availability from Festzelt OS
Oktoberfest portals and serves a filterable web UI + SSE live stream.

- Docker image: `dachrisch/platzler-heid:latest` (tags `latest`, `v1.0.0`; `node:24-alpine`,
  non-root `node` user, exposes port 3000, `HEALTHCHECK` → `GET /health`)
- URL: `platzler-heid.lehel.xyz`
- Service dir: `platzler-heid/`

## Changes

- `platzler-heid/docker-compose.yml` (new) — single app container (`web`, image
  `dachrisch/platzler-heid:latest`) on the external `proxy` network, exposed via Traefik
  using `${SERVICE_NAME}`-templated router names (matches this repo's "Adding a New Service"
  convention, modeled on `dontforget`). `NODE_ENV=production` / `PORT=3000` set inline in the
  `environment:` block (not secrets, don't vary by host).
- `ansible/plays/roles/docker_service/templates/platzler-heid/.env.j2` (new) — carries
  `SERVICE_HOST`/`SERVICE_NAME`/`TRAEFIK_ENTRYPOINT`/`TRAEFIK_TLS`/`TRAEFIK_CERTRESOLVER`
  (needed for docker-compose's own `${VAR}` label interpolation). TLS vars default to
  production (`websecure`/`true`/`letsencryptdnsresolver`).
- `ansible/plays/user.yml` — new `docker_service` role invocation, tags
  `[user.docker, user.docker.platzler-heid]` with `env_templates` pointing at the custom
  `.env.j2`. `service_host` left at its default (`platzler-heid.{{ inventory_hostname }}`).
- `ansible/plays/roles/user/tasks/docker_extras.yml` — registered `platzler-heid` in the
  `forall_docker_services.sh` service list, after `dontforget`.
- `ansible/testing` — `platzler_heid_traefik_{entrypoint,tls,certresolver}` overrides
  (`web`/`false`/empty) for `servyy-test.lxd`, same pattern as `searxng`/`job-search`/
  `dontforget`'s test entries. (Not exercised this deployment — test host unreachable.)

## Deploy

```bash
cd ansible && ansible-playbook plays/user.yml --tags "user.docker.repo,user.docker.platzler-heid" -i production
```

Deployed to **production only** (`lehel.xyz`) at the explicit request of the operator. The
test host (`servyy-test.lxd`) was not resolvable from the deployment environment.

## Verification (production)

- `docker ps` — `platzler-heid.web` running/healthy.
- `curl -s https://platzler-heid.lehel.xyz/health` → `{"status":"ok"}`.

## Notes

- Image requires `curl` — already bundled in the image (the scraper shells out to it).
- To keep data fresh without scheduled scraping, set `SCRAPE_INTERVAL_MIN` (e.g. `15`) or hit
  `POST /api/refresh`; results stream to the UI via SSE (`/api/stream`). All image env vars
  (`PORT`, `THROTTLE_MS`, `CONCURRENCY`, `SCRAPE_INTERVAL_MIN`) are optional and left at their
  defaults for this deployment.
