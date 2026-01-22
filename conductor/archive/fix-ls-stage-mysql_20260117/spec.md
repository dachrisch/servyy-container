# Specification - Fix LeagueSphere Stage MySQL Health Issue

## Overview
Investigate and resolve the issue where the `leaguesphere_stage` MySQL container fails to reach a "healthy" state during fresh deployments on `servyy-test.lxd`. This transient failure prevents the full Ansible suite from completing successfully and impacts deployment reliability.

## Functional Requirements
- **Failure Reproduction:** Establish a reliable method to reproduce the "unhealthy" state by performing a "clean slate" simulation (deleting data volumes and project files) on `servyy-test.lxd`.
- **Root Cause Analysis:** Identify exactly why the container is failing its health check (e.g., initialization script error, timeout during DB creation, or resource exhaustion).
- **Corrective Fix:** Implement a fix in the Ansible roles or Docker Compose configuration to ensure the MySQL container starts correctly and reaches a healthy state.
- **Reliability Verification:** Ensure that subsequent runs of the full Ansible suite consistently succeed without manual intervention.

## Non-Functional Requirements
- **Idempotency:** The fix must not break existing deployments and should remain idempotent.
- **Observability:** Ensure that initialization logs are clear enough to diagnose similar issues in the future.

## Acceptance Criteria
- The `leaguesphere_stage` MySQL container consistently reaches a "healthy" state on fresh deployments in the `servyy-test.lxd` environment.
- The root cause of the connection errors during initialization is identified and mitigated.
- The full Ansible suite (`./servyy-test.sh`) completes without failing at the `leaguesphere_stage` deployment step.

## Out of Scope
- Migrating the production database.
- Refactoring the core `leaguesphere` application logic (unless directly required for the fix).
