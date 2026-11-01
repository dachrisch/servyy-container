# ADR: Traefik edge guard + fast bans — one client must not take the proxy down

**Date:** 2026-11-01
**Status:** Accepted (deployed to `servy.lehel.xyz` and `codey.lehel.xyz`)
**Commit:** see the PR that carries this file (`feat(traefik): per-client edge guard + fast fail2ban path`)
**Relates to:** [`2026-10-29_traefik-security-headers.md`](2026-10-29_traefik-security-headers.md) (the entrypoint-middleware mechanism this reuses), [`2026-10-30_monitor-provisioning-render-trap.md`](2026-10-30_monitor-provisioning-render-trap.md) (why `user.docker.monitor` never travels alone)

---

## Context

Between **06:02 and 06:33 CET** on 2026-11-01 every hostname behind Traefik on
`servy.lehel.xyz` became unreachable. Five UptimeRobot monitors mailed DOWN/UP, and
the hourly LeagueSphere probe failed. Nothing restarted, no disk filled, DNS and TLS
were fine.

One source did it:

| Evidence | Value |
|---|---|
| Source | `49.13.6.173` (Hetzner, AS24940) — 786 of 800 sampled log lines in a flood minute |
| Volume | ~100 000 requests in 31 min (~50–75 r/s sustained) across *all* vhosts |
| Paths | `/login.php`, `/service/rapture/session`, `/backupsettings.dat`, `/index.php?route=/…` — an exploit-probe wordlist |
| Traefik CPU | 0.02 → **2.0 cores** of 4 |
| Traefik memory | 52 → **300 MB** |
| Request duration | p50 **9.8 s** (baseline ~50 ms), p90 11.1 s |
| Host load | 4 → **27** |
| UptimeRobot | DOWN 06:11–06:12, then flapping UP/DOWN until 06:27 |

Two independent defects:

1. **Nothing bounded one client.** The entrypoints carried `security-headers` and
   `error-pages` and nothing else, so a single source could consume the whole proxy.
   There *was* a `crawler-ratelimit` middleware (10 r/s, burst 20) on 9 routers — it fired
   **9 509** times during the hour and still did not help, because it keys on
   `User-Agent` and the scanner rotated UAs (Safari 14/16, `JFrogArtifactory/…`). It is a
   crawler control, not flood protection.
2. **The ban was an hour too late.** The `loki-blocklist` fail2ban jail *did* ban
   `49.13.6.173` — at **07:04**, 31 minutes after the flood stopped. Its poller ran hourly
   and its flood-relevant queries looked at `[1m]`/`[2m]` windows, so a 31-minute burst
   between two polls was invisible to them; only the `[24h]` queries caught it
   retrospectively.

## Decision

**Bound the client at the entrypoint** (Traefik), and **ban it at the firewall within
minutes** (fail2ban). Each layer covers what the other cannot.

### 1. `edge-guard` chain on both entrypoints

`traefik/dynamic.yaml` (file provider, hot):

```yaml
    edge-ratelimit:
      rateLimit: {average: 25, period: 1s, burst: 50}   # per client IP
    edge-inflight:
      inFlightReq: {amount: 100}                        # per client IP
    edge-guard:
      chain: {middlewares: [edge-ratelimit, edge-inflight]}
```

`traefik/traefik.yaml` (static, one recreate per host):

```yaml
      middlewares:
        - security-headers@file
        - edge-guard@file
        - error-pages@file
```

`security-headers` stays **outermost** so the limiter's 429s also carry HSTS/nosniff.
The `metrics` entrypoint stays bare so Prometheus scrapes stay raw. No per-service
labels — that is why the entrypoint list, not the 25 routers, is the right place.

**Why 25 r/s / burst 50:** the scanner sustained 50–75 r/s; a browser opens ~6
connections and pulls a few dozen assets. 25 r/s with a 50-request burst sheds the
former and never touches the latter.

**There is deliberately no proxy-level blocklist.** `ipBlockList` was *removed* in
Traefik v3: 3.7 answers `field not found, node: ipBlockList` and then discards the whole
file provider configuration, so every hostname drops to the catchall 404. This was
caught in the rehearsal, not in production. Address blocking stays with fail2ban, which
drops the packets **before** the TLS handshake — cheaper than any proxy-level check.

### 2. A fast ban path

In `ansible/plays/roles/system/templates/fail2ban/`:

* **`quick` mode + `update-blocklist-quick.timer`** — the short-window queries
  (`traefik-rate-flood`, `traefik-rate-limit`, `traefik-aggressive-crawler`) run every
  **2 minutes**; the expensive `[24h]` queries (SSH brute force, scanner UAs, secret
  probes) stay on the hourly timer.
* **New flood trigger** — ≥ 200 responses with `DownstreamStatus="429"` per client in
  2 minutes ⇒ `traefik-rate-flood`. The limiter from (1) produces them, so this is an
  exact "this client is being shed" signal, not an inference from load or latency.
* **Thresholds retuned** (they were calibrated for hourly sampling, and 10 req/min is
  below a normal page view — a silent false-positive generator): request rate 10 → 600/min,
  crawler 20 → 200/2 min. Calibration from live traffic: the busiest *legitimate* client
  did 171 429s per **day**; real scrapers sit at 130–270 req/2 min; the flood did
  **9 304** 429s in one hour.

### 3. A bug found on the way

`log()` wrote to **stdout**, and each query function's stdout is consumed through a
process substitution — so every function's own log line was read as a result row and
written back into the blocklist file as `2026-11-01 2026-11-01 [blocklist] Querying …`.
77 such lines were in `/var/log/fail2ban-loki.log`. `log()` now writes to stderr, and
`add_ips()` rejects any "IP" that is not an IPv4 address.

## Verification

**Off-host rehearsal** (throwaway `traefik:3.7` + `traefik/whoami` on codey, docker
provider absent, the repo's real middleware definitions — never against live traffic):

| Test | Result |
|---|---|
| single request | `200` |
| security headers on 200 | HSTS + `nosniff` present |
| 100 parallel, same UA | 74 × 200, 26 × 429 |
| 100 parallel, **rotating UA** | 75 × 200, 25 × 429 — IP-keyed, so UA rotation does not help |
| headers on a shed 429 | present (chain order correct) |
| request after the burst | `200` — bucket refills, no stuck state |
| `ipBlockList` in the file | `ERR field not found, node: ipBlockList` → config dropped → **removed from the design** |

**Poller dry run** (rendered template, `bash -n` clean, run on servy in `quick` mode with
the blocklist path redirected to `/tmp`):

| Check | Result |
|---|---|
| detection | `Added 13.66.174.80 (traefik-aggressive-crawler attempts=477)` — a real no-UA scraper walking `/gamedays/gameday/652/game/…` at ~4 r/s |
| junk entries | none (77 before) |
| real blocklist log | untouched |

**Baseline before the change** (`monitor.lehel.xyz`, no middleware labels):
100 parallel requests with the same UA → `100 302`; with rotating UAs → `100 302`. No
per-source limit existed.

**Production** — recorded in the PR body: normal vhosts keep answering, a rotating-UA
burst now yields 429s, the quick timer is active on both hosts, and the LeagueSphere
probe and UptimeRobot stay green.

## Known issues found, not fixed here

* **Grafana admin password drift** — the vault `GF_SECURITY_ADMIN_PASSWORD` does not match
  the password in Grafana's database (Grafana applies the env only on first init), so the
  alert API returns 401. Unknown whether `High System Load (5 min)` (expression
  `node_load5/cores > 2`) reached the inbox during the 6.7-cores-per-vCPU flood: the
  alert *should* have fired around 06:12. Needs an admin reset or a Grafana CLI password
  change — deliberately not done unilaterally.
* **Distributed floods are not covered.** Both controls are per source IP; a botnet
  rotating addresses is a Volume/WAF problem, not a rate-limit problem.
* **86 IPs were banned** at the time of writing, several by the old 10 req/min and
  20 req/2 min thresholds — i.e. some of those may be legitimate clients that happened to
  load a page during an hourly sample. The retuned thresholds stop that from recurring;
  existing bans expire within 24 h.
* `restic-backup-home.service` still fails hourly with `exit_code=3` (unrelated).
