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

- **DB dump ARRIVED 2026-10-28 and is fully rehearsed** (details:
  `history/2026-10-28_offd-dump-measured-and-rehearsed.md`). 134 MB gz / 1.62 GB, MariaDB 10.6,
  4 248 users, 104 courses, 1.67 GB (58 % is the standard log), only two third-party plugins
  (`enrol_waitlist`, `qbehaviour_adaptiveallnothing`). Imported + auto-upgraded 4.5.12 → 4.5.15 on
  `servyy-test.lxd`; front page renders `Home | Flag Academy`.
- **Still blocked on the ~14 GB `moodledata`** — the other half of the export. Without it
  `pluginfile.php` links 404 (images/PDFs/SCORM), so the file half of the migration is unexercised.
- wwwroot replace is measured, not guessed: **~134 live rows** (`mdl_question.questiontext` 106,
  `mdl_question_answers.answer` 13, `mdl_book_chapters.content` 8, `mdl_url.externalurl` 6,
  `mdl_page.content` 1, optional `mdl_question_attempts.questionsummary` 310). Proved on the test box
  against the real data → 0 hits left.
- Sizing settled: 1.67 GB DB + ~14 GB files ≈ 15.7 GB vs **21 GB free** → no volume needed.
- Still unknown from Christoph: whether `www.offd.de` moves too, whether anything else lives on
  `offd.de/`, and whether the 965 MB standard log should be kept or trimmed.
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

Three things, in order:

1. **Get the `moodledata` (~14 GB) onto prod** — the only unexercised half. Mirror it into
   `<service dir>/data/moodledata` (uid 65534), then spot-check a `pluginfile.php` link.
2. **Install `enrol_waitlist`** (expected version `2025072001`, needed by 35 courses): obtain the zip
   (Christoph's instance, or his browser — moodle.org 404s from here), serve it from a URL the host
   can reach, add it to `PLUGINS=` in `moodle.app.env.j2`, deploy, then run
   `admin/cli/upgrade.php --non-interactive` once so Moodle registers it.
3. **Decide outbound mail** (SMTP relay) — currently non-functional: the old host used its local MTA,
   this container has none, and the image fills in placeholder Gmail creds.
