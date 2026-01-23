# Track Specification: Restic Restore Validation & Fixes

## Overview

Validate and fix the existing restic restore functionality for all services currently configured with restore tasks. Ensure 100% reliability on servyy-test through comprehensive testing, including full restore from empty container scenarios. Remove legacy rsync restore code only after production deployment succeeds.

## Current State

**Restic Backups (Working):**
- ✅ Home directory backup: Hourly snapshots to Hetzner Storagebox
- ✅ Root filesystem backup: Daily snapshots to Hetzner Storagebox
- Logs: `/var/log/restic/backup-home.log`, `/var/log/restic/backup-root.log`

**Restic Restore Tasks (Status Unknown):**
- Gitea: `git/repos` (user.docker.restore.git tag)
- PhotoPrism: `photoprism/database` (user.docker.restore.photoprism tag)
- Vaultwarden: `pass/vw-data` (user.docker.restore.pass tag)

**Legacy Code:**
- Commented-out `docker_repo_restore.yml` (rsync-based) exists but is inactive

## Problem Statement

The current restic restore tasks (`ansible/plays/roles/user/tasks/includes/restic_restore.yml`) have never been fully tested. We need to:
1. Verify restic snapshots exist for all 3 services
2. Test actual restoration by wiping data and restoring from backup
3. Fix any broken restore logic
4. Ensure empty container recovery works end-to-end

## Functional Requirements

### FR1: Backup Verification
- Verify restic snapshots exist for git/repos, photoprism/database, pass/vw-data
- Document backup frequency and retention for each service
- Identify any services missing backups

### FR2: Restore Testing on servyy-test
- For each service (git, photoprism, pass):
  1. Wipe the target directory (e.g., delete `git/repos` contents)
  2. Run restore task with appropriate tag
  3. Verify restore completes without errors
  4. Verify restored service starts successfully (Docker container runs)

### FR3: Empty Container Recovery
- Deploy to completely fresh servyy-test.lxd container
- All 3 restore tasks must execute during initial deployment
- All restored services must start successfully
- Document the full bootstrap sequence

### FR4: Environment-Aware Error Handling
- **servyy-test.lxd**: FAIL deployment if backup missing (catch issues early)
- **lehel.xyz**: Log error and continue (allow fresh installations)
- Modify `restic_restore.yml` to check `inventory_hostname` for behavior switching

### FR5: Fix Broken Restore Logic
- Fix any issues discovered during testing (e.g., incorrect paths, permissions, missing dependencies)
- Ensure `restic_restore.yml` handles:
  - Missing target directories (create if needed)
  - Empty directories vs non-existent directories
  - Correct ownership/permissions after restore

### FR6: Legacy Code Removal
- Keep commented `docker_repo_restore.yml` during testing phase
- Remove after successful production deployment and verification
- Document removal in commit message

## Non-Functional Requirements

### NFR1: Safety
- Zero changes to production until servyy-test validates successfully
- No modifications to rsync code during development
- All changes must be reversible

### NFR2: Testing Rigor
- 100% testing on servyy-test before production
- Test both incremental restore (wiped directory) and full restore (empty container)
- Molecule tests for restic_restore.yml role if feasible

### NFR3: Documentation
- Document backup/restore procedure in `history/YYYY-MM-DD_*.md`
- Include verification commands for each service
- Document known limitations or caveats

## Acceptance Criteria

### AC1: Backup Verification Complete
- [ ] Confirmed restic snapshots exist for all 3 services
- [ ] Documented snapshot counts and dates
- [ ] Identified any backup gaps or failures

### AC2: Individual Service Restore Tests Pass
- [ ] Git repos: Wiped → Restored → Gitea container starts
- [ ] PhotoPrism database: Wiped → Restored → PhotoPrism container starts
- [ ] Vaultwarden data: Wiped → Restored → Vaultwarden container starts

### AC3: Empty Container Restore Works
- [ ] Fresh servyy-test.lxd deployment succeeds
- [ ] All 3 services restored from restic automatically
- [ ] All restored services running and healthy

### AC4: Environment-Aware Behavior Verified
- [ ] servyy-test fails deployment when backup missing (tested)
- [ ] Production behavior confirmed (log error + continue)

### AC5: Production Deployment Successful
- [ ] User approval received for production deployment
- [ ] Production deployment completes successfully
- [ ] All services remain operational on lehel.xyz

### AC6: Cleanup Complete
- [ ] Commented rsync code removed from codebase
- [ ] History documentation created
- [ ] Commit includes clear summary of changes

## Out of Scope

- Vaultwarden password lookup integration (future track)
- Disaster recovery automation for CIFS/storagebox mounting issues
- New backup strategies or additional services
- Backup performance optimization
- Restic repository maintenance (prune/check already configured)
- Migration of services not currently using restore tasks
- Automated restore testing in CI/CD

## Technical Notes

### Files to Modify
- `ansible/plays/roles/user/tasks/includes/restic_restore.yml` - Add environment-aware error handling
- `ansible/plays/roles/user/tasks/main.yml` - Remove commented rsync code (post-production)

### Files to Create
- `history/2026-01-23_restic-restore-validation.md` - Track documentation

### Verification Commands
```bash
# Check backups exist
ssh lehel.xyz "source /etc/restic/env.home && restic snapshots | grep -E 'git/repos|photoprism/database|pass/vw-data'"

# Test restore on servyy-test
cd ansible && ./servyy-test.sh --tags user.docker.restore.git

# Verify service health
ssh servyy-test.lxd "docker ps | grep -E 'git|photoprism|pass'"
```

## Dependencies
- Existing restic backup infrastructure (already deployed)
- Hetzner Storagebox with existing snapshots
- servyy-test.lxd container for testing
- Docker services configured on servyy-test matching production
