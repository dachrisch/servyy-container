# Track Specification: Refactor Manual Backup Verification to use Loop

## Overview
Refactor the existing manual backup verification task (`restic_check_recent.yml`) to eliminate code duplication by utilizing a loop block. This will streamline the logic for checking multiple Restic repositories (home and root).

## Goals
- DRY (Don't Repeat Yourself) code: Use a single set of tasks inside a loop instead of separate blocks for `home` and `root`.
- Improve maintainability: Adding future repositories (e.g., `database`) will only require updating a list.
- Consistent reporting: Provide a standardized success message for each repository checked.

## Functional Requirements
- **Loop Logic:** Iterate over a list of repository names: `['home', 'root']`.
- **Dynamic Task Execution:** Use `include_tasks` with a loop to execute the check logic for each repository.
- **Improved Assertion:** Use `ansible_facts['date_time']` (continuing from previous fix) and ensure clear, descriptive error/success messages.
- **Tagging:** Maintain the `testing.restic.check_recent` and `never` tags.

## Acceptance Criteria
- [ ] `restic_check_recent.yml` is refactored to use a loop over repositories.
- [ ] Successfully verified on `servyy-test.lxd` for both `home` and `root` repositories via a single command.
- [ ] Playbook still fails if *any* repository in the loop is missing a recent snapshot.
- [ ] Code is cleaner and more readable.

## Out of Scope
- Changing the 24-hour verification window.
- Implementing automatic backups on failure.
