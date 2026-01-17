# Specification - Early Vaultwarden Restore and Deployment

## Overview
Move the restoration and deployment of the Vaultwarden service (`pass`) to the earliest possible stage in the Ansible execution. This allows subsequent tasks to interact with the running service (e.g., via CLI or API) for verification or data seeding.

## Functional Requirements
- **Task Extraction:** Extract Vaultwarden-specific restoration (Restic) and Docker configuration (Compose/Env) logic into reusable task files.
- **Early Deployment:** Implement a "standalone" deployment of Vaultwarden before the main Docker service loop.
- **SSL Support:** Utilize the project's `mkcert` role to generate trusted SSL certificates for the early instance, ensuring compatibility with CLI tools that require HTTPS.
- **CLI Connectivity:** Ensure the Vaultwarden CLI can successfully connect to the early instance using the local `mkcert` CA.

## Non-Functional Requirements
- **Branch-Based Development:** All changes must be implemented and tested in a dedicated feature branch (`claude/vw-early-restore`) before merging to master.
- **Reusability:** Ensure the extracted tasks are used for both the early deployment and the standard service lifecycle to maintain a DRY (Don't Repeat Yourself) codebase.
- **Compatibility:** The early deployment must respect existing volume paths and network configurations.

## Acceptance Criteria
- Vaultwarden is running and accessible via HTTPS before the main `user.yml` service loop begins.
- The `restic_restore.yml` logic is successfully reused.
- Subsequent Ansible tasks can successfully execute CLI commands against the running Vaultwarden instance.
- No regression in the final production deployment state.

## Out of Scope
- Migrating other services to early deployment.
- Modifying the core Traefik configuration (unless necessary for the standalone instance to function).
