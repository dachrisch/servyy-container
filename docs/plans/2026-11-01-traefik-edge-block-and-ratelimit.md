# Traefik edge guard + fast ban: one abusive client must not take the proxy down

> **Status:** implemented 2026-11-01. ADR: `history/2026-11-01_traefik-scan-flood.md`.

**Goal:** make a single abusive client unable to take the whole proxy down — bound what one client may consume, and ban it at the firewall within minutes instead of an hour, without touching the 25 per-service routers.

**What the incident proved (2026-11-01, 06:02–06:33 CET):**

| Observation | Value |
|---|---|
| One source | `49.13.6.173` (Hetzner, AS24940) — 786 of 800 sampled log lines |
| Volume | ~100 000 exploit-probe requests (`/login.php`, `/service/rapture/session`, `/backupsettings.dat`, …) |
| Traefik CPU / memory | 0.02 → **2.0 cores**, 52 → **300 MB** |
| Request duration | p50 **9.8 s** (normally ~50 ms) |
| Host load | 4 → **27** on 4 vCPU |
| External monitors | 5 UptimeRobot checks DOWN 06:11–06:12, flapping UP/DOWN until 06:27 |
| Existing UA limiter | `crawler-ratelimit` fired **9 509** times — and was evaded by User-Agent rotation |
| Ban | applied **07:04** — 31 minutes *after* the flood ended |

Two separate defects: nothing bounded one client, and the ban machinery polled hourly with 1–2 minute windows, so a 31-minute burst fell between two polls.

---

## Part 1 — bound one client (Traefik, entrypoint level)

`security-headers@file` was already attached to the `web`/`websecure` entrypoints, which is the only way to cover all routers without per-service labels. The guard rides the same mechanism.

**`traefik/dynamic.yaml`** (file provider, `watch: true` → hot reload):

```yaml
    edge-ratelimit:
      rateLimit:
        average: 25
        period: 1s
        burst: 50
    edge-inflight:
      inFlightReq:
        amount: 100
    edge-guard:
      chain:
        middlewares:
          - edge-ratelimit
          - edge-inflight
```

**`traefik/traefik.yaml`** (static → one container recreate per host):

```yaml
      middlewares:
        - security-headers@file
        - edge-guard@file
        - error-pages@file
```

Order matters: `security-headers` stays outermost so the 429s the limiter produces still carry HSTS/nosniff. The `metrics` entrypoint stays bare so Prometheus scrapes stay raw.

**No Traefik blocklist.** `ipBlockList` was removed in Traefik v3; 3.7 answers `field not found, node: ipBlockList` and then drops the *entire* file provider config (rehearsed, see below). Address blocking belongs to fail2ban, which drops packets before the TLS handshake — cheaper than any proxy-level check.

## Part 2 — ban fast (fail2ban + Loki)

The `loki-blocklist` jail already existed and already banned `49.13.6.173` — just too late. Two changes in `ansible/plays/roles/system/templates/fail2ban/`:

1. **`update-blocklist-quick.service/.timer` + `quick` mode** — the short-window queries (429 flood, request rate, crawler) now run every 2 minutes; the 24 h queries (SSH, scanner UAs, secret probes) stay hourly, because they are expensive and have no short-term meaning.
2. **New flood trigger** — `get_rate_flood_ips()`: ≥ 200 responses with `DownstreamStatus="429"` per client in 2 minutes ⇒ `traefik-rate-flood`. The limiter from Part 1 is what produces them, so this is an exact signal rather than an inference from load.
3. **Thresholds retuned** (they were calibrated for hourly sampling, and 10 req/min is below a normal page view): request rate 10 → 600/min, crawler 20 → 200/2 min.
4. **`log()` writes to stderr.** It used to write to stdout, and the result loops read a query function's stdout through a process substitution — so each function's own log line was consumed as a result row and written back into the blocklist file as `<date> 2026-11-01 [blocklist] Querying …` (77 such lines were in the file). A result-IP shape check is now the second line of defence.

---

## Verification

**Off-host rehearsal** — throwaway `traefik:3.7` + `traefik/whoami` on codey, docker provider absent, the repo's real middleware definitions:

| Test | Result |
|---|---|
| single request | `200` |
| security headers on 200 | `strict-transport-security`, `x-content-type-options: nosniff` ✔ |
| 100 parallel requests, same UA | 74 × 200, 26 × 429 |
| 100 parallel requests, **rotating UA** | 75 × 200, 25 × 429 (proves IP-keyed, not UA-keyed) |
| headers on a shed 429 | present (order of the chain is right) |
| request after the burst | `200` (bucket refills, no stuck state) |
| `ipBlockList` in the file | `ERR field not found, node: ipBlockList` → whole config dropped → **removed from the design** |

**Script** — rendered with the real Jinja vars, `bash -n` clean, then dry-run on servy in `quick` mode against the live Loki with the blocklist path redirected to `/tmp`:

| Check | Result |
|---|---|
| output | `Added 13.66.174.80 (traefik-aggressive-crawler attempts=477)` — a real no-UA scraper walking `/gamedays/gameday/652/game/…` at ~4 r/s |
| junk entries | none (was 77 before the stderr fix) |
| real blocklist log | untouched |

**Production** (after deploy): see the ADR.

## Rollback

| Situation | Action |
|---|---|
| limiter too tight (real 429s) | raise `average`/`burst` in the host's `dynamic.yaml` → hot reload (~3 s), then commit the same edit |
| guard must go, right now | edit the host's `dynamic.yaml`: empty the `edge-guard` chain (`middlewares: []`) → hot reload |
| ban too aggressive | `/etc/systemd/system/update-blocklist-quick.timer` → `systemctl disable --now update-blocklist-quick.timer`, and `fail2ban-client set loki-blocklist unbanip <ip>` |
| full revert | `git revert <sha>` + `--tags user.docker.repo,user.docker.monitor,user.docker.traefik` + `docker compose up -d --force-recreate` on both hosts |

## Known limits

- **Distributed floods are not covered.** Both controls are per source IP; a botnet rotating through hundreds of addresses is a different problem (Volume-based mitigation or a WAF).
- **A NAT'd office shares one bucket** — 25 r/s sustained is still generous for humans.
- **An IP that is already banned is skipped by the poller**, so a client banned for 24 h is invisible to the queries until the ban expires; if it resumes afterwards, it is banned again within 2 minutes.
