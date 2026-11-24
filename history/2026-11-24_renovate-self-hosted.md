# Self-hosted Renovate on servy

**Date:** 2026-11-24
**Status:** ✅ Deployed on servy.lehel.xyz (timer armed; first live run pending)
**Relates to:** `history/2026-11-20_forgejo-platform-setup.md` ("self-hosted
Renovate" was a follow-up), `renovate/AGENTS.md`

## Problem

The fleet relied on Mend's hosted Renovate app on GitHub. Migrating repos to
ci.lehel.xyz would leave them without dependency updates, and the hosted app had
already failed once on a fork (`history/2026-10-29_exposure-triage.md`).

A dry run against `cda/dontforget` proved Renovate 44.259 works with the native
`forgejo` platform: 46 dependencies in 9 files extracted in ~22 s. It also
showed two gaps — no GitHub token for action changelogs and Docker Hub 403s.

## Solution

- `renovate/docker-compose.yml`: pinned `renovate/renovate:44.259.0`, one-shot,
  no ports, no Traefik, `env_file: renovate.env`.
- `ansible/plays/roles/renovate/`: user systemd `renovate.service` +
  `renovate.timer` (daily 04:17, outside the 02:00–04:00 restic window),
  `ExecStart=/usr/bin/docker compose run --rm renovate`.
- `ansible/plays/roles/docker_service/templates/renovate/renovate.env.j2`:
  `RENOVATE_PLATFORM=forgejo`, endpoint, autodiscovery, and two hostRules.
- `ansible/plays/vars/secrets.yml`: three tokens (git-crypt encrypted) —
  `renovate_forgejo_token` (dedicated PAT:
  `write:repository,read:user,write:issue,read:organization`),
  `renovate_github_token` (classic, `public_repo`, expires 2027-02-22),
  `renovate_dockerhub_token` (`repo:public_read`). Recovery copies are
  Vaultwarden items of the same names; **no `bw` call at deploy or runtime**.
- Wired into `ansible/plays/user.yml` (tags `user.docker.renovate`),
  `ansible/production` (`services_enabled.renovate: true`; absent on test),
  and `forall_docker_services.sh`.

The tokens were minted in the browser (GitHub/Docker Hub) and via
`forgejo admin user generate-access-token` (Forgejo), then written straight into
`secrets.yml` — they never appear in a deployment command or the container
image.

## Deploy and verification

```bash
ansible-playbook ansible/servyy.yml --syntax-check -i testing
cd ansible && ./servyy.sh --limit servy.lehel.xyz --tags user.docker.renovate --check
cd ansible && ./servyy.sh --limit servy.lehel.xyz \
  --tags user.docker.repo,user.docker.renovate
```

Note: `--check` with `user.docker.repo` hits a **pre-existing** bug in
`roles/user/tasks/includes/repository.yml:24` (a skipped URI task has no
`status`). Checking only `user.docker.renovate` is clean.

After deploy: `systemctl --user status renovate.timer` on servy must show it
armed; `journalctl --user -u renovate.service` shows runs. A dry run can be
triggered with `docker compose run --rm -e RENOVATE_DRY_RUN=full renovate`.

## Follow-ups

- Bump `renovate/renovate` deliberately; the config schema changes across majors.
- Add the `bumbleflies` Forgejo org to autodiscovery once it exists.
- Branch protection / required checks on Forgejo should be set before Renovate
  automerge is trusted for production repos.
