# ADR: servy load alerts — retire the flapping thresholds, fix what they pointed at

**Date:** 2026-10-30
**Status:** Proposed (rules and compose changes committed; production deploy pending approval)
**Relates to:** [`2026-10-29_servy-memory-pressure.md`](2026-10-29_servy-memory-pressure.md) (the memory caps this tuning is measured against), [`2026-10-29_monitor-restart-policy.md`](2026-10-29_monitor-restart-policy.md) (alerting must not be the blind spot)

## Context

`servy.lehel.xyz` alerted on high load again on 2026-10-30: three times for
`High System Load (5 min)` (05:30, 12:26, 19:24 UTC) and eleven times for
`High System Load (15 min)`. Inspection at 20:39 UTC:

| Signal | Value | Reading |
|---|---|---|
| `node_load5` / `load15` | 6.66 / 6.88 on **4 vCPU** | ~1.7x the core count |
| CPU (today) | 33.6 % user + 13.0 % sys = **46.6 %** busy, iowait 0.3 % | yesterday 48.5 % — unchanged |
| CPU PSI | `some avg300 15.5 %`, `full 0.00 %` | waiting ~15 % of the time, nothing stalls |
| Threads / tasks (`sar plist-sz`) | **1,858** | runqueue 5 average, bursts to 17–20 |
| Swap | **3,497 MiB of 6,441 (54 %)** | up from 1.4 GiB after the 2026-10-29 fix |
| OOM kills | 0 since the 2026-10-29 deploy | 45 containers, none stopped |

So the host is queue-bound, not CPU-bound: it has headroom (53 % idle) and still
prints a load of 2x its cores. `node_load5` counts **runnable threads**, and this box
carries 1,858 of them, which is why the idle baseline is already ~0.8 load per core.

Three separate problems sat behind the alert:

1. **The rules were tuned for an idle host.** `load15 > 3` is 0.75 per core against a
   3.2 all-day baseline; `sum(rate(cpu_total))*100 > 200` is 50 % of a 4-core box against
   a 46.6 % baseline; `swap > 50 %` is where this host parks cold pages permanently.
   By 20:47 UTC the day's alert-state history held **157 annotations**, 27 of them
   `High Total CPU Usage` Pending/Normal pairs — the rules were reporting the
   operating point, not an anomaly.
2. **Healthcheck churn.** Every Docker healthcheck is a `docker exec`: measured **2.8/s**
   (85 `exec_create` events in 30 s) with 19 containers on a **10 s** interval. Each one
   spawns dockerd + containerd + shim + runc and a burst of runnable tasks — `dockerd`
   13 % and `containerd` 11 % of a core, and 13 % of the whole machine in kernel time.
   That churn is a direct contributor to runqueue depth, and the 10 s interval buys
   nothing: `retries` already provides the detection window.
3. **One container is permanently against its memory ceiling.** `leaguesphere.app` sat at
   **854 MiB resident + 963 MiB swap** against `mem_limit: 1g` + the daemon's implicit
   1g swap, with `memory.events max = 5559` — the cgroup was in direct reclaim
   continuously. Six gunicorn workers at ~310 MiB each need ~1.86 GiB; the 1g cap sized on
   2026-10-29 came from a **454M + 334M measurement taken on freshly restarted (cold)
   workers**, which is ~130 MiB each. That container is the largest single source of the
   host's 3.5 GiB of swap, and the next OOM kill.

## Decision

**A. Retune the load/CPU rules so they describe contention instead of baseline**
(`monitor/provisioning/alerting/alert-rules.yml`, group `system-resources-alerts`):

| Rule | Before | After |
|---|---|---|
| `high_load_average_5m` | `node_load5 > 6`, 5m | `node_load5 / cores > 2.0`, **10m** |
| `high_load_average_15m` | `node_load15 > 3`, 5m | `node_load15 / cores > 1.5`, **15m** |
| `high_cpu_total` | `> 200 %` absolute, 10m | **`> 80 %` of capacity**, 15m |
| `high_cpu_system` | `> 20 %`, 5m | `> 30 %`, 10m |
| `high_swap_usage` | `> 50 %`, 10m, medium | `> 80 %`, 15m (cushion nearly gone) |
| `node_cpu_pressure_high` | — | **new**: CPU PSI `> 50 %` for 15m, high |

Load and CPU are now expressed **relative to the host's core count**
(`count without (cpu, mode) (node_cpu_seconds_total{mode="idle"})`), so a resize does not
silently invalidate them, and the numbers mean "per core" rather than raw thread counts.
The new PSI rule is the one that actually describes "the host feels loaded": ~13–16 % on a
healthy day, 56 % during the 2026-10-29 incident, so 50 % for 15m is a real event, and it
still fires when load alone is inconclusive. Thresholds were chosen against the 30-day
load history (baseline 3.2; today's episode peaked at 6.88 load15 = 1.72/core, so the
15-min rule still catches that episode).

**B. Healthcheck intervals 10 s → 30 s** for every container this repository owns that was
still on 10 s (16 of them): `shared` mongo/redis/postgres, `bnb-office` db+web, `groceries`,
`dontforget` mongo+web, `moodle` db, `bumbleflies` bnb/edu/live/www, `energy`,
`leagues-finance`, `finance` importer, `traefik` error-pages. Where the 10 s came from the
image, only `interval:` is set and Docker keeps the image's test.

**C. `leaguesphere.app` fits inside its cap again** (separate repository,
`dachrisch/leaguesphere`, `deployed/docker-compose.yaml`): workers `-w 6` → **`-w 4`**,
`mem_limit` `1g` → **`1500m`** with explicit **`memswap_limit: 2g`**, and
`--max-requests 500 --max-requests-jitter 100` so a worker that has grown from ~130 MiB
cold to ~300 MiB warm is recycled instead of accumulating. That is ~1.25 GiB resident for
4 workers with headroom, and 8 concurrent request slots against a measured peak of ~5 req/s
and ~0.15 cores total container CPU. The three `*.www` frontend containers in the same
repository get the same 30 s interval override.

## Consequences

### Positive
- The two load rules stop alerting at the host's normal operating point; what remains is
  an anomaly signal, plus a PSI rule that measures the symptom users feel.
- Host-wide healthcheck churn drops by roughly 45 % (19 containers on 10 s → 16 on 30 s),
  which removes a measurable part of the runqueue churn and of the 13 % system CPU.
- `leaguesphere.app` stops spending the day in cgroup reclaim and stops dumping ~940 MiB
  of live heap into the host's swap — the largest recoverable chunk of the 3.5 GiB.

### Negative / Tradeoffs
- Unhealthy detection is slower: with `retries: 5`, a dead dependency is now marked
  unhealthy after ~2.5 min instead of ~50 s. No consumer of these checks (the container
  probe, watchtower's blue-green gate) needs better than that.
- Fewer production gunicorn workers (12 → 8 concurrent slots). Request rate and CPU say
  this is ample, but a pathological slow-request burst will now queue earlier.
- `--max-requests` recycles workers, which bounds the symptom (memory creep) and not the
  cause. A per-request leak inside the app would still grow within one worker's lifetime;
  the app-side growth (130 MiB → 300 MiB per worker over ~24 h) is untriaged.

### Known issues
- `leaguesphere_stage.staging-app` and `leaguesphere-demo.demo-app` each burn ~0.14 cores
  with no traffic (two spinning threads per worker, 21 843 + 29 063 ticks accumulated in
  ~1 h). Not addressed here.
- The host is still 4 vCPU / 7.6 GiB for 45 containers. This change removes noise and one
  mis-sized ceiling; it does not add capacity, and the 8 vCPU resize remains the honest
  fix if load stays at 2x cores after the deploy.

## Implementation details

**Files modified (`servyy-container`):**
- `monitor/provisioning/alerting/alert-rules.yml` — MODIFY (5 rules retuned, 1 added)
- `shared/docker-compose.yml`, `bnb-office/docker-compose.yml`, `groceries/docker-compose.yml`,
  `dontforget/docker-compose.yml`, `moodle/docker-compose.yml`, `bumbleflies/docker-compose.yml`,
  `energy/docker-compose.yml`, `leagues-finance/docker-compose.yml`,
  `finance/docker-compose.yml`, `traefik/docker-compose.yml` — MODIFY (healthcheck intervals)
- `history/2026-10-30_load-alert-tuning.md` — NEW (this file)

**Files modified (`leaguesphere`):**
- `deployed/docker-compose.yaml` — MODIFY (workers, caps, `--max-requests`, www interval)
- `deployed/docker-compose.staging.yaml`, `deployed/docker-compose.demo.yaml` — MODIFY (www interval)
- `deployed/README.md` — MODIFY (correct the ~134 MiB/worker figure to ~130 cold / ~300 warm)

**Validation performed:**
- YAML parses for all 11 modified YAML files; `yamllint` reports only the file's
  pre-existing long-annotation warnings.
- Alert rules checked structurally (43 rules, unique UIDs, every `condition` present in
  `data`, every rule has `severity` + `isPaused`) and then **provisioned into a throwaway
  `grafana/grafana:latest`** (the image production runs) with a stand-in `prometheus`
  datasource: all 43 rules loaded, zero provisioning errors, and the six touched rules
  came back with the intended `for`, severity and thresholds.
- Every changed PromQL expression was **evaluated against production Prometheus** before
  committing: load5/core 0.65, load15/core 0.79, CPU-total 43 % of capacity, CPU PSI
  13.9 % — all quiet under the new thresholds, all producing the intended number.
- Interval-only healthcheck override verified on a throwaway image on `codey.lehel.xyz`:
  the container config came back with the **image's test** and `Interval` 30 s, so the
  override is safe for the nine services whose 10 s check lives in their image.
- `docker compose config` accepted the modified `leaguesphere` production compose file
  (command parses as `-w 4`, `mem_limit`/`memswap_limit` accepted).

**Key learnings:**
1. A load threshold on a host with ~1,850 threads measures the host's shape, not its
   health. Always normalise by cores, and prefer PSI (`some avgN`) for "is work waiting".
2. A `mem_limit` sized from a measurement taken just after a restart measures cold
   workers. The 1g cap from 2026-10-29 was based on 130 MiB/worker; warm workers cost
   ~310 MiB, so the cap converted a memory problem into a permanent reclaim loop that then
   showed up as *load*.
3. `memory.events` `max` on a cgroup is the cheapest way to spot "this container's ceiling
   is being hit" — it was 5559 while every memory alert read OK.
4. Docker merges healthcheck config per field: an override with only `interval:` keeps the
   image's `test` (confirmed by experiment, not by reading docs).
