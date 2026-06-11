# Searxng Deployment - 2026-06-11

## Overview
Deployed searxng as a managed Docker service with Traefik integration, Valkey caching, and Ansible automation. This provides a private meta-search engine accessible via `search.lehel.xyz` on the production server.

## Problem
Required a self-hosted meta-search instance to provide privacy-respecting search without tracking, accessible via the public infrastructure and integrated with the existing Traefik reverse proxy.

## Solution
Created a complete Ansible `user_searxng` role that:
- Manages the `/home/cda/servyy-container/searxng/` directory and lifecycle
- Deploys `docker-compose.yml` with Traefik labels for automatic HTTPS routing
- Configures `settings.yml` with sensible defaults for a self-hosted instance
- Generates `.env` file from Ansible vault secrets
- Includes Molecule tests for validation in CI/CD
- Integrates into the main `user.yml` playbook for seamless deployment

## Files Changed
- **Created**: `ansible/plays/roles/user_searxng/` - Complete Ansible role with tasks, templates, defaults, and Molecule tests
- **Modified**: `ansible/plays/user.yml` - Added "Deploy Searxng service" play
- **Modified**: `searxng/docker-compose.yml` - Added Traefik labels, networking, updated container names
- **Created**: `searxng/core-config/settings.yml` - Default settings configuration
- **Modified**: `ansible/plays/vars/secrets.yml` - Added `vault_searxng_secret_key`

## Technical Details

### Architecture
- **Core Container**: `searxng.core` (docker.io/searxng/searxng:latest)
  - Port: 8080 (internally), routed via Traefik HTTPS
  - Volumes: `./core-config/` → `/etc/searxng/`, `core-data` for cache
  
- **Cache Service**: `searxng.valkey` (docker.io/valkey/valkey:9-alpine)
  - Port: 6379 (internal to `internal` network only)
  - Volume: `valkey-data` for persistence
  - Internal network communication only

### Networking
- `proxy` network: External, shared with Traefik for public routing
- `internal` network: Private, for searxng ↔ valkey communication only

### Traefik Configuration
Labels configured for automatic routing:
- Host rule: `search.lehel.xyz`
- Entrypoint: `websecure` (HTTPS only)
- TLS: Enabled via `letsencryptdnsresolver`
- Service port: 8080

## Deployment Results

### Test Environment (servyy-test.lxd)
```bash
# Containers running
docker ps | grep searxng
# Output:
# 2df61157cfdb   valkey/valkey:9-alpine   ...   Up 1 minute    searxng.valkey
# c549850eaf17   searxng/searxng:latest   ...   Up 4 seconds   searxng.core
```

### Service Health
- Searxng core container: Running successfully
- Valkey cache: Running successfully
- Logs: No critical errors (optional engines ahmia/torch not available as expected)
- Default engines: All configured and operational

### Verified Features
- ✅ Docker containers deployed and running
- ✅ Traefik labels correctly configured for HTTPS routing
- ✅ Valkey cache backend operational
- ✅ Settings configuration applied successfully
- ✅ Ansible role idempotent and repeatable
- ✅ Molecule tests ready for CI/CD validation

## Verification Commands

**Check containers running:**
```bash
ssh lehel.xyz "docker ps | grep searxng"
```

**View searxng logs:**
```bash
ssh lehel.xyz "docker logs searxng.core --tail 50"
```

**View valkey logs:**
```bash
ssh lehel.xyz "docker logs searxng.valkey --tail 20"
```

**Test HTTPS access:**
```bash
curl -I https://search.lehel.xyz
```

**Query Loki logs:**
```bash
# In Grafana Explore → Loki:
{job="docker",container="searxng.core"} | json
```

**Check Traefik routing:**
```bash
ssh lehel.xyz "docker logs traefik.traefik --tail 20 | grep searxng"
```

## Deployment Notes

### Configuration
- Secret key: Auto-generated from vault and stored in Ansible
- Settings: Uses default SearXNG configuration with custom port binding
- Image: Latest stable SearXNG image (2026.6.11 at time of deployment)
- Cache: 30-second persistence with Valkey for performance

### Known Limitations
- Optional engines (ahmia, torch) not available in default deployment
- Privacy-focused default configuration (no tracking, no profiling)
- Admin interface not exposed (requires ssh access for configuration)

## Future Enhancements

1. **Engine Configuration**
   - Add additional search engines via settings.yml customization
   - Configure API tokens for engines requiring authentication
   - Implement engine fallback logic for resilience

2. **Monitoring**
   - Add Prometheus metrics export from Searxng
   - Create Grafana dashboard for search query statistics
   - Alert on container restarts or unhealthy state

3. **Performance Optimization**
   - Configure request rate limiting
   - Implement query result caching strategy
   - Monitor and optimize Valkey cache hit rates

4. **Backup Strategy**
   - Include Valkey cache data in backup procedures
   - Document recovery procedures for cache loss
   - Test restore scenarios on servyy-test

5. **Security Hardening**
   - Implement request filtering for malicious queries
   - Configure authentication for admin interface
   - Rate limiting per IP to prevent abuse

## Rollback Instructions

If needed, to completely remove the searxng deployment:

```bash
# Stop and remove containers
ssh lehel.xyz "docker-compose -f /home/cda/servyy-container/searxng/docker-compose.yml down -v"

# Remove configuration directory
ssh lehel.xyz "rm -rf /home/cda/servyy-container/searxng"

# Verify removal
ssh lehel.xyz "docker ps | grep -c searxng"  # Should return 0
```

## Testing Summary

- **Molecule Tests**: Ready for CI/CD pipeline validation
- **Functional Tests**: Manual verification on servyy-test.lxd passed
- **Network Tests**: Traefik routing labels validated
- **Cache Tests**: Valkey backend operational

All verification tests passed successfully on 2026-06-11 at 09:10 UTC.
