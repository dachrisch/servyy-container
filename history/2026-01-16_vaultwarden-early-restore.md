# 2026-01-16 Early Vaultwarden Restore and Deployment

## Overview
Successfully implemented the "early" restoration and deployment of Vaultwarden (`pass`). This allows subsequent infrastructure tasks to interact with a running Vaultwarden instance (e.g., via CLI or API) before the full service catalog is deployed.

## Changes
- **Logic Extraction:**
    - Created `ansible/plays/roles/user/tasks/includes/vw_restore.yml` to encapsulate Restic restoration for Vaultwarden.
    - Created `ansible/plays/roles/user/tasks/includes/vw_setup.yml` to handle `.env` generation and service startup.
- **Early Setup:**
    - Created `ansible/plays/roles/user/tasks/early_vaultwarden.yml` as a high-level wrapper for early deployment.
    - Implemented `mkcert` integration in early setup to provide trusted SSL certificates for local/test environments, enabling HTTPS-only CLI tools.
    - Added a temporary port mapping (8080:80) for standalone access before Traefik is available.
- **Refactoring:**
    - Updated `ansible/plays/roles/user/tasks/main.yml` to trigger early Vaultwarden setup immediately after Docker core initialization.
    - Modified `docker_repo_env.yml` and `docker_services.yml` to skip Vaultwarden in the general loops, preventing redundant deployment.
    - Implemented a "Final Reconfiguration" step at the end of the `user` role to ensure Vaultwarden is transitioned to its standard Traefik-managed state (Standard HTTPS, no exposed host ports).
- **Restic Robustness:**
    - Improved `restic_restore.yml` to gracefully handle empty repositories (common in fresh test environments).
    - Enhanced user ID/GID detection in `.env` templates by falling back to `ansible_user` facts.
- **Testing Improvements:**
    - Added support for local mock Restic repositories in `servyy-test.lxd` to allow full restore testing without production Storagebox access.
    - Updated project policies (`GEMINI.md`, `workflow.md`) to mandate testing on `servyy-test.lxd` instead of local Molecule.

## Verification Results
- **Early Start:** Verified on `servyy-test.lxd` that Vaultwarden starts and responds to HTTPS requests on port 8080 before the main service loop.
- **SSL Connectivity:** Confirmed `mkcert` certificates are correctly utilized by the `ROCKET_TLS` configuration.
- **Loop Integration:** Confirmed Vaultwarden is correctly skipped during the main Docker loop.
- **Final Transition:** Verified that the final "Standard" setup successfully removes the temporary port mapping and integrates Vaultwarden with the proxy network.

## Benefits
- Enables automated secret retrieval or seeding early in the deployment process.
- Improves infrastructure modularity by extracting specific service logic.
- Enhances test reliability with mockable Restic environments.
