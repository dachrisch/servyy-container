# 2026-01-17 Fix LeagueSphere Stage MySQL Health and Infrastructure Robustness

## Context
During deployments on `servyy-test.lxd`, the `leaguesphere_stage` MySQL container would frequently fail to reach a "healthy" state when the environment was newly created. This caused the full Ansible suite to fail. Additionally, several transient issues were identified in the infrastructure roles that impacted testing reliability.

## Changes

### LeagueSphere Stage Fixes
- **MySQL Connection Robustness:** Updated the initialization script and healthcheck command to use `-h localhost`. This prevents MariaDB from attempting DNS resolution for its own service name during the early startup phase, which was causing "Can't connect to server" (115) errors.
- **Lenient Healthcheck:** Added a `blockinfile` override for the staging `docker-compose.staging.yaml` to provide a more lenient healthcheck for the `app` container. This allows up to 120 seconds for database migrations to complete before the container is marked unhealthy.
- **Task Integration:** Integrated a new `fix_staging.yaml` task into the `ls_app` role to apply these fixes dynamically after pulling the repository.

### Infrastructure Robustness
- **Monit Race Condition:** Fixed a race condition in the `system` role where Monit would sometimes fail to restart or report status correctly during provisioning. Added `meta: flush_handlers` and a `wait_for: port 2812` task to ensure Monit is ready before proceeding.
- **Backup Skip Logic:** Added `skip_storagebox` conditions to all legacy backup tasks in the `user` role to prevent failures in test environments where the Hetzner Storagebox is not mounted.
- **Restic Restore Robustness:** Improved `restic_restore.yml` to handle uninitialized or empty repositories gracefully and ensured all operations run as `root` for consistent permission handling.
- **User Fact Fallback:** Added a fallback to `ansible_user_id` in `.env` generation tasks to ensure correct ownership even when the `created_user` fact is missing.

## Verification Results

### Test Environment (servyy-test.lxd)
- **Full Suite Success:** A complete run of `./servyy-test.sh` passed successfully.
- **LeagueSphere Stage:** Confirmed `leaguesphere_stage.mysql` and `leaguesphere_stage.app` reach a healthy state consistently on fresh installs.
- **Monit:** Confirmed Monit status is callable and healthy after provisioning.
- **Backups:** Verified that backup tasks are correctly skipped when `skip_storagebox: true`.
- **Restic Restore:** Confirmed successful restoration of Git and PhotoPrism data using local Restic mocks.
