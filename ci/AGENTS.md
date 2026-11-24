# ci/ — Forgejo (Git + Actions CI) at ci.lehel.xyz

Self-hosted Forgejo on **servy**: private Git hosting, Forgejo Actions CI and a
package/container registry. It is meant to replace `git.lehel.xyz` (`git/`, the
EOL nginx-git image) and the fleet's dependency on GitHub. **No repo has been
migrated yet**, and `git/` + `git.lehel.xyz` stay untouched until that cut-over.

| | |
|---|---|
| URL | `https://ci.lehel.xyz` (test: `http://ci.servyy-test.lxd`) |
| Container | `ci.forgejo` on `servy.lehel.xyz` |
| Image | `codeberg.org/forgejo/forgejo:17.0.2-rootless` (v17 is **not** LTS; supported until 2027-01-28, so plan the next upgrade) |
| Database | SQLite, `./data/data/gitea.db` (WAL mode) |
| Access | private: registration closed, sign-in required, single admin `cda` |
| Git transport | HTTPS (access token) and SSH on port 22 via servy's host sshd (`git@ci.lehel.xyz:cda/<repo>.git`) |
| Runners | `codey` (arm64, dind) and `runny` (amd64, rootless): see `runny/AGENTS.md` |
| History | `history/2026-11-20_forgejo-platform-setup.md`, `history/2026-11-23_ci-ssh.md`, `history/2026-11-23_ci-server.md` (v17 + current state), `history/2026-11-23_runner-rootless.md`, `history/2026-11-23_forgejo-theme.md` |

## Using it

### Sign in

- Web UI: `https://ci.lehel.xyz`, user `cda`. The password is
  `forgejo_admin_password` in `ansible/plays/vars/secrets.yml`, with a copy in
  Vaultwarden as **"forgejo - admin (ci.lehel.xyz)"**.
- Public repos are anonymously readable since 2026-11-24
  (`REQUIRE_SIGNIN_VIEW=false`); private repos still require sign-in and all
  writes need a token/SSH key. Registration remains closed, so only accounts an
  admin creates exist.
- **Password basic auth is off** (`ENABLE_BASIC_AUTHENTICATION=false`). The
  password works only in the web login form. The API, git over HTTPS and
  `docker login` all need a **token**, sent either as the basic-auth password
  or as `Authorization: token …`. The API also cannot list or delete tokens
  any more: do that in the UI (Settings → Applications).
- The default theme `lehel` only applies to new accounts and signed-out pages.
  To use it on an existing account: Settings → Appearance → `lehel`.

### API token (managed)

API automation, and the agent skill `.claude/skills/managing-ci` (`fj` helper),
uses one `all`-scope token for `cda`:

- **Local copy:** `~/.config/forgejo/ci.<domain>.token` (0600).
- **Vaultwarden:** item `forgejo - api token (ci.<domain>)`.
- **Ansible:** `plays/forgejo_api_token.yml` → `roles/forgejo_bootstrap/tasks/api_token.yml`.
  Tags `user.docker.ci` / `user.docker.ci.token`.

The resolve order: local copy, else Vaultwarden (needs `~/.ssh/vw.key`). The
token is validated against the API from inside the container.

- **200:** keep it, and sync both copies.
- **401, or no copy anywhere:** mint `ansible-manage-<utc ts>` with
  `forgejo admin user generate-access-token`.
- **Anything else:** fail. A token is never minted blind.

A re-mint leaves the old token valid. Revoke it in the UI under Settings →
Applications.

### Git over SSH

```bash
git clone git@ci.lehel.xyz:cda/<repo>.git
```

The client key is `~/.ssh/ci_lehel` (ed25519). Its source of truth is the
Vaultwarden SSH Key item **"ssh - ci.lehel.xyz (cda)"**. setup-home restores it
and writes the `Host ci.lehel.xyz` block (`User git`, `IdentitiesOnly yes`):
`ansible-playbook ansible/plays/user.yml --tags user.ssh.vaultwarden`. That
needs `~/.ssh/vw.key` on a machine that lacks the key. The public key is
registered for `cda` as `ci_lehel (<host>)`. A new machine reuses the same key,
so it needs no new Forgejo entry. The host key you see is **servy's** (same
machine as `ssh servy.lehel.xyz`). `ssh git@ci.lehel.xyz` answers "Hi there, cda! You've
successfully authenticated…, but Forgejo does not provide shell access."

How it works (passthrough, no published port):

```
git@ci.lehel.xyz:22 -> servy sshd, Match User git (sshd_config.d/zz-forgejo-git.conf)
  AuthorizedKeysCommand /usr/local/bin/forgejo-keys -> sudo forgejo-exec keys -> docker exec `forgejo keys`
  forced command /usr/local/bin/forgejo-serv key-N  -> sudo forgejo-exec serv -> docker exec -i `forgejo serv`
```

- The host user `git` is **not** in the docker group. Its only privilege is
  `/usr/local/sbin/forgejo-exec` via sudoers. That wrapper accepts nothing
  but `keys <user> <type> <key>` and `serv key-<id>`, with each argument
  validated.
- The forced command comes from
  `FORGEJO__server__SSH_AUTHORIZED_KEYS_COMMAND_TEMPLATE` in `forgejo.env`.
  Forgejo's default points at `/app/gitea/gitea`, which exists only inside
  the image.
- No forwarding, TTY or agent for `git`. Failed logins go through the host
  sshd, so the existing sshd fail2ban jails cover them.
- servy's sshd has `MaxAuthTries 3`. The setup-home ssh config pins the key
  (`IdentitiesOnly`). Without it, a full agent can run out of attempts.
- If `ci.forgejo` is down, `git@` logins fail with "Permission denied
  (publickey)": the keys command gets no answer.
- Debug: `ssh servy.lehel.xyz 'sudo -u git /usr/local/bin/forgejo-keys git <type> <base64>'`
  prints the `command=` line Forgejo serves for that key, or nothing.
- Code: `ansible/plays/roles/forgejo_bootstrap/tasks/ssh_passthrough.yml`
  (tag `user.docker.ci.ssh`).

### Git over HTTPS

Create a personal access token (Settings → Applications, scope
`write:repository`, plus `write:package` if you push images) and use it as the
password:

```bash
git remote add forgejo https://ci.lehel.xyz/cda/<repo>.git
git push forgejo master            # username: cda, password: <token>
```

Create repos in the UI or with the API (`POST /api/v1/user/repos` with
`Authorization: token <token>`; see `.claude/skills/managing-ci`).

### Running CI

Workflows go in `.forgejo/workflows/*.yml`. Existing `.github/workflows` files
also run unchanged (`workflow_call` included). Pick a runner with `runs-on`:

| `runs-on` | Runner | Image / arch | Use it for |
|---|---|---|---|
| `ubuntu-latest` | codey | `catthehacker/ubuntu:act-22.04`, **arm64** | general jobs, tests |
| `docker` | codey | `node:20-bookworm`, arm64 | light node jobs |
| `arm64` | codey | act-22.04, arm64 | explicitly arm64 work |
| `amd64` | runny | act-22.04, **amd64** | amd64 image builds and running/testing amd64 images; global since 2026-11-24 (rootless runner, no host secrets) |

What to know before writing a workflow:

- **Actions come from `data.forgejo.org`**, not GitHub
  (`DEFAULT_ACTIONS_URL`), and there is no fallback. `actions/checkout`,
  `setup-node`, `docker/setup-buildx-action` and `docker/build-push-action` are
  mirrored and work. An action that is not mirrored fails the job with
  `remote: Not found`. Reference it by full URL instead
  (`uses: https://github.com/<owner>/<action>@<ref>`).
- **Artifacts:** `actions/upload-artifact@v4` and later fail
  (`not supported on GHES`). Use `@v3` or the Forgejo fork
  `https://data.forgejo.org/forgejo/upload-artifact@v4` (not yet verified on
  v17).
- **Cache:** `actions/setup-node` with `cache: npm` works on both runners.
  `cache-from/cache-to: type=gha` in `build-push-action` misses silently and
  builds cold. It does not fail.
- **Docker inside jobs:**
  - On `amd64` (runny), jobs get a rootless Docker socket, so
    `build-push-action` works. The job runs as the unprivileged `runner` user:
    no `--privileged` escape, host disk unreadable, `--memory=900m` enforced.
  - On codey, jobs get the dind socket. That one is privileged, see
    `runny/AGENTS.md`.
- **Keep heavy test suites off runny.** It is a 1-vCPU-class box (2 threads,
  951 MB, heavy CPU steal): vitest with `mongodb-memory-server` times out there.
  Run tests on `ubuntu-latest` (codey) and use `amd64` only for the amd64 image
  build (cold about 409 s, warm about 108 s).
- **Secrets:** repo or user Settings → Actions → Secrets, read as
  `${{ secrets.NAME }}`.

### Container registry

```bash
docker login ci.lehel.xyz -u cda          # password: token with write:package
docker push ci.lehel.xyz/cda/<image>:<tag>
```

In a workflow, log in with a token stored as a secret. Packages
(`./data/packages`) are **not backed up**: treat them as rebuildable.

### Dependency updates (self-hosted Renovate)

Renovate runs as a one-shot container on servy, once daily at 04:17
(`renovate.timer`, a user systemd timer). It uses the native Forgejo platform
(`RENOVATE_PLATFORM=forgejo`, endpoint `https://ci.lehel.xyz/api/v1`) and
autodiscovers repos. Repo-level `renovate.json` files work unchanged.

Credentials are rendered into `~/servyy-container/renovate/renovate.env` (0600)
from git-crypt `ansible/plays/vars/secrets.yml` at deploy time; **nothing calls
`bw` at runtime**. A dedicated Forgejo PAT plus read-only GitHub and Docker Hub
PATs are used as hostRules for datasource lookups. See `renovate/AGENTS.md`.

## Operating it

### Deploy

```bash
cd ansible
./servyy-test.sh --tags user.docker.repo,user.docker.ci                  # test first
./servyy.sh      --tags user.docker.repo,user.docker.ci --limit servy.lehel.xyz
```

`user.docker.repo` syncs servy's checkout, which is what carries `ci/custom/`
and the compose file. Never run the untagged playbook for a CI change: that
runs every play.

### Upgrade Forgejo

Renovate bumps the image tag in `ci/docker-compose.yml`. Merging that bump does
nothing until you deploy. The procedure used for 15.0.12 → 17.0.2 on 2026-11-23:

1. Read the release notes' breaking changes for every major version crossed.
2. Run on servyy-test first (deploy as above), including one Actions job.
3. Fresh DB dump, then flush queues on servy:
   ```bash
   ssh servy.lehel.xyz 'systemctl --user start forgejo-dump.service; ls -la ~/servyy-container/ci/data/backup/'
   ssh servy.lehel.xyz 'docker exec ci.forgejo forgejo manager flush-queues'
   ```
4. Deploy to servy. Migrations run on start: check
   `docker logs ci.forgejo | grep Migration` and the API version
   (`GET /api/v1/version`).
5. Check the runners are `idle` again (they log a few seconds of
   `failed to fetch task` 502/405 during the restart; that is expected).
6. **Re-check the sign-in page.** `custom/templates/user/auth/signin.tmpl` is a
   full-template override and can break on any upgrade.

`forgejo doctor check --all` reports `/var/lib/gitea/data/log ... not
accessible`. That is harmless: Forgejo logs to the console here.

### Backup

- The bare repos (`./data/git/repositories`) ride servy's `home` restic repo.
- A nightly DB dump goes to `./data/backup/forgejo-db-<ts>.tar.gz` (systemd
  **user** timer `forgejo-dump.timer`, 01:30, keeps the last 3). It runs
  `forgejo dump --database sqlite3` and skips repos, logs, attachments and
  packages.
- **Excluded on purpose:** the live `gitea.db` (+ `-wal`/`-shm`), because a
  snapshot of a live SQLite file is worthless, and the package registry.

### Configuration

- All config comes from `forgejo.env`, rendered by the `docker_service` role from
  `ansible/plays/roles/docker_service/templates/ci/forgejo.env.j2`
  (`FORGEJO__<section>__<KEY>`). Secrets come from `plays/vars/secrets.yml`. Nothing
  secret goes in the compose file (compose files are plaintext, see the
  git-crypt rule in AGENTS.md).
- Forgejo writes its own `./data/custom/conf/app.ini`. Do not mount over
  `/var/lib/gitea/custom` as a whole: only `custom/templates` and
  `custom/public` are mounted (read-only).

## Registration model (shared secret)

Runners register offline with a shared secret, no UI step:

- Forgejo side (servy, `forgejo_bootstrap` role):
  `forgejo forgejo-cli actions register --secret <forgejo_runner_secrets[<runner>]> --name <runner> --keep-labels [--scope <owner>]`.
  `--keep-labels` stops a re-registration from wiping the other runners' labels.
  `--scope` comes from `forgejo_runner_scopes`; it is empty for both runners since 2026-11-24, so neither is scoped.
- Runner side (`forgejo_runner` role, on codey/runny):
  `forgejo-runner create-runner-file --instance https://ci.lehel.xyz --name <runner> --secret <forgejo_runner_secrets[<runner>]>`

Both reference `forgejo_runner_secrets[<runner>]` from `plays/vars/secrets.yml`, never a
`lookup('password', …)` seed (AGENTS.md rule 6).

servy's fail2ban crawler and rate-limit queries ignore
`/api/actions/runner.v1.*`. The runners poll every 2 s and used to get banned
mid-job.

## Monitoring

- `[metrics] ENABLED=true` + a bearer `TOKEN` (rendered into
  `monitor/rendered/forgejo-metrics-token`), scraped by servy's Prometheus over
  the `proxy` network (`ci.forgejo:3000/metrics`).
- Runner liveness is probed from servy by `system_probe`'s
  `forgejo_runners.sh.j2`, which queries the Forgejo admin API and pushes
  `forgejo_runner_online` / `forgejo_runner_last_seen_seconds` /
  `forgejo_actions_jobs` to the Pushgateway.
- Grafana dashboard `forgejo-ci.json`. Alerts: `forgejo_down`,
  `forgejo_runner_offline`, `forgejo_jobs_stuck_waiting`, `runny_swap_exhausted`.

See `ansible/plays/roles/forgejo_bootstrap/` for the admin-user + runner
registration + DB-dump timer.

## Theme

A custom "modern developer" look (Space Grotesk headings, Inter body, JetBrains
Mono for hashes/metrics/tags; amber accent; rounded cards; a faint 24px grid
background; automatic light/dark via `prefers-color-scheme`). Everything lives
in the tracked `ci/custom/` tree, mounted read-only into the container's
`CUSTOM_PATH` (`/var/lib/gitea/custom` on the rootless image):

```
ci/custom/
  public/assets/css/theme-lehel.css   # the theme (registered below)
  public/assets/js/theme-lehel.js     # hero version + keyboard shortcuts
  public/assets/fonts/*.woff2         # Inter / Space Grotesk / JetBrains Mono (OFL)
  public/assets/fonts/OFL-*.txt       # the font licences
  templates/user/auth/signin.tmpl     # full-template override (see risk note)
  templates/custom/body_inner_post.tmpl # loads theme-lehel.js before </body>
```

- **Registration**: `FORGEJO__ui__THEMES=forgejo-auto,forgejo-light,forgejo-dark,lehel`
  and `FORGEJO__ui__DEFAULT_THEME=lehel` in
  `ansible/plays/roles/docker_service/templates/ci/forgejo.env.j2`. Theme name =
  the CSS filename minus the `theme-` prefix / `.css` suffix.
- **How it works**: `theme-lehel.css` starts with
  `@import "./theme-forgejo-auto.css"`, the built-in auto theme, which is always
  served at `/assets/css/theme-forgejo-auto.css`. That keeps every `--color-*`
  variable the app references defined. The file then overrides the semantic
  surface/text/accent variables for light, and again inside
  `@media (prefers-color-scheme: dark)`. It is loaded *instead of* the built-in
  theme when `lehel` is the default, so it must re-declare the variables it
  changes. Do not remove the `@import`.
- **Sign-in hero**: `templates/user/auth/signin.tmpl` is a **full-template
  override** (the only one). Forgejo has no hook that places content beside the
  sign-in card: `custom/signin_mid.tmpl` only injects *inside* the card. The
  override adds a `.lehel-hero` column and keeps `signin_inner` unchanged.
  **Upgrade risk**: this template must be re-checked on Forgejo upgrades.
- **No fake data**: the hero's "Forgejo {version}" and host come from
  `window.config`, which Forgejo sets. `theme-lehel.js` never invents values.
  The design's runner-status card and push heatmap are **deliberately
  omitted**: a signed-out user can't reach those APIs on 17.0.2.
- **Keyboard shortcuts** (in `theme-lehel.js`): `/` focuses search,
  `g a` → `/admin/actions`, `g r` → `/explore/repos`.
- **To change it**: edit `ci/custom/public/assets/css/theme-lehel.css`, run
  `./servyy-test.sh --tags user.docker.repo,user.docker.ci -e docker_branch=<branch>`
  (test), check the sign-in page in a **signed-out** browser at desktop and phone
  width, then deploy to prod as above. A template change (`signin.tmpl`) needs a
  `docker restart ci.forgejo`. Fonts are self-hosted under
  `custom/public/assets/fonts` (OFL), so do not add Google Fonts calls.
