# Implementation Plan - Manual Backup Verification

## Phase 1: Task Implementation
- [x] Task: Initialize Track and Branch
    - [x] Create branch `claude/restic-check-task`
- [~] Task: Develop `restic_check_recent.yml`
    - [ ] Create `ansible/plays/roles/user/tasks/restic_check_recent.yml`
    - [ ] Implement `restic snapshots --json` parsing logic
    - [ ] Add `assert` tasks for < 24h validation
- [ ] Task: Integrate Task into User Role
    - [ ] Include the new task file in `ansible/plays/roles/user/tasks/main.yml`
    - [ ] **Critical:** Assign tags `['never', 'user.restic.check_recent']` to the inclusion.
- [ ] Task: Conductor - User Manual Verification 'Task Implementation' (Protocol in workflow.md)

## Phase 2: Local & Test Verification
- [ ] Task: Verify Manual Trigger Only
    - [ ] Run a standard ansible task (e.g., `--tags user.atuin`) and confirm `restic_check_recent` is skipped.
- [ ] Task: Verify on `servyy-test.lxd`
    - [ ] Run `ansible-playbook ... --tags user.restic.check_recent`
    - [ ] Confirm success with current snapshots
- [ ] Task: Conductor - User Manual Verification 'Local & Test Verification' (Protocol in workflow.md)

## Phase 3: Finalization
- [ ] Task: Document and Merge
    - [ ] Create history entry `history/2026-01-15_manual-backup-check-task.md`
    - [ ] Final commit and merge to master
- [ ] Task: Conductor - User Manual Verification 'Finalization' (Protocol in workflow.md)
