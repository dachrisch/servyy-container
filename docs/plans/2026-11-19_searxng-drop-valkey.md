# Drop the unused `searxng.valkey` container

**Date:** 2026-11-19
**Repo:** `servyy-container` (`/home/cda/dev/infrastructure/container`)
**Status:** planned
**Host:** `servy.lehel.xyz` only (searxng is not in the `servyy-test` inventory)

## Goal

Remove the `searxng.valkey` sidecar container, its volume and its network.
It is not a cache for SearXNG and never was — it is dead weight.

Decision taken 2026-11-19: **delete, do not repoint at `shared.redis`**
(option "just delete" over "consolidate onto shared.redis").

## Findings (verified 2026-11-19 against production)

| Fact | Evidence |
|---|---|
| Nothing uses it | `docker exec searxng.valkey valkey-cli dbsize` → `0`; `info stats` → `total_connections_received: 3`, `total_commands_processed: 4` since `2026-11-14T04:30:47Z` |
| SearXNG has no valkey URL | `settings_defaults.py` defaults `valkey.url` to `false`; `SEARXNG_VALKEY_URL` / `SEARXNG_REDIS_URL` are unset in the container env; `settings.yml.j2` has no `valkey:`/`redis:` block |
| SearXNG's result cache is SQLite | `searx/cache.py` → `sqlitedb`, stored in `/var/cache/searxng` → the `core-data` volume |
| The only valkey consumer is the limiter | `searx/limiter.py`, `searx/botdetection/{ip_limit,link_token}.py` via `searx/valkeydb.py`; `server.limiter` is `false` and `use_default_settings` keeps it false |
| Nothing else is on its network | `searxng_internal` contains only `searxng.core` and `searxng.valkey` |
| Cost | ~7.6 MB RSS, no healthcheck, one more container to keep patched |
| The deployment history overstates it | `history/2026-06-11_searxng-deployment.md` says "Valkey caching" / "Redis cache — persisted via volume"; both are wrong |

Why not `shared.redis`: it is job-queue state for `leagues-finance`/`queen`, and
pointing SearXNG at it while `server.limiter` stays `false` would be a
connection that does nothing (only the limiter ever reads it). Enabling the
limiter is a separate behaviour change (it also needs `trusted_proxies` for the
`172.18.0.0/16` Traefik network, otherwise every request is limited as one
Traefik IP). Recorded as out of scope, with the re-add recipe.

## Change

### 1. `searxng/docker-compose.yml` — remove the service

Delete the `valkey:` block (service, image, `command`, volume, label), drop
`internal` from `core.networks`, delete the `internal:` network definition and
the `valkey-data` volume. Resulting file:

```yaml
# Read the documentation before using the `docker-compose.yml` file:
# https://docs.searxng.org/admin/installation-docker.html
# Managed by Ansible - do not edit manually

name: searxng

services:
  core:
    container_name: searxng.core
    image: "docker.io/searxng/searxng:${SEARXNG_VERSION:-latest}"
    restart: unless-stopped
    networks:
      - proxy
    env_file: ./.env
    volumes:
      - ./core-config/:/etc/searxng/:Z
      - core-data:/var/cache/searxng/
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.searxng.rule=Host(`${SERVICE_HOST:-search.lehel.xyz}`)"
      - "traefik.http.routers.searxng.entrypoints=${TRAEFIK_ENTRYPOINT:-websecure}"
      - "traefik.http.routers.searxng.tls=${TRAEFIK_TLS:-true}"
      - "traefik.http.routers.searxng.tls.certresolver=${TRAEFIK_CERTRESOLVER:-letsencryptdnsresolver}"
      - "traefik.http.services.searxng.loadbalancer.server.port=${SEARXNG_PORT:-8080}"
  # No valkey/cache sidecar. SearXNG caches results in SQLite (the `core-data`
  # volume); the only valkey consumer is the bot-detection limiter, which is
  # off (`server.limiter: false`). The standalone `searxng.valkey` was removed
  # 2026-11-19 after four days at 0 keys / 3 connections. If the limiter is
  # ever enabled, point it at `shared.redis` (db 2) on an external
  # `shared_backend` network instead of re-adding a local container.
  # See history/2026-11-19_searxng-drop-valkey.md.

networks:
  proxy:
    external: true

volumes:
  core-data:
```

No other file changes: `settings.yml.j2` has no valkey key, `restic.yml` backs
up only `settings.yml`, and the container-health probe resolves container names
from each compose file at deploy time (`roles/system_probe/templates/
system_container_health.sh.j2`), so `searxng.valkey` drops out of Pushgateway/
Grafana by itself on the next 5-minute push. `docker.io/valkey/valkey:9-alpine`
stays in use by `shared.redis`.

### 2. Deploy

```bash
cd /home/cda/dev/infrastructure/container/ansible
./servyy.sh --limit servy.lehel.xyz --tags user.docker.searxng
```

`user.docker.searxng` (`plays/user.yml:106-125`) runs `docker_compose_v2
state: absent` on the project, writes `settings.yml`, then the `docker_service`
role re-ups it. Expect **seconds of downtime** on `search.lehel.xyz` (core is
recreated) and an *orphan container* warning: compose `down`/`up` does not
remove a container or network that is no longer in the file.

### 3. Clean up the orphans (prod, once)

```bash
ssh servy.lehel.xyz '
  docker exec searxng.valkey valkey-cli dbsize   # must print 0 before removing
  docker rm -f searxng.valkey
  docker volume rm searxng_valkey-data
  docker network rm searxng_internal
'
```

Abort the volume removal if `dbsize` is not 0 (it was 0 on 2026-11-19; nothing
has ever written to it).

### 4. Verify

```bash
# only core is left, and it is up
ssh servy.lehel.xyz "docker ps -a --filter name=searxng"

# results still served (JSON format is enabled in settings.yml)
curl -s 'https://search.lehel.xyz/search?q=opencode&format=json' | head -c 200

# no valkey/redis complaints since the recreate
ssh servy.lehel.xyz "docker logs searxng.core --since 10m 2>&1 | grep -iE 'valkey|redis'"

# network and volume are gone
ssh servy.lehel.xyz "docker network ls | grep searxng; docker volume ls | grep valkey"
```

Then, after the next container-health push (≤5 min): no
`system_container_running{name="searxng.valkey"}` in Grafana (explore the
`system_container_health` job), i.e. the series disappeared rather than reading 0.

### 5. Record it

New `history/2026-11-19_searxng-drop-valkey.md`:

- what was removed (service, volume, network) and that the cache is SQLite;
- the evidence that it was unused (0 keys, 3 connections since 2026-11-14);
- the deploy command, the orphan cleanup, and the verification output;
- the correction of the 2026-06-11 history/spec claim of "Valkey caching";
- the re-add recipe: enable `server.limiter`, add `limiter.toml` with
  `trusted_proxies` covering `172.18.0.0/16` + `fd00:c0de:1::/64`, set
  `valkey.url: valkey://shared.redis:6379/2` and join external
  `shared_backend`.

Old history entries and `docs/superpowers/{specs,plans}/2026-06-11-searxng-*`
stay untouched (they are records of what was designed then); the new entry
supersedes them.

## Risks / rollback

| Risk | Mitigation |
|---|---|
| Seconds of `search.lehel.xyz` downtime when `core` is recreated | Same as every other searxng config deploy; pick a quiet moment |
| A hidden consumer of the valkey instance | None found: 0 keys, 3 connections in 4 days, no `valkey.url` configured anywhere, only `core` on its network |
| Lost cache/session data | Nothing to lose (`dbsize` 0); SearXNG's real cache is the `core-data` volume, which is untouched |
| Leftover container/volume/network | Explicit cleanup step 3, verified in step 4 |
| Rollback | `git revert` the commit and redeploy `--tags user.docker.searxng`; compose recreates `searxng.valkey` on a fresh empty volume. No data to restore |

## Out of scope

- Enabling `server.limiter` (a real behaviour change; needs `trusted_proxies`
  so client IPs come from `X-Forwarded-For`, plus a `limiter.toml` rendered by
  Ansible like `settings.yml`).
- Repointing SearXNG's limiter at `shared.redis` — only meaningful together
  with the limiter.
- The floating `searxng:latest` image tag in this compose file (separate
  concern, `history/2026-10-30_image-tag-floating.md`).
- Any change to `shared.redis`, `shared/docker-compose.yml`, or the probe
  wiring.
