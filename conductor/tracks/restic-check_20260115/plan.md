# Implementation Plan - Backup Verification (Restic Audit)

## Phase 1: Initial Setup
- [~] Task: Initialize Track and Branch
    - [x] Mark task as IN PROGRESS in `plan.md`
    - [x] Create feature branch `claude/restic-audit-20260115`
- [x] Task: Define Audit Parameters
    - [x] List required Restic tags for verification: `home`, `root`
    - [x] Prepare Loki log queries for `restic-backup-home` and `restic-backup-root` (container label or systemd unit)
- [ ] Task: Conductor - User Manual Verification 'Initial Setup' (Protocol in workflow.md)

## Phase 2: servyy-test Audit
- [ ] Task: Molecule Test Verification
    - [ ] Audit existing Molecule tests for Restic roles (`ansible/plays/roles/user/tasks/restic.yml`)
    - [ ] Ensure tests accurately verify backup timer and service creation
    - [ ] Run `molecule test` to validate the baseline automation logic
- [ ] Task: servyy-test Live Validation
    - [ ] Connect to `servyy-test.lxd`
    - [ ] Run `restic snapshots` to confirm daily backups exist
    - [ ] Check `systemctl status restic-backup.timer` (or equivalent)
    - [ ] Verify `monit status` reflects healthy backups on test host
- [ ] Task: Conductor - User Manual Verification 'servyy-test Audit' (Protocol in workflow.md)

## Phase 3: Production Audit & History
- [ ] Task: Production Health Check
    - [ ] Connect to `lehel.xyz`
    - [ ] Verify production Restic snapshots (last 24h)
    - [ ] Perform Loki log audit for production backup success messages
    - [ ] Check Monit dashboard/status for backup alerts or healthy state
- [ ] Task: Document Findings
    - [ ] Present audit results to user
    - [ ] Create history entry `history/2026-01-15_restic-backup-audit.md` summarizing the health of the system
- [ ] Task: Conductor - User Manual Verification 'Production Audit & History' (Protocol in workflow.md)

## Phase 4: Finalization
- [ ] Task: Finalize Track
    - [ ] Stage and commit all findings/test updates
    - [ ] Attach audit summary via `git notes`
    - [ ] Update `plan.md` to COMPLETED with commit SHA
- [ ] Task: Conductor - User Manual Verification 'Finalization' (Protocol in workflow.md)