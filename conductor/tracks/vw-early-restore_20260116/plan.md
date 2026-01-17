# Implementation Plan - Early Vaultwarden Restore and Deployment

## Phase 1: Setup & Task Extraction
- [x] Task: Initialize Track and Branch
    - [x] Create branch `claude/vw-early-restore`
- [x] Task: Extract Vaultwarden Logic
    - [x] Create `ansible/plays/roles/user/tasks/includes/vw_setup.yml` (Extraction of Compose/Env logic)
    - [x] Create `ansible/plays/roles/user/tasks/includes/vw_restore.yml` (Specialized wrapper for Restic restore)
- [x] Task: Refactor Main Service Loop
    - [x] Update `ansible/plays/roles/user/tasks/main.yml` to use the extracted `vw_setup.yml` for the standard deployment.
- [ ] Task: Conductor - User Manual Verification 'Setup & Task Extraction' (Protocol in workflow.md)

## Phase 2: Standalone Deployment Implementation
- [x] Task: Implement SSL/mkcert Logic for Vaultwarden
    - [x] Add `mkcert` generation tasks to the early setup phase.
- [x] Task: Develop Early Deployment Task
    - [x] Create `ansible/plays/roles/user/tasks/early_vaultwarden.yml`.
    - [x] Implement logic to start a standalone container on a temporary port with `mkcert` certificates.
- [x] Task: Implement CLI Connectivity Verification
    - [x] Add tasks to `early_vaultwarden.yml` to verify connectivity (using `curl` for reliability).
- [ ] Task: Conductor - User Manual Verification 'Standalone Deployment Implementation' (Protocol in workflow.md)

## Phase 3: Test Verification on servyy-test
- [ ] Task: Verify on `servyy-test.lxd`
    - [ ] Deploy the full playbook to the test container.
    - [ ] Verify that Vaultwarden starts early and is accessible via HTTPS.
    - [ ] Confirm that subsequent tasks (e.g., seeding) can communicate with the service.
- [ ] Task: Conductor - User Manual Verification 'Local & Test Verification' (Protocol in workflow.md)

## Phase 4: Finalization & Rollout
- [ ] Task: Documentation & Cleanup
    - [ ] Create history entry `history/2026-01-16_vaultwarden-early-restore.md`.
    - [ ] Ensure all temporary configurations are removed after the full deployment cycle.
- [ ] Task: Production Rollout
    - [ ] Seek user approval for production deployment to `lehel.xyz`.
    - [ ] Execute production deployment.
- [ ] Task: Conductor - User Manual Verification 'Finalization & Rollout' (Protocol in workflow.md)
