# Put Moodle into the `leaguesphere` Portainer team (container label)

**Date:** 2026-11-19
**Repo:** `servyy-container` (`/home/cda/dev/infrastructure/container`)
**Status:** planned

## Goal

Make `moodle.moodle` (servy) manageable by the Portainer team `leaguesphere`,
the same way the `leaguesphere/*` containers already are: by adding the Docker
label `io.portainer.accesscontrol.teams=leaguesphere`.

Scope is **Moodle itself only** — not its database, not any other service.

## Findings (verified 2026-11-19 against production)

Portainer `https://portainer.lehel.xyz`, CE **2.45.3**, endpoint `servy` (Id 1,
local socket). Endpoint `codey` (Id 9) is the agent.

| Fact | Evidence |
|---|---|
| The label works on this CE build | `leaguesphere.app` carries `io.portainer.accesscontrol.teams=leaguesphere` **and** has `Portainer.ResourceControl` Id 220, `TeamAccesses: [{TeamId: 1, AccessLevel: 1}]` (via `GET /api/endpoints/1/docker/containers/<id>/json`) |
| Team access is resource-scoped, not host-wide | Endpoint 1 `TeamAccessPolicies = {"1": {"RoleId": 0}}` — the team reaches servy *only* through resource controls. No Operator grant on the whole endpoint is needed. |
| The team exists | `GET /api/teams` → `{Id: 1, Name: leaguesphere}`; member `chris0chris` (UserId 2, team leader) |
| Moodle is untagged | `moodle.moodle` has no `io.portainer.*` label and no resource control |
| Moodle's DB is not in its own project any more | WP-7b (2026-11-18): `DB_HOST=db-business.mariadb`; `moodle.db` is `exited` (rollback window, D11) |

Consequence: only the `moodle` service needs the label. `db-business.mariadb`
also serves `bnb-office`, so tagging it would hand the leaguesphere team bnb's
database.

## Change

### 1. Label the Moodle container

`moodle/docker-compose.yml`, `services.moodle.labels` (append after the Traefik
labels, before the end of the block):

```yaml
      # Portainer CE creates a ResourceControl from this label when it discovers
      # the container, so team "leaguesphere" can manage this container without
      # endpoint-wide access to servy. Same convention as the leaguesphere/*
      # containers (their compose carries the identical label).
      - io.portainer.accesscontrol.teams=leaguesphere
```

The value is the team **name** (not id), matching the existing containers.

Do **not** add the label to:
- `db-business.mariadb` (shared with `bnb-office`),
- `moodle.db` (exited rollback container),
- any other service.

### 2. Deploy only Moodle

```bash
cd /home/cda/dev/infrastructure/container/ansible
./servyy.sh --limit servy.hel.xyz --tags user.docker.moodle
```

A label change alters the compose config hash, so the container is recreated:
a few seconds of downtime on `offd.de`. The image re-runs
`configure_moodle_settings` on boot (documented in `moodle/AGENTS.md`; env wins
over DB) — no data impact. `moodledata`/DB untouched.

### 3. Verify

```bash
# label is on the running container
ssh lehel.xyz "docker inspect moodle.moodle \
  --format '{{index .Config.Labels \"io.portainer.accesscontrol.teams\"}}'"
# -> leaguesphere
```

Then via the Portainer API (admin token), on the container's inspect:

```bash
# GET /api/endpoints/1/docker/containers/<moodle container id>/json
# -> .Portainer.ResourceControl.TeamAccesses contains {"TeamId": 1, ...}
```

Finally: log in as `chris0chris` and confirm `moodle.moodle` is visible while
the rest of servy is not.

### 4. Record it

- New `history/2026-11-19_moodle-portainer-team-label.md`: what changed, the
  verification output, and the note that the label is read from the container
  rather than set in the Portainer UI.
- `moodle/AGENTS.md`: one short line documenting the label (so a future
  `compose down/up` by hand keeps it), and while there, fix the **stale layout
  table** — it still lists `moodle.db` as a project container, but WP-7b moved
  the DB to `db-business.mariadb`.

## Risks / rollback

| Risk | Mitigation |
|---|---|
| Seconds of `offd.de` downtime on recreate | Deploy in a quiet window; rollback = revert the label and redeploy |
| Team gains edit rights on the Moodle container | Intended; `AccessLevel: 1` = same level the leaguesphere containers already have. Remove the label (and the resulting resource control) to revoke |
| Portainer doesn't create the resource control on its own | Verified mechanism exists for the leaguesphere containers; if it does not appear, check Portainer's container list refresh, then set the control once via the UI (Access control → team `leaguesphere`) |

## Out of scope

- Endpoint-wide RBAC on `servy` (not needed; resource controls cover it).
- Giving the team access to Moodle's MariaDB.
- Cleanup of the exited `moodle.db` / `moodledata/mariadb` (WP-8, after the
  one-week rollback window).
- ~~The inert `io.portainer.accesscontrol.teams=photoprism` label on
  `photoprism.mariadb`~~ — **resolved, nothing to remove** (verified 2026-11-19 on
  the host and in the repo): the label left with the WP-6b cutover, which removed
  the `mariadb:` service from `photoprism/docker-compose.yml`. `docker ps -a` shows
  **no** container carrying team `photoprism`, and `grep -rn accesscontrol.teams`
  over this repo's compose files returns nothing. The only team labels that exist
  now are `leaguesphere` on the LS stacks, and they come from the leaguesphere
  repo's own compose. Nothing to delete, and no phantom team to clean up in the
  Portainer UI beyond the org's own bookkeeping.
