# Searxng Deployment - 2026-06-11

## Overview

Deployed searxng as a private meta-search engine with Google and DuckDuckGo only, accessible via `search.lehel.xyz` (production) and `search.servyy-test.lxd` (test). Integrated with Traefik, Valkey caching, Loki logging, and Ansible automation.

## Architecture

```
Internet
    ↓
Traefik (routes search.lehel.xyz → HTTPS)
    ↓
Docker "proxy" network
    ↓
searxng.core (searxng/searxng:latest)
    ↔ searxng.valkey (valkey:9-alpine) via internal network
    ↔ Promtail → Loki (automatic via container name)
```

### Responsibility Split

| What | Who manages it |
|------|---------------|
| `searxng/docker-compose.yml` | Git — never touched by Ansible |
| `searxng/core-config/settings.yml` | Ansible — contains engine tokens and secret key |
| `searxng/.env` | Ansible — contains `SEARXNG_SECRET_KEY`, `SERVICE_HOST`, Traefik vars |
| `searxng/core-config/.gitkeep` | Git — tracks the directory |

## Configuration

### settings.yml (Ansible-managed, from `settings.yml.j2`)

```yaml
use_default_settings:
  engines:
    keep_only:
      - google
      - duckduckgo

server:
  secret_key: "<from vault>"
  bind_address: 0.0.0.0
  port: 8080
  image_proxy: true

search:
  formats:
    - html
    - json

engines:
  - name: google
    tokens:
      - "<from vault>"
  - name: duckduckgo
    tokens:
      - "<from vault>"
```

### .env (Ansible-managed, from `env.j2`)

```
SEARXNG_SECRET_KEY=<vault_searxng_secret_key>
SERVICE_HOST=search.lehel.xyz          # overridden per inventory
TRAEFIK_ENTRYPOINT=websecure           # web for test, websecure for prod
TRAEFIK_TLS=true                       # false for test
TRAEFIK_CERTRESOLVER=letsencryptdnsresolver  # empty for test
```

### Vault secrets (in `ansible/plays/vars/secrets.yml`)

```yaml
vault_searxng_secret_key: ...
vault_searxng_google_token: ...
vault_searxng_duckduckgo_token: ...
```

### Test inventory overrides (in `ansible/testing`)

```yaml
searxng_service_host: search.servyy-test.lxd
searxng_traefik_entrypoint: web
searxng_traefik_tls: "false"
searxng_traefik_certresolver: ""
```

## Ansible Role

**Role:** `ansible/plays/roles/user_searxng/`

Tasks (in order):
1. Stop container (so settings.yml can be written without ownership conflict)
2. Fix `core-config/` ownership (container runs as uid 977, Ansible needs to write there)
3. Deploy `settings.yml` from template
4. Deploy `.env` from template
5. Start docker-compose services

## Deployment

```bash
# Test
cd ansible && ./servyy-test.sh --tags "user.docker.searxng"

# Production (requires explicit approval)
cd ansible && ./servyy.sh --tags "user.docker.searxng" --limit lehel.xyz
```

## Querying the API

```bash
# HTML search
curl "https://search.lehel.xyz/search?q=your+query&tokens=<token>"

# JSON search
curl "https://search.lehel.xyz/search?q=your+query&tokens=<token>&format=json"

# On test (HTTP)
curl "http://search.servyy-test.lxd/search?q=your+query&tokens=<token>&format=json"
```

Note: parameter is `tokens` (plural).

## Verification

```bash
# Containers running
ssh lehel.xyz "docker ps | grep searxng"

# Logs
ssh lehel.xyz "docker logs searxng.core --tail 20"

# Traefik routing
ssh lehel.xyz "docker logs traefik.traefik --tail 20 | grep searxng"

# Loki (Grafana Explore)
{job="docker",container="searxng.core"} | json
```

## Known Issues / Notes

- `core-config/` directory gets owned by uid 977 after container runs — Ansible stops container and uses `become_user: root` to fix ownership before writing `settings.yml`.
- Test environment uses HTTP (no TLS) via `TRAEFIK_ENTRYPOINT=web` and `TRAEFIK_TLS=false` in `.env`.
- Engines return empty results if token values are placeholders — update vault with real tokens.
