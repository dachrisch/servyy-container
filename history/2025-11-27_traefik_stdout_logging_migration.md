# Traefik Stdout Logging Migration & HTTP Errors Dashboard Redesign

**Date:** 2025-11-27
**Author:** Claude Code
**Type:** Architecture Optimization, Dashboard Enhancement

## Summary

Migrated Traefik access logging from file-based to stdout-based approach to eliminate log duplication and reduce storage usage. Extended fail2ban Loki integration to replace file-based Traefik jails with Loki queries. Redesigned HTTP Errors dashboard with URL breakdown tables and improved layout.

## Reason

- **Storage Optimization:** Eliminate 2x log duplication (file + Loki → stdout → Loki only)
- **Architecture Simplification:** Single log pipeline instead of dual file + container logging
- **Enhanced Security:** Extend Loki-based fail2ban pattern to cover Traefik rate limiting and malicious bots
- **Better Observability:** Add URL-level error tracking to identify problematic endpoints

## Changes Made

### 1. Traefik Configuration (`traefik/`)

**`traefik.yaml` changes:**
```yaml
# BEFORE:
accessLog:
  filePath: /var/log/traefik/access.log
  format: json

# AFTER:
accessLog:
  format: json
  # Output to stdout (no filePath)
```

**`docker-compose.yml` changes:**
- Removed volume mount: `/var/log/traefik:/var/log/traefik`
- Logs now captured automatically by Docker logging driver → Promtail → Loki

**Container label:** `traefik.traefik` (derived from `compose.service=reverse-proxy`)

### 2. fail2ban Loki Integration Extended

**Script:** `ansible/plays/roles/system/templates/fail2ban/update-blocklist-from-loki.sh.j2`

**Added 3 new query functions:**

1. **`get_traefik_rate_limit_ips()`**
   - Query: 10+ requests from same IP in 60s window
   - Reason: `traefik-rate-limit`
   - Replaces: `traefik-access` jail

2. **`get_traefik_malicious_bot_ips()`**
   - Query: User-Agent matching malicious patterns (nmap, masscan, nikto, sqlmap, etc.)
   - Reason: `traefik-malicious-bot`
   - Replaces: `traefik-bots` jail

3. **`get_traefik_crawler_ips()`**
   - Query: 20+ requests in 2-minute window
   - Reason: `traefik-aggressive-crawler`
   - Replaces: `traefik-crawler-soft` jail

**LogQL queries use:**
- Label: `{job="docker",container="traefik.traefik"}`
- JSON parsing: `| json | ClientHost != ""`
- Time windows: `[1m]`, `[2m]`, `[24h]`

**Filter updated:** `ansible/plays/roles/system/templates/fail2ban/filter.d/loki-blocklist.conf.j2`
```
# Extended failregex to match new Traefik reasons
failregex = ^\s*<HOST>\s+(?:ssh-brute-force|scanner-bot|excessive-errors|traefik-rate-limit|traefik-malicious-bot|traefik-aggressive-crawler)\s+attempts=\d+\s*$
```

**Jails removed:** `ansible/plays/roles/system/templates/fail2ban/jail.local.j2`
- `[traefik-access]` - file-based rate limiting
- `[traefik-bots]` - file-based bot detection
- `[traefik-crawler-soft]` - file-based crawler rate limiting

All replaced by `[loki-blocklist]` jail with Loki queries.

### 3. Grafana Dashboards Updated

**HTTP Errors Dashboard** (`monitor/provisioning/dashboards/http-errors.json`)

**Layout changes:**
- Moved 400 & 500 Breakdown pie charts side-by-side (was stacked)
  - 4xx: gridPos x=0, w=12
  - 5xx: gridPos x=12, w=12
- Removed "Error Logs" markdown panel (configuration error message)

**New panels added:**
1. **Top 10 URLs - 4xx Errors** (table, y=14)
   ```logql
   topk(10, sum by (RequestPath) (count_over_time({job="docker",container="traefik.traefik"} | json | DownstreamStatus >= 400 | DownstreamStatus < 500 [$__range])))
   ```

2. **Top 10 URLs - 5xx Errors** (table, y=14)
   ```logql
   topk(10, sum by (RequestPath) (count_over_time({job="docker",container="traefik.traefik"} | json | DownstreamStatus >= 500 [$__range])))
   ```

**Container label updated:** `container="traefik"` → `container="traefik.traefik"`

**Security Dashboard** (`monitor/provisioning/dashboards/security.json`)

Updated 6 Loki queries to use new loki-blocklist approach:
- Traefik Bot Bans: `|~ "fail2ban.*\\[loki-blocklist\\].*Ban.*traefik-malicious-bot"`
- Traefik 4xx Bans: Updated to new pattern
- Crawler Soft Bans: `|~ "fail2ban.*\\[loki-blocklist\\].*Ban.*traefik-aggressive-crawler"`
- Ban Activity Over Time: 3 queries updated

## Critical Fix: Container Label Mismatch

**Issue:** Promtail extracts container name from `__meta_docker_container_name` as `traefik.traefik`, but queries used `container="traefik"`

**Resolution:**
- Updated fail2ban script: 3 queries now use `container="traefik.traefik"`
- Updated HTTP Errors dashboard: 2 queries now use `container="traefik.traefik"`

**Root cause:** Docker Compose creates containers with pattern `{project}.{service}` where:
- Project: `traefik` (directory name)
- Service: `reverse-proxy` (from docker-compose.yml)
- Label: `com.docker.compose.service=reverse-proxy`
- Container name: `traefik.traefik` (Promtail uses directory.service pattern)

## Files Modified

| File | Change Type | Description |
|------|-------------|-------------|
| `traefik/traefik.yaml` | Modified | Removed `accessLog.filePath` for stdout logging |
| `traefik/docker-compose.yml` | Modified | Removed `/var/log/traefik` volume mount |
| `ansible/plays/roles/system/templates/fail2ban/update-blocklist-from-loki.sh.j2` | Modified | Added 3 Traefik query functions, updated container labels |
| `ansible/plays/roles/system/templates/fail2ban/filter.d/loki-blocklist.conf.j2` | Modified | Extended failregex for Traefik reasons |
| `ansible/plays/roles/system/templates/fail2ban/jail.local.j2` | Modified | Removed 3 file-based Traefik jails |
| `monitor/provisioning/dashboards/security.json` | Modified | Updated 6 queries for loki-blocklist pattern |
| `monitor/provisioning/dashboards/http-errors.json` | Modified | Layout redesign, added URL tables, updated container labels |

## Deployment & Verification

**Deployment method:**
```bash
cd ansible
./servyy.sh --limit lehel.xyz
ssh lehel.xyz "sudo sed -i 's/container=\"traefik\"/container=\"traefik.traefik\"/g' /usr/local/bin/blocklist/update-from-loki.sh"
ssh lehel.xyz "docker restart monitor.grafana"
```

**Verification tests:**
1. ✅ Traefik logs visible in Loki: `{job="docker",container="traefik.traefik"}`
2. ✅ JSON parsing working: `| json | DownstreamStatus >= 400`
3. ✅ fail2ban script executing all 6 queries successfully
4. ✅ HTTP Errors dashboard rendering 24 4xx URLs, 1 5xx URL
5. ✅ Security dashboard updated with loki-blocklist queries
6. ✅ File duplication eliminated (no /var/log/traefik/access.log)

**Results:**
- Traefik logs: Streaming to Loki continuously
- fail2ban: Currently blocking 3 SSH + 7 new IPs from latest run
- Dashboards: Operational with correct queries
- Storage: Reduced from 2x to 1x (50% reduction for Traefik logs)

## Impact

**Positive:**
- 50% storage reduction for Traefik access logs
- Unified log pipeline (all Docker logs → Promtail → Loki)
- Extended fail2ban coverage with 3 new Traefik protection patterns
- Better error observability with URL-level tracking
- Simplified architecture (no file-based log management)

**Risks mitigated:**
- Container label mismatch detected and fixed before going unnoticed
- All fail2ban functionality preserved with Loki queries
- Dashboard queries verified working before completion

## Future Improvements

- Consider adding error rate alerts based on URL patterns
- Monitor Loki storage usage with new log volume
- Add dashboard panel for Traefik rate limit violations over time
- Consider implementing IP allowlisting for known good crawlers

## Related Changes

- Built on: [2025-11-23 Logging to Loki Migration](2025-11-23_logging_to_loki_migration.md)
- Extended: fail2ban Loki integration pattern
- Improved: HTTP Errors dashboard from initial creation
