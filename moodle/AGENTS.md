# moodle/ — Moodle (OFFD / Flag Academy)

Christoph's referee-training platform, moved off €15/month FTP-only shared hosting onto servy.
Live target: `https://offd.de` (root of the host — not a subpath). Rehearsal hostname:
`m.leaguesphere.app` (wildcard `*.leaguesphere.app` → servy, no DNS work needed).

**Plan, verified baseline, cutover runbook:** [docs/plans/2026-10-27-moodle-offd-hosting.md](../docs/plans/2026-10-27-moodle-offd-hosting.md)

## Layout

| Container | Image | Purpose |
|---|---|---|
| `moodle.moodle` | `erseco/alpine-moodle:v4.5.15` | nginx + php-fpm + **cron**, one container, configured by env |
| `moodle.db` | `mariadb@sha256:2bdff15…` (already on the host) | project-internal DB, no published port |

There is **no separate cron container, no `config.php` in git, and no Dockerfile**: the image writes
`config.php` from env vars on first boot, runs `admin/cli/install.php`, and runs
`admin/cli/upgrade.php` whenever the image is newer than the database (`AUTO_UPDATE_MOODLE=true`).

Data (never in git): `$MOODLE_DATA_ROOT/{moodledata,mariadb}` — existing server storage
(`<service dir>/data`). Ansible owns the directories and their ownership:
[`roles/user/tasks/moodle_data_dirs.yml`](../ansible/plays/roles/user/tasks/moodle_data_dirs.yml).
A dedicated volume is supported but not used: set `moodle_volume_device` + `moodle_volume_path`.

## Load-bearing invariants — do not "clean these up"

1. **Served at the host root, not at a subpath.** Upstream Moodle does not support path-based serving
   (erseco docs, issue #127) and the image owns its docroot. The old live site was
   `https://offd.de/offd/moodle`, which is why the imported database needs a one-time `wwwroot`
   search-replace — see the plan, Task 5. Never reintroduce a subpath.
2. **The service name becomes a DNS alias on the shared `proxy` network** and must stay globally
   unique. It is `moodle` on purpose; `app` took leaguesphere.app down for 10 minutes on 2026-10-27.
3. **`moodledata` must be owned by uid 65534** (`nobody` — Alpine). Wrong ownership does not error at
   start; Moodle fails later, deep inside an unrelated request.
4. **`SITE_URL` is `$CFG->wwwroot`** and is derived from `service_host`, so the cutover to `offd.de`
   is one inventory value plus the A record. No trailing slash, no path.
5. **`REVERSEPROXY` must stay `false`.** On a single-URL deployment it makes Moodle answer
   "Reverse proxy enabled so the server cannot be accessed directly". `SSLPROXY=true` is the correct
   knob behind a TLS-terminating proxy (and follows `TRAEFIK_TLS`).
6. **`MOODLE_SITENAME` may not contain spaces** — the image passes it to `install.php` unquoted, so
   first boot dies with "unrecognized options". The real display name comes from the imported DB.
7. **HTTP-01, not DNS-01.** Neither `offd.de` (All-Inkl) nor `leaguesphere.app` (GoDaddy) is in
   Porkbun scope, so `letsencryptdnsresolver` cannot issue.

## The image rewrites site settings on every boot

`02-configure-moodle.sh` runs `configure_moodle_settings` and `update_admin_user.php` on **every**
container start — not only at install. On an already-installed database that means env wins over
whatever is in the DB for:

| env var | writes |
|---|---|
| `MOODLE_USERNAME` / `MOODLE_PASSWORD` / `MOODLE_EMAIL` | the **first** site admin (`get_admin()` → lowest id in `siteadmins`) |
| `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`/`SMTP_PROTOCOL` | `smtphosts`, `smtpuser`, `smtppass`, `smtpsecure` |
| `MOODLE_MAIL_NOREPLY_ADDRESS`, `MOODLE_MAIL_PREFIX` | `noreplyaddress`, `emailsubjectprefix` |
| — (hardcoded) | `enableblogs=0`, `pathtophp`, `pathtodu`, `debug`/`debugdisplay` |

Consequences for OFFD: the site admin is the role account `OFFD Admin` (id 2) and its password is
**Ansible-managed** — changing it in the UI reverts at the next deploy. `enableblogs` is forced to 0
with no env override despite 2 existing blog posts. Mail settings must be supplied via env or the
image writes placeholder Gmail credentials.

This bit us once on 2026-10-28: importing Christoph's dump silently rewrote the admin email, the
noreply address and the mail prefix.

## Plugins

Third-party plugins live outside the image and are installed **at every boot** from `PLUGINS=`
(`type_name=url`, space separated) in `moodle.app.env.j2`, so the code tree stays immutable.
OFFD has exactly two, and only one is in use:

- **`enrol_waitlist`** (version `2025072001`) — **required**: 35 courses use the `waitlist`
  enrolment method.
- `qbehaviour_adaptiveallnothing` — installed in the DB, used by **no** quiz.

## Everyday operations

```bash
# deploy / re-render .env, db.env, app.env (after an inventory change)
cd ansible && ./servyy.sh --tags user.docker.repo,user.docker.moodle --limit servy.lehel.xyz

# logs (nginx, fpm, cron and Moodle all log to stdout — one container, one log)
ssh lehel.xyz "docker logs moodle.moodle --tail 100 -f"

# pending upgrade check (exit 2 = upgrade required)
ssh lehel.xyz "docker exec -u 65534 moodle.moodle php /var/www/html/admin/cli/upgrade.php --is-pending; echo \$?"

# run a CLI task
ssh lehel.xyz "docker exec -u 65534 moodle.moodle php /var/www/html/admin/cli/cron.php"
```

Version bumps: change the image tag in `docker-compose.yml` (renovate opens PRs for `v4.5.x`);
on the next deploy the container starts, notices the DB is older than the code, and runs
`upgrade.php` automatically. Major versions (5.x) stay a **manual, rehearsed** event — Moodle 5.1+
moves the docroot to `/public` and every plugin needs re-verification.

## Verifying a `moodledata` export before importing it

Every `filedir` file is named after the SHA1 of its content, so the *file set* looking complete proves
nothing — the 2026-11-03 export had all 9,317 DB hashes present **by name** while 9,247 files were
ASCII-mangled. Always hash the content against the filename, streaming it straight out of the tar
(no extract, no disk needed):

```bash
ssh lehel.xyz "sudo python3 - <<'PY'
import tarfile, hashlib
p='/var/jail/home/leaguesphere/moodledata.tar.gz'
ok=bad=0
with tarfile.open(p,'r|gz') as tf:
    for m in tf:
        if not m.isfile(): continue
        parts=m.name.split('/')
        if len(parts)==5 and parts[1]=='filedir':
            h=hashlib.sha1(); f=tf.extractfile(m)
            while (b:=f.read(1<<20)): h.update(b)
            ok += h.hexdigest()==parts[4]; bad += h.hexdigest()!=parts[4]
print('filedir_sha1_ok', ok, 'bad', bad)   # bad must be 0
PY"
```

Two corroborating signals from the bad export: every mtime equalled the download time, and any file
whose content contains a bare LF failed. Note the Storage Box CIFS mount has thrown `Bad address` on
a large single-stream `mv` — verify sha256 after copying, and retry with `cp`.

## Backups (restic)

Two scopes, both gated on `moodle_enabled` (`services_enabled.moodle`), sharing one password
(`restic_password_moodle`, seed `plays/vars/.restic_password_moodle` + the Vaultwarden item
`restic - moodle (lehel.xyz)`):

| Repo | Source | Timer | Retention |
|---|---|---|---|
| `restic-moodle-db` | `…/data/db-backup/current/` — logical `mariadb-dump --single-transaction` written at `:40` | snapshot `*:50` (hourly) | 24 h / 14 d / 8 w / 6 mo + last 24 |
| `restic-moodle-files` | `…/data/moodledata` (sudo) | daily `01:20` | 7 d / 4 w / 6 mo + last 7 |

- **Two repos, not one with two tags:** the hourly DB stream and the ~6 GB file stream must not share
  locks/prune, and `system_probe` reports one snapshot age per repo — one repo would hide stale files
  behind a fresh DB snapshot.
- **Logical dump, not `mariadb-backup`:** same pattern as `bnb-office.db` and the nightly LeagueSphere
  prod→stage sync; needs no bind mount in `docker-compose.yml`, and `log_bin` is OFF on this DB so a
  physical set would not buy PITR either. Want PITR? Add `--log-bin` to the `db` command in
  `docker-compose.yml` first.
- **Ordering matters:** files are snapshotted *after* the 00:40 dump, so the file set is a superset of
  the DB's references. Files are content-addressed and never rewritten in place, so this cannot lose
  content.
- The dump script refuses to write a dump smaller than 10 MB or failing `gzip -t`, **verifies after the
  swap** that `current/moodle.sql.gz` has exactly the byte size just dumped (a nested
  `current/new/` would otherwise leave the old dump in place), and the `moodle-db` restic script
  **exits 1 if `current/` is older than 2 h** — a dead dump job must not keep producing fresh-looking
  snapshots of old data.
- **The pre-cutover baseline is pinned.** The first pair (files `5.781 GiB` + the 11:04 dump) is
  tagged `baseline`, and both moodle forget calls pass `--keep-tag baseline`, so the tag survives the
  GFS buckets instead of ageing out after ~6 monthly runs. Pin any later snapshot the same way:
  `restic tag --add baseline <id>` inside the repo's env.
- `current/` must always contain **exactly one** `moodle.sql.gz`. If it ever contains a `new/`
  subdirectory, the swap regressed (see `history/2026-11-06_moodle-restic-scopes.md`, learning 8).

```bash
# status / sizes
ssh lehel.xyz 'systemctl --user list-timers --all | grep moodle'
ssh lehel.xyz "sudo bash -c 'source /etc/restic/env.moodle-files && restic snapshots --no-lock'"
# force a cycle
ssh lehel.xyz 'systemctl --user start moodle-dump.service && systemctl --user start restic-backup-moodle-db.service'
# logs
ssh lehel.xyz 'sudo tail -20 /var/log/restic/backup-moodle-{db,files}.log /var/log/restic/moodle-dump.log'
```

**Restore runbook** (rehearsed end-to-end on `servyy-test.lxd` 2026-11-06 — full loss, both scopes):

```bash
cd /home/cda/servyy-container/moodle && docker compose -p moodle down
sudo mv data/moodledata data/moodledata.aside && sudo mv data/mariadb data/mariadb.aside
# re-hydrate both scopes through the restic role (other scopes skip on a healthy host):
cd /home/cda/dev/infrastructure/container/ansible && ./servyy.sh --limit servy.lehel.xyz --tags restic.restore
docker compose -p moodle up -d db                  # initialises a FRESH datadir
for i in $(seq 1 40); do [ "$(docker inspect -f '{{.State.Health.Status}}' moodle.db)" = healthy ] && break; sleep 3; done
sudo gunzip -c data/db-backup/current/moodle.sql.gz | docker exec -i moodle.db sh -c 'exec mariadb -uroot -p"$MARIADB_ROOT_PASSWORD"'   # ~7 min
docker compose -p moodle up -d                     # app
docker exec -u 65534 moodle.moodle php /var/www/html/admin/cli/purge_caches.php
```

Verify afterwards: `select count(*) from mdl_files` / `mdl_course` match the pre-loss numbers, and the
front page returns 200. Two mode facts: the dump is written `0644` inside a `0755` dir on purpose (the
host's sudo umask is 027), and Moodle re-applies its own `$CFG->directorypermissions` (`02777`) to the
dataroot on the next boot, so a restored tree ends up `2777` rather than the import's `2770` — that is
Moodle, not the restore.

## Not done yet (see the plan)

- The `leaguesphere` side of the URL change: `MOODLE_URL` plus the hardcoded `/moodle/…` segments in
  `officials/service/moodle/`. Not touched yet on purpose — prod LeagueSphere still points at the old
  live offd.de until the search-replace is proven on the test box.
- Plugin list → `PLUGINS` in `moodle.app.env.j2` (installed at every boot, so the code tree stays
  immutable).
- SMTP env (`SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`) once the mail decision is made.
- Binlogs for point-in-time recovery (see "Backups" above).
