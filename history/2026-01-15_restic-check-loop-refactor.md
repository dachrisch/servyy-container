# 2026-01-15 Refactor Restic Check Task to use Loop

## Overview
Refactored the manual backup verification task (`testing.restic.check_recent`) to eliminate code duplication and improve maintainability. The logic now iterates over a list of repositories.

## Changes
- **Task Refactoring:** Moved the core verification logic into a private sub-task file `ansible/plays/roles/testing/tasks/_restic_check_single.yml`.
- **Loop Implementation:** Updated `ansible/plays/roles/testing/tasks/restic_check_recent.yml` to loop over `['home', 'root']` and include the sub-task.
- **Reporting:** Standardized success/failure messages for each repository checked.

## Verification Results
- **Test Deployment:** Verified on `servyy-test.lxd` using the `testing.restic.check_recent` tag.
- **Outcome:** Successfully verified both `home` and `root` repositories in a single run.
- **Logic Integrity:** Confirmed that the `never` tag and explicit trigger still work as expected.
