# ci.lehel.xyz: Ansible-managed API token, managing-ci skill, no password basic auth

**Date:** 2026-11-23
**Status:** 🚧 Phase A (token + skill) verified on servyy-test; prod pending approval. Phase B (basic auth off) not started.
**Relates to:** `2026-11-23_ci-ssh.md`

## Problem

Forgejo accepted `cda:<password>` as HTTP basic auth on the API (no 2FA), and
automation used exactly that: the admin password from `secrets.yml`. It was also
how an agent registered an SSH key, and how secrets ended up in transcripts. The
goal was one managed API token, stored in Vaultwarden plus a local copy, a skill
that uses it, and then password basic auth switched off.

**Order matters:** mint and prove the token first (Phase A), and disable basic
auth only after that (Phase B), so nothing depends on the password when it
stops working.

## Phase A: managed token + skill

- **`plays/forgejo_api_token.yml`** (strategy **linear**, imported in
  `servyy.yml` after `forgejo_vaultwarden.yml`) runs
  `roles/forgejo_bootstrap/tasks/api_token.yml` with tags `user.docker.ci` and
  `user.docker.ci.token`. It is a separate play because `bw` must never run in
  the `strategy: free` user play (`roles/vaultwarden/tasks/unlock.yml`).
- **Token:** user `cda`, scopes `all`, name `ansible-manage-<utc ts>`.
  - Local copy: `~/.config/forgejo/ci.<domain>.token` (0600, dir 0700).
  - Vaultwarden: `forgejo - api token (ci.<domain>)`.
- **Resolve order.** A token is never minted blind (rule-6 drift trap):
  1. The candidate is the local copy, else the Vaultwarden item. With no local
     copy and no `vw.key`, the run fails.
  2. The candidate is validated inside the container
     (`docker exec -e FJ_TOKEN … wget -S /api/v1/user`). The token travels via
     the environment, never argv. 200 keeps it; 401 replaces it; anything else
     fails.
  3. A token is minted only for "no copy anywhere" or 401
     (`forgejo admin user generate-access-token`), and the new one must
     validate with 200.
  4. The local copy is written, and Vaultwarden is updated with
     `push_items.yml` (create or update).
- **Skill `.claude/skills/managing-ci`:** `SKILL.md` covers the rules (never
  print the token, never read secrets.yml) and recipes for repos,
  migrate/mirror, keys, Actions secrets/variables, runs, runners and packages.
  `fj METHOD /path [body|@file]` passes the token to curl through a `-K -`
  stdin config.

## Bugs found while testing (fixed)

- **First test run:** the mint block's `when` was re-evaluated for each task.
  After "Adopt the minted token" changed the candidate, the next task read
  `.stdout` of the skipped check and failed. The mint had already run, so one
  orphan token is left on servyy-test. The decision is now computed once,
  before the block (`forgejo_api_token_mint`).
- **Runners endpoint:** it is `/admin/actions/runners` on v17, not
  `/admin/runners` (404).

## Verification: servyy-test (Phase A)

| Step | Result |
|---|---|
| 1. no copy anywhere | "Candidate from nowhere", minted, VW item created, local 0600 / dir 0700 |
| 2. rerun | local, HTTP 200, no mint, VW unchanged, file unchanged |
| 3. local file deleted | from Vaultwarden, HTTP 200, no mint, restored (41 bytes, 0600) |
| 4. local file = garbage | local, HTTP 401, 1 mint, VW updated, file replaced |
| 5. rerun after re-mint | local, HTTP 200, no mint, VW unchanged |
| `fj` | `GET /user` = cda; create, secret PUT, variable POST, tasks, delete repo; runners `[('test','idle')]`; keys, packages, user secrets OK; token not in `ps`; clear error without a token file |

Stale test tokens: the orphan from the first run, plus the token replaced in
step 4.

## Phase B: disable password basic auth

_Pending._
