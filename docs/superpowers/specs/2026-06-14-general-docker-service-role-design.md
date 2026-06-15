# Design: General `docker_service` Role

**Date:** 2026-06-14  
**Status:** Approved  
**Scope:** Unify array-based service deployment and single-service dedicated roles into one reusable Ansible role. `ls_*` roles are out of scope.

---

## Problem

The `user` role's array-based deployment (loop over `docker.services[]`) was clean initially, but has accumulated per-service special cases:

- 5 inline special-case env template blocks in `docker_repo_env.yml` (energy, opencode, groceries, leagues-finance, finance)
- Two single-service dedicated roles (`user_searxng`, `user_job_search`) with their own templates and deploy tasks
- `user_job_search` generates 3 separate env files, further diverging from the array pattern

The result is split logic: some deployment behavior lives in the array loop, some in dedicated roles, and the generic template is no longer generic.

---

## Solution: `roles/docker_service`

A general-purpose Ansible role that encapsulates the full lifecycle of a single Docker service: env file rendering + docker-compose deployment. Invoked once per service in `plays/user.yml` with role-level vars — the same pattern `ls_app` uses.

---

## Role Interface

**`roles/docker_service/defaults/main.yml`:**
```yaml
service_dir: ""                                         # required: directory name (e.g. "traefik")
service_name: "{{ service_dir }}"                       # docker-compose project name
service_host: "{{ service_dir }}.{{ inventory_hostname }}"
env_templates:
  - src: docker.env.j2
    dest: .env
compose_file: docker-compose.yml
manual: false                                           # if true: render env files, skip deploy
```

---

## Role Tasks

**`tasks/main.yml`:**
```yaml
- include_tasks: env.yml
- include_tasks: deploy.yml
  when: not manual
```

**`tasks/env.yml`** — single clean loop, no special cases:
```yaml
- name: Render env files for {{ service_dir }}
  template:
    src: "{{ item.src }}"
    dest: "{{ docker.remote_dir }}/{{ service_dir }}/{{ item.dest }}"
  loop: "{{ env_templates }}"
```

**`tasks/deploy.yml`:**
```yaml
- name: Deploy {{ service_dir }}
  community.docker.docker_compose_v2:
    project_src: "{{ docker.remote_dir }}/{{ service_dir }}"
    project_name: "{{ service_name }}"
    files:
      - "{{ compose_file }}"
    env_files:
      - "{{ docker.remote_dir }}/{{ service_dir }}/.env"
    state: present
```

---

## Template Layout

All templates consolidated into the role:

```
roles/docker_service/templates/
├── docker.env.j2              # generic base (moved from user/templates/)
├── energy/.env.j2             # was user/templates/energy.env.j2
├── groceries/.env.j2          # was user/templates/groceries.env.j2
├── opencode/.env.j2           # was user/templates/opencode.env.j2
├── leagues-finance/.env.j2    # was user/templates/leagues-finance.env.j2
├── finance/.env.j2            # was user/templates/finance.env.j2
├── searxng/.env.j2            # was user_searxng/templates/env.j2
├── job-search/.env.j2         # was user_job_search/templates/env.j2
├── job-search/api.env.j2      # was user_job_search/templates/api.env.j2
└── job-search/crawler.env.j2  # was user_job_search/templates/crawler.env.j2
```

Ansible template search resolves `src: energy/.env.j2` → `docker_service/templates/energy/.env.j2` automatically.

---

## Usage in `plays/user.yml`

```yaml
roles:
  - role: user                        # non-docker tasks unchanged

  # Simple services — zero extra config
  - role: docker_service
    vars: { service_dir: traefik }
  - role: docker_service
    vars: { service_dir: git }
  - role: docker_service
    vars: { service_dir: photoprism }
  - role: docker_service
    vars: { service_dir: bumbleflies }
  - role: docker_service
    vars: { service_dir: dns }
  - role: docker_service
    vars: { service_dir: pass }
  - role: docker_service
    vars: { service_dir: achim-hoefer }
  - role: docker_service
    vars: { service_dir: opencode }
  - role: docker_service
    vars: { service_dir: searxng }

  # Services with custom env templates
  - role: docker_service
    vars:
      service_dir: energy
      env_templates:
        - { src: docker.env.j2,    dest: .env }
        - { src: energy/.env.j2,   dest: energy.env }

  - role: docker_service
    vars:
      service_dir: groceries
      env_templates:
        - { src: docker.env.j2,       dest: .env }
        - { src: groceries/.env.j2,   dest: groceries.env }

  - role: docker_service
    vars:
      service_dir: leagues-finance
      env_templates:
        - { src: docker.env.j2,            dest: .env }
        - { src: leagues-finance/.env.j2,  dest: leagues-finance.env }

  - role: docker_service
    vars:
      service_dir: finance
      env_templates:
        - { src: docker.env.j2,   dest: .env }
        - { src: finance/.env.j2, dest: finance.env }

  # Multiple env files
  - role: docker_service
    vars:
      service_dir: job-search
      env_templates:
        - { src: docker.env.j2,             dest: .env }
        - { src: job-search/api.env.j2,     dest: api.env }
        - { src: job-search/crawler.env.j2, dest: crawler.env }

  # Manual services — env rendered, compose not started
  - role: docker_service
    vars: { service_dir: monitor, manual: true }
```

Note: order in `user.yml` replaces the old `depends` field — `traefik` is listed first, naturally expressing the dependency.

---

## What Gets Removed

| Deleted | Replaced by |
|---------|-------------|
| `user/tasks/docker_repo_env.yml` | `docker_service/tasks/env.yml` |
| `user/tasks/docker_services.yml` | explicit role invocations in `user.yml` |
| `docker.services[]` array in `secrets.yml` | role vars per service in `user.yml` |
| `roles/user_searxng/` (entire role) | `docker_service` invocation + moved template |
| `roles/user_job_search/` (entire role) | `docker_service` invocation + moved templates |
| `user/templates/energy.env.j2` etc. | moved to `docker_service/templates/{service}/` |

The `user` role itself is retained — only its docker-related task includes are removed.

---

## Out of Scope

- `ls_*` roles (`ls_app`, `ls_demo`, `ls_db_sync`, `ls_access`, `ls_setup`) — remain unchanged
- `system` role — unrelated
- Molecule tests for the new role — added as part of implementation
