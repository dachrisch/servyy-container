# 2026-03-19 Staging Healthcheck Fix

## Context
The staging environment had connectivity issues requiring manual fixes during deployment (`ansible/plays/roles/ls_app/tasks/fix_staging.yaml`). The issues were:
1.  MariaDB defaulting to socket connection instead of TCP (`-h localhost`).
2.  Missing application healthcheck causing premature container restarts.

## Changes
- **Source Code (`leaguesphere` repo):**
    - `deployed/docker-compose.staging.yaml`: Updated MySQL healthcheck to force TCP connection (`-h localhost`) and added a lenient healthcheck for the App container.
    - `deployed/mysql-init/01-create-staging-db.sh`: Updated `mariadb` command to force TCP connection (`-h localhost`).
- **Deployment (`infrastructure` repo):**
    - `ansible/plays/roles/ls_app/tasks/main.yaml`: Removed the inclusion of `fix_staging.yaml`.
    - `ansible/plays/roles/ls_app/tasks/fix_staging.yaml`: Deleted the file.
