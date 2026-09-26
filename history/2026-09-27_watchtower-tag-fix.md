# 2026-09-27 — Watchtower tag fix (v1.19.0 → 1.19.0)

PR #153 swapped the four watchtower instances to `openserbia/watchtower:v1.19.0`,
but that tag does not exist on Docker Hub — the fork publishes release versions
without the `v` prefix (GitHub release `v1.19.0` → Hub tag `1.19.0`).

Deploying #153 failed on both hosts with:
`failed to resolve reference "docker.io/openserbia/watchtower:v1.19.0": not found`.
Verified via Hub API: `v1.19.0` → 404, `1.19.0` → 200 (amd64/arm64/arm/riscv64,
published 2026-07-24). Old `containrrr/watchtower:latest` containers kept running
— compose failed at pull, before recreating anything.

## Changes

- `portainer/docker-compose.yml` and `portainer-agent/docker-compose.yml`:
  `image: openserbia/watchtower:v1.19.0` → `openserbia/watchtower:1.19.0` (4 instances).

## Rollout

- Same as #153: `./servyy.sh --tags "user.docker.repo,user.docker.portainer,user.docker.portainer-agent"`
  (`user.docker.repo` is required — a tags-only run without it leaves the remotes
  on the old commit and compose becomes a silent no-op).
- Verify: `docker ps | grep watchtower` shows `1.19.0`;
  `docker logs portainer.watchtower-prod` shows the fork banner, no scan errors.
