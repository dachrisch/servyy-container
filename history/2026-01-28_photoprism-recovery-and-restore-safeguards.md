# 2026-01-28 PhotoPrism Recovery and Restic Restore Safeguards

## Context
On January 28, 2026, the PhotoPrism service on production (`lehel.xyz`) was found to be unhealthy/down. Investigation revealed that a previous attempt to restore from Restic backups had failed, likely due to a combination of missing directory handling and potential race conditions during the restore process. Furthermore, the restore logic lacked safety checks, which could have led to data corruption if executed against a running container or a non-empty directory.

## Incident Timeline
- **Discovery:** PhotoPrism reported as down by the user.
- **Investigation:** Found that the PhotoPrism data directory was in an inconsistent state.
- **Resolution:**
    1.  Developed and tested a robust restore decision matrix on `servyy-test.lxd`.
    2.  Implemented safeguards to prevent restoration into non-empty directories or while containers are running.
    3.  Successfully recovered PhotoPrism on production using the improved `restic_restore.yml` logic.

## Changes Implemented

### 1. Restic Restore Decision Matrix (`restic_restore.yml`)
Implemented a strict safety matrix to prevent accidental data loss:
- **Container Check:** The restore task now automatically detects if the service container is running. If it is, the restore is **skipped** to prevent file system corruption.
- **Directory Validation:**
    - **Missing Directory:** Automatically created (Enables bootstrap/recovery).
    - **Empty Directory:** Restore proceeds.
    - **Non-Empty Directory:** Restore is **skipped** (Preserves existing data).
- **Snapshot Validation:** On test environments, the task fails if no snapshots are found. On production, it warns but continues (allowing for fresh service setups).

### 2. Safeguard Logic
Added the following logic to `ansible/plays/roles/user/tasks/includes/restic_restore.yml`:
- Automated `docker ps` check for target services.
- `stat` and `find` checks to determine directory state.
- Descriptive skip messages to inform the operator *why* a restore was not performed.

### 3. Documentation and Testing
- Created a comprehensive test report: `docs/testing/2026-01-28-restic-restore-safeguards-test-report.md`.
- Validated all 6 major failure/success scenarios on the test environment.

## Safeguards in Action
The following matrix is now enforced during every deployment:

| Snapshots | Target Dir | Containers | Expected Action |
|-----------|------------|------------|-----------------|
| No        | Any        | Any        | Warn/Skip       |
| Yes       | Missing    | Any        | **Restore**     |
| Yes       | Empty      | Stopped    | **Restore**     |
| Yes       | Non-empty  | Stopped    | **Skip** (Safe) |
| Yes       | Empty      | Running    | **Skip** (Safe) |

## Lessons Learned
- **Never assume an empty state:** Restore logic must proactively check the target environment.
- **Safety first:** Automating the check for running containers is critical when performing file-level restores.
- **Environment Parity:** Using `servyy-test.lxd` to replicate production failure modes allowed for rapid and safe development of the fix.

## Status
- **PhotoPrism:** Recovered and healthy on production.
- **Safeguards:** Fully active in the `master` branch and applied to all services using the shared restic restore include.
