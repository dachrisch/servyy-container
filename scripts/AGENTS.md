# scripts/ — host-side operational scripts

One-off helpers run from the controller or a host. None of these are deployed as
services; the cleanup timers below are configured by Ansible (`system` role).

## Scripts

| Script | Purpose |
|---|---|
| `cleanup_space.sh` | Disk space cleanup helper |
| `delete_test_container.sh` | Remove the servyy-test LXD container |
| `disable_systemd_services.sh` | Disable unwanted host services |
| `dns-layout.sh` | Render the DNS layout; `PORKBUN_ACCOUNT=<name>` (default `dachrisch`) picks the Porkbun account |
| `index-photos.sh`, `index-photos-batch.sh` | PhotoPrism indexing |
| `opencode-pair.sh` | Pair an OpenCode app/browser with codey |
| `provision-oracle-codey.sh`, `provision-oracle-runner.sh` | Oracle cloud host provisioning |
| `setup_test_container.sh`, `servyy-test.yaml`, `setup_test_runner_vm.sh` | Test environment bootstrap |
| `startup_docker_services.sh`, `status_docker_services.sh` | Host-level Docker service helpers |
| `watch-staging.sh` | Staging watcher |
| `etc/` | Miscellaneous configuration snippets |

`setup_test_container.sh` must run before `ansible/servyy-test.sh` on a fresh controller.

## Cleanup Automation

**Automated disk space management** (deployed via Ansible):

**Journal Logs** (declarative):
- Config: `/etc/systemd/journald.conf.d/retention.conf`
- Limit: 500MB max, 4-week retention
- No manual intervention required

**Docker Cleanup** (weekly on servy/codey; daily on runny):
- Schedule: Every Sunday at 02:00 CET (servy/codey); runny's rootless daemon is pruned daily 02:00 by the `runner` user's `docker-prune.timer` instead (`systemctl --user status docker-prune.timer`)
- Mode: Aggressive (`docker system prune -a -f --volumes`)
- Removes all unused images, containers, volumes
- Log: `/var/log/docker-cleanup.log` (servy/codey only)
- Monitoring: monit alerts if log not updated in 8 days (servy/codey only; runny has no root-run docker_cleanup)

**Kernel Cleanup** (monthly):
- Schedule: 1st Sunday of each month at 01:00 CET
- Removes old kernel packages (preserves current kernel)
- Script: `/usr/local/bin/kernel-cleanup.sh`
- Log: `/var/log/kernel-cleanup.log`
- Monitoring: monit alerts if log not updated in 32 days

**Apt Package Upgrades** (daily, both servy.lehel.xyz and codey.lehel.xyz):
- Mechanism: `unattended-upgrades` (Ubuntu's standard tool), configured via `ansible/plays/roles/system/tasks/apt_upgrade.yml`
- Scope: all available upgrades (`-security` and `-updates` pockets), not security-only
- Run time: 05:00 CET daily (`apt-daily-upgrade.timer`, pinned via a systemd drop-in so it's not randomized into the 02:00-04:00 nightly restic backup window)
- Reboot: only if a reboot-requiring upgrade (e.g. new kernel) was installed, at a fixed time of 05:30 CET (`Unattended-Upgrade::Automatic-Reboot-Time`) — this briefly restarts all Docker containers on that server
- Config: `/etc/apt/apt.conf.d/50unattended-upgrades`, `/etc/apt/apt.conf.d/20auto-upgrades`
- Log: `/var/log/unattended-upgrades/unattended-upgrades.log` (also mirrored to syslog → Promtail/Loki)

**Check cleanup status:**
```bash
# View cleanup/upgrade timers
ssh lehel.xyz "systemctl list-timers | grep -E 'cleanup|apt-daily'"

# Check Docker cleanup logs
ssh lehel.xyz "tail -50 /var/log/docker-cleanup.log"

# Check kernel cleanup logs
ssh lehel.xyz "tail -50 /var/log/kernel-cleanup.log"

# Check apt upgrade logs
ssh lehel.xyz "sudo tail -50 /var/log/unattended-upgrades/unattended-upgrades.log"

# Verify monit monitoring
ssh lehel.xyz "sudo monit status | grep cleanup"
```

## Reference

- [Root AGENTS.md](../AGENTS.md) — deployment workflow and DNS architecture.
