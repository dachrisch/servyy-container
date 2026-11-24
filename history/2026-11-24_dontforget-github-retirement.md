# Retiring `github.com/dachrisch/dontforget`

**Date:** 2026-11-24
**Status:** Phases 1–4 complete; **Phase 5 (GitHub archive) awaiting confirmation**
**Relates to:** `history/2026-11-24_knope-release-cycle.md`,
`history/2026-11-24_renovate-self-hosted.md`, `renovate/AGENTS.md`

## Decisions

1. Docker Hub publishing moves to the Forgejo release workflow (option A); the
   compose image `dachrisch/dontforget:latest` does not change.
2. The OpenCode server keeps the path `/root/dev/dachrisch/dontforget`.
3. The two open GitHub PRs (#123, #111) were closed with a pointer comment.
4. The `gh-dash` topic was removed from the GitHub repo after the server override
   was proven.

## Phase 1 — Forgejo publishes the image

- Minted a write-scoped Docker Hub PAT (`Repo Read & Write`, description
  `dontforget-publish-ci-lehel.xyz`), stored it in Vaultwarden and in git-crypt
  `secrets.yml` as `dontforget_dockerhub_write_token`, and seeded the Forgejo
  Actions secret `DOCKERHUBTOKEN`.
- `.forgejo/workflows/release.yaml` now logs into Docker Hub and pushes
  `dachrisch/dontforget:<version>` and `:latest` alongside the Forgejo registry.
  Added `workflow_dispatch` so the publish path could be tested without cutting
  a new version.
- Verified: task 68 green, Docker Hub tags `0.28.81` and `latest` updated at
  2026-11-24T11:54Z.

## Phase 2 — local clone switched

`switch-refs.sh … --apply` in `~/dev/dontforget` repointed origin to
`git@ci.lehel.xyz:cda/dontforget.git` and rewrote 538 CHANGELOG URLs. The push
of `1b12f8a` ran Forgejo CI green (task 69); zero GitHub URLs remain in tracked
files. No worktree was created and the GitHub repo was not pushed to.

## Phase 3 — OpenCode server (the previously untested part)

- `opencode/scripts/provision-dev.sh` now skips `dachrisch/dontforget` in GitHub
  discovery and clones/updates it from `git@ci.lehel.xyz:cda/dontforget.git`
  under the **old path**. Added a `ci.lehel.xyz` SSH host block and root-owned
  `id_ci_lehel`, provisioned by the opencode role from the workstation key.
- Server skills: dropped GitHub-only `release-please`, added
  `migrating-repos-to-forgejo`. Deployed with `--tags user.docker.opencode`
  (`changed=8, failed=0`); the provision script change restarted the container.
- Verified after restart: checkout origin `git@ci.lehel.xyz:cda/dontforget.git`,
  HEAD `1b12f8a`, clean tree, new skill present, old skill gone.
- **Smoke test through a real codey session** (`ses_df28bb412ffes6G5F1fvvq0Xd4`):
  the worker independently confirmed all of the above plus a working `gh`
  wrapper (`gh repo view dachrisch/dontforget` succeeded). No changes made.

The smoke test also found that Forgejo `master` still carried the migrated
`.github/workflows` (8 files), so Forgejo could run GitHub-style jobs too. They
were removed in commit `5602e65`; Forgejo `master` now has only
`.forgejo/workflows/{prepare_release,release}.yaml`, and its CI is green.

## Phase 4 — config/docs

- `architecture/landscape.yaml`: `dontforget` notes now record the Forgejo home,
  the Docker Hub publisher, and the OpenCode path/override.
- The two GitHub PRs were closed with pointer comments; `gh-dash` topic removed
  (`topics: []`). GitHub repo is still **not archived**.

## Phase 5 — pending

Archive with `gh repo archive dachrisch/dontforget` only after explicit user
confirmation. Keep the repo as a read-only pointer; never delete. Rollback is
`gh repo unarchive`.

Note: `--check` deployments with `user.docker.repo` fail on two pre-existing
bugs (repository.yml URI result, vaultwarden unlock); checking the narrow
`user.docker.opencode` / `user.docker.renovate` tags is clean.
