# Track Specification: Implement restic restore for docker services

## Overview
Transition the data restoration logic for Docker services from the legacy file-copy method (referencing the Storagebox `backup_dir`) to the modern Restic-based restoration. This ensures that the infrastructure uses the same tool for both backup and disaster recovery.

## Goals
- Replace `docker_repo_restore.yml` logic with a new `restic_restore.yml` task.
- Ensure restoration can be performed for `git/repos`, `photoprism/database`, and `pass/vw-data`.
- Maintain the "Deactivate but do not delete" policy for legacy rsync/copy restoration code (keep files but skip execution).
- Priority: Start with `git/repos` to verify the restore logic.
- **Testing:** Include Molecule tests using a local mock Restic repository to verify restoration logic.

## Functional Requirements
- **restic_restore.yml:** A new include task that performs `restic restore latest`.
- **Target Selection:** The task must handle different Restic repositories (home vs root) based on the target path.
- **Verification:** Confirm data is restored to the correct location with proper ownership and permissions.
- **Fallback/Safety:** Restoration should only happen if the target directory is empty or if explicitly requested.

## Acceptance Criteria
- [ ] `restic_restore.yml` is implemented and used in `user/tasks/main.yml`.
- [ ] **Molecule tests pass**, verifying that data is successfully restored from a local mock Restic repository.
- [ ] Successfully restored `git/repos` on `servyy-test.lxd` from a Restic snapshot.
- [ ] Successfully restored `photoprism/database` and `pass/vw-data` on `servyy-test.lxd`.
- [ ] Legacy `docker_repo_restore.yml` is no longer called but remains in the repository.

## Out of Scope
- Automated restoration of the entire host OS.
- Changing the Restic backup frequency.