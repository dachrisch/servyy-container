# Restic Production Rollout & Monit Infrastructure Fixes

**Date:** 2026-01-15
**Status:** ✅ Complete
**Environment:** `servyy-test.lxd`, `lehel.xyz` (Production)

## Problem Summary

Following the initial fix on the test environment (Jan 13), several issues were identified during the production rollout and ongoing monitoring:

1.  **Restic Idempotency:** The initialization task was not correctly skipping already initialized repositories when environment templates were updated, leading to task failures.
2.  **Production Password Mismatch:** Production repositories were inaccessible due to generated password mismatches, mirroring the earlier test environment issue.
3.  **Monit Syntax Error:** A shell script was incorrectly deployed to `/etc/monit/conf.d/container-check-portainer` on production, causing Monit startup failures.
4.  **SSH Warnings:** Constant "Permanently added" warnings in Restic logs were cluttering the output.

## Solution & Implementation

### 1. Restic Initialization Improvements
- **Task Refactoring:** Updated `ansible/plays/roles/user/tasks/restic_init.yml` to use `restic snapshots` for state detection instead of relying on fragile shell output redirection.
- **Idempotency:** Added logic to only attempt initialization when Restic environment files or Storage Box directories change.
- **Error Handling:** Added `failed_when` conditions to gracefully handle "config file already exists" scenarios.

### 2. Production Rollout (`lehel.xyz`)
- **Repository Re-initialization:** Performed a clean start by deleting and re-initializing the `home` and `root` repositories on the Storage Box using stable cached passwords.
- **Verification:** Confirmed successful snapshots for both repositories on production.

### 3. Monit Infrastructure Repair
- **Redeployment:** Identified that recent fixes for file duplication in Monit container monitoring had not been fully applied to production.
- **Fix:** Redeployed the `system.monit` role, which correctly moved scripts to `/etc/monit/scripts/` and configuration to `/etc/monit/conf.d/`.
- **Validation:** Verified `monit status` is clean and all 10 Docker services are being monitored.

### 4. SSH Warning Suppression
- **`known_hosts` Management:** Added new idempotent tasks to automatically populate the `known_hosts` file for both the `create_user` and `root` using `ssh-keyscan`.
- **Template Updates:** Removed `StrictHostKeyChecking no` and `UserKnownHostsFile /dev/null` from SSH config templates to allow standard host key verification.

### 5. Critical Infrastructure Protocols
Updated `GEMINI.md` with new mandatory rules:
- **No Manual Fixes:** All deployment errors must be fixed by updating the corresponding Ansible task and redeploying.
- **Production Safety:** Debugging and fixing directly on production is prohibited. All issues must be recreated and fixed on `servyy-test.lxd` first.
- **Server Dependency:** Production deployments must always use the `--limit` flag to target only relevant servers.

## Verification Results

### Production Snapshots (`lehel.xyz`)
| Repository | ID | Time | Size |
| :--- | :--- | :--- | :--- |
| Home | `bb9a0da5` | 2026-01-15 01:11:16 | 1.483 GiB |
| Root | `7b65d2a0` | 2026-01-15 01:14:01 | 6.455 GiB |

### Monitoring Status
- ✅ **Monit:** All checks OK (no syntax errors).
- ✅ **SSH:** No "Permanently added" warnings in command output.
- ✅ **Timers:** All systemd timers active and correctly scheduled.

## Lessons Learned
- **Redirection Risks:** Avoid `&>/dev/null` when the task relies on `changed_when` logic tied to `stdout`.
- **Environment Consistency:** Infrastructure fixes developed on test must be rigorously redeployed to production to ensure configuration drift is corrected.
- **Protocol Enforcement:** Documenting critical safety rules in `GEMINI.md` is essential for maintaining infrastructure integrity across multiple sessions.
