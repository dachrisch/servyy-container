# 2026-10-08 — Restic ls-db 4-week outage: stale-lock recovery + snapshot-age monitoring

## Status

- **Backup health (verified live on `servy`)**: home ✅ ( snapshot today 20:03),
  root ✅ (today 00:04), ls-db ✅ recovered (new snapshot `eb4c17b0` today
  20:25, hourly runs flowing again, `restic check` passes all 3 repos).
- **Code (branch `claude/restic-snapshot-age-monitoring`)**: snapshot-age probe +
  Grafana rules + testing coverage. Probe deploys from the working tree, so it
  is **already live on prod** (metrics flowing). Alert-rules ship via the
  `servyy-container` git checkout on prod → go live on merge + `git pull` +
  `docker restart monitor.grafana`.

## Problem

`restic-ls-db` (LeagueSphere prod DB) had **zero successful backup, forget, or
check for ~4 weeks** (last snapshot 2026-09-10 04:05). Every hourly backup,
daily forget, and weekly check failed identically:

```
repository is already locked exclusively by PID 1753602 on servy by cda
lock created 2026-09-10 05:01:40 (~687h ago)
```

No restic process was running — the lock was stale. home/root were unaffected
(separate repos/locks). SFTP storage healthy (36% used) — backup-health issue,
not disk.

## Root cause (from `/var/log/restic/forget.log`)

1. 2026-09-10 05:01:40 — daily `restic-forget` started `--prune` on the db repo,
   taking an **exclusive** lock.
2. Mid-repack (33/57 packs) restic received **SIGTERM** (`signal terminated
   received, cleaning up`), then the SSH/SFTP connection dropped while removing
   the lock (`connection lost`, `exit status 255`) → lock file never deleted.
3. A **second forget instance started 05:01:51** (11s later — no concurrency
   guard on the oneshot service) and the same minute saw a DNS outage
   (`Could not resolve hostname u318127.your-storagebox.de`).
4. Exact killer (reboot/OOM/manual) unrecoverable after 4 weeks (no journal
   retention) — but the structural defects are fixed regardless (below).

## Why nothing alerted (3 gaps, all fixed)

1. **ls-db was never monitored at all.** The log-freshness probe
   (`system_probe_log_checks`) and the `stale_maintenance_log` Grafana rule
   covered home/root/forget/check — but not `restic-backup-ls-db`. Fixed: ls-db
   log added to both.
2. **Log-mtime cannot detect backup failure.** The failing script still writes
   `Starting restic backup` + error hourly, so mtime stays fresh forever. This
   failure mode is invisible to freshness monitoring *by design*. Fixed: new
   `system-restic-snapshots.sh` probe pushes the **newest-snapshot age per repo**
   (`restic snapshots --latest 1 --json --no-lock`; `--no-lock` so the probe
   keeps reporting even under a stale exclusive lock), with a new
   `restic-snapshot-alerts` Grafana group (db stale = **high** >2h, home/root =
   medium, plus probe-failing/probe-stale). Thresholds mirror
   `system_probe_restic_repos` in `system_probe/defaults/main.yml`.
3. **Manual verification skipped db.** `testing/restic_check_recent.yml`
   looped only home+root. Fixed: db check added, guarded by
   `/etc/restic/env.db` existence so repo-less hosts skip cleanly.

Deliberately NOT done: auto-`unlock` in the backup path. Removing locks
automatically risks killing a legitimately running prune; hourly retries plus
a <2h alert make manual recovery (`restic unlock` after confirming no process)
the safe response. Recovery runbook: `ps` for restic → `restic list locks` →
`restic unlock` → trigger `restic-backup-ls-db.service` → run
`restic-forget` + `restic-check` to clear the backlog and verify integrity.

## Test-first verification

- `servyy-test.lxd`: `./servyy-test.sh --tags system.probe` → ok=39 failed=0;
  script renders (`bash -n` clean), exits 0 with `probe_success=1` and no
  Pushgateway (PR #63 precedent), timer `*:0/30:00` validates via
  `systemd-analyze calendar`. Jinja matrix (db enabled/disabled) verified
  locally. (`testing.restic.check_recent` cannot run on test — pre-existing:
  no repos configured there; fails at home before reaching db.)
- Prod (scoped `--tags system.probe,user.docker.monitor --limit
  servy.lehel.xyz`): ok=45 failed=0. Live metrics confirm real parsing against
  restic output: `db 624s / home 1976s / root 73919s`, `probe_success 1`.
  `restic-check` after recovery: all repos pass (interrupted prune caused no
  corruption). NOTE: `user.docker.monitor` only renders env + `compose state:
  present` — it does **not** sync `monitor/provisioning` (bind-mounted from the
  `/home/cda/servyy-container` master checkout), hence the merge+pull step.

## Follow-up (on merge)

1. Merge PR → `git pull` in `/home/cda/servyy-container` on servy →
   `docker restart monitor.grafana` → confirm 37 rules scheduled via
   `docker exec monitor.grafana wget -q -O- http://localhost:3000/metrics`
   (`grafana_alerting_rule_group_rules`, look for `restic-snapshot-alerts`).
2. Optional: after the next 05:00 forget + Sunday check run green, consider a
   `Conflicts=`/flock guard so hourly backup and daily forget never contend —
   currently tolerated (one failed hour, retry next) but it produced the
   original collision window.
