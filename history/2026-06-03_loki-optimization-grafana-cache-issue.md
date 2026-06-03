# Loki Optimization - Grafana Dashboard Cache Issue

**Date:** 2026-06-03  
**Status:** Deployed but Grafana not using optimized queries  

## Problem Summary

Grafana is still executing **unoptimized security dashboard queries** despite deploying updated `security.json` with optimized queries. Loki CPU remains at **86.85%** instead of the expected <5%.

### Root Cause

**Grafana caches dashboard definitions in its SQLite database.** The provisioning system updates the JSON files, but Grafana doesn't automatically reload or reimport dashboards that already exist in its database.

## Evidence

### Old (Unoptimized) Query Still Running

```
query="sum(count_over_time({job=\"docker\"} |~ \"(?i)(sql.*injection|union.*select|<script|javascript:|eval\\\\(|exec\\\\()\"[15m]))"
duration=29.99183041s  # 30-second timeout
status=500             # Query failed
```

### Expected (Optimized) Query Not Running

```
query="sum(count_over_time({job=\"docker\", container=~\"traefik.*\"} |= \"select\" | path =~ \"(?i)(sql.*injection|union.*select|<script|javascript:|eval|exec)\"[15m]))"
```

## CPU Impact

| Stage | Loki CPU | Promtail CPU |
|-------|----------|--------------|
| Before optimization | 132% | ~0.5% |
| After deploy (no Grafana) | 2.86% | 39.67% |
| After Grafana restart | 86.85% | 0.74% |
| **Current (old queries)** | **86.85%** | **0.74%** |

## Deployed Changes (✅ Correct)

All three optimization components were successfully deployed:

1. ✅ **Promtail** (`monitor/promtail.yml`)
   - Added Traefik JSON parsing
   - Added structured metadata extraction (method, status, path, user_agent)

2. ✅ **Loki** (`monitor/loki.yml`)
   - `allow_structured_metadata: true`
   - `query_timeout: 30s`
   - `split_queries_by_interval: 15m`

3. ✅ **Security Dashboard** (`monitor/provisioning/dashboards/security.json`)
   - 10 queries rewritten with container filter
   - Structured metadata field filters added

### Commit Deployed
```
7665174 feat: optimize Loki security queries with structured metadata extraction
```

Server git log confirms commit is present:
```bash
$ ssh lehel.xyz "cd servyy-container && git log --oneline -3"
7665174 feat: optimize Loki security queries with structured metadata extraction
3ad9e0c feat: update k6 dashboard - add multi-percentile latency chart and CPU history
200b03b docs: add migration and rebuild learnings from servy.lehel.xyz restore
```

## Why Grafana Didn't Pick Up Changes

### Attempt 1: Restart Grafana
- ❌ Failed - Grafana database already had old dashboard cached
- Used `docker restart monitor.grafana`

### Attempt 2: Clear dashboard directory
- ❌ Failed - Grafana database persisted
- Used `docker run --rm -v monitor_grafana_data:/data alpine rm -rf /data/dashboards`

### Attempt 3: Wipe SQLite database
- ⏸️ Blocked by user permission requirement
- Would use `docker volume rm monitor_grafana_data`

## Solution Options

### Option A: Delete Grafana Volume (Recommended)
```bash
ssh lehel.xyz "docker stop monitor.grafana && docker volume rm monitor_grafana_data && docker start monitor.grafana"
```
- Forces fresh reimport from provisioning
- Loses all manual Grafana changes (if any)
- Takes ~30-60 seconds for full reload

### Option B: Update Dashboard Version
Edit `security.json` to increment the version field:
```json
"version": 1  // Change to version: 2
```
Then restart Grafana. This triggers reimport even if dashboard exists.

### Option C: Delete Dashboard via API
```bash
# Get dashboard ID
curl -s http://monitor.grafana:3000/api/dashboards/uid/security -H "Authorization: Bearer $TOKEN"

# Delete it
curl -X DELETE http://monitor.grafana:3000/api/dashboards/uid/security -H "Authorization: Bearer $TOKEN"

# Restart Grafana to reimport
```

## Next Steps

1. **Confirm user approval** to delete Grafana volume OR implement version bump
2. **Execute chosen solution**
3. **Verify optimization:**
   - Check Loki logs for queries with `container=~"traefik.*"`
   - Monitor Loki CPU - should drop to <10%
   - Verify structured metadata is being extracted
4. **Document the solution** in a follow-up history file

## Lessons Learned

- Grafana provisioning doesn't auto-reload cached dashboards
- Changing JSON files in `provisioning/dashboards/` requires either:
  - Wiping Grafana's database volume
  - Incrementing dashboard version
  - Deleting dashboard via API
- For future updates, consider:
  - Adding version auto-increment to deployment scripts
  - Using Grafana's API to force reimport instead of file provisioning
  - Documenting this gotcha in deployment procedures

## Files Modified

- `monitor/promtail.yml` - Deployed ✅
- `monitor/loki.yml` - Deployed ✅  
- `monitor/provisioning/dashboards/security.json` - Deployed but not loaded ❌

## Related

- Issue: Loki CPU spike from expensive regex queries on `{job="docker"}` 
- Root cause: Security dashboard scanning all containers instead of just Traefik
- Fix: Add structured metadata + narrow stream selector to queries
