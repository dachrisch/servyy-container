# ADR: LeagueSphere maintenance probe — retry transient stalls instead of alerting on them

**Date:** 2026-10-31
**Status:** Accepted (deployed to `servy.lehel.xyz`)
**Commit:** `e69be50` (PR [#257](https://github.com/dachrisch/servyy-container/pull/257), merge `b849371`)
**Relates to:** [`2026-08-11_leaguesphere-maintenance-probe-design`](../docs/superpowers/specs/2026-08-11-leaguesphere-maintenance-probe-design.md) (the probe this changes), [`2026-10-30_monitor-provisioning-render-trap.md`](2026-10-30_monitor-provisioning-render-trap.md) (the trap this deploy hit again)

---

## Context

The medium alert **`LeagueSphere Maintenance Probe Failing`** mailed repeatedly on
2026-10-31 — four emails for two incidents, for a site that was healthy throughout.

Traefik/Loki evidence (31 days of logs, ~2,800 probe requests):

| time (CET) | request | Traefik status | duration |
|---|---|---|---|
| 15:00:46 | `GET /health/` | `499` | 14.8 s |
| 17:00:50 | `GET /api/game-progress/?page_size=100` | `499` | 14.9 s |

`499` is the probe hanging up at its own `--max-time 15`, not the app failing. The
probe pushed `leaguesphere_probe_success=0` for that run; the rule then waits
`for: 10m` and fires — and because the gauge is only refreshed **hourly**, the `0`
stays visible for the rest of the hour, so the alert kept firing ~50 minutes and
sent a second (resolve) mail. No container restarts, no DB errors, and the very next
hourly run was green.

Root cause was **alert design, not availability**: one 15 s ceiling, one attempt per
hour, a boolean that means "both endpoints are fine", and an alert whose firing
window is longer than the gap between samples.

## Decision

Keep the hourly cadence (no extra load on a host already running 45 containers) and
make a *single* slow response unable to produce an alert:

1. **Retry inside the run.** Each endpoint gets 3 attempts, 5 s apart
   (`--retry 2 --retry-delay 5 --retry-all-errors --retry-connrefused`), so timeouts,
   5xx and a restarting frontend all retry. Worst case 3×15 s + 2×5 s = **55 s** per
   endpoint.
2. **`-f` on `/health/`**, so a 5xx is retried and counted as a failure instead of
   being parsed as a non-JSON body.
3. **Per-endpoint gauges** `leaguesphere_health_probe_success` /
   `leaguesphere_games_probe_success` — diagnosis without reading the journal.
   `leaguesphere_probe_success` keeps its old meaning (both checks OK) so no
   dashboard or alert semantics moved, and the `blocking` fail-safe is untouched
   (maintenance active + games state unknown ⇒ `blocking=1`).
4. **`TimeoutStartSec=300`** on the unit, via a new optional `service.timeout_start`
   in the shared oneshot template (backwards compatible: omitted ⇒ nothing emitted),
   because two stalled endpoints plus the push can exceed systemd's 90 s default for
   `Type=oneshot`.
5. **Push failures are visible.** The script now exits non-zero when the Pushgateway
   `PUT` fails; previously the trailing `echo` masked it with exit 0.
6. **The alert text says what the rule means** ("failed every retry — 3 attempts per
   endpoint, ~1 minute of trying") instead of "for 10+ minutes", which only described
   the `for:` duration.

The alert therefore now means *three consecutive failed attempts over ~a minute* — a
real problem — instead of *one request that missed its deadline*.

## Verification

Rendered script against a stub origin on `servy` (`bash -n` plus four scenarios,
pushing to a throwaway job `leaguesphere_maintenance_probe_selftest`, deleted after):

| scenario | result | attempts |
|---|---|---|
| fast origin | `health=1 games=1 probe=1`, 0.12 s | 1 + 1 |
| `/health/` stalls > 15 s | `health=0 games=1 probe=0`, 55.1 s | **3** health, 1 games |
| games API stalls > 15 s | `health=1 games=0 probe=0`, 55.2 s | 1 health, **3** games |
| games stalls + maintenance active | `blocking=1` (fail-safe preserved) | 3 games |

Production after deploy:

- `systemctl --user cat ls-maintenance-probe.service` → `TimeoutStartSec=300`.
- One manual run: `maintenance_active=0 active_games=0 blocking=0 health_success=1
  games_success=1 probe_success=1`, `Result=success`, `ExecMainStatus=0`.
- Pushgateway exposes all six gauges; Prometheus has
  `leaguesphere_probe_success = leaguesphere_health_probe_success =
  leaguesphere_games_probe_success = 1`.
- Timer still `enabled` + `active`, next run on the hour.

## Deploy notes / what went wrong on the way

1. **Fresh-clone deploy key regression (fixed).** The deploy ran from a clean clone of
   `master` (the long-lived checkout has git-crypt re-encryption drift that blocks
   `git pull`). That clone had no `ansible/plays/vars/.servyy_container_deploy_key`
   seed (it is untracked), so `github_deploy_key.yml` **generated a new key and
   overwrote the host's registered deploy key** — the next `git fetch` failed with
   `Permission denied (publickey)`. The PAT cannot add repo deploy keys (`HTTP 403`).
   Recovered by copying the *registered* key (fingerprint `SHA256:IFnvl2kTBckqYo37uqL8WF9Zcya3TNvDBfdhOz4aoCc`,
   title `servyy-container-repo-sync`) from `codey`'s
   `/home/cda/.ssh/id_servyy_container_deploy` into the seed path and re-running the
   deploy, which restored it on the host.
   **Lesson:** any deploy controller must carry that seed file; a bare clone silently
   rotates the host key.
2. **Monitor provisioning render trap, again.** `--tags user.docker.repo` fast-forwards
   the host checkout, which reverts the three *rendered* monitor files to raw Jinja.
   Restarting Grafana afterwards crash-looped it on
   `Datasource provisioning error: yaml: unmarshal errors: line 23`.
   Fixed by running `--tags user.docker.monitor` (re-renders promtail/datasources/
   contact-points and restarts the stack) — see
   [`2026-10-30_monitor-provisioning-render-trap.md`](2026-10-30_monitor-provisioning-render-trap.md).
   **Rule for next time:** `user.docker.repo` and `user.docker.monitor` must be deployed
   together, never repo-sync alone followed by a Grafana restart.
3. **Unit change needed a daemon-reload.** The role's `systemd` task only starts the
   timer; a changed unit file stays unloaded until `systemctl --user daemon-reload`
   (so `TimeoutStartSec` was inert until done by hand). The task now sets
   `daemon_reload: yes`.

## Duplicate probes

- **Removed on `codey.lehel.xyz`** (leftover from an earlier tag-scoped deploy): it ran
  hourly, probed *production*, and pushed to a Pushgateway that does not exist there
  (`localhost:9091`), so it could never alert. Commands:

  ```bash
  systemctl --user disable --now ls-maintenance-probe.timer
  rm -f ~/.config/systemd/user/ls-maintenance-probe.{service,timer} ~/.backup-scripts/ls-maintenance-probe.sh
  systemctl --user daemon-reload
  ```

  The play already `end_host`s hosts without LeagueSphere enabled, so this cannot
  reappear through a normal deploy.
- **A third prober remains unidentified.** Traefik/Loki shows a second pair of
  `ls-maintenance-probe` user-agent requests in some hours (e.g. 14:01:09, 15:05:09,
  16:05:09, 17:04:09 CET) arriving from `172.18.0.1`. Likely `servyy-test.lxd` running
  the role with the default production URL. Not reachable from the opencode container,
  so it is documented only; if the test host should be probed too, pass
  `-e ls_maintenance_probe_url=https://stage.leaguesphere.app` when deploying there.

## Known issues found, not fixed here

- **Grafana admin password drift.** `GF_SECURITY_ADMIN_PASSWORD` from vault no longer
  matches the password stored in Grafana's DB (Grafana applies the env value only on
  first init), so `admin:<vault value>` gets `401` on the API. The vault value was
  already newer than the DB before this work; re-rendering `grafana.env` made the
  mismatch visible. Align if wanted with
  `docker exec monitor.grafana grafana cli admin reset-admin-password <vault value>`.
- `restic-backup-home.service` fails hourly with `exit_code=3` on `servy` (unrelated,
  observed while checking the probe journal).
