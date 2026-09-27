# Retire social (Pleroma) and bumbleflies repository/archive services

**Date:** 2026-09-27
**Author:** Claude (via user dachrisch)
**Type:** Service Retirement
**Status:** Implemented on `claude/retire-social-webhook`, not yet deployed to production

## Summary

Retired two dormant services from the servyy-container infrastructure:

1. **social** (Pleroma + its Postgres) — already fully decommissioned at runtime
   (not in `docker.services`, not in `services_enabled`, no containers, empty
   directory on `servy.lehel.xyz`), but leftover config and secrets remained in git.
2. **bumbleflies.repository** (`dachrisch/docker-git-webhook`) and its consumer
   **bumbleflies.archive** (`archive.bumbleflies.de`) — the webhook was idle
   since the site's last commit on 2026-07-09 (only healthcheck traffic since),
   and its image had not been updated since 2023-05-30.

## Problem / Goal

An infrastructure audit (2026-09-27) listed services by the last-changed date of
the image they pull. `social`'s image dated to 2020/2021 and the service was not
deployed anywhere; `bumbleflies.repository`'s webhook image was 3.4 years old
and no webhook push had been received for over two months. Both were candidates
for retirement. The goal was to remove them cleanly from git while leaving a
clear, documented path for the (deferred) production cleanup.

## Solution

### Removed files

- `social/` — full service directory (docker-compose, README, environments,
  volumes/static assets, ~2MB).
- `ansible/plays/vars/secrets.yml` — removed the `social:` block (Pleroma
  `hive` user/password). `porkbun_api` block untouched.
- `ansible/plays/roles/user/tasks/disabled_social.yml` — orphaned task file
  (was no longer imported by `main.yml`).
- `bumbleflies/docker-compose.yml` — removed the `repository:` service
  (webhook routes `webhook.bumbleflies.de`, `GIT_HOOK_TOKEN`, `./hooks` and
  `./site` mounts) and the `archive:` service (`archive.bumbleflies.de`,
  `./site`, `./nginx.conf`, `./logs` mounts, `depends_on: repository`).
- `bumbleflies/hooks/` and `bumbleflies/nginx.conf` — only consumed by the
  removed `repository`/`archive` services.
- `ansible/plays/roles/user/tasks/bumbleflies.yml` — its only task set
  `git config safe.directory` on `bumbleflies/site` for the removed webhook
  container's git operations; import removed from `main.yml`.

### Retained

- `bumbleflies` service itself continues: `www`, `bnb`, `edu` + `proxy` network
  unchanged. The `user.docker.bumbleflies` deployment tag in `user.yml` is
  unchanged (it targets the bumbleflies docker_service deployment, not the
  removed task file).

### Deferred production deployment steps

Deployment was deferred by user decision. When ready, on `servy.lehel.xyz`:

```bash
# 1. Deploy updated bumbleflies compose (removes archive+repository from project)
cd ansible && ./servyy.sh --limit servy.lehel.xyz --tags "user.docker.bumbleflies"

# 2. Remove orphaned containers + leftover data
#    (docker compose up does not remove removed services without --remove-orphans)
ssh servy.lehel.xyz \
  "docker rm -f bumbleflies.repository bumbleflies.archive && \
   rm -rf /home/cda/servyy-container/bumbleflies/site /home/cda/servyy-container/bumbleflies/logs"

# 3. Verify
ssh servy.lehel.xyz "docker ps | grep bumbleflies"   # expect www, bnb, edu only
ssh servy.lehel.xyz "curl -sI https://www.bumbleflies.de | head -1"
```

### External cleanup (left to user)

- **DNS**: `webhook.bumbleflies.de`, `social.bumbleflies.de`, and
  `archive.bumbleflies.de` A records point to `49.13.6.173`. They live in the
  **bumbleflies.de registrar account** (not the lehel.xyz Porkbun account
  configured in this repo — that API returns INVALID_DOMAIN for bumbleflies.de).
  No `_acme-challenge` TXT records to remove (subdomains use HTTP-01).
- **GitHub webhook**: remove the webhook on `github.com/bumbleflies/web` that
  points at `webhook.bumbleflies.de`.

## Verification

- `bumbleflies/docker-compose.yml` parses cleanly; services now: `www`, `bnb`,
  `edu`; networks: `proxy`.
- No remaining references to `disabled_social.yml`, `bumbleflies.yml`,
  `nginx.conf`, or `docker-git-webhook` in active ansible/play content.
- Not yet deployed to production; no production impact so far.

## Related Decisions

- ADR-004 (Service Undeployment via Inventory Control) — pattern for removing
  services via git + inventory rather than manual SSH edits.