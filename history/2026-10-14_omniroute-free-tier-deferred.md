# OmniRoute free-first tier — deferred (setup too complex)

**Date:** 2026-10-14
**Status:** Deferred / abandoned for now
**Relates to:** docs/plans/2026-10-13-omniroute-free-tier-design.md, docs/plans/2026-10-13-omniroute-free-tier-plan.md, PR #212 (`claude/omniroute-free-tier`)

## Context

Goal was to make the codey opencode server "work for free, nearly unlimited,
by default" by adding an OmniRoute gateway sidecar (`diegosouzapw/omniroute`)
inside the `opencode` compose project, routing session models over pooled free
quotas while keeping paid providers (`bailian-payg`, `opencode-go`) as explicit
user choice. A full branch + PR (#212, 9 files) was implemented behind Molecule
fixtures and a design/plan doc.

## Test deploy on servyy-test.lxd (Task 9) — RED

Scoped deploy was clean (`ok=52 failed=0`), and the container came up healthy,
but the smoke gates all failed:

1. **`baseURL` unreachable.** Committed `http://localhost:20128/v1`; from
   `opencode.web` (separate netns) → *Connection refused*. The gateway is only
   reachable as `http://omniroute:20128/v1` over the compose `proxy` network.
2. **Model IDs don't exist upstream.** Template keys `omniroute-auto/cheap/coding`
   are sent verbatim as the model id; the gateway returns
   `400 Unable to determine provider for model 'omniroute-cheap'`. Real gateway
   ids are combos (`auto/cheap`, `auto/coding`, `auto/best-free`, …; no bare `auto`).
3. **Free pool is empty — the core promise fails.** `/api/providers` →
   `{"connections":[],"total":0}`; every free combo (`auto/cheap`, `auto/best-free`,
   `auto/fast`, `auto/chat`, `auto/coding`) returns
   `503 ALL_TARGETS_SKIPPED`; all 10 built-in keyless `oc/*` targets are skipped for
   `reason: availability`. Bootstrap log: *"These providers will not work until
   configured."* `/api/providers/free-onboarding` returns **0 eligible providers**,
   so the in-app "free onboarding" wizard cannot populate the pool either.

Egress from the container is fine (openai 401, pollinations 200) — the pool is
empty because nothing is *configured*, not because of network.

The design's premise — keyless free-forever routes work with zero setup — does
not hold for image `3.8.51`. Making it actually free requires hand-configuring
provider connections (keyless no-auth ones won't onboard, and official free tiers
need API keys), which is more setup than the "just works" value proposition
justified. `/api/free-models` lists 78 free-capable providers / 489 entries, but
turning them into a working default pool is ongoing provider-plumbing work.

## Decision

- Do **not** merge PR #212. Remove the sidecar from `servyy-test.lxd` (reverted to
  master via `ansible-playbook servyy.yml -i testing --tags user.docker.opencode`;
  removed orphan container, forwarder, and volume).
- The branch and PR stay as the reference implementation if we revisit.

## If revisited (gotchas to fix first)

- `baseURL` → `http://omniroute:20128/v1` (service name over the `proxy` network),
  not `localhost`. Confirmed reachable with the gateway API key.
- Model keys must be real gateway combo ids (`auto/cheap`, `auto/coding`,
  `auto/best-free`) — not invented aliases.
- Confirm the image can actually populate a free pool without manual provider
  config; if not, the feature needs a provider-provisioning story (which free
  providers, which keys) before it delivers any value.
- Dashboard is localhost-only and, behind a port-forward, treats the peer as
  non-local: onboarding needs the one-time bootstrap token (`docker logs`), and
  the password is set via `POST /api/settings/require-login` (loopback-trusted).
