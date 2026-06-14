---
title: job-search service integration
date: 2026-06-14
status: approved
---

# job-search Service Integration

Integrate the `job-search` project into the servyy-container Ansible infrastructure so deployments to test and production are automated, version-controlled, and consistent with every other managed service.

## Context

The `job-search` project (`/home/cda/dev/job-search`) is a Node.js monorepo (API, React frontend, Python crawler) backed by MongoDB and Redis. Pre-built Docker images are published to Docker Hub (`dachrisch/job-search-*:latest`). A `deploy/servyy-test/` directory in the project already contains a reference docker-compose and env examples. The files were manually placed on servyy-test; this integration automates that.

## Files

```
servyy-container/
├── job-search/
│   └── docker-compose.yml              # NEW — parameterized Traefik labels
│
└── ansible/
    ├── testing                         # MODIFIED — add job_search_* host vars for servyy-test.lxd
    └── plays/
        ├── user.yml                    # MODIFIED — add user_job_search role play
        ├── vars/secrets.yml            # MODIFIED — add vault_job_search_jwt_secret
        └── roles/
            └── user_job_search/
                ├── defaults/main.yml   # NEW
                ├── tasks/main.yml      # NEW
                ├── templates/
                │   ├── env.j2          # NEW
                │   ├── api.env.j2      # NEW
                │   └── crawler.env.j2  # NEW
                └── molecule/
                    └── default/        # NEW — converge + verify
```

## docker-compose.yml

Based on `deploy/servyy-test/docker-compose.yml` with these changes:
- Traefik labels use env vars instead of hardcoded values: `${TRAEFIK_ENTRYPOINT:-websecure}`, `${TRAEFIK_TLS:-true}`, `${TRAEFIK_CERTRESOLVER:-letsencryptdnsresolver}`
- Drop `_local` routers (dev shortcuts, not managed config)
- Drop explicit `ports:` mappings (Traefik handles routing; exposed ports are only needed for direct access)
- Add `name: job-search` at top level for explicit project naming

Services: `mongodb`, `redis`, `api`, `frontend`, `crawler`  
Networks: `internal` (private), `proxy` (external, Traefik)

## Ansible Role: user_job_search

### defaults/main.yml

Production defaults — overridden per host in the inventory:

```yaml
job_search_service_host: jobs.lehel.xyz
job_search_traefik_entrypoint: websecure
job_search_traefik_tls: "true"
job_search_traefik_certresolver: letsencryptdnsresolver
job_search_jwt_secret: "{{ vault_job_search_jwt_secret }}"
job_search_searxng_token: "{{ vault_searxng_brave_token }}"
job_search_searxng_url: https://search.lehel.xyz
container_project_name: job-search
container_home: "{{ ansible_facts['user_dir'] }}/servyy-container"
```

### tasks/main.yml

1. Generate `.env` from `env.j2` (mode 0600)
2. Generate `api.env` from `api.env.j2` (mode 0600)
3. Generate `crawler.env` from `crawler.env.j2` (mode 0600)
4. `community.docker.docker_compose_v2: state=present` (tagged `molecule-notest`)

### Templates

**env.j2** — service routing config:
```
SERVICE_HOST={{ job_search_service_host }}
SERVICE_NAME={{ container_project_name }}
TRAEFIK_ENTRYPOINT={{ job_search_traefik_entrypoint }}
TRAEFIK_TLS={{ job_search_traefik_tls }}
TRAEFIK_CERTRESOLVER={{ job_search_traefik_certresolver }}
```

**api.env.j2** — API runtime config (no CLAUDE_API_KEY — set by users at runtime):
```
NODE_ENV=production
LOG_LEVEL=info
JWT_SECRET={{ job_search_jwt_secret }}
```

**crawler.env.j2** — crawler config:
```
SEARXNG_URL={{ job_search_searxng_url }}
SEARXNG_TOKEN={{ job_search_searxng_token }}
```

## Secrets

Add to `ansible/plays/vars/secrets.yml`:
```yaml
vault_job_search_jwt_secret: "<generated with openssl rand -hex 32>"
```

Reuses existing `vault_searxng_brave_token` for the SEARXNG_TOKEN.

## Inventory Changes

In `ansible/testing`, add to `servyy-test.lxd` host vars:
```yaml
job_search_service_host: job-search.servyy-test.lxd
job_search_traefik_entrypoint: web
job_search_traefik_tls: "false"
job_search_traefik_certresolver: ""
```

## user.yml Playbook

Add a new play block following the searxng pattern:
```yaml
- name: Deploy job-search service
  hosts: all
  ...
  roles:
    - name: user_job_search
      vars:
        container_project_name: job-search
        container_home: "{{ ansible_facts['user_dir'] }}/servyy-container"
  tags:
    - user
    - user.docker
    - user.docker.job-search
```

## Molecule Test

Mirrors the searxng molecule scenario:
- `prepare.yml` — install python3-requests if needed
- `converge.yml` — create job-search dir, inline docker-compose, include role with test vault vars
- `verify.yml` — assert `.env`, `api.env`, `crawler.env` exist and contain expected values

## Environment Differences

| Setting | servyy-test.lxd | lehel.xyz (prod) |
|---|---|---|
| SERVICE_HOST | job-search.servyy-test.lxd | jobs.lehel.xyz |
| TRAEFIK_ENTRYPOINT | web | websecure |
| TRAEFIK_TLS | false | true |
| TRAEFIK_CERTRESOLVER | (empty) | letsencryptdnsresolver |
