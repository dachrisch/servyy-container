# Moodle (OFFD) — blank instance on servy, `m.leaguesphere.app`

**Date:** 2026-10-27
**Plan:** [docs/plans/2026-10-27-moodle-offd-hosting.md](../docs/plans/2026-10-27-moodle-offd-hosting.md)
**Branch:** `feat/moodle-offd` (fast-forwarded onto `master`)

## What this is

Christoph runs the referee-training platform OFFD ("Flag Academy") as a Moodle instance on €15/month
FTP-only shared hosting at All-Inkl, and maintains it by unzipping release archives by hand. The
2026-10-27 LeagueSphere v5 call decided to move it onto our infrastructure as a maintained Docker
stack. This change lands the **blank instance**; the data migration and the `offd.de` cutover are
separate, later steps.

Chosen shape: a `docker_service` on `servy`, next to LeagueSphere, with its data on existing server
storage — not a separate VM. A 100 GB Hetzner volume was built first and then **detached and deleted
the same day**, because no new spend should happen before the real import has been measured.

## What was built

| Piece | Where |
|---|---|
| Compose project (`app` + `db` + `cron`) | `moodle/docker-compose.yml` |
| Pinned image (official Moodle PHP base + Moodle 4.5.12) | `moodle/app/Dockerfile` |
| Upgrade guard entrypoint | `moodle/app/entrypoint.sh` |
| Subdirectory guide | `moodle/AGENTS.md` |
| `docker_service` block + `compose_build` support | `ansible/plays/user.yml`, `roles/docker_service/tasks/deploy.yml` |
| Rendered env/config templates | `roles/docker_service/templates/moodle*.j2` |
| Volume mount/format/ownership | `roles/user/tasks/moodle_volume.yml`, `moodle_data_dirs.yml` |
| Inventory (prod + test) | `ansible/production`, `ansible/testing` |

**Storage:** `<service dir>/data` on the root disk — `moodledata/` (uid 33) and `mariadb/` (uid 999),
217 MB for a blank instance, 21 GB free on `/`. The volume support stays dormant in the repo behind
`moodle_volume_device`; attaching one later is a two-line inventory change plus `moodle_data_root`.
The Storage Box is deliberately excluded: it is CIFS (unsafe for InnoDB locking/fsync) *and* the
restic destination, so it cannot also hold the only copy. `restic-home` now excludes
`servyy-container/moodle/data` so the hourly snapshot does not try to upload a live datadir.

**URL shape:** Moodle lives at `/var/www/html/offd/moodle` so the on-disk path mirrors the live
wwwroot `https://offd.de/offd/moodle`. No rewrite rule, and the 14 GB database keeps its absolute
URLs when it is imported. `$CFG->wwwroot` is derived from the `moodle_service_host` inventory var, so
the eventual move to `offd.de` is one variable plus the A record — not a DB edit.

## Verified

- `https://m.leaguesphere.app/offd/moodle/` → `200 Home | offd`; login page renders its form.
- Let's Encrypt certificate issued via HTTP-01, valid to 2027-01-25 (neither `offd.de` at All-Inkl
  nor `leaguesphere.app` at GoDaddy is in Porkbun scope, so DNS-01 cannot be used).
- Installed version `4.5.12 (Build: 20260608)` — **the same build live offd.de runs**, so the later
  import needs no upgrade at all.
- Cron container runs `admin/cli/cron.php` every minute (`Cron run completed correctly`).
- Memory: 209 MB app + 223 MB db + 128 MB cron against 768/768/256 limits; host keeps ~3 GB available.
- Same stack validated first on `servyy-test.lxd` (TLS off, `./data` instead of the volume).

## Five things that had to be fixed on the way

Recorded because each was a 403/500 whose cause is not visible from the symptom:

1. **Overriding the image's ENTRYPOINT kills the site.** `moodlehq/moodle-php-apache` ships
   `moodle-docker-php-entrypoint`, which exports `APACHE_DOCUMENT_ROOT`; without it the vhost has an
   empty DocumentRoot and every request is a 403. Our guard now precedes that entrypoint instead of
   replacing it.
2. **`$CFG->reverseproxy` must not be set.** Moodle 4.5 raises `reverseproxyabused` when the request
   Host matches wwwroot (it expects the proxy to rewrite Host; Traefik preserves it). `sslproxy`
   alone is correct.
3. **`docker_compose_v2` never rebuilt the image** — compose's `missing` policy silently served the
   old tag after a Dockerfile change. New opt-in `compose_build` var on the role (default `omit`, so
   pre-built-image services are unaffected).
4. **The `docker_service` role could not see `services`** (a `set_fact` from the play's task list,
   which runs after roles) — role-level includes silently skipped. They read `services_enabled.<name>`.
5. **TLS-dependent settings are gated on `TRAEFIK_TLS`**: wwwroot scheme, `sslproxy`, and the
   http→https redirect router. Without that, `servyy-test.lxd` (no https listener) redirected every
   request into a void.

The blank instance was installed with `admin/cli/install_database.php` — the web installer cannot
write the Ansible-rendered `config.php`.

## Not done yet

- **Backups (`restic-moodle`) and one executed restore drill — must land before any real data.**
- Dry run: 14 GB over `lftp` + the `mysqldump` from All-Inkl (still the hard dependency on Christoph).
- Cutover: `offd.de` A record → servy, new `MOODLE_WSTOKEN` in `secret_main.yaml` + `secret_stage.yaml`,
  then the `m.` router removed.
- Upgrade automation (watchtower scope is deliberately unset; 5.x stays manual — the docroot moves to
  `/public`).

## Rollback

Fully additive. `moodle: false` in `services_enabled` plus `docker compose -p moodle down`; the
volume and its data stay. Nothing existing on servy was modified.
