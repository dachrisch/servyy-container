# Bare repos migrated to Forgejo; git.lehel.xyz retired

**Date:** 2026-11-24
**Status:** ✅ Live — three private `cda/*` repos on ci.lehel.xyz, all CI green;
`git.www` and its bare-repo directory removed from servy.
**Relates to:** `ci/AGENTS.md`, `history/2026-11-20_forgejo-platform-setup.md`,
`../setup-home/history/2026-11-23_migrating-repos-to-forgejo-skill.md`.

## Problem

Five bare repos still lived on the EOL nginx-git service (`git.lehel.xyz`,
image `emarcs/nginx-git:latest` with nginx 1.14). Only three were still in use:
`cloudy`, `home` and `notes`. `archive` and `me` were unused. Forgejo was
platform-ready but had no repos beyond two earlier GitHub imports.

## Change

### Repos

- Mirror-cloned `cloudy.git`, `home.git`, `notes.git` from
  `/home/cda/servyy-container/git/repos/` on servy and pushed them to
  `git@ci.lehel.xyz:cda/<name>.git` with `git push --mirror`.
- Created all three with `fj POST /user/repos` using `private: true` and
  `auto_init: false`; set `default_branch: master` after the push.
- `verify-refs.sh` matched every branch/tag (one `master` ref each).
- Local checkouts (`setup-cloudy`, `setup-home`, `~/Documents/notes`) had their
  `origin` switched to Forgejo; no-op pushes confirm the new remote.

### CI (cloudy, home)

The container repo's CI pattern was ported into `.forgejo/workflows/ci.yml`:
manifest-driven Molecule matrix plus yamllint, ansible-lint, syntax-check,
pytest (`home`), and an always-on `CI Gate` job. Key Forgejo adjustments:

- `actions/checkout@v7` / `actions/setup-python@v7` are mirrored at
  `data.forgejo.org`; no unmirrored actions are used.
- Molecule driver is the separate `molecule-docker==2.1.0` package (not
  `molecule-plugins[docker]`), with `community.docker` + `ansible.posix`
  collections installed in the job.
- `ANSIBLE_ALLOW_BROKEN_CONDITIONALS=True` is set because molecule-docker 2.1.0
  uses string `when:` conditionals that core 2.20 rejects by default.
- Scenarios converge throwaway containers with dummy vars: `cloudy` renders
  the storagebox credential/mount-script tasks; `home` includes the real
  `user/tasks/bashrc.yml` slice. `home`'s live-machine roles are not converged.
- `renovate.json` enables the Dependency Dashboard; self-hosted Renovate
  onboarded both repos and opened its first PRs/issues.

### Retiring the old service

- `plays/remove_service.yml` (with `target_host=servy.lehel.xyz`,
  `service_to_remove=git` and `docker.remote_dir=/home/cda/servyy-container`
  as extra-vars, run with `-b` for the root-owned `repos/` dir) removed
  `git.www` and `~/servyy-container/git/`. The unused `archive`/`me` bare repos
  went with it; their local clones keep their working data.
- Inventory: `git: false`. Removed the `docker_service` role invocation,
  `docker_extras.yml` forall entry, Traefik branded error-page branch, the
  `git.lehel.xyz` reachability probe and credential-login tasks (plus their
  Molecule fixtures and CI mocks), the `git.services[]` and `servyy_git_repo`
  entries in `secrets.yml`, the `git/` directory, and the `landscape.yaml` entry.
- `ci/AGENTS.md` updated to record that the cut-over is done.

## Verification

- Forgejo: `verify-refs.sh` OK for all three repos; all 6 `cda/cloudy` jobs
  (run 46) and all 7 `cda/home` jobs (run 50, plus the post-switch docs commit
  run 53) were `success`, including `CI Gate`.
- Renovate: Dependency Dashboard issue #2 present in both repos; PRs opened.
- Local checkouts: HEAD matches Forgejo `master` for all three; `git push
  origin master` reports "Everything up-to-date".
- Server: `git.www` container and `~/servyy-container/git/` absent; DNS still
  resolves via the `*.lehel.xyz` wildcard, no explicit record changed.

## Deployment

- GitHub CI on `bdd4afe1`: all 34 jobs green, including `CI Gate`.
- `servyy-test.lxd` full run failed on two **pre-existing, unrelated** issues:
  `auditd` could not start in the LXD container, and a `github_deploy_key.yml`
  assertion hit `object of type 'dict' has no attribute 'stat'`. Neither touches
  the git-service retirement; CI's Molecule matrix covered the changed user role.
- Production: Pushgateway's stale `system_container_health` series was cleared,
  then a targeted deploy (`--limit servy.lehel.xyz --tags
  user.docker.traefik,system.probe`) finished with `failed=0, changed=1`. A full
  deploy was tried first but was stopped — the service was already removed
  directly, so only the Traefik error page needed deploying.
- Final state on servy: zero containers matching `git.*`, no
  `~/servyy-container/git/` directory, `https://git.lehel.xyz` returns 404.

## Follow-up

- GitHub repos are a separate, one-at-a-time queue; `servyy-container` stays on
  GitHub (its checkout is the deploy source).
- `archive` and `me` clones are intentionally orphaned; delete locally if unwanted.
- A stale `git.lehel.xyz` line may remain in `~/.git-credentials` on servy — it
  is inert now that the host is gone and no task re-creates it.
