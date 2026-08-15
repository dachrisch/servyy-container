# PR #63 — Monit→Grafana `system_probe` Migration — Merge & Production Deploy

**Date:** 2026-08-15
**Status:** ✅ Merged, fixed, tested on servyy-test.lxd, deployed to production (`lehel.xyz`), verified working.
**Repo:** `servyy-container`

## Background

PR #63 migrated four remaining Monit sub-projects (system resources, log-freshness,
storagebox, container health) to the probe → Pushgateway → Grafana alert pattern already
established by `ls_maintenance_probe`. New `system_probe` role
(`ansible/plays/roles/system_probe/`), three user-scoped systemd timers, new Grafana alert
rule groups in `monitor/provisioning/alerting/alert-rules.yml`, and the corresponding old
Monit check templates deleted (SSHD monitoring intentionally stays on Monit — process
supervision/auto-restart is a different job). All 21 CI checks passed; merged via merge commit
`b8a9363`.

## Bugs found during test-first verification (both fixed, tested, merged to `master`)

1. **`b1f53fe`** — Invalid systemd `OnCalendar` syntax. The role used cron-style `*/N` step
   syntax (`*-*-* *:*/30:00`, `*-*-* *:*/5:00`) which systemd's calendar spec rejects
   (`BadUnitSetting`) — it requires `value/N` form (`0/30`, `0/5`), matching the convention
   already used elsewhere in this repo (`docker-photo-index.timer` → `00/2:30:00`). First
   servyy-test.sh run aborted mid-deploy on this.
2. **`b4781b5`** — All three new probe scripts used `set -euo pipefail`, so a failed
   Pushgateway push (`curl -sf`) aborted the whole script instead of just reporting
   `probe_success=0` — turning a soft metric-push failure into a hard systemd unit `Failed`
   state (confirmed via manual trigger on servyy-test with no Pushgateway reachable there:
   `status=7` on all three). Fixed by dropping `-e` (`set -uo pipefail` + explanatory comment),
   matching the existing `ls_maintenance_probe.sh.j2` pattern exactly ("each step handles its
   own failure explicitly so a problem can't abort the script before it pushes anything").

Both fixes verified on servyy-test.lxd before proceeding: timers create/start with valid
next-elapse times, all three services exit `status=0` and reach their final `echo
probe_success=...` line even without Pushgateway reachable.

## Production deployment

Ran `./servyy.sh --limit lehel.xyz` (**untagged, full run** — see process note below).
`PLAY RECAP: ok=489 changed=78 unreachable=0 failed=1 skipped=173`.

**`system_probe` — fully successful, verified on `lehel.xyz`:**
- All Ansible tasks: `ok`/`changed`, zero failures
- All three timers (`system-log-freshness`, `system-storagebox`, `system-container-health`)
  active with valid schedules, each already fired once on its own timer before manual checks
- Manual trigger + journal check: all three exit `status=0`, report
  `log-freshness probe_success=1`, `storagebox mounted=1 usage_pct=35 probe_success=1`,
  `container-health all_running=1 probe_success=1`
- Pushgateway confirms metrics landing (`push_failure_time_seconds=0` for all three jobs),
  including per-container running-state gauges for every service on the host
- `monitor.grafana` restarted (`docker restart monitor.grafana`) to load the new alert-rules
  provisioning file — came back healthy, no provisioning errors in the startup log. (Grafana
  hadn't restarted since Aug 12, three days before this deploy, and this project's own
  documented pitfall notes provisioning changes need a restart to take effect.)

**The one recap failure — unrelated, pre-existing, left alone by user request:**
`ls_db_migrate` (`plays/leaguesphere.yml`) failed exporting from an external LeagueSphere DB
host (`s207.goserver.host`, user `web35_8`) — "Access denied," stale/rotated credentials on
that external host. Failed at the very first step (mysqldump), before any import — no partial
state written. User confirmed this is a known issue with an old external server, not to be
touched this session.

## Process note: untagged full deploy triggered unrelated LeagueSphere roles

Running `./servyy.sh --limit lehel.xyz` with no `--tags` runs *every* play in `servyy.yml`,
including `leaguesphere.yml`'s `ls_db_sync` (tags `ls.db.sync`/`ls.app.stage`/`ls.app` — always
included in a full run) and `ls_db_migrate` (tag `ls.db.migrate`, commented "tag-only, not in
default ls run" — but `servyy.sh` passes no default `--skip-tags`, so that comment doesn't
actually hold). For a change scoped entirely to `system.yml`/monitor alerting, this should have
been a tagged run (`--tags system,docker` or similar) per CLAUDE.md's own targeted-deployment
example. Consequence: `ls_db_sync` refreshed the staging LeagueSphere DB from production as an
unintended side effect (confirmed harmless/expected behavior by user — staging-from-prod
refresh happens on every full deploy by design), and `ls_db_migrate` failed as described above.
Because a task failure removes a host from the rest of the run, everything after that point in
`leaguesphere.yml` was skipped for `lehel.xyz` — but everything the actual change needed
(`system.yml`, `user.yml`, `opencode_authgate.yml`, `restic.yml`, all of `system_probe` +
alert-rules.yml placement) had already completed earlier in the play order, so the deployment's
actual goal was unaffected. Saved as project memory
(`feedback_scoped_deploy_tags`) for future deploys.

## Validation: did Grafana actually take over, and was Monit actually retired?

Asked explicitly after the initial deploy, since "no errors in the Grafana startup log" isn't
proof the new rules are live. Checked properly:

- **Grafana — confirmed active**, not just "loaded without error": queried its own
  unauthenticated `/metrics` endpoint (`grafana_alerting_rule_group_rules`,
  `grafana_alerting_schedule_alert_rules`) directly on `lehel.xyz`. All four new groups
  scheduled and active — `container-health-alerts` (4 rules), `log-freshness-alerts` (3),
  `storagebox-alerts` (4), `system-resources-alerts` (10 active + 1 paused) — 33 rules total
  scheduled, 0 currently firing.
- **Monit — NOT actually retired.** `monit.yml` only manages the files it currently generates
  (`sshd`/`log`/`status`/`alert`); it never had a `state: absent` task for the templates PR #63
  deleted, so the *old* `system-check`, `storagebox-check`, and 12 `container-check-*` files
  (one per compose project) were still sitting in `/etc/monit/conf.d/`, still "Monitored"/
  "active" — running in full parallel with the new probes. Caught live: Monit's `System 'servy'`
  check showed "Resource limit matched" (15-min load average 3.36) at the same moment
  `system-resources-alerts` in Grafana was evaluating the identical condition.

## Follow-up: `monit_cleanup` role (commit `205c54b`)

New role `ansible/plays/roles/monit_cleanup/` finds and removes the stale
`system-check`/`storagebox-check`/`container-check-*` files and restarts Monit. Wired into
`system.yml` tagged **both** `monit.cleanup` and `never` — unlike `ls_db_migrate`'s
non-functional "tag-only" comment (see process note above), the `never` tag actually excludes
it from any run that doesn't explicitly pass `--tags monit.cleanup`, confirmed by testing a
normal tagged run and seeing the role not execute.

Tested on `servyy-test.lxd` first (which had the same 14 stale files): removed all of them,
Monit restarted cleanly, re-run showed `changed=0` (idempotent). Committed straight to `master`
(no PR — same pattern as the two bug-fix commits above) and pushed as `205c54b`. Deployed to
production scoped to just this tag: `./servyy.sh --tags monit.cleanup --limit lehel.xyz` —
`ok=14 changed=2 failed=0`. Verified on `lehel.xyz`: `/etc/monit/conf.d/` now contains only
`alert`, `log`, `sshd`, `status`; `monit status` shows only SSHD-related checks. Monit is now
genuinely retired from system/storagebox/container-health monitoring — Grafana has full,
non-duplicated ownership of those checks.

## Left as-is (by explicit user decision, not fixed this session)

- `ls_db_migrate`'s external-host credential failure and its "tag-only" comment not actually
  being enforced (no `never` tag) — known, left for a future session. (Note: `monit_cleanup`
  above demonstrates the correct fix pattern — add `never` — for whenever this is revisited.)
- `servyy-test.lxd` has some general network flakiness independent of this PR (a dead sshfs
  mount on one test run, a `git.lehel.xyz` submodule fetch timeout on another) — not
  investigated further, out of scope.

## Post-deployment cleanup

- Remote branch `origin/monit-to-grafana-migration` — already auto-deleted by GitHub on merge
  (this repo has auto-delete-on-merge enabled); local stale tracking ref pruned.
- Empty 0-byte `/tmp/ls_prod_seed_*.sql` left by the failed `ls_db_migrate` task on `lehel.xyz`
  — root-owned, harmless, not worth a sudo escalation to remove; left in place.

## Session closed 2026-08-15

`system_probe` is live on production and verified working end-to-end (timers → probes →
Pushgateway → Grafana alert rules loaded and actively evaluating, confirmed via Grafana's own
metrics). Monit is now genuinely retired from the four migrated check areas — no more duplicate
coverage. Both bugs found during test-first verification, plus the `monit_cleanup` follow-up,
are fixed and merged to `master`. Remaining open items above are explicitly deferred per user
direction, not carried as unfinished work.
