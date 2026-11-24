# searxng/ — private search frontend

`searxng.core` (`docker.io/searxng/searxng`), reachable at `search.lehel.xyz` through
Traefik on the `proxy` network. The compose file is managed by Ansible — do not
hand-edit it on a host.

## Files

- `docker-compose.yml` — one service. `env_file: ./.env`; config mounted from
  `core-config/` to `/etc/searxng/:Z`, cache in the `core-data` volume.
- `.env.example` — the supported variables: `SEARXNG_VERSION`, `SEARXNG_HOST`,
  `SEARXNG_PORT` (default 8080). Router/entrypoint/TLS/certresolver and
  `SERVICE_HOST` come from the rendered `.env`.
- `core-config/` — SearXNG settings; `.gitkeep` only, actual settings are rendered.

## Rules

- **No valkey/cache sidecar.** SearXNG caches results in SQLite (`core-data`); the
  only valkey consumer is the bot-detection limiter, which is off
  (`server.limiter: false`). `searxng.valkey` was removed on 2026-11-19 after four
  days at 0 keys / 3 connections. If the limiter is ever enabled, point it at
  `shared.redis` (db 2) on an external `shared_backend` network — do not re-add a
  local container. See `history/2026-11-19_searxng-drop-valkey.md`.
- Never publish a port on all interfaces; Traefik owns 80/443.

## Reference

- [Root AGENTS.md](../AGENTS.md) — service naming, Docker service guidelines and deploy rules.
