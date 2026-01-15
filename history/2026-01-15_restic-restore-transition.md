# 2026-01-15 Transition to Restic Restore for Docker Services

## Overview
Successfully transitioned the data restoration logic for critical Docker services from the legacy file-copy method (referenced via `backup_dir`) to a modern, Restic-based approach. This ensures consistency between our backup and recovery tooling.

## Changes
- **New Task:** Created `ansible/plays/roles/user/tasks/includes/restic_restore.yml` to handle generic Restic restoration.
- **Service Updates:** Updated `ansible/plays/roles/user/tasks/main.yml` to use Restic for:
    - Git repositories (`git/repos`)
    - PhotoPrism metadata (`photoprism/database`)
    - Vaultwarden data (`pass/vw-data`)
- **Integration Testing:** Created `ansible/test_restic_restore.yml` to verify the logic using a local mock Restic repository.
- **Deactivation:** Legacy `docker_repo_restore.yml` calls have been commented out but the files remain in the repository for historical reference.

## Verification Results
All restorations were successfully verified on `servyy-test.lxd`:
1. **Git:** Verified repo structure and commit objects.
2. **PhotoPrism:** Verified MariaDB database files and configuration.
3. **Vaultwarden:** Verified SQLite database and RSA keys.

## Benefits
- Improved reliability: Restores are now performed from verified snapshots.
- Architectural Consistency: The same tool (Restic) is used for both ends of the data lifecycle.
- Reduced dependency: Removed reliance on plain-text files residing in the Storagebox `backup/` directory for these services.
