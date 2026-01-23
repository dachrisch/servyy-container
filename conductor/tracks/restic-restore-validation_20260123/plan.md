# Implementation Plan: Restic Restore Validation & Fixes

## Phase 1: Investigation & Backup Verification

- [x] Task 1.1: Create feature branch `claude/restic-restore-validation`
- [x] Task 1.2: Verify restic snapshots exist for all services
  - [x] Subtask 1.2.1: Check home backup snapshots for git/repos path
  - [x] Subtask 1.2.2: Check home backup snapshots for photoprism/database path
  - [x] Subtask 1.2.3: Check home backup snapshots for pass/vw-data path
  - [x] Subtask 1.2.4: Document snapshot counts, dates, and sizes
- [x] Task 1.3: Analyze current restic_restore.yml implementation
  - [x] Subtask 1.3.1: Review restore logic and conditionals
  - [x] Subtask 1.3.2: Identify potential issues (permissions, paths, error handling)
  - [x] Subtask 1.3.3: Document findings in track notes
- [x] Task 1.4: Review backup configuration
  - [x] Subtask 1.4.1: Verify backup schedules are active
  - [x] Subtask 1.4.2: Check recent backup logs for errors
  - [x] Subtask 1.4.3: Document backup frequency and retention
- [ ] Task: Conductor - User Manual Verification 'Phase 1: Investigation & Backup Verification' (Protocol in workflow.md)

## Phase 2: Environment-Aware Error Handling Implementation

- [x] Task 2.1: Fix critical restore logic issues in restic_restore.yml
  - [x] Subtask 2.1.0: **CRITICAL FIX**: Remove condition requiring directory to exist (line 46) - restore must create directory if missing
  - [x] Subtask 2.1.1: Add inventory_hostname check (servyy-test.lxd vs lehel.xyz)
  - [x] Subtask 2.1.2: Implement FAIL behavior for servyy-test when snapshots missing
  - [x] Subtask 2.1.3: Implement LOG+CONTINUE behavior for production
  - [x] Subtask 2.1.4: Add clear error messages for both scenarios
  - [x] Subtask 2.1.5: Verify restore path includes absolute path correctly (line 35)
- [x] Task 2.2: Write Molecule test for restic_restore.yml (if feasible)
  - [x] Subtask 2.2.1: Assessed feasibility - no molecule infrastructure for user role
  - [x] Subtask 2.2.2: Decision: Skip molecule tests, rely on real-world servyy-test validation
  - [x] Subtask 2.2.3: Real-world testing in Task 2.3 and Phase 3 will validate functionality
- [x] Task 2.3: Test error handling on servyy-test
  - [x] Subtask 2.3.1: Test with missing backup (should FAIL) - ✅ PASSED
  - [x] Subtask 2.3.2: Verify error message clarity - ✅ Clear and actionable
  - [x] Subtask 2.3.3: Document behavior in test logs - ✅ Documented
- [x] Task: Conductor - User Manual Verification 'Phase 2: Environment-Aware Error Handling Implementation' (Protocol in workflow.md)

## Phase 3: Individual Service Restore Testing

- [ ] Task 3.1: Test Gitea (git/repos) restore
  - [ ] Subtask 3.1.1: Backup current git/repos on servyy-test
  - [ ] Subtask 3.1.2: Wipe git/repos directory
  - [ ] Subtask 3.1.3: Run restore: `./servyy-test.sh --tags user.docker.restore.git`
  - [ ] Subtask 3.1.4: Verify restore completed successfully
  - [ ] Subtask 3.1.5: Verify Gitea container starts
  - [ ] Subtask 3.1.6: Check Gitea accessibility and repo list
  - [ ] Subtask 3.1.7: Document any issues and fixes applied
- [ ] Task 3.2: Test PhotoPrism (photoprism/database) restore
  - [ ] Subtask 3.2.1: Backup current photoprism/database on servyy-test
  - [ ] Subtask 3.2.2: Wipe photoprism/database directory
  - [ ] Subtask 3.2.3: Run restore: `./servyy-test.sh --tags user.docker.restore.photoprism`
  - [ ] Subtask 3.2.4: Verify restore completed successfully
  - [ ] Subtask 3.2.5: Verify PhotoPrism container starts
  - [ ] Subtask 3.2.6: Check PhotoPrism DB connectivity
  - [ ] Subtask 3.2.7: Document any issues and fixes applied
- [ ] Task 3.3: Test Vaultwarden (pass/vw-data) restore
  - [ ] Subtask 3.3.1: Backup current pass/vw-data on servyy-test
  - [ ] Subtask 3.3.2: Wipe pass/vw-data directory
  - [ ] Subtask 3.3.3: Run restore: `./servyy-test.sh --tags user.docker.restore.pass`
  - [ ] Subtask 3.3.4: Verify restore completed successfully
  - [ ] Subtask 3.3.5: Verify Vaultwarden container starts
  - [ ] Subtask 3.3.6: Check Vaultwarden data exists
  - [ ] Subtask 3.3.7: Document any issues and fixes applied
- [ ] Task 3.4: Fix any identified restore issues
  - [ ] Subtask 3.4.1: Address permission issues
  - [ ] Subtask 3.4.2: Fix path resolution problems
  - [ ] Subtask 3.4.3: Correct ownership/group settings
  - [ ] Subtask 3.4.4: Re-test all services after fixes
- [ ] Task: Conductor - User Manual Verification 'Phase 3: Individual Service Restore Testing' (Protocol in workflow.md)

## Phase 4: Empty Container Recovery Testing

- [ ] Task 4.1: Prepare fresh servyy-test.lxd container
  - [ ] Subtask 4.1.1: Destroy existing servyy-test.lxd: `lxc delete servyy-test --force`
  - [ ] Subtask 4.1.2: Create fresh container: `./setup_test_container.sh`
  - [ ] Subtask 4.1.3: Verify container is clean (no existing data)
- [ ] Task 4.2: Run full deployment with restore
  - [ ] Subtask 4.2.1: Deploy: `./servyy-test.sh --tags user.docker,user.restic.restore`
  - [ ] Subtask 4.2.2: Monitor deployment for errors
  - [ ] Subtask 4.2.3: Capture deployment logs
- [ ] Task 4.3: Verify all services restored and running
  - [ ] Subtask 4.3.1: Check all 3 services have restored data
  - [ ] Subtask 4.3.2: Verify all containers started successfully
  - [ ] Subtask 4.3.3: Test basic functionality of each service
  - [ ] Subtask 4.3.4: Document bootstrap sequence and timing
- [ ] Task 4.4: Document empty container recovery procedure
  - [ ] Subtask 4.4.1: Write step-by-step recovery guide
  - [ ] Subtask 4.4.2: Include verification commands
  - [ ] Subtask 4.4.3: Note any manual steps required
- [ ] Task: Conductor - User Manual Verification 'Phase 4: Empty Container Recovery Testing' (Protocol in workflow.md)

## Phase 5: Production Deployment

- [ ] Task 5.1: Create history documentation
  - [ ] Subtask 5.1.1: Create `history/2026-01-23_restic-restore-validation.md`
  - [ ] Subtask 5.1.2: Document problem, solution, and test results
  - [ ] Subtask 5.1.3: Include verification commands
  - [ ] Subtask 5.1.4: Note known limitations or caveats
- [ ] Task 5.2: Prepare production deployment plan
  - [ ] Subtask 5.2.1: Review changes to be deployed
  - [ ] Subtask 5.2.2: Identify deployment tags needed
  - [ ] Subtask 5.2.3: Document rollback procedure
  - [ ] Subtask 5.2.4: Present plan to user for approval
- [ ] Task 5.3: **PAUSE - Await user approval for production deployment**
- [ ] Task 5.4: Deploy to production
  - [ ] Subtask 5.4.1: Execute: `./servyy.sh --limit lehel.xyz --tags [approved-tags]`
  - [ ] Subtask 5.4.2: Monitor deployment progress
  - [ ] Subtask 5.4.3: Capture deployment logs
- [ ] Task 5.5: Verify production health
  - [ ] Subtask 5.5.1: Check all services remain operational
  - [ ] Subtask 5.5.2: Verify no unintended changes
  - [ ] Subtask 5.5.3: Monitor logs for errors (15-30 minutes)
  - [ ] Subtask 5.5.4: Confirm backup/restore capability intact
- [ ] Task: Conductor - User Manual Verification 'Phase 5: Production Deployment' (Protocol in workflow.md)

## Phase 6: Cleanup & Finalization

- [ ] Task 6.1: Remove legacy rsync code
  - [ ] Subtask 6.1.1: Remove commented docker_repo_restore.yml imports from main.yml
  - [ ] Subtask 6.1.2: Delete docker_repo_restore.yml file
  - [ ] Subtask 6.1.3: Update any documentation referencing rsync restore
- [ ] Task 6.2: Final commit and documentation
  - [ ] Subtask 6.2.1: Stage all changes
  - [ ] Subtask 6.2.2: Commit with conventional commit message
  - [ ] Subtask 6.2.3: Attach verification summary via git notes
  - [ ] Subtask 6.2.4: Update track status to completed
- [ ] Task 6.3: Merge to master
  - [ ] Subtask 6.3.1: Create PR or merge feature branch
  - [ ] Subtask 6.3.2: Verify master branch on production
  - [ ] Subtask 6.3.3: Delete feature branch
- [ ] Task: Conductor - User Manual Verification 'Phase 6: Cleanup & Finalization' (Protocol in workflow.md)

## Notes

- All testing must be performed on servyy-test.lxd before production
- Keep commented rsync code until Phase 6 (after production deployment)
- Document all issues and fixes discovered during testing
- Each phase builds on previous phase validation
