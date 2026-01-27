# 2026-01-27 Restic Restore Validation and Robustness Improvements

## Context
The disaster recovery capability (restoring services from Restic backups) needed validation. Previous implementations had brittle logic that could fail if the target directory didn't exist or if snapshots were missing, potentially leaving services in an undefined state during a bootstrap scenario (Empty Container Recovery).

## Changes

### 1. Robust Restore Logic (`restic_restore.yml`)
- **Empty Directory Handling:** Removed the condition requiring the destination directory to exist. The restore task now automatically creates the parent directory if missing, enabling bootstrap from scratch.
- **Environment Awareness:** Added logic to distinguish between Test (`servyy-test.lxd`) and Production environments.
    - **Test:** Fails explicitly if no snapshots are found (to catch testing errors).
    - **Production:** Logs a warning but continues if no snapshots are found (allowing for new service provisioning).
- **Tagging Fixes:** Added `user.restic.restore` tag to the result display task to prevent "undefined variable" errors when the restore task is skipped via tags.

### 2. Test Infrastructure (`restic_test_setup.yml`)
- **Static Password:** Switched to a static password for the local test repository. This prevents authentication errors when multiple Ansible runs occur on the same container (previously, a new random password was generated each run, locking out the existing repo).
- **Robust Initialization:** Replaced fragile `restic snapshots` output parsing with a direct check for the repository config file (`/tmp/restic-test-repo/config`) to determine if initialization is needed.
- **Privilege Escalation:** Fixed permission issues by ensuring `become_user: root` is explicitly set for sensitive tasks.

### 3. Container Recovery Verification
Performed a full "Empty Container Recovery" test on a fresh `servyy-test.lxd` instance:
1.  **Deployment:** Successfully deployed the full infrastructure stack (`./servyy-test.sh`).
2.  **Failure Mode:** Verified that the deployment correctly fails (with a clear message) when attempting to restore from a missing backup on the test environment.
3.  **Restore Cycle:**
    - Created a local test backup with dummy data for Gitea, PhotoPrism, and Vaultwarden.
    - Wiped the data directories.
    - Executed the restore tags (`user.restic.test.restore.*`).
    - **Result:** All data was successfully restored with correct permissions.

## Recovery Procedure (Empty Container)

To recover the infrastructure on a fresh container/server:

1.  **Provision:** Set up the host (e.g., `setup_test_container.sh` or manual server setup).
2.  **Deploy:** Run the Ansible playbook:
    ```bash
    ./servyy.sh --limit <hostname>
    ```
3.  **Restore Behavior:**
    - The playbook will automatically attempt to restore data for defined services (Git, PhotoPrism, Vaultwarden).
    - If backups exist in the configured Restic repository, data will be restored.
    - If no backups exist (e.g., new service), the restore is skipped (on Production) or fails (on Test) to alert the operator.

## Verification
All changes have been verified on `servyy-test.lxd` using the `claude/restic-restore-validation` branch.
