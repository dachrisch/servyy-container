# Implementation Plan - Refactor Restic Check to use Loop

## Phase 1: Implementation
- [x] Task: Initialize Track and Branch
    - [x] Create branch `claude/restic-check-refactor`
- [x] Task: Create Sub-task File
    - [x] Create `ansible/plays/roles/testing/tasks/_restic_check_single.yml` containing the core logic
- [x] Task: Refactor Main Task File
    - [x] Update `ansible/plays/roles/testing/tasks/restic_check_recent.yml` to loop over `['home', 'root']` and include the sub-task
- [x] Task: Conductor - User Manual Verification 'Implementation' (Protocol in workflow.md) [checkpoint: Phase 1 Complete]

## Phase 2: Verification
- [x] Task: Verify on `servyy-test.lxd`
    - [x] Run `ansible-playbook ... --tags testing.restic.check_recent`
    - [x] Confirm both repositories are checked and successful
- [x] Task: Conductor - User Manual Verification 'Verification' (Protocol in workflow.md) [checkpoint: Phase 2 Complete]

## Phase 3: Finalization
- [x] Task: Final Document and Merge
    - [x] Update `history/`
    - [x] Final commit and merge
- [x] Task: Conductor - User Manual Verification 'Finalization' (Protocol in workflow.md) [checkpoint: Phase 3 Complete]
