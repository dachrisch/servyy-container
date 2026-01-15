# Track Specification: check backup creation with restic on servyy-test and prod.

## Overview
This track involves a comprehensive verification of the Restic backup system across both the test (`servyy-test.lxd`) and production (`lehel.xyz`) environments. The goal is to ensure that backups are being created continuously, and that the health monitoring systems (Loki and Monit) are accurately reflecting the status of these backups.

## Goals
- Confirm the presence and frequency of Restic snapshots on both environments.
- Verify that automated backup timers/services are active and triggering as expected.
- Validate that observability tools (Loki logs and Monit status) correctly report backup success and health.

## Functional Requirements
- **Snapshot Verification:** Execute `restic snapshots` to confirm daily backups exist for both environments within the last 24 hours.
- **Log Audit:** Query Loki logs for patterns from `restic_backup.sh` to confirm successful executions and capture any warnings.
- **Monitoring Health:** Check `monit status` on both hosts to ensure the backup monitoring tasks are initialized and reporting "OK".
- **Continuous Check:** Verify that the systemd timers or cron jobs responsible for the backups are enabled and active.

## Acceptance Criteria
- [ ] Confirmed valid Restic snapshots exist for both `servyy-test` and production from the last 24 hours.
- [ ] Loki log analysis shows consistent "backup successful" entries with no recent errors.
- [ ] Monit status reports all backup-related checks as healthy on both environments.
- [ ] A summary of the current backup state (last snapshot date, repository health) is documented.

## Out of Scope
- Triggering manual restores (unless a critical failure is detected).
- Modifying the backup schedule or retention policies.
- Upgrading the Restic binary version.
