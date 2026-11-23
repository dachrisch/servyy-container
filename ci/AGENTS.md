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
  `@import "./theme-forgejo-auto.css"` (the built-in auto theme — always served
  at `/assets/css/theme-forgejo-auto.css`) so every `--color-*` variable the app
  references stays defined, then overrides the semantic surface/text/accent
  variables for light, and again inside `@media (prefers-color-scheme: dark)`.
  It is loaded *instead of* the built-in theme when `lehel` is the default, so
  it must re-declare the variables it changes — do not remove the `@import`.
- **Sign-in hero**: `templates/user/auth/signin.tmpl` is a **full-template
  override** (the only one) because Forgejo has no hook that places content
  beside the sign-in card (`custom/signin_mid.tmpl` only injects *inside* the
  card). It adds a `.lehel-hero` column and keeps `signin_inner` unchanged.
  **Upgrade risk**: this template must be re-checked on Forgejo upgrades.
- **No fake data**: the hero's "Forgejo {version}" and host come from
  `window.config` (set by Forgejo); `theme-lehel.js` never invents values. The
  design's runner-status card and push heatmap are **deliberately omitted** —
  those APIs aren't available to a signed-out user on 17.0.2.
- **Keyboard shortcuts** (in `theme-lehel.js`): `/` focuses search,
  `g a` → `/admin/actions`, `g r` → `/explore/repos`.
- **To change it**: edit `ci/custom/public/assets/css/theme-lehel.css` and
  re-run `./servyy-test.sh --tags user.docker.ci` (test) then
  `./servyy.sh --limit servy.lehel.xyz` (prod). Forgejo must restart to pick up
  env/config changes; a plain `docker compose up -d` after the env render is
  enough. Fonts are self-hosted under `custom/public/assets/fonts` (OFL) — do
  not add Google Fonts calls.
