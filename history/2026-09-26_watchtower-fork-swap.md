# 2026-09-26 — Watchtower swap to openserbia fork (health-gated updates)

Swapped all four watchtower instances to `openserbia/watchtower`, a maintained
fork of `containrrr/watchtower` (archived upstream late 2024). Motivation:

- Services briefly return Traefik 404s while watchtower swaps an image
  (stop → recreate → boot). The fork adds `--health-check-gated`
  (wait for the replacement to report healthy, auto-rollback to the previous
  image if it never does) and a `blue-green` update strategy (v1.15+):
  start green alongside blue, gate on HEALTHCHECK, drain, retire blue —
  zero downtime for stateless Traefik-routed services.

## Changes

- `portainer/docker-compose.yml` (servy) and `portainer-agent/docker-compose.yml`
  (codey, `project_name: portainer` so container names stay
  `portainer.watchtower-prod`/`portainer.watchtower-dev`):
  - `image: containrrr/watchtower:latest` → `openserbia/watchtower:v1.19.0`
    (pinned — third-party fork, latest release 2026-07-24).
  - Added `WATCHTOWER_HEALTH_CHECK_GATED: "true"` (both instances).
  - Removed `DOCKER_API_VERSION: "1.44"` — the fork negotiates the daemon API
    version; pinning blocks the containerd-store local-build detection.
  - Scopes (`prod`/`dev`), poll intervals, cleanup unchanged.
- Blue-green is opt-in per container (`com.centurylinklabs.watchtower.update-strategy=blue-green`)
  and enabled separately in the leaguesphere repo (PR
  `claude/watchtower-blue-green`) for prod `www`/`app` and staging
  `www`/`staging-app`. Everything else stays on `recreate`.
  Global `WATCHTOWER_UPDATE_STRATEGY` deliberately not set (default `recreate`).

## Fork trust notes

- Drop-in: same CLI flags, `com.centurylinklabs.watchtower.*` labels, HTTP API,
  notification backends; resumes the upstream version line at v1.8.0.
- Supply chain: keyless cosign signatures, SLSA provenance, CycloneDX SBOM,
  distroless runtime base — better hygiene than the archived upstream.
- Still a third-party binary holding `docker.sock` — version is pinned
  consciously; bump via renovate/manual review.

## Validation / rollout

- `docker compose config --quiet` clean for both stacks.
- Deploy: `./servyy.sh --limit servy.lehel.xyz`, then `--limit codey.lehel.xyz`.
- Verify: `docker ps | grep watchtower` (image shows v1.19.0);
  `docker logs portainer.watchtower-prod` shows the fork banner and no scan errors.
- First health-gated update per service replaces the stop/recreate 404 window
  with a rollback-capable swap; blue-green cutover lines appear as
  `blue-green: cutover complete`.
