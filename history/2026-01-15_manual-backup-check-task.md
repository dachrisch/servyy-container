# 2026-01-15 Manual Backup Verification Task

## Overview
Implemented a dedicated Ansible task to manually verify the presence of recent Restic snapshots (within the last 24 hours) for both `home` and `root` repositories.

## Implementation Details
- **Location:** `ansible/plays/roles/testing/tasks/restic_check_recent.yml`
- **Logic:** Uses `restic snapshots --json` to fetch the latest snapshot and compares its timestamp against the host's current time.
- **Safety:** Tagged with `never` and `testing.restic.check_recent`. It will NOT run during standard deployments.
- **Trigger:** Must be explicitly called using `--tags testing.restic.check_recent`.

## Verification Results
- **Default Run:** Verified that the task is skipped when running standard tags (e.g., `user.ping`).
- **Explicit Run:** Verified on `servyy-test.lxd` that the task correctly identifies recent snapshots and passes.
- **Failure Scenario:** Verified (via logic) that the `assert` module will fail the playbook if no snapshot is found within the 24-hour window.
