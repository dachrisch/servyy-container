# ci/ — Forgejo (Git + Actions CI) at ci.lehel.xyz

Self-hosted Forgejo instance that will eventually replace `git.lehel.xyz`
(`git/`, the EOL nginx-git image). **This round is platform-only: no repo has
been migrated, and `git/` + `git.lehel.xyz` stay untouched until the later
cut-over.**

- One container, `ci.forgejo`, from the pinned Forgejo LTS image
  (`codeberg.org/forgejo/forgejo:<lts>-rootless`), running as uid 1000 with a
  SQLite database in `./data` (bind-mounted to `/var/lib/gitea`).
- Config comes entirely from `forgejo.env` (rendered from `FORGEJO__section__KEY`
  vars by the `docker_service` role) — nothing secret is in this compose file.
- Git is HTTPS-only (tokens). No SSH port; the instance is private
  (`DISABLE_REGISTRATION`, `REQUIRE_SIGNIN_VIEW`) with a single admin `cda`.
- Backup of record: the bare repos (`./data/git/repositories`) ride servy's
  `home` restic repo, and a nightly DB dump (`./data/backup/forgejo-db.sql.gz`,
  `forgejo dump --database sqlite3`, keep 3) is made by a systemd timer at
  01:30. The live `./data/data/gitea.db` and the container registry
  (`./data/packages`) are deliberately **excluded** from backup (regenerable /
  a live-SQLite snapshot is worthless).
- Actions runners are a separate concern: the `runny/` service dir (deployed to
  codey and to the amd64 runner host `runny.lehel.xyz`) and the
  `forgejo_runner` role. Forgejo itself never runs CI jobs.

## Registration model (shared secret)

Runners register offline with a shared secret, no UI step:

- Forgejo side (servy, `forgejo_bootstrap` role):
  `forgejo forgejo-cli actions register --secret <forgejo_runner_secrets[<runner>]> --name <runner>`
- Runner side (`forgejo_runner` role, on codey/runny):
  `forgejo-runner create-runner-file --instance https://ci.lehel.xyz --name <runner> --secret <forgejo_runner_secrets[<runner>]>`

Both reference `forgejo_runner_secrets[<runner>]` from `plays/vars/secrets.yml` — never a
`lookup('password', …)` seed (CLAUDE.md rule 6).

## Monitoring

- `[metrics] ENABLED=true` + a bearer `TOKEN` (rendered into
  `monitor/rendered/forgejo-metrics-token`), scraped by servy's Prometheus over
  the `proxy` network (`ci.forgejo:3000/metrics`).
- Runner liveness is probed from servy by `system_probe`'s
  `forgejo_runners.sh.j2`, which queries the Forgejo admin API and pushes
  `forgejo_runner_online` / `forgejo_runner_last_seen_seconds` /
  `forgejo_actions_jobs` to the Pushgateway.

See `ansible/plays/roles/forgejo_bootstrap/` for the admin-user + runner
registration + DB-dump timer, and the history entry for the full setup.
