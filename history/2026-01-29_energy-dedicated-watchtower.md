# Energy Service: Dedicated Watchtower Deployment

**Date:** 2026-01-29
**Status:** ✅ Completed
**Branch:** `claude/energy-dedicated-watchtower` (merged to master)

## Problem

Energy service was monitored by global portainer watchtower with 2-hour poll interval. Needed faster update cycle matching leaguesphere staging's approach (10 minutes) with isolated scope control.

## Solution

Added dedicated watchtower instance to energy service:
- **Scope:** `energy` (only monitors energy.energy container)
- **Poll interval:** 10 minutes (600s)
- **Cleanup enabled:** Removes old images after updates
- **Health checks:** Configured with 15s interval, 5s timeout, 5 retries, 120s start period
- **Timezone:** Europe/Berlin for consistent log timestamps

## Implementation

### Files Changed

**energy/docker-compose.yml:**
- Added `com.centurylinklabs.watchtower.scope=energy` label to energy service
- Added dedicated watchtower service with configuration matching leaguesphere staging pattern

### Architecture

```
Watchtower Isolation:
  portainer.watchtower → monitors other services (2-hour interval, scope: none)
  leaguesphere_stage.watchtower → monitors staging services (10-min interval, scope: ls-staging)
  energy.watchtower → monitors only energy.energy (10-min interval, scope: energy)
```

### Configuration Details

```yaml
watchtower:
  restart: unless-stopped
  image: containrrr/watchtower
  container_name: ${COMPOSE_PROJECT_NAME}.watchtower
  labels:
    - traefik.enable=false
    - com.centurylinklabs.watchtower.scope=energy
  environment:
    WATCHTOWER_CLEANUP: "true"
    WATCHTOWER_POLL_INTERVAL: "600"
    WATCHTOWER_INCLUDE_RESTARTING: "true"
    WATCHTOWER_SCOPE: "energy"
    TZ: "Europe/Berlin"
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock
    - /etc/localtime:/etc/localtime:ro
  healthcheck:
    interval: 15s
    timeout: 5s
    retries: 5
    start_period: 120s
```

## Deployment Timeline

1. **Created feature branch:** `claude/energy-dedicated-watchtower`
2. **Modified:** `energy/docker-compose.yml`
3. **Committed:** `fd8b552`
4. **Merged to master:** 2026-01-29 22:00 CET
5. **Deployed to production:** 2026-01-29 22:07 CET

### Deployment Steps

```bash
# Updated git repository on server
./servyy.sh --tags "user.docker.repo,docker" --limit lehel.xyz

# Restarted docker services with new configuration
./servyy.sh --tags "user.docker.services.start" --limit lehel.xyz
```

## Verification

### Container Status

```bash
$ ssh lehel.xyz "docker ps | grep energy"
energy.energy         Up 21 seconds (healthy)
energy.watchtower     Up 21 seconds (healthy)
```

### Watchtower Logs

```
time="2026-01-29T22:07:49+01:00" level=info msg="Watchtower 1.7.1"
time="2026-01-29T22:07:49+01:00" level=info msg="Only checking containers in scope \"energy\""
time="2026-01-29T22:07:49+01:00" level=info msg="Scheduling first run: 2026-01-29 22:17:49 +0100 CET"
```

### Scope Label Verification

```bash
$ ssh lehel.xyz "docker inspect energy.energy -f '{{index .Config.Labels \"com.centurylinklabs.watchtower.scope\"}}'"
energy
```

### Service Accessibility

```bash
$ curl -I https://energy.lehel.xyz
HTTP/2 200
```

✅ **All checks passed**

## Running Watchtowers

| Container | Scope | Poll Interval | Status |
|-----------|-------|---------------|--------|
| portainer.watchtower | none | 2 hours (7200s) | Healthy |
| leaguesphere_stage.watchtower | ls-staging | 10 minutes (600s) | Healthy |
| energy.watchtower | energy | 10 minutes (600s) | Healthy ✅ |

## Expected Behavior

### Update Flow

1. Every 10 minutes: Watchtower checks Docker Hub for `dachrisch/energy.consumption:latest`
2. If new image available:
   - Pull new image
   - Stop energy.energy container
   - Remove old container
   - Start new container with same config
   - Remove old image (cleanup enabled)
3. Monitoring captures:
   - Loki logs the container restart
   - Prometheus tracks service downtime (typically <5 seconds)
   - Grafana dashboards show update events

### First Update Check

Scheduled for: **2026-01-29 22:17:49 CET** (10 minutes after deployment)

## Monitoring & Observability

- **Watchtower logs:** `ssh lehel.xyz "docker logs energy.watchtower"`
- **Energy service logs:** `ssh lehel.xyz "docker logs energy.energy"`
- **Container status:** `ssh lehel.xyz "docker ps | grep energy"`
- **Loki query:** `{job="docker",container="energy.energy"}`
- **Grafana:** https://monitor.lehel.xyz (Services & Infra dashboard)

## Known Issues

None identified during deployment.

## Future Enhancements

- Consider adding watchtower notification integration (Slack/email) for update events
- Monitor Docker Hub API rate limits (144 checks/day per service)
- Evaluate consolidating watchtower instances if more services need rapid updates

## Rollback Plan

If issues arise:

```bash
# Option 1: Revert git commit
git revert fd8b552
./servyy.sh --tags "user.docker.repo,user.docker.services.start" --limit lehel.xyz

# Option 2: Stop watchtower manually (energy service continues normally)
ssh lehel.xyz "docker stop energy.watchtower && docker rm energy.watchtower"
```

Energy service will continue functioning normally - it will fall back to manual updates or portainer watchtower monitoring.

## References

- **Leaguesphere staging watchtower:** `/home/cda/dev/leaguesphere/deployed/docker-compose.staging.yaml:85-105`
- **Watchtower documentation:** https://containrrr.dev/watchtower/
- **Container naming convention:** `{directory}.{compose-service}` (e.g., `energy.watchtower`)

## Lessons Learned

1. **Scope-based filtering:** Enables multiple watchtower instances without interference
2. **Git workflow:** Always update repo on server before restarting services
3. **Health checks:** Essential for monitoring watchtower reliability
4. **Cleanup:** Automatic old image removal prevents disk space issues
5. **Poll interval:** 10 minutes balances freshness with API rate limits

---

**Deployment successful!** Energy service now has dedicated watchtower with 10-minute update checks, isolated from other services via scope filtering.
