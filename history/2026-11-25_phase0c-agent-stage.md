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

## Review fixes (2026-11-25, coordinator review)

- The proxy now joins a dedicated non-internal `edge` bridge: Docker does not
  reliably publish ports from a container attached only to `internal` networks.
  `backend` stays internal for proxy↔ref/cand traffic.
- opentunnel is installed by the role (official installer, `creates:` on
  `~/.local/bin/opentunnel`), then the two routes are added only when
  `route list` does not already contain the port. The systemd unit template was
  dropped: the CLI keeps its own encrypted bridge. If `--help` does not
  advertise a list command, the install still runs and the role prints the two
  manual `route add` commands instead of risking duplicates.
- Harness-user provisioning is a `block/always`: the 0600 secrets script is
  removed even when the `docker exec` fails.
- Runbook: role-linkage limits for `agent_team_manager`/`agent_official`
  (TODO Phase 1), the pre-apply schema check (stage build must equal the pinned
  ref image), and the opentunnel URL read-back command.
- Nightly-timer verification in the runbook now names the right owner
  (`create_user`, i.e. `cda`), not `leaguesphere`.

## Deliberate limits

- Not applied by the author (no host access from codey; DNS for
  `servyy-test.lxd` does not resolve there). The coordinator applies
  `./servyy-test.sh --tags ls.agent.stage` after review.
- No Molecule scenario: the role targets one host's existing stage stack and
  database tier; a container fixture cannot rehearse the shared-DB contract.
  Syntax/lint is the gate here, and the first apply is the integration test.
- Never re-run `ls.app.stage` / `ls.db.sync` during a phase: both reset the
  stage DB.
