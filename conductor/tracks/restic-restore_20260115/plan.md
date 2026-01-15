# Implementation Plan - Restic Restore Transition

## Phase 1: Setup & Logic Definition
- [x] Task: Initialize Track and Branch abdaf5e
    - [x] Create branch `claude/restic-restore-transition`
- [x] Task: Draft `restic_restore.yml` abdaf5e
    - [x] Create `ansible/plays/roles/user/tasks/includes/restic_restore.yml`
    - [x] Implement logic to detect existing snapshots and restore latest
    - [x] Handle permissions (`owner`, `group`) after restore
- [x] Task: Integration Test (Mock Repo on servyy-test) abdaf5e
    - [x] Create a test playbook `ansible/test_restic_restore.yml`
    - [x] Setup a mock local restic repo inside `servyy-test.lxd`
    - [x] Run the test playbook and verify restoration
- [x] Task: Conductor - User Manual Verification 'Setup & Logic Definition' (Protocol in workflow.md) abdaf5e [checkpoint: abdaf5e]

## Phase 2: Implementation (Git Repos)
- [x] Task: Update `main.yml` for Git Repos abdaf5e
    - [x] Comment out `docker_repo_restore.yml` call for `git/repos`
    - [x] Add `restic_restore.yml` call for `git/repos`
- [x] Task: Verify Git Restore on `servyy-test` abdaf5e
    - [x] Clear `git/repos` on `servyy-test`
    - [x] Run Ansible with `user.docker.restore.git` tag
    - [x] Verify repositories are present and usable
- [x] Task: Conductor - User Manual Verification 'Implementation (Git Repos)' (Protocol in workflow.md) abdaf5e [checkpoint: abdaf5e]

## Phase 3: Implementation (PhotoPrism & Pass)
- [x] Task: Update `main.yml` for Photoprism and Pass abdaf5e
    - [x] Transition `photoprism/database` and `pass/vw-data` to `restic_restore.yml`
- [x] Task: Verify Restores on `servyy-test` abdaf5e
    - [x] Run Ansible and verify data restoration for both services
- [x] Task: Conductor - User Manual Verification 'Implementation (PhotoPrism & Pass)' (Protocol in workflow.md) abdaf5e [checkpoint: abdaf5e]

## Phase 4: Cleanup & Finalization
- [ ] Task: Final Documentation & Checkpoint
    - [ ] Update `history/` with the transition details
    - [ ] Final commit and merge
- [ ] Task: Conductor - User Manual Verification 'Cleanup & Finalization' (Protocol in workflow.md)