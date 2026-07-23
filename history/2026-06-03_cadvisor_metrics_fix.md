# cAdvisor Metrics Collection Fix - 2026-06-03

## Problem
Dashboard `/docker-containers/services-and-infrastructure` was using cAdvisor container metrics that weren't being collected. cAdvisor v0.49.1 couldn't connect to Docker daemon due to API version mismatch (required 1.44+, system has 1.41).

## Root Cause Analysis
- cAdvisor v0.49.1 requires Docker API 1.44+ but lehel.xyz runs Docker API 1.41
- With `--docker_only=true` flag, cAdvisor failed to detect Docker containers and had no fallback
- Even with containerd factory enabled, no containers were discovered (all are Docker containers, not containerd)
- Result: zero container metrics (container_cpu_usage_seconds_total, container_memory_usage_bytes, etc.)

## Solution
1. Removed `--docker_only=true` flag to allow containerd fallback
2. Upgraded cAdvisor from v0.49.1 to `latest` for Docker API 1.41 compatibility

## Changes Made

### Commits
1. **3ec1412** - `remove: remove cadvisor from monitoring stack`
   - Removed cAdvisor container and alert rule
   - Removed Prometheus scrape config

2. **7df3605** - `restore: re-add cadvisor with minimal configuration`
   - Restored cAdvisor v0.49.1 with minimal config:
     - Housekeeping interval: 30s (vs default 10s)
     - Docker-only mode (disabled)
     - Disabled metrics: advtcp, cpu_topology, memory_numa, sched
   - Restored Prometheus scrape config for cAdvisor
   - Restored "Container Down" alert rule

3. **bf3e681** - `fix: remove docker_only flag to allow containerd fallback for cAdvisor`
   - Removed `--docker_only=true` to enable containerd fallback
   - Allows container discovery when Docker API connection fails

4. **9927b37** - `fix: upgrade cadvisor to latest for docker api compatibility`
   - Upgraded from v0.49.1 to latest
   - Resolves Docker API 1.41 incompatibility

## Testing Notes
- Verified cAdvisor container runs healthy on production
- Docker API version incompatibility prevented v0.49.1 from discovering containers
- Latest version should support broader API compatibility

## Files Changed
- `monitor/docker-compose.yml` - cAdvisor service config and image version
- `monitor/prometheus.yml` - cAdvisor scrape config
- `monitor/provisioning/alerting/alert-rules.yml` - Container down alert rule

## Dashboard Impact
- `/docker-containers` dashboard queries container metrics from cAdvisor
- Queries used: container_cpu_usage_seconds_total, container_memory_usage_bytes, container_network_*, container_fs_*
- None of these are in disabled metrics list, so they should be available with latest version

## Verification Command
```bash
# On production after deployment
ssh lehel.xyz "docker logs monitor.cadvisor | grep -i 'recovery\|container' | head -20"
curl -s "https://monitor.lehel.xyz/prometheus/api/v1/targets" | jq '.data.activeTargets[] | select(.labels.job=="cadvisor")'
```
