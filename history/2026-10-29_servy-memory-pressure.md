# 2026-10-29 — servy memory pressure: 702 OOM kills in a week, none of them alerted on

## Summary

`servy.lehel.xyz` (4 vCPU / 7.6 GiB) was running at a sustained load average of ~6,
2.4–3.3 GiB of swap in use, and had **702 cgroup OOM kills in the previous seven days —
100 % of them inside `moodle.moodle`**. The kernel was killing php-fpm workers on the
live Moodle site, and no alert existed for it: the dashboards had been gone since the
05:30 reboot (fixed earlier today in
[`2026-10-29_monitor-restart-policy.md`](2026-10-29_monitor-restart-policy.md)), and
every existing rule watched load, MemFree percentage, swap *usage* and disk — none of
which describes "a container ran out of memory".

This entry covers the four fixes applied here plus the one that has to land in a
different repository (LeagueSphere worker count).

## Measurements (2026-10-29, 18:30 CET, host up 13 h)

| Metric | Value | Reading |
|---|---|---|
| Load average | `5.86 / 3.44 / 2.92`, day average `6.04 / 5.47 / 5.20` | ~1.5× oversubscribed on 4 cores, all day — not a spike |
| Memory | 4.6 GiB used, **185–250 MiB free**, 3.1 GiB available (page cache) | no real headroom |
| Swap | **2.4 GiB** of 6.3 used (`sar` day average 43 %) | steady-state backing store, not an emergency cushion |
| PSI memory | some `avg60 0.38 %`, full `avg60 0.25 %`, 615 s fully stalled since boot | moderate now, spikes under load |
| PSI cpu | some `avg10 56 %` | CPU contention is the binding constraint at that moment |
| OOM kills (7 d) | **702**, all `oom_memcg=/system.slice/docker-9f2c7e1c…` = `moodle.moodle` | user-facing 502s for a week |

Per-container working set (resident + swap, limit):

```
leaguesphere_stage.staging-app   645M +   0   no limit
leaguesphere-demo.demo-app       579M +   0   no limit   ← 50 % of a core at the time
leaguesphere.app                 454M + 334M  no limit
shared.mongo                     285M +  88M  no limit
monitor.grafana                  285M +  38M  no limit
monitor.loki                     200M +  40M  no limit
monitor.prometheus               192M +  21M  no limit
traefik.traefik                  152M +  11M  no limit
photoprism.mariadb               144M + 132M  no limit
moodle.moodle                    105M + 9.2M 768M limit   ← OOM-killed 702×
moodle.db                         99M + 304M 768M limit   ← a third of the buffer pool in swap
leaguesphere.db                   73M + 233M no limit
photoprism.photoprism             52M +  63M 1536M limit
```

## Root causes

1. **Moodle could not fit in its own limit.** The image
   (`erseco/alpine-moodle:v4.5.15`) ships `/etc/php83/php-fpm.d/www.conf` with
   `pm = ondemand` and `pm.max_children = 100`, and `app.env` set
   `memory_limit=512M` per worker — inside `mem_limit: 768m`. Two or three concurrent
   real course pages and the cgroup killer fired. Nothing an app-level config could
   tune: the ceiling was the container limit.
2. **`moodle.db` was swapping its buffer pool.** A 256 M InnoDB pool inside a 768 M
   limit, yet 304 MiB of that container was in swap — every course page paid disk
   latency for its own hot data.
3. **Only two containers had a limit at all** (moodle and photoprism). Instead of a
   bounded failure, the kernel relieved pressure by pushing cold-but-hot-path pages of
   `leaguesphere.app` (334 MiB), `leaguesphere.db` (233 MiB) and stage MySQL (146 MiB)
   to swap.
4. **`vm.swappiness` was effectively 60, not 1.** The Ansible task wrote
   `value: "1"` to `/etc/sysctl.conf`, but systemd-sysctl only reads `/etc/sysctl.d/*.conf`
   unless `/etc/sysctl.conf` is symlinked as `/etc/sysctl.d/99-sysctl.conf` — it is not on
   this host. The file had said `vm.swappiness=1` since 3 June and the running kernel
   said 60 the whole time.
5. **Three full gunicorn stacks on prod hardware.** Prod, stage and demo each ran
   `-w 6 --threads 2` at ~134 MiB/worker ≈ 0.8 GiB each; stage + demo are dev
   environments consuming ~1.2 GiB and most of a core for ~no traffic.

## Changes applied in this repository

### A. Moodle fits inside its limit again

`moodle/docker-compose.yml`:
- app `mem_limit: 768m` → **`1.5g`** (5 workers × 256 M + nginx + the image's cron loop)
- db `mem_limit: 768m` → **`1g`** (256 M pool + connections + working set of the imported
  dataset), so the pool stops being swapped out

`moodle/php-fpm-limits.conf` (new), bind-mounted read-only at
`/etc/php83/php-fpm.d/zz-limits.conf`:
```
[www]
pm.max_children = 5
pm.max_requests = 500
pm.process_idle_timeout = 10s
```
`php-fpm.conf` has `include=/etc/php83/php-fpm.d/*.conf`, so `zz-` sorts after the image's
`www.conf` and wins. The image does not template the pm settings from env (verified via
`grep -rn max_children` in the container), which is why a bind mount was the only option
short of a custom image.

`ansible/plays/roles/docker_service/templates/moodle.app.env.j2`:
- `memory_limit` **512M → 256M** (Moodle's requirement is 128–256 M)
- added `opcache_memory_consumption=128`; opcache itself stays **off** (`opcache_enable=0`,
  the image default) — the budget is declared so that turning it on later cannot silently
  eat the container limit.

Worst case is now 5 × 256 M + nginx + cron ≈ 1.35 G inside 1.5 G, instead of
100 × 512 M inside 768 M.

### B. Ceilings on the big consumers

Chosen at roughly 1.5× the measured working set, so a leak fails loudly inside one
container instead of pushing every other container's hot pages to swap:

| Service | Limit | File |
|---|---|---|
| `moodle.moodle` | 1.5g | `moodle/docker-compose.yml` |
| `moodle.db` | 1g | `moodle/docker-compose.yml` |
| `shared.mongo` | 512m | `shared/docker-compose.yml` |
| `monitor.prometheus` | 768m | `monitor/docker-compose.yml` |
| `monitor.loki` | 512m | `monitor/docker-compose.yml` |
| `monitor.grafana` | 384m | `monitor/docker-compose.yml` |
| `traefik.reverse-proxy` | 256m | `traefik/docker-compose.yml` |
| `leaguesphere.app` | 1g | **other repo** — see below |
| `leaguesphere.db` | 512m | **other repo** — see below |
| stage / demo apps | 512m each | **other repo** — see below |

**Deviation from the reviewed plan: `photoprism.photoprism` was left at 1536M**, not
lowered to 1g. The file's own header (lines 4–5, from upstream) warns that "setting a
memory/swap limit can cause unexpected restarts, when the indexer temporarily needs more
memory to process large files", and the container currently keeps 63 MiB of a 52 MiB
working set in swap. The indexer is the one workload here that genuinely spikes; a 1g cap
risks killing it mid-scan. It keeps the existing 1536M `deploy.resources.limits.memory`
and is the single item of the reviewed plan not tightened.

### D. `vm.swappiness` 60 → 20, and it now survives a reboot

`ansible/plays/roles/system/tasks/swap.yml`:
```yaml
- name: set swappiness
  sysctl:
    name: vm.swappiness
    value: "20"
    sysctl_file: /etc/sysctl.d/99-swappiness.conf
    reload: true
```
20, not the previously coded 1: swappiness 1 is a database-server setting, and on a
45-container app host it makes reclaim drop page cache instead of swapping genuinely cold
pages. 60 was letting the kernel swap hot pages of a 7.6 GiB host. 20 keeps swap for cold
pages and emergencies. `sysctl_file` is the actual fix for the persistence bug — the task
had been reporting `changed` for months while writing to a file systemd never reads.

`vm.overcommit_memory` stays at 0 (the safe default).

### E. The failure mode is now alertable

Five rules appended to the existing `system-resources-alerts` group (folder
`Infrastructure`) in `monitor/provisioning/alerting/alert-rules.yml`:

| Rule | Severity | Expression | For |
|---|---|---|---|
| `container_oom_killed` | critical | `sum by (name) (increase(container_oom_events_total{name!=""}[30m])) > 0` | 1m |
| `node_memory_pressure_full` | critical | `rate(node_pressure_memory_stalled_seconds_total[5m]) * 100 > 5` | 5m |
| `node_memory_pressure_some` | high | `rate(node_pressure_memory_waiting_seconds_total[5m]) * 100 > 10` | 10m |
| `node_swap_out_thrash` | high | `rate(node_vmstat_pswpout[5m]) > 500` | 15m |
| `container_memory_near_limit` | medium | working-set / limit `> 0.9` for capped containers | 15m |

Notes on the tuning, all measured against the live Prometheus before being committed:
- `increase()` over 30 m, not `rate()`: OOM kills are discrete and rare, a rate rounds
  them to zero.
- PSI thresholds are ~20× the observed baseline (0.2–0.5 %), so they fire on the
  condition, not on normal reclaim. PSI is used rather than `MemFree` percentage because
  `MemFree` sits at ~200 MiB permanently by design (page cache owns the rest) while work
  stalls — that is exactly why the old memory rule was quiet through 702 kills.
- `rate(node_vmstat_pswpout[5m])` was ~250 pages/s during the incident, so the 500 page/s
  threshold fires at roughly double today's steady state rather than immediately.
- `container_memory_near_limit` filters `container_spec_memory_limit_bytes > 0` and
  `< 1e12` to drop the sentinel value cAdvisor reports for uncapped containers, so it only
  evaluates `moodle.moodle`, `moodle.db`, `photoprism.photoprism` and the bnb-office pair.
- All five use the existing `prometheus` datasource uid and route through
  `notification-policies.yml` (critical → `email-critical`, high/medium → `email-admin`).

## Not in this repository — LeagueSphere worker count (C) and its limits

`leaguesphere_stage` and `leaguesphere-demo` are deployed from a **separate repository**
(`dachrisch/leaguesphere`, `deployed/docker-compose{,.staging,.demo}.yaml`) via the
`ls_app` role into git checkouts in the deploy user's home. Changing gunicorn there is a
change in that repo, not here:

- `deployed/docker-compose.staging.yaml` + `deployed/docker-compose.demo.yaml`:
  `gunicorn -w 6 --threads 2` → **`-w 1 --threads 2`** (~−120 MiB and most of the CPU each;
  these are dev environments with ~no traffic). Production keeps `-w 6`.
- `mem_limit` for the three apps and their databases per the table above.

This entry will be updated (or a follow-up written) when that lands.

## Verification

Pending deployment. Checklist:

```bash
# A + D
ssh lehel.xyz 'sysctl vm.swappiness'                     # → vm.swappiness = 20
ssh lehel.xyz 'cat /etc/sysctl.d/99-swappiness.conf'     # → vm.swappiness = 20

# A — the limit and the pool override are both live
ssh lehel.xyz "docker inspect moodle.moodle --format '{{.HostConfig.Memory}}'"   # → 1610612736
ssh lehel.xyz 'docker exec moodle.moodle grep -h "^pm" /etc/php83/php-fpm.d/zz-limits.conf'
ssh lehel.xyz 'docker exec moodle.moodle php -i | grep memory_limit'             # → 256M

# B
ssh lehel.xyz 'docker inspect shared.mongo monitor.prometheus monitor.loki monitor.grafana traefik.traefik moodle.db --format "{{.Name}} {{.HostConfig.Memory}}"'

# A — the actual goal: no new moodle OOM kills
ssh lehel.xyz "sudo journalctl -k --since '24 hours ago' | grep -c oom-kill"
ssh lehel.xyz "docker exec monitor.grafana curl -s -G --data-urlencode \
  'query=sum by (name) (increase(container_oom_events_total{name=~\".+\"}[1h]))' \
  http://prometheus:9090/api/v1/query"                   # → all zeros, moodle.moodle absent

# E — rules loaded and evaluating
curl -s https://monitor.lehel.xyz/api/health | head
# Grafana → Alerting → Alert rules → Infrastructure → "Container OOM Kill" (Normal, not Error)
```

Also worth re-reading after ~24 h: `sar -q` load average (target < 4 on 4 cores) and
`sar -S` swap usage (target: falling, not flat at 2.4 GiB).

## Why not just add RAM

4 vCPU / 8 GiB for 45 containers including two MariaDBs, MySQL, MongoDB, Postgres, Loki
and Prometheus is genuinely undersized, and a Hetzner step up (8 vCPU / 16 GiB) remains
the honest ceiling. It is not the first move: every cause above is a configuration defect
that costs nothing to fix, and the fixes above were applied first so that a resize is a
capacity decision rather than a way to keep masking a container that OOMs itself.
