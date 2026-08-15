# Monit → Grafana Migration (Steps 2–5)

## Context

Step 1 (ls_maintenance_probe) established the reusable pattern: **host-level probe script → Pushgateway → Grafana alert**.
This design migrates the remaining 4 Monit sub-projects using the same pattern. See
[step 1 design](2026-08-11-leaguesphere-maintenance-probe-design.md#roadmap-context-this-is-step-1-of-a-larger-monit--grafana-migration).

| Sub-project | Source | Strategy |
|---|---|---|
| System resources (load/mem/swap/CPU, root + extension disk) | node-exporter metrics already scraped | Grafana alert rules from node-exporter (no new probes) |
| Log-freshness (restic + cleanup scripts) | `check file ... if timestamp > N` | Host probe → Pushgateway → Grafana (`system_log_freshness`) |
| Storagebox (mount presence + space) | `check filesystem / check program` | Host probe → Pushgateway → Grafana (`system_storagebox`) |
| Container health (per-service running-state) | `check program ... check_docker_compose-*.sh` | Host probe → Pushgateway → Grafana (`system_container_health`) |
| **SSHD** | `check process sshd` | **Stays on Monit permanently** — process supervision + auto-restart, a different job |

All three probes live in a single role `system_probe` (three systemd user timers), reusing the
same `oneshot.service.j2` / `oneshot.timer.j2` templates as `ls_maintenance_probe`.

> **Debounce parity note:** Monit's default cycle is ~2 minutes (OS package default; never
> declared in-repo). Grafana's `for:` windows in this migration assume that value: "1 cycle"
> ≈ `for: 2m`, "2 cycles" ≈ `for: 5m`, "4 cycles" ≈ `for: 10m`. If the Monit cycle is ever
> changed, these debounce values should be revisited.

## 1. System Resources — node-exporter Grafana alerts

Already scraped via `monitor/docker-compose.yml` node-exporter service. Monit thresholds (`monit.system.check.j2`):

### Load
```
Monit: if loadavg (5min) > 6 for 2 cycles then alert
       if loadavg (15min) > 3 for 2 cycles then alert
```
→ node-exporter `node_load5`, `node_load15` → Grafana alerts.

### Memory
```
Monit: if memory usage > 80% for 4 cycles then alert
```
→ `(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100 > 80` → Grafana alert.

### Swap
```
Monit: if swap usage > 50% for 4 cycles then alert
```
→ `(node_memory_SwapTotal_bytes - node_memory_SwapFree_bytes) / node_memory_SwapTotal_bytes * 100 > 50` → Grafana alert.

### CPU
```
Monit: if cpu usage (user) > 80% for 2 cycles then alert
       if cpu usage (system) > 20% for 2 cycles then alert
       if cpu usage (wait) > 80% for 2 cycles then alert
       if cpu usage > 200% for 4 cycles then alert
```
→ `sum by (instance) (rate(node_cpu_seconds_total{mode="user|system|iowait"}[5m])) * 100` →
Grafana alerts. Rules: `high_cpu_user` (>80%, 5m), `high_cpu_system` (>20%, 5m),
`high_cpu_iowait` (>80%, 5m), `high_cpu_total` (user+system+iowait >200%, 10m). Total mirrors
Monit's "including user, system and wait" semantics.

### Disk
```
Monit: root if space usage > 90% then alert / > 95% for 2 cycles then alert
       extension volume if has_10g_volume: > 80% / > 85% for 2 cycles
```
→ `high_root_disk_usage` (`>90%`, `for: 2m` ≈ 1 cycle) plus escalation tier
`critical_root_disk_usage` (`>95%`, `for: 5m` ≈ 2 cycles, critical).
For the extension volume: the existing `high_disk_usage` alert (infrastructure-alerts) already
covers every mounted filesystem at <15% free (≈ >85% used). Monit's stricter `has_10g_volume`
>80% tier is preserved as a **dormant** rule `extension_disk_high_usage` (`isPaused: true`,
`mountpoint!="/"`, >80%) — a host with a secondary physical volume should unpause it. Dormant
because `alert-rules.yml` is provisioned statically (not templated per-host) and lehel.xyz has
`has_10g_volume: false`.

## 2. Log-Freshness — `system_log_freshness` probe (part of `system_probe` role)

Host-level probe (systemd timer + script) that checks the timestamp of log files written by restic
backup scripts and docker/kernel cleanup cron jobs, pushes to Pushgateway.

### Log files and thresholds (from `monit.system.check.j2`)

```
Monit: check file docker_cleanup_log    with path /var/log/docker-cleanup.log     if timestamp > 8 days then alert
       check file kernel_cleanup_log    with path /var/log/kernel-cleanup.log     if timestamp > 32 days then alert
       check file restic_backup_home_log path {{ restic.logs.backup_home }}       if timestamp > 2 hours then alert
       check file restic_backup_root_log path {{ restic.logs.backup_root }}       if timestamp > 25 hours then alert
       check file restic_forget_log     path {{ restic.logs.forget }}             if timestamp > 25 hours then alert
       check file restic_check_log      path {{ restic.logs.check }}              if timestamp > 8 days then alert
```

The per-log thresholds are configured via `system_probe_log_checks` (defaults/main.yml), each entry
having `name`, `path` and `threshold_seconds`. The script pushes the age for every log plus a
probe_success gauge; **the thresholds themselves are evaluated in Grafana** (per-log threshold rule).

### Metrics pushed (job `system_log_freshness`)

| Metric | Type | Meaning |
|---|---|---|
| `system_log_freshness_seconds{log="docker-cleanup"}` | gauge | Age of the file in seconds |
| `system_log_freshness_seconds{log="kernel-cleanup"}` | gauge | Age of the file in seconds |
| `system_log_freshness_seconds{log="restic-backup-home"}` | gauge | Age of the file in seconds |
| `system_log_freshness_seconds{log="restic-backup-root"}` | gauge | Age of the file in seconds |
| `system_log_freshness_seconds{log="restic-forget"}` | gauge | Age of the file in seconds |
| `system_log_freshness_seconds{log="restic-check"}` | gauge | Age of the file in seconds |
| `system_log_freshness_probe_success` | gauge | 0/1 — whether the script ran completely |

### Grafana alert rules

| Rule | Condition | for | severity |
|---|---|---|---|
| `stale_maintenance_log` | freshness_seconds > threshold (per-log) | 10m | medium |
| `log_freshness_probe_failure` | probe_success == 0 | 10m | medium |
| `log_freshness_probe_stale` | time() - push_time_seconds > 5400 | 1m | medium |

Schedule: every 30min (gives headroom for 2h restic home check).

## 3. Storagebox — `system_storagebox` probe (part of `system_probe` role)

Host-level probe that checks storagebox mount presence and space usage.

### Monit config (from `monit.storagebox.check.j2`)
```
check program storagebox-mounted with path "/bin/mountpoint -q {{ storagebox.mount }}"
    if status != 0 then alert
check filesystem storagebox with path {{ storagebox.mount }}
    if space usage > 50% then alert
```

### Metrics pushed (job `system_storagebox`)

| Metric | Type | Meaning |
|---|---|---|
| `system_storagebox_mounted` | gauge | 0/1 — is the storagebox mount present |
| `system_storagebox_usage_pct` | gauge | disk usage percentage |
| `system_storagebox_threshold_pct` | gauge | configured threshold (default 50) |
| `system_storagebox_probe_success` | gauge | 0/1 |

### Grafana alert rules

| Rule | Condition | for | severity |
|---|---|---|---|
| `storagebox_unmounted` | storagebox_mounted == 0 | 5m | critical |
| `storagebox_high_usage` | storagebox_usage_pct > 50 | 5m | medium |
| `storagebox_probe_failure` | storagebox_probe_success == 0 | 10m | medium |
| `storagebox_probe_stale` | time() - push_time_seconds > 5400 | 1m | medium |

Schedule: hourly.

## 4. Container Health — `system_container_health` probe (part of `system_probe` role)

Monit currently deploys a bespoke script per docker-compose service. Rather than deriving absence
from cAdvisor time-series (fragile), we mirror the Monit script but publish to Pushgateway.

### Monit config (from `monit.container.check.j2`)
```
check program "Docker Service {{ service.name }}" with path "/etc/monit/scripts/check_docker_compose-{{ service.dir }}.sh"
    with timeout 30 seconds
    if status != 0 for 2 cycles then alert
    group docker
```

### Container health probe

Container names are resolved from each service's `docker-compose.yml` at deploy time
(`docker.local_dir` + `docker.services`), skipping services tagged `manual` (same filtering as the
Monit script). The script runs `docker container inspect --format '{{.State.Running}}'` per container.

| Metric | Type | Meaning |
|---|---|---|
| `system_container_running{name="...",service="..."}` | gauge per container | 0/1 — is the container running |
| `system_container_all_running` | gauge | 0/1 — all monitored containers running |
| `system_container_health_probe_success` | gauge | 0/1 — did the probe script complete |

### Grafana alert rules

| Rule | Condition | for | severity |
|---|---|---|---|
| `container_not_running` | container_running < 0.5 (unfiltered gauge) | 2m | medium |
| `containers_all_down` | container_all_running == 0 | 5m | critical |
| `container_health_probe_failure` | container_health_probe_success == 0 (e.g. Docker daemon unreachable) | 10m | medium |
| `container_health_probe_stale` | time() - push_time_seconds > 5400 | 1m | medium |

Schedule: every 5 minutes.

## Summary of changes

### New
- `monitor/provisioning/alerting/alert-rules.yml` — add groups: `system-resources-alerts`,
  `log-freshness-alerts`, `storagebox-alerts`, `container-health-alerts`
- `ansible/plays/roles/system_probe/` — consolidated probe role: `system_log_freshness`,
  `system_storagebox`, `system_container_health` (defaults, tasks, templates + oneshot include)
- Wire `system_probe` role into `ansible/plays/system.yml`

### Removed
- `ansible/plays/roles/system/tasks/monit.yml` — remove system check, storagebox check, container check sections
  (keep SSHD, logging, http, alert email sections)
- `ansible/plays/roles/system/templates/monit.system.check.j2` — removed
- `ansible/plays/roles/system/templates/monit.storagebox.check.j2` — delete
- `ansible/plays/roles/system/templates/monit.container.check.j2` — delete
- `ansible/plays/roles/system/templates/check_docker_compose.sh.j2` — delete

### Kept on Monit
- `monit.sshd.check.j2` — SSHD process monitor + auto-restart
- `monit.log.j2` — Monit log config
- `monit.status.j2` — Monit HTTP status
- `monit.alert.j2` — Monit email alert
