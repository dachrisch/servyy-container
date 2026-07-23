# 2026-07-23 — Deploy Sproutlings (thore.lehel.xyz)

## Status

**Created new service for [Sproutlings](https://github.com/dachrisch/sproutlings)** — a cozy,
kid-friendly creature-collector idle game.

- Docker image: `dachrisch/sproutlings:latest` (nginx static site, built from v1.0.0)
- URL: `thore.lehel.xyz`
- Service dir: `thore/`

## Changes

- Created `sproutlings/docker-compose.yml` — single-service compose with Traefik labels
- Added `docker_service` role invocation in `ansible/plays/user.yml` with custom
  `service_host: "thore.{{ inventory_hostname }}"`

## Deploy

```bash
cd ansible && ansible-playbook plays/user.yml --tags user.docker.sproutlings -i production
```
