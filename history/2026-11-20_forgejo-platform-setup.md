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

## Review and servyy-test rehearsal (2026-11-20)

Fixes found in review or during the test deploy, on top of the opencode implementation:

- **Per-runner secrets** (`forgejo_runner_secrets[<name>]`). The offline secret
  is the runner identity, so one shared secret would make codey and runny the
  same runner. `forgejo-cli actions register` is idempotent per secret.
- **Container uid:** the deploy user is uid 1000 on servy but 1001 on servyy-test.
  Forgejo and the runner now run as `getent passwd cda`. The previous
  `ansible_facts['user_uid'] | default(0)` rendered **0**, and Forgejo refuses
  to run as root. A custom uid also needs `USER=git`, because the image's
  passwd has no entry for it.
- The **runner ignored `config.yml`** until it was started with
  `daemon --config /data/config.yml`. Without that flag, labels and capacity
  were silently defaults.
- **Host-socket runner** gets the host's docker gid via `group_add`.
- The **runny :9100 filter** is now a boot-persistent oneshot that inserts
  v4+v6 rules above the Oracle image's INPUT REJECT.
- Prometheus mounts `rendered/forgejo-metrics-token`.
- The **http→https redirect router** only matches where TLS is on (moodle
  pattern).
- **servyy-test only:** `forgejo_runner_extra_hosts` maps `ci.servyy-test.lxd`
  to the host gateway, for the runner and its job containers.

Verified on servyy-test.lxd:
- `/api/healthz` reports pass.
- Anonymous `/explore/repos` returns 303 to login, and the API returns 403.
- Admin `cda` was created.
- Runner `test` is declared with label `ubuntu-latest`.
- Smoke repo `cda/forgejo-smoke`: `actions/checkout@v4` from data.forgejo.org
  plus a `run` step, and the workflow reported **success**.
- A second deploy reported `changed=0`.

Not rehearsable on servyy-test:
- The Grafana runner alert: probes are disabled there (`system_probe_push_enabled: false`).
- runny itself, which is not provisioned yet.
- Phase 4: the amd64 build benchmark.

## runny: no repo, no secrets (2026-11-20)

The first full bootstrap of runny ran the plays every host gets:
- the user role cloned and **git-crypt unlocked** the deploy checkout, so
  `secrets.yml` was in plaintext on disk;
- it installed the GitHub deploy key and the `git.lehel.xyz` login;
- the opencode play wrote `id_github` and `id_servy`.

The plan assumed runny "holds no secrets", and that assumption is why its runner
uses the host Docker socket. In fact any CI job could have read all of the
above. No job had run on runny when this was found.

Fix: `repo_checkout: false` on runny.
- The user role skips the deploy key, the git login, the clone and
  docker_extras, and `no_checkout.yml` removes anything left from earlier runs.
- The opencode play ends for that host.
- The runner is rendered to `/home/cda/runny`.
- `restic_skip` now also gates and removes the system role's
  restic-forget/check timers.

Tested by the molecule scenario `user/no-checkout`.

## Probe token, Vaultwarden copy, DB path (2026-11-20)

- **Probe token:** `forgejo_admin_api_token` is a `read:admin` token named
  `runner-probe` for user cda. It was generated on servy and written straight
  into secrets.yml.
- **What the API actually returns:** the admin runners endpoint returns
  `status` (idle / active / offline), not an `online` boolean, and has no
  last-seen field. The probe now takes:
  - online state from the API;
  - `last_online` and job counts from SQLite. Job status codes are 5 = waiting
    and 6 = running, not 1/2 (those are success and failure).
- **Live DB path:** the database is `ci/data/data/gitea.db` in WAL mode, not
  `ci/data/gitea/forgejo.db`. That meant:
  - the restic exclude never matched, so the live DB was in servy's home
    backup;
  - the probe's `immutable=1` read would have ignored the WAL.

  The excludes now cover gitea.db plus its -wal/-shm, sessions and
  repo-archive. The probe reads with WAL visibility, as the probe's uid.
- **Vaultwarden:** `plays/forgejo_vaultwarden.yml` (`--tags ci.vaultwarden`)
  pushes the admin password as "forgejo - admin (ci.lehel.xyz)".

## Later changes

- 2026-11-23: Forgejo upgraded to 17.0.2, runny moved to a rootless runner scoped
  to `cda`, fail2ban stopped banning runner polling, and the `lehel` theme went
  live. See [`2026-11-23_ci-server.md`](2026-11-23_ci-server.md). Usage and
  operations: [`ci/AGENTS.md`](../ci/AGENTS.md).
