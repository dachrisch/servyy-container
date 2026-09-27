# Codey Ofelia scheduler — one system for container jobs (2026-09-27)

## Problem

Codey had no Ofelia scheduler (only servy runs `portainer.ofelia`; Ofelia's
`--docker` discovery is daemon-local), so `opencode.web`'s `ofelia.job-exec`
labels (`prune-sessions` daily, `npm-cache-clean` weekly) never fired. The
manual reclaim earlier today (217 stale sessions, 1.9G npm cache, 12 orphaned
snapshots) was the direct fallout. Meanwhile the only host-scheduled container
jobs (claude-hub reaper every 15min + weekly force-cleanup via systemd timers)
duplicated the scheduling mechanism.

## Solution (single scheduler: Ofelia)

1. **`portainer-agent/docker-compose.yml`** — new `ofelia-scheduler` service
   (verbatim mirror of servy's block: `mcuadros/ofelia:latest`,
   `daemon --docker`, `TZ: UTC`, pidof healthcheck, `scope=prod`, hourly
   job-local heartbeat). Lands as `portainer.ofelia` (agent project name).
2. **`claude-hub/docker-compose.yml`** — `ofelia.enabled=true` plus
   `hub-reaper` (`@every 1h`, session parking) and `hub-force-cleanup`
   (`0 4 * * 7`, preserving the old Sun 06:00 host-local fire instant in UTC)
   job-exec labels.
3. **Retired systemd units**: `claude_hub_reaper.yml` /
   `claude_hub_force_cleanup.yml` are now teardown-only (stop/disable + absent
   files, same precedent as the earlier prune→reaper rename); 6 templates
   deleted; defaults blocks removed; molecule converge vars dropped and
   with-docker verify asserts flipped to absence. Old
   `/var/log/claude-hub-*.log` files left as history.
4. **Docs**: `session-fleet/SKILL.md`, `force-cleanup-stale.sh` header,
   `CLAUDE.md` service table, `claude-hub/.env.j2` comment updated.
5. Host-level jobs (docker/kernel/apt/restic/fail2ban/security-audit) stay on
   systemd — they need the host. "One system" = one system for container jobs.
   Servy's Ofelia + finance importer untouched.

## Sunday-is-7 bug (found live, fixed same day)

This Ofelia build **rejects DOW `0`/`SUN` at job registration** (WARNING, job
silently never runs); `7` registers. Proven on servyy-test.lxd with probe
labels (`0`/`SUN` failed, `1`/`7` registered). This fixed a second latent bug:
the `npm-cache-clean` label (`0 5 * * 0`, added 2026-09-05) could never have
fired anywhere — now `0 5 * * 7`. Both compose files carry a comment warning
not to "fix" 7 back to 0. Servy's finance label (`0 6 * * *`, no DOW) was
never affected.

## Verification

- Test-first on servyy-test.lxd (scoped tags, ok, failed=0). Note: the
  portainer-agent stack isn't deployed there, so the scheduler itself was
  validated with a throwaway Ofelia + labeled holder project (since removed):
  registration, `@every` + cron parsing, heartbeat. Teardown asserts verified
  via the real deploy (timers/units/scripts gone).
- Prod (`codey`): `portainer.ofelia` healthy, startup logs show
  **5 jobs registered** (prune-sessions, npm-cache-clean, hub-reaper,
  hub-force-cleanup, heartbeat); `systemctl list-timers` no longer lists hub
  timers; unit files absent; reaper `--action run` executed manually in-hub
  (only session `hub`, correctly skipped); all containers healthy;
  `code.lehel.xyz` → 401.
- Deploy-order lessons: opencode/hub/agent composes deploy via different paths
  (opencode role copies working tree; hub/agent via git checkout) — the prod
  deploy needed `user.docker.repo` + all three service tags, and Ofelia needed
  a restart after its targets were (re)created to pick up their labels (event
  watch missed containers starting in its own boot window).
- Commits: `0194cc0` (scheduler + move + teardown), `535692e` (Sunday-7 fix).

## Follow-up

- Natural soak proof: reaper runs hourly, prune-sessions at next 04:00 UTC —
  confirm in `docker logs portainer.ofelia` tomorrow.
- The old unrotated `/var/log/claude-hub-*.log` files stop growing now; remove
  them on a later pass if desired.
