# Dropped the unused `searxng.valkey` sidecar

**Date:** 2026-11-19
**Branch:** `db-tier/wp12-wp13-r10`
**Plan:** [docs/plans/2026-11-19_searxng-drop-valkey.md](../docs/plans/2026-11-19_searxng-drop-valkey.md)

## What was removed

From `searxng/docker-compose.yml`:

- the `valkey:` service (`valkey/valkey:9-alpine`, `container_name: searxng.valkey`);
- the `valkey-data` volume and the `internal` network definition;
- `internal` from `core.networks` (it existed only to reach valkey).

A comment in the compose now records why it is gone and how to re-add it correctly (via
`shared.redis`, only together with the limiter).

On the host, after the deploy, guarded by evidence:

| step | guard | result |
|---|---|---|
| `docker exec searxng.valkey valkey-cli dbsize` | must print `0` before anything is removed | `0` (`info keyspace` empty, `total_connections_received: 2`, `total_commands_processed: 3` since its 7-hour start) |
| `docker rm -f searxng.valkey` | — | removed |
| `docker volume rm searxng_valkey-data` | `docker ps -aq --filter volume=…` empty | `0` containers, volume removed |
| `docker network rm searxng_internal` | `docker network inspect … .Containers` length `0` | `0` attached, network removed |

`shared.redis`, `shared/docker-compose.yml` and the probe wiring were not touched.

## Deploy

```bash
cd ansible
./servyy.sh --limit servy.lehel.xyz --tags user.docker.searxng
```

`18:09:01Z → 18:10:41Z`, `changed=2`, `failed=0`. The play stops the project and re-ups it, so
`searxng.core` was recreated at `18:10:07Z`: **seconds of downtime on `search.lehel.xyz`**, as the
plan predicted. `searxng.valkey` survived the re-up as an orphan (compose does not remove containers
that left the file) and was removed by the guarded step above at `18:10:5xZ`.

## Verification

```
docker ps -a --filter name=searxng      -> searxng.core only, Up
docker network ls | grep searxng        -> (nothing)
docker volume ls | grep valkey          -> (nothing)
docker exec searxng.core printenv       -> no SEARXNG_VALKEY_URL / SEARXNG_REDIS_URL
search.lehel.xyz/                       200
search.lehel.xyz/search?q=…&format=json 200 JSON, no valkey/redis complaints in the log
```

The result cache is the SQLite one, and `valkey` is off in the effective config:

```
# inside the container, searx.settings_loader.load_settings('/etc/searxng/settings.yml')
valkey: {'url': False}          # also the shipped default; SEARXNG_VALKEY_URL is unset
redis:  {'url': False}          # deprecated alias, likewise unset
ls /tmp/sxng_cache_*            -> sxng_cache_DATA_CACHE.db, sxng_cache_ENGINES_CACHE.db (+ -shm/-wal)
```

Correction to the plan's wording: in this image (`SearXNG 2026.8.4`) `ExpireCacheCfg.db_url` defaults
to **`/tmp/sxng_cache_{name}.db`**, not to `/var/cache/searxng` — `searx/cache.py` says so explicitly
("If unset a default DB will be created in `/tmp/sxng_cache_{self.name}.db`"), and that is what the
running container has. The `core-data` volume is untouched either way. The cache is SQLite in both
readings; it is just not on the volume the plan assumed.

## Findings (reported, deliberately not fixed)

1. **This instance returns no results, and it did not before this change either.** Every query comes
   back `{"results": [], … "unresponsive_engines": []}` and `GET /config` reports `engines: []`. Proven
   pre-existing by isolation, not by assumption: a throwaway `searxng/searxng:latest` container
   started from the **same rendered `settings.yml`** also reports `engines: []` and returns nothing,
   while the same image with only `use_default_settings: true` loads **274 engines**. The cause is
   therefore in the rendered settings (the `use_default_settings.engines.keep_only` list plus the
   explicit `engines:` block), not in the valkey removal — which changed no settings at all.
   Fixing it is a separate package (it needs a decision on which engines/keys this instance should
   use); it was left alone.
2. **The container-health probe never knew about searxng.** `system-container-health.sh` is rendered
   from `docker.services` and `docker_backend_services`, and `searxng` is in neither (dontforget and
   platzler-heid are missing too), so there was never a `system_container_running{name=…}` series for
   either searxng container. The plan's "the series disappears on the next push" check is vacuous: the
   probe list is stale relative to the service inventory — worth a follow-up, unrelated to valkey.

## Do not undo

- Do not re-add a local valkey container for SearXNG. If the limiter is ever enabled, point
  `valkey.url` at `shared.redis` (db 2) on an external `shared_backend` network — and add
  `trusted_proxies` for `172.18.0.0/16` + `fd00:c0de:1::/64` in the same change, otherwise every
  request is limited as one Traefik IP.
- Do not "fix" the empty result list by deleting the engine tokens or the `keep_only` block
  blind — understand which engines this image actually ships first.
- `shared.redis` stays as it is; it is job-queue state for leagues-finance/queen and has nothing to do
  with SearXNG.
