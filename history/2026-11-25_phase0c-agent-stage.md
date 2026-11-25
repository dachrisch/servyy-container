# Phase 0c agent stage (leaguesphere#2536)

| | |
|---|---|
| Date | 2026-11-25 |
| Scope | `ansible/plays/roles/ls_agent_stage` (new), `ansible/plays/leaguesphere.yml`, `ansible/plays/roles/ls_db_sync`, `docs/leaguesphere-environments.md` |
| Host | `servyy-test.lxd` only (never prod / public stage) |
| Status | authored, not applied |

## Why

LeagueSphere's Phase 0c (`leaguesphere#2536`) proves refactors behave the same
by diffing two deployments that share one database. That needs a long-lived
stage on the test host: `ref` pinned to the phase's master image, `cand` on
`leaguesphere/backend:agent-candidate`, one basic-auth proxy, dedicated
harness accounts — and no per-run setup or secret handoff.

## What changed

- **`ls_agent_stage` role** renders and runs a two-app compose project
  (`ref`, `cand`, `proxy`) that joins the stage database tier
  (`db_nonprod_backend`) and the stage media volume. `ref` carries no
  watchtower label; `cand` carries `com.centurylinklabs.watchtower.scope=dev`.
  Harness users are (re)created in the stage DB from the git-crypt secret.
- **Basic-auth proxy** (nginx) in front of both apps on loopback ports
  18081/18082. Route names are not authentication: the opentunnel hostname is
  public in CT logs. The proxy forces `X-Forwarded-Proto: https` (stage
  redirects HTTP) and `Host: localhost` (stage `ALLOWED_HOSTS`).
- **opentunnel**: installed out of band; the role renders the persistent unit
  only when `ls_agent_stage_opentunnel_command` is supplied, so no CLI
  contract is guessed in review.
- **Nightly sync guard**: `ls_db_sync` no longer installs
  `ls-db-sync-nightly.timer` on `is_test_host`, and stops/masks a leftover
  unit. A nightly prod re-clone would delete the harness accounts.
- **Runbook**: "Agent stage (Phase 0c)" in `docs/leaguesphere-environments.md`.

## Deliberate limits

- Not applied by the author (no host access from codey; DNS for
  `servyy-test.lxd` does not resolve there). The coordinator applies
  `./servyy-test.sh --tags ls.agent.stage` after review.
- No Molecule scenario: the role targets one host's existing stage stack and
  database tier; a container fixture cannot rehearse the shared-DB contract.
  Syntax/lint is the gate here, and the first apply is the integration test.
- Never re-run `ls.app.stage` / `ls.db.sync` during a phase: both reset the
  stage DB.
