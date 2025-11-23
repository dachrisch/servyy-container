# Logging to Loki Migration

**Date:** 2025-11-23
**Author:** Claude Code
**Type:** Service Replacement

## Summary

Replaced the standalone Logdy logging service with Grafana Loki integrated into the monitor stack. Added Promtail for Docker container log collection and enabled Traefik metrics for full observability.

## Reason

- **Consolidation:** Combine logging with existing monitoring infrastructure (Grafana/Prometheus)
- **Better Integration:** Loki integrates natively with Grafana for log exploration
- **Full Observability:** Added Traefik metrics for request-level monitoring
- **Unified Stack:** All observability tools (metrics + logs) in one place

## Changes Made

### 1. Monitor Stack Updated (`monitor/docker-compose.yml`)

**Added services:**
- **Loki** (`grafana/loki:latest`) - Log aggregation backend
- **Promtail** (`grafana/promtail:latest`) - Log collector for Docker containers

**Updated:**
- Grafana now has provisioned datasources (Prometheus + Loki)
- Added `loki_data` volume for persistence

### 2. New Configuration Files

| File | Purpose |
|------|---------|
| `monitor/loki.yml` | Loki server configuration (31-day retention) |
| `monitor/promtail.yml` | Docker container and system log scraping |
| `monitor/provisioning/datasources/datasources.yml` | Auto-provision Prometheus + Loki datasources |
| `monitor/provisioning/dashboards/dashboards.yml` | Dashboard provisioning config |

### 3. Traefik Metrics Enabled

**`traefik/traefik.yaml` changes:**
```yaml
entrypoints:
  metrics:
    address: ":8082"

metrics:
  prometheus:
    entryPoint: metrics
    addEntryPointsLabels: true
    addRoutersLabels: true
    addServicesLabels: true
```

**`traefik/docker-compose.yml` changes:**
- Added port mapping: `8082:8082`

### 4. Prometheus Configuration Updated

**`monitor/prometheus.yml` - Added scrape jobs:**
- `traefik` → `traefik.traefik:8082`
- `loki` → `loki:3100`

### 5. Logging Service Removed

**Deleted:**
- `logging/docker-compose.yml`

**Updated:**
- `ansible/plays/vars/secrets.yml` - Removed logging service entry

### 6. Shell Function Updated

**`~/.zprezto/custom/functions/logdy`:**
- Rewritten to use Loki push API (`/loki/api/v1/push`)
- Same CLI interface preserved (`logdy info "message" key=value`)
- Uses `LOKI_URL` environment variable instead of `LOGDY_URL`

**`~/.zshenv`:**
- Changed from `LOGDY_URL`/`LOGDY_API_KEY` to `LOKI_URL`/`LOKI_API_KEY`

## Security

Loki is protected using multi-tenant mode (`auth_enabled: true`). The `X-Scope-OrgID` header acts as an API key:
- Requests without the header are rejected
- Only clients with the correct tenant ID can push/query logs
- Tenant ID is configured in `promtail.yml`, Grafana datasource, and `~/.zshenv`

## Original Logging Service

```yaml
# logging/docker-compose.yml (REMOVED)
services:
  logdy:
    image: rickraven/logdy:latest
    container_name: ${COMPOSE_PROJECT_NAME}.log
    labels:
      - traefik.http.routers.${SERVICE_NAME}.tls=true
      - traefik.http.routers.${SERVICE_NAME}.rule=Host(`${SERVICE_HOST}`)
      - traefik.http.routers.${SERVICE_NAME}.tls.certresolver=letsencryptdnsresolver
      - traefik.http.services.${SERVICE_NAME}.loadbalancer.server.port=8080
    volumes:
      - ./data:/app/data
    environment:
      - LOGDY_ADMIN_USER=<redacted>
      - LOGDY_ADMIN_PASS=<redacted>
      - LOGDY_API_KEY=<redacted>
    networks:
      - proxy
```

## New Architecture

```
                    ┌─────────────────────────────────────────┐
                    │            monitor stack                 │
                    ├─────────────────────────────────────────┤
Internet ──────────▶│  Grafana (monitor.lehel.xyz)            │
                    │     ↓              ↓                    │
                    │  Prometheus     Loki                    │
                    │     ↑              ↑                    │
                    │  ┌──┴──┐       ┌──┴──┐                 │
                    │  │cAdv │       │Promtail               │
                    │  │Node │       │  ↑                    │
                    │  └─────┘       │Docker logs            │
                    │     ↑          └─────────────────────  │
                    │  Traefik:8082 (metrics)                │
                    └─────────────────────────────────────────┘

Shell scripts ──────▶ POST https://monitor.lehel.xyz/loki/api/v1/push
```

## Verification Steps

1. **Deploy monitor stack:**
   ```bash
   cd monitor && docker-compose up -d
   ```

2. **Deploy traefik (for metrics):**
   ```bash
   cd traefik && docker-compose up -d
   ```

3. **Verify Loki is receiving logs:**
   ```bash
   # Check Loki health
   curl https://monitor.lehel.xyz/loki/ready

   # Test shell function
   source ~/.zprezto/custom/functions/logdy
   LOKI_DRY_RUN=1 logdy info "Test message" key=value
   ```

4. **Verify in Grafana:**
   - Open https://monitor.lehel.xyz
   - Go to Explore → Select Loki datasource
   - Query: `{job="docker"}`

## Rollback Procedure

1. **Restore logging service:**
   ```bash
   git checkout HEAD~1 -- logging/docker-compose.yml
   git checkout HEAD~1 -- ansible/plays/vars/secrets.yml
   cd logging && docker-compose up -d
   ```

2. **Restore shell function:**
   ```bash
   git checkout HEAD~1 -- ~/.zprezto/custom/functions/logdy
   git checkout HEAD~1 -- ~/.zshenv
   ```

3. **Revert traefik metrics (optional):**
   ```bash
   git checkout HEAD~1 -- traefik/traefik.yaml
   git checkout HEAD~1 -- traefik/docker-compose.yml
   ```

## Impact Assessment

| Component | Status |
|-----------|--------|
| Grafana dashboards | Enhanced with Loki datasource |
| Log collection | Docker containers + system logs now collected |
| Shell logging | Same interface, different backend |
| Backup scripts | Will log to Loki instead of Logdy |
| Metrics | Now includes Traefik request metrics |

## Next Steps

1. Create Grafana dashboards for:
   - Docker container logs view
   - Traefik request metrics
   - Combined metrics + logs dashboard

2. Configure alerting rules in Grafana for:
   - Error log spikes
   - Service health issues
   - High request latency
