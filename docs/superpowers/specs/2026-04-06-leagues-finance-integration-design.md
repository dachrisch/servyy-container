# Design Spec: Leagues Finance Infrastructure Integration

**Date:** 2026-04-06
**Topic:** Integrating `leagues.finance` app into the `servyy-container` infrastructure.

## 1. Overview
This project involves integrating the `leagues.finance` application into the existing self-hosted infrastructure managed by Ansible and Docker Compose. The goal is to make the application available at `finance.leaguesphere.app` with proper SSL, database persistence, and secret management.

## 2. Infrastructure Requirements
The application will be deployed as a new Docker Compose project within the `servyy-container` repository.

### 2.1 Domain & Routing
- **Primary Domain:** `finance.leaguesphere.app`
- **Reverse Proxy:** Traefik (existing)
- **SSL:** Let's Encrypt via Traefik's `letsencryptdnsresolver`.

### 2.2 Tech Stack
- **Backend/Frontend:** Node.js (Express/tRPC/Vite)
- **Database:** MongoDB 7 (Standalone container)
- **Orchestration:** Docker Compose v2
- **Provisioning:** Ansible

## 3. Implementation Details

### 3.1 Docker Compose Configuration (`leagues-finance/docker-compose.yml`)
The service definition will follow the `groceries` pattern:
- **Service: `app`**
  - Image: `dachrisch/leagues.finance:latest` (built in CI)
  - Network: `proxy` (external)
  - Environment: Loaded from `.env` and `leagues-finance.env`
  - Traefik Labels: Host rule for `finance.leaguesphere.app`, TLS enabled.
- **Service: `mongo`**
  - Image: `mongo:7`
  - Volumes: `mongo_data:/data/db`
  - Internal network for communication with `app`.

### 3.2 Ansible Integration
- **`ansible/plays/vars/secrets.yml`**:
  - Add `leagues_finance` entry to `docker.services`.
  - Add secret variables:
    - `google_client_id`
    - `google_client_secret`
    - `google_callback_url`
    - `jwt_secret`
    - `ls_db_host`, `ls_db_name`, `ls_db_user`, `ls_db_password` (LeagueSphere MySQL credentials)
- **`ansible/plays/roles/user/templates/leagues-finance.env.j2`**:
  - Template for the application's specific secrets.
- **`ansible/plays/roles/user/tasks/docker_repo_env.yml`**:
  - Add task to generate `leagues-finance.env` from the template.

## 4. Security & Persistence
- **Secrets:** All sensitive variables will be managed via `git-crypt` in `secrets.yml`.
- **Database:** MongoDB data will be persisted in a named volume (`mongo_data`) on the host.

## 5. Verification Plan
1. **Local Validation:** Run `ansible-lint` on the new tasks and templates.
2. **Test Deployment:** Deploy to `servyy-test.lxd` using `./servyy-test.sh --tags user.docker.env.leagues-finance,user.docker.services.start`.
3. **Connectivity Check:** Verify `finance.leaguesphere.app` resolves and serves the app (checking logs in Loki).
4. **Database Check:** Ensure MongoDB container starts and accepts connections.

## 6. Success Criteria
- The application is accessible at `https://finance.leaguesphere.app`.
- Google OAuth login functions correctly.
- Data persists across container restarts.
- Logs and metrics are correctly captured by the monitoring stack.
