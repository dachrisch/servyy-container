# 2026-11-26 — Agent stage: static assets for frontend equivalence (Phase 3 Layer 1)

## Problem

The long-lived agent stage on `servyy-test.lxd` ran the **backend** image only
(`ref`/`cand`). Every `/static/…` request returned 404, so Phase 3's frontend
journey equivalence could not be measured (roadmap issue #2539, Phase 3 plan §3).

## Change

Infra branch `agent-stage-frontend-phase3`, based on `agent-stage-tunnel-up`
(`0a64fce9`), never merged and applied only by the coordinator with
`./servyy-test.sh --limit servyy-test.lxd --tags ls.agent.stage`:

- `defaults/main.yml`: two new images, `leaguesphere/frontend:agent-ref` and
  `leaguesphere/frontend:agent-candidate`, built by the leaguesphere
  `deploy.yaml` `agent-image` job from the same full SHA as their backend
  counterparts.
- `docker-compose.agent-stage.yaml.j2`: `www-ref` / `www-cand` static-only nginx
  services on the internal `backend` network. No env file, no DB network, no
  schema check; `www-ref` has no update mechanism, `www-cand` has no watchtower
  label.
- `nginx.agent-stage.conf.j2`: proxy routes `/static/`, `/favicon.ico`,
  `/manifest.json`, `/sw.js` and `/service-worker.js` to the matching `www`
  service; all other paths keep going to the backend. Basic auth remains in
  front of both.
- `cand-update.sh.j2`: the existing system timer now pulls and restarts
  `cand` and `www-cand` together, health-gated on the backend.
- `docs/leaguesphere-environments.md`: build order, static/health probes, asset
  hash stability, timer behaviour and the full revert procedure.

`ls_agent_stage_schema_check` stays `true` (Phase 3 has no migration), the
test-host guard is unchanged, and `ls-db-sync-nightly.timer` stays off on
servyy-test. No host-level work was done from codey.

## Verification

- To be recorded by the coordinator after apply: `/static/` returns 200 on both
  sides; `/health/version/` reports the expected full SHAs; candidate timer
  picks up both images.

## Rollback

Remove the `www` services and static proxy routes, restore the one-service
timer, re-apply `ls.agent.stage` on servyy-test, stop using the frontend
harness. See the runbook section "Static assets and rollback (Phase 3)".
