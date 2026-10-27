# Fork status — move OFFD's Moodle off shared hosting onto servy (next to LeagueSphere)
Written: 2026-10-27 22:5x (Europe/Berlin)

## Done

- **container** `master` — `ae5d890` `feat(moodle): add OFFD Moodle stack (app+db+cron) with attached
  data volume`, `2ff83c5`, `ae5d890` fixes; `d737902` `chore(moodle): use existing server storage`;
  `49c26d0` docs. All pushed to `origin` (github.com/dachrisch/servyy-container).
- **container** `master` — `f6edd97` **switched to `erseco/alpine-moodle:v4.5.15`** (nginx+fpm+cron in
  one container, env-configured, PHP 8.3.36). The self-built image (`moodlehq/moodle-php-apache:8.3` +
  4.5.12 tarball, `app/Dockerfile`, upgrade-guard entrypoint, `moodle.cron`, rendered `config.php`) is
  **gone**. Reason: a local build owns the PHP patch cadence and nothing can pull it; `v4.5.12` was
  rejected because that tag ships PHP 8.3.15 (Dec 2024, unpatched). See
  `history/2026-10-28_moodle-image-switch.md`.
- **URL is now the host root, not `/offd/moodle`** — upstream Moodle does not support subpaths and the
  image owns its docroot. Decided while the instance is empty on purpose (see In progress).
- **container** `master` — Ansible: `docker_service` block, `compose_build` support in
  `roles/docker_service/tasks/deploy.yml`, templates `moodle.env.j2` / `moodle.db.env.j2` /
  `moodle.config.php.j2`, `roles/user/tasks/moodle_volume.yml` + `moodle_data_dirs.yml`,
  `vault_moodle_db_{,root_}password` seeds, prod + testing inventory entries.
- **Live URL: https://m.leaguesphere.app/** — blank instance reinstalled on the new image,
  `200 Startseite | moodle`, `/login/index.php` 200 with form, Let's Encrypt cert (HTTP-01) valid to
  2027-01-25. Version `4.5.15 (Build 20261005)`, PHP 8.3.36.
  Blank-instance admin is `admin` with `vault_moodle_admin_password` (Ansible seed at
  `ansible/plays/vars/.moodle_admin_password`, generated on the controller). Earlier throwaway
  credentials are void: the instance was reinstalled on the new image and its database wiped.
- **servy** — `moodle.moodle` / `moodle.db` / `moodle.cron` healthy, 0 restarts, cron ticking each
  minute; installed version `4.5.12 (Build: 20260608)` = identical to live offd.de, `--is-pending` rc 0.
- **servy** — data on existing root-disk storage: `/home/cda/servyy-container/moodle/data/{moodledata,mariadb}`
  (217 MB, 21 GB free on `/`). The 100 GB Hetzner volume was detached, deleted and removed from fstab
  the same day (no new spend before the import is measured). Volume support stays dormant behind
  `moodle_volume_device`.
- **container** — `docs/plans/2026-10-27-moodle-offd-hosting.md` (plan + verified status + six
  gotchas), `history/2026-10-27_moodle-offd-blank-instance.md` and
  `history/2026-10-27_moodle-proxy-alias-outage.md`.
- **Incident fixed (`e807aff`, `2c4d32c`)** — the service was named `app`, which hijacked the `app`
  DNS alias on the shared `proxy` network and took **leaguesphere.app down for ~10 min** (frontend
  re-resolves `app:8000` every 5 s → 502 → unhealthy → Traefik withdrew routers → 404). Renamed to
  `moodle` (container `moodle.moodle`), alias now unique; verified again after a forced recreate.
  Service also registered in `docker.services[]` (health probe) and `forall_docker_services.sh`,
  which the first pass had missed; `host_ping` gained an optional per-entry `host`.
- Validated first on `servyy-test.lxd` (`moodle: true`, TLS off), as the repo requires.

## In progress / blocked

- **Blocked on Christoph's export** — the `mysqldump` from All-Inkl plus the 14 GB `moodledata`
  (`lftp mirror`). He promised the export for **2026-10-28**; without the dump the migration would
  lose quiz attempts, grades and the custom profile fields LeagueSphere reads.
- Still unknown from him: actual DB size, plugin list (`Site admin → Plugins overview`), whether
  `www.offd.de` moves too, whether anything else lives on `offd.de/`.
- Not started: `restic-moodle` scope (backup gate before real data lands) and one executed restore
  drill on `servyy-test.lxd`.

## Open decisions

- If 14 GB + DB does not fit in the 21 GB free: prune/relocate on the host first, buy a volume second
  (€4.40/100 GB)? Options: prune / volume / shrink scope.
- Moodle's outgoing mail: no central SMTP relay exists in this repo (services use a Gmail app
  password). Options: Gmail relay / transactional provider + SPF-DKIM at All-Inkl.
- Cutover timing and window — must be before the Lehrgänge are created for the January season.
- Ownership/billing (sync-doc Open Question #1) — currently €0 new spend, so it is not urgent.

## Background tasks

- None dispatched by this session.
- **Foreign working-tree state (not mine, do not sweep into a commit):** another concurrent session is
  editing this same checkout — it committed `f9012e4` (monitor/Grafana provisioning) and
  `6714de0`/`5980069` (repo-sync chmod) during this work, and may have further uncommitted edits in
  `ansible/plays/...`. Check `git status` and `git diff` before any `git add -A`.
- Note: `git merge` in this repo dies with `fatal: stash failed` (git-crypt smudge filter). Workaround
  used: fast-forward with `git reset --hard <branch>` when the branch is a descendant of `master`.

## Owed: the url change on the LeagueSphere side

Decided, not started, and **must not be touched until the replace is proven on the test box** —
prod LeagueSphere keeps pointing at the old live offd.de in the meantime:

1. `leaguesphere` repo: `MOODLE_URL` in `secret_main.yaml` **and** `secret_stage.yaml`.
2. `leaguesphere` code: the hardcoded `"/moodle/…"` segments in
   `officials/service/moodle/moodle_api.py` (`webservice/rest/server.php`, `login/token.php`) and
   `moodle_service.py` (`MOODLE_PROFILE`, `MOODLE_COURSE`), plus their tests.
3. One-time `wwwroot` replace for teacher-entered absolute links in course content.

## Next step

Add the `restic-moodle` scope (daily moodledata snapshot + hourly `mariadb-backup` set, seed file +
vaultwarden item + `restic_seeds` entries) and run **one restore drill on `servyy-test.lxd`** — that
is the gate before the 14 GB lands. Then, when the export arrives, dry-run the import on
`m.leaguesphere.app`: `lftp mirror` the 14 GB, import the dump into `moodle.db`, keep the code at
4.5.12, and point **stage** LeagueSphere (`secret_stage.yaml`) at `https://m.leaguesphere.app/offd` to
exercise the web service end-to-end.
