# 2026-06-15 — Unified docker_service Role

## Problem

Docker service deployments were managed via two separate mechanisms:
- A loop-based task in the `user` role that iterated over a `docker.services` array
- Dedicated per-service roles (`user_searxng`, `user_job_search`) for services needing custom env templates

This made adding new services verbose and inconsistent — simple services needed array entries, complex ones needed full roles.

## Solution

Introduced a new generic `docker_service` role (`ansible/plays/roles/docker_service/`) that handles all service types through a single interface:

| Variable | Purpose |
|----------|---------|
| `service_dir` | Service directory name under `docker.remote_dir` |
| `env_templates` | List of `{src, dest}` template mappings (defaults to single `docker.env.j2 → .env`) |
| `service_host` | Override Traefik hostname (defaults to `{service_dir}.{inventory_hostname}`) |
| `service_name` | Override Traefik router name (defaults to `service_dir`) |
| `manual` | If `true`, render env but skip `docker-compose up` |

## Files Changed

**New role:**
- `ansible/plays/roles/docker_service/defaults/main.yml` — role interface defaults
- `ansible/plays/roles/docker_service/tasks/main.yml` — include env + conditional deploy
- `ansible/plays/roles/docker_service/tasks/env.yml` — render env templates
- `ansible/plays/roles/docker_service/tasks/deploy.yml` — docker_compose_v2 deploy
- `ansible/plays/roles/docker_service/molecule/default/` — molecule scenario

**Migrated templates** (moved from `user_searxng`, `user_job_search` into `user/templates/`):
- `searxng/.env.j2`, `job-search/.env.j2`, `job-search/api.env.j2`, `job-search/crawler.env.j2`

**Refactored:**
- `ansible/plays/user.yml` — rewritten to use explicit `docker_service` role invocations per service
- `ansible/plays/roles/user/tasks/docker_extras.yml` — new file with hardcoded service list for script generation
- `ansible/plays/roles/user/tasks/main.yml` — imports `docker_extras.yml`, dropped loop-based tasks

**Deleted:**
- `ansible/plays/roles/user_searxng/` — replaced by `docker_service` + searxng templates
- `ansible/plays/roles/user_job_search/` — replaced by `docker_service` + job-search templates

## CI Fixes Required

Three CI issues were found and fixed during the PR:

1. **yamllint braces** — inline `{ key: val }` flow mappings have spaces inside braces, violating the `braces` default rule. Fixed by expanding to block style throughout `user.yml`, `docker_extras.yml`, and `converge.yml`.

2. **ansible-lint role-name[path]** — `include_role` in molecule `converge.yml` used `name: "{{ playbook_dir }}/../../"` (a path, not a name). Fixed by using `name: docker_service`.

3. **molecule roles_path** — `config_options.defaults.roles_path: ../../../` in `molecule.yml` is relative to molecule's ephemeral ansible.cfg directory (a temp dir), not the scenario. In CI the role was not found. Fixed by adding `ANSIBLE_ROLES_PATH: "${MOLECULE_PROJECT_DIRECTORY}/.."` to provisioner env — molecule sets `MOLECULE_PROJECT_DIRECTORY` to the role directory, so `..` resolves to `ansible/plays/roles/`.

## Verification

- All 18 CI jobs green on commit `ac40777`
- PR #19 squash-merged to master as `dfdf69e`

## Pattern for Future Services

```yaml
# Simple service (single .env)
- role: docker_service
  vars:
    service_dir: my-service
  tags: [user.docker, user.docker.my-service]

# Multi-template service
- role: docker_service
  vars:
    service_dir: my-service
    env_templates:
      - src: docker.env.j2
        dest: .env
      - src: my-service/.env.j2
        dest: service.env
  tags: [user.docker, user.docker.my-service]

# Manual service (env only, no compose up)
- role: docker_service
  vars:
    service_dir: my-service
    manual: true
  tags: [user.docker, user.docker.my-service]
```
