# Forgejo platform setup (ci.lehel.xyz + Actions runners on codey and runny)

**Date:** 2026-11-20
**Branch:** `claude/forgejo-ci-runny`

## Problem

`git.lehel.xyz` runs `emarcs/nginx-git:latest`, which ships EOL nginx 1.14
(#198). The long-term goal is **Forgejo**, hosting the bare repos and the GitHub
repos with workflows, so the fleet stops depending on GitHub. This round sets up
the **platform only** — no repo is migrated, and `git/` + `git.lehel.xyz` stay
untouched until a later cut-over.

## What was done

### Phase 1 — Forgejo on servy (`ci/`)
- `ci/docker-compose.yml`: single `forgejo` service (container `ci.forgejo`),
  rootless image pinned to Forgejo LTS `15.0.12-rootless`, uid 1000, `./data` +
  `./conf` bind mounts, healthcheck `/api/healthz`, Traefik labels modeled on
  `waggle/` but with `letsencryptdnsresolver` + `crawler-ratelimit@file`, port
  3000. Git over HTTPS only (`DISABLE_SSH`), no SSH port.
- `ansible/plays/roles/docker_service/templates/ci/{docker.env.j2,forgejo.env.j2}`:
  `.env` carries the compose-interpolation + Traefik knobs; `forgejo.env`
  carries the `FORGEJO__section__KEY` settings (private instance, sqlite3,
  actions + packages on, mailer off, metrics bearer token, `INSTALL_LOCK`,
  `SECRET_KEY`/`INTERNAL_TOKEN` from secrets.yml).
- `ansible/plays/roles/forgejo_bootstrap/`: idempotent admin-user creation
  (`forgejo admin user create --admin cda`), offline runner registration
  (`forgejo forgejo-cli actions register --secret … --name <runner>` for each
  name in `forgejo_runners`), and the nightly DB-dump systemd timer
  (`forgejo dump --database sqlite3 --skip-repository --skip-log
  --skip-attachment-data --skip-package-data`, 01:30, keep last 3, into
  `./data/backup/`).

### Phase 2 — runner service `runny/` (codey dind, runny host)
- `ansible/plays/roles/forgejo_runner/`: renders the templated compose
  (`runner` + optional `dind` sidecar) and `config.yml` (labels / capacity /
  `container.options`), registers via `forgejo-runner create-runner-file
  --secret`, and optionally installs amd64 binfmt (QEMU). Backend chosen per
  host by `forgejo_runner_docker`: `dind` on codey (host socket would expose
  claude-hub/opencode credentials), `host` on runny (~100 MB saved).
- `runny/AGENTS.md` documents the split.

### Phase 2b — monitoring
- `monitor/prometheus.yml`: `forgejo` scrape job (bearer token from
  `monitor/rendered/forgejo-metrics-token`) over the `proxy` network, plus a
  `runny` scrape job for the runner host's node-exporter.
- `ansible/plays/roles/system_probe/templates/forgejo_runners.sh.j2`: pushes
  `forgejo_runner_online` / `forgejo_runner_last_seen_seconds` /
  `forgejo_actions_jobs` from the Forgejo admin API (SQLite `action_runner` /
  `action_run_job` fallback), every 5 minutes.
- `monitor/provisioning/dashboards/infrastructure/forgejo-ci.json` and four
  alert rules in `monitor/provisioning/alerting/alert-rules.yml`
  (`forgejo_down`, `forgejo_runner_offline`, `forgejo_jobs_stuck_waiting`,
  `runny_swap_exhausted`).

### Phase 3 — the amd64 runner host (`runny.lehel.xyz`)
- `scripts/provision-oracle-runner.sh`: E2.1.Micro, Ubuntu 24.04 minimal amd64,
  same VCN as codey, SSH-only ingress (+ `:9100` from servy's Prometheus only).
- Inventory (`ansible/production`): servy gets `ci: true` + `forgejo_runners:
  [codey, runny]`; codey gets `runny: true` + its runner vars; new host
  `runny.lehel.xyz` (4 GB swap, stateless, no restic, no Traefik, light system
  play). `ansible/testing` rehearses the same on servyy-test (runner `test`).

### Light system play for runny
- `roles/system/tasks/fail2ban.yml` + `jail.local.j2`: the Loki blocklist is
  gated on `loki_blocklist_enabled` (default true; runny sets it false).
  portainer-agent and promtail are simply not enabled on runny.

### Backup
- `ansible/plays/vars/restic.yml`: excludes the live SQLite DB, the container
  registry, the actions/tmp/queues/indexers/sessions dirs and
  `servyy-container/runny` from `restic.home`; the bare repos and the nightly
  DB dump stay in scope.

## Secrets (all added by Claude to `plays/vars/secrets.yml`, never here)

`forgejo_secret_key`, `forgejo_internal_token`, `forgejo_admin_password`,
`forgejo_runner_secrets[<runner>]` (40 hex), `forgejo_metrics_token`,
`forgejo_admin_api_token`. The admin API token is created **once** against the
admin user — `forgejo admin user generate-access-token --username cda
--token-name ansible --scopes all --raw` — and stored in secrets.yml; the
runner-registration idempotency check (and the liveness probe) read it.

## Registries

`docker.services[]` needs `- {name: ci, dir: ci}` (added by Claude; runners are
**not** in `docker.services[]` — they never run on servy). `docker_extras`
forall list carries both `ci` and `runny`.

## Verification

- `ansible-playbook servyy.yml --syntax-check -i testing` and
  `plays/user.yml` / `plays/system.yml` syntax checks.
- Molecule: `docker_service/molecule/forgejo` (renders forgejo.env + .env),
  `forgejo_runner/molecule/default` (renders config.yml + compose in both dind
  and host variants), `forgejo_bootstrap/molecule/default` (renders the DB-dump
  script + unit/timer), each with an `idempotence` step; all three registered in
  `.github/molecule-matrix.yml`.
- servyy-test rehearsal + Phase 4 smoke/benchmark, then production one host at a
  time (servy `user.docker.ci`, codey + runny `user.docker.runny`), each after
  explicit approval.

## Open items

- Confirm the Forgejo admin API endpoint (`/api/v1/admin/actions/runners`) and
  the SQLite column names the probe's fallback assumes, on servyy-test's
  `/swagger.v1.json` (the plan's own "check first").
- Confirm the live SQLite path (`ci/data/gitea/forgejo.db`) against the running
  container — the restic exclude must match the real file.
- codey has no Prometheus host-metrics path today (node-exporter is
  collect-only on servy); the "codey load" dashboard panel is a placeholder
  until the Phase 4 benchmark decides whether to add node-exporter to codey.
- `forgejo dump` emits a tar.gz (named `forgejo-db-*.tar.gz` here), not the
  plan's literal `forgejo-db.sql.gz`; the restic include scope is the same.

## Later (not this round)

Cut-over (adopt the 5 bare repos, move `git.lehel.xyz`, retire `git/`), GitHub
migration with push-mirror, self-hosted Renovate, Git-over-SSH.
