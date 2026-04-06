# 2026-04-06 Fix leagues-finance App Command and Healthcheck

## Problem

The pre-built image `dachrisch/league.finance:latest` was missing two things:
1. A `dist/client` symlink required for static file serving
2. A working healthcheck (`curl` is not present in the image; `/api/health` does not exist)

## Fix

Moved both fixes into the `Dockerfile` in the `leagues.finance` project (not the infra compose file):

- `RUN ln -s . dist/client` — creates the symlink at image build time
- `HEALTHCHECK` using `wget` targeting `http://localhost:3000/`

The `command` and `healthcheck` overrides have been removed from `leagues-finance/docker-compose.yml`.

## Files Changed

- `leagues-finance/docker-compose.yml` — removed `command` and `healthcheck` for `app` service
- `leagues.finance/Dockerfile` — added symlink `RUN` step and `HEALTHCHECK` directive

## Verification

- `ansible-playbook` successfully deployed the service to `servyy-test.lxd`.
- Container status: `Up (healthy)`.
- Reachability: `curl -k -I -H "Host: finance.leaguesphere.app" https://localhost` returns `HTTP/2 200`.
