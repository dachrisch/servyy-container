# Track Specification: Manual Backup Verification Task

## Overview
Implement an Ansible task that manually verifies the presence of recent Restic snapshots (within the last 24 hours) for both the `home` and `root` repositories. This provides a quick, automated way to audit backup health before performing critical maintenance or deployments.

## Goals
- Add a dedicated Ansible task/tag for backup verification.
- Ensure both `home` and `root` repositories are audited.
- Fail the playbook execution if no valid snapshot is found in the defined window.
- **Safety:** Ensure the task is NEVER run during standard deployments unless explicitly requested.

## Functional Requirements
- **restic_check_recent.yml:** A new task file (likely in the `user` role) that executes `restic snapshots --json`.
- **Logic:**
    - Fetch snapshots from the `home` repository.
    - Fetch snapshots from the `root` repository.
    - Parse the timestamps and compare them against the current time.
- **Error Handling:** Use the Ansible `assert` module to verify that at least one snapshot exists with a timestamp < 24 hours old.
- **Tagging Strategy:**
    - Use the `never` tag to ensure it's skipped by default.
    - Use a descriptive tag (e.g., `user.restic.check_recent`).
    - Run command: `ansible-playbook ... --tags user.restic.check_recent` (the explicit tag override will bypass the `never` restriction).

## Acceptance Criteria
- [ ] Running Ansible with the new tag on `servyy-test.lxd` successfully verifies existing snapshots.
- [ ] Running a standard Ansible deployment (without tags or with different tags) does NOT execute this check.
- [ ] The playbook fails with a clear error message if a snapshot is missing or aged beyond 24 hours.

## Out of Scope
- Automated scheduling of this check.
- Repairing or initializing repositories.
- Verifying the *content* of the backup (integrity check).
