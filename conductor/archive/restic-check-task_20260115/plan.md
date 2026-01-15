# Implementation Plan - Manual Backup Verification

## Phase 1: Task Implementation
- [x] Task: Initialize Track and Branch c893396
    - [x] Create branch `claude/restic-check-task`
- [x] Task: Develop `restic_check_recent.yml` c893396
    - [x] Create `ansible/plays/roles/user/tasks/restic_check_recent.yml` (moved to testing)
    - [x] Implement `restic snapshots --json` parsing logic
    - [x] Add `assert` tasks for < 24h validation
- [x] Task: Integrate Task into User Role c893396
    - [x] Include the new task file in `ansible/plays/roles/testing/tasks/main.yml`
    - [x] **Critical:** Assign tags `['never', 'testing.restic.check_recent']` to the inclusion.
- [x] Task: Conductor - User Manual Verification 'Task Implementation' (Protocol in workflow.md) c893396 [checkpoint: c893396]

## Phase 2: Local & Test Verification
- [x] Task: Verify Manual Trigger Only c893396
    - [x] Run a standard ansible task (e.g., `--tags user.ping`) and confirm `restic_check_recent` is skipped.
- [x] Task: Verify on `servyy-test.lxd` c893396
    - [x] Run `ansible-playbook ... --tags testing.restic.check_recent`
    - [x] Confirm success with current snapshots
- [x] Task: Conductor - User Manual Verification 'Local & Test Verification' (Protocol in workflow.md) c893396 [checkpoint: c893396]

## Phase 3: Finalization
- [x] Task: Document and Merge c893396
    - [x] Create history entry `history/2026-01-15_manual-backup-check-task.md`
    - [x] Final commit and merge to master
- [x] Task: Conductor - User Manual Verification 'Finalization' (Protocol in workflow.md) c893396 [checkpoint: c893396]
