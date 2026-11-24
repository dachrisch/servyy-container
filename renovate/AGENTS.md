# renovate/ — self-hosted Renovate for ci.lehel.xyz

A **one-shot** dependency updater, not a web service. `renovate.timer` runs it
once a day; nothing stays running, no port is exposed, and there is no Traefik
router.

| | |
|---|---|
| Image | `renovate/renovate:44.259.0` (pinned; bump deliberately) |
| Schedule | daily 04:17, user systemd timer on servy (`renovate.timer`) |
| Platform | `forgejo`, endpoint `https://ci.lehel.xyz/api/v1` |
| Discovery | all repos the dedicated Forgejo token can reach (`RENOVATE_AUTODISCOVER=true`) |
| Secrets | `renovate.env`, mode 0600, rendered from `ansible/plays/vars/secrets.yml` |

## Tokens (deploy-time, never runtime)

`renovate.env` is rendered by the `docker_service` role from three keys in
`ansible/plays/vars/secrets.yml` (git-crypt encrypted):

- `renovate_forgejo_token` — dedicated Forgejo PAT, scopes
  `write:repository,read:user,write:issue,read:organization`.
- `renovate_github_token` — read-only classic PAT (`public_repo`), used only as
  a hostRule for the `github-tags` datasource (action version lookups).
- `renovate_dockerhub_token` — read-only Docker Hub PAT (`repo:public_read`),
  used only as a hostRule for Docker tag lookups.

The Vaultwarden items of the same names are the human-facing recovery copies.
**Do not** call `bw` from the timer, the container or this repo's deploy — if a
token is lost, restore it into `secrets.yml` and redeploy.

## Operating it

```bash
# On servy: is the timer armed and when does it next fire?
ssh servy.lehel.xyz 'systemctl --user status renovate.timer --no-pager'
# Run once now (real run — can open PRs)
ssh servy.lehel.xyz 'cd ~/servyy-container/renovate && docker compose run --rm renovate'
# Dry-run only, no PRs/branches (override needs the env file explicitly)
ssh servy.lehel.xyz 'cd ~/servyy-container/renovate && docker compose run --rm -e RENOVATE_DRY_RUN=full renovate'
# Last run's log
ssh servy.lehel.xyz 'journalctl --user -u renovate.service -n 100 --no-pager'
```

Renovate's cache is intentionally not persisted (`--rm` with no volume): a run
takes ~22 s and a cold datasource cache is acceptable. Keep the image pinned —
Renovate's config schema changes across majors.
