# Automated Apt Package Upgrades

**Date:** 2026-09-08
**Author:** Claude (via user dachrisch)
**Type:** Feature Implementation
**Status:** ✅ Tested on servyy-test.lxd — awaiting production approval

## Summary

Added automated daily package upgrades for both production servers (servy.lehel.xyz, codey.lehel.xyz) using Ubuntu's standard `unattended-upgrades` tool. No such automation existed previously — packages were only updated manually. Follows the same Ansible-role/systemd-timer pattern established by the existing docker-cleanup/kernel-cleanup automation (see [2025-11-27_cleanup-automation.md](2025-11-27_cleanup-automation.md)).

## Requirements (from user)

- Mechanism: `unattended-upgrades` (standard tool, not a bespoke script)
- Scope: all available upgrades, not just security
- Reboot: automatic, but only in a fixed off-peak window between 02:00–06:00 CET

## Solution

- `unattended-upgrades` + `apt-listchanges` installed via the `system` Ansible role
- `/etc/apt/apt.conf.d/50unattended-upgrades` — `Allowed-Origins` includes both `-security` and `-updates` pockets (not `-backports`/`-proposed`); removes unused kernel packages/dependencies; `Automatic-Reboot "true"` with `Automatic-Reboot-Time "05:30"`; `SyslogEnable "true"` so activity reaches Promtail/Loki like other services
- `/etc/apt/apt.conf.d/20auto-upgrades` — turns on the periodic update/upgrade cycle
- A systemd drop-in (`/etc/systemd/system/apt-daily-upgrade.timer.d/override.conf`) pins the stock `apt-daily-upgrade.timer` to a fixed `05:00` daily run (no randomized delay) instead of Ubuntu's default randomized daytime schedule, so it lands after the nightly restic backups (02:00–04:00) and comfortably before the 05:30 reboot cutoff — both times fall inside the requested 02:00–06:00 window

## Files Created

- `ansible/plays/roles/system/tasks/apt_upgrade.yml` — install package, deploy the two apt.conf.d templates, deploy timer override, enable `apt-daily.timer`/`apt-daily-upgrade.timer`
- `ansible/plays/roles/system/templates/50unattended-upgrades.j2`
- `ansible/plays/roles/system/templates/20auto-upgrades.j2`
- `ansible/plays/roles/system/templates/apt-daily-upgrade-timer-override.conf.j2`

## Files Modified

- `ansible/plays/vars/default.yml` — new `apt_upgrade` var block (`enabled`, `run_time: '05:00'`, `reboot_time: '05:30'`)
- `ansible/plays/roles/system/tasks/main.yml` — wired in with tags `system.apt_upgrade`, `system.maintenance`
- `ansible/plays/roles/system/molecule/with-docker/converge.yml` + `verify.yml` — added scenario coverage (package installed, config files exist with expected reboot settings, timer override has the expected run time)
- `CLAUDE.md` — new "Apt Package Upgrades" entry under Cleanup Automation, updated status-check commands

## Testing

Local `molecule test -s with-docker` could not run (this workstation has no local Docker daemon and `Bash(docker:*)` is explicitly denied by project policy — Docker work happens on remote hosts only). Verified instead via a real deployment to `servyy-test.lxd`, scoped with `--tags system.apt_upgrade`:

```bash
cd ansible && ./servyy-test.sh --tags system.apt_upgrade
```

Results:
- First run: `changed=5`, `failed=0` — package installed, both apt.conf.d files deployed, timer override deployed, timers enabled
- Second run (idempotency check): `changed=0`, `failed=0`
- `systemctl status apt-daily-upgrade.timer` confirmed `Trigger: ... 05:00:00 CET` (drop-in honored)
- `sudo unattended-upgrade --dry-run --debug` confirmed the config parses correctly, correctly selects real upgradeable security/updates-pocket packages (e.g. `openssl`, `libssl3t64`), and correctly excludes `-backports` (pinned out, not in `Allowed-Origins`)
- `ansible-lint` (production profile) passed on all new/changed files

## Not Yet Done

- **Production deployment** — requires explicit user approval per this repo's mandatory workflow (`CLAUDE.md` → "CRITICAL DEPLOYMENT RULES"). Deploy with:
  ```bash
  cd ansible && ./servyy.sh --tags system.apt_upgrade --limit servy.lehel.xyz
  cd ansible && ./servyy.sh --tags system.apt_upgrade --limit codey.lehel.xyz
  ```
- **monit monitoring** — unlike docker-cleanup/kernel-cleanup, this task does not yet have a monit log-staleness check, since `unattended-upgrades` manages its own log file/rotation rather than a bespoke one. Not implemented; can be added later if desired (e.g. check `/var/log/unattended-upgrades/unattended-upgrades.log` mtime).

## Technical Decisions

### Why `unattended-upgrades` instead of a bespoke script (like kernel-cleanup.sh)?
User's explicit choice. It's Ubuntu's standard, well-tested mechanism for this exact job — less custom code to maintain than reimplementing apt upgrade logic in bash, and its origin/reboot/logging behavior is configurable via a couple of well-documented apt.conf.d files.

### Why pin `apt-daily-upgrade.timer` instead of leaving Ubuntu's default schedule?
The default (`OnCalendar=*-*-* 6,18:00` with a large `RandomizedDelaySec`) could land anywhere across a wide window, including inside the nightly restic backup window (02:00–04:00) or in the middle of the day. Pinning it to a fixed 05:00 keeps the whole upgrade+possible-reboot cycle inside the user-specified 02:00–06:00 window and clear of backups.

### Why not narrow to security-only updates?
User's explicit choice — all available upgrades, not just security.
