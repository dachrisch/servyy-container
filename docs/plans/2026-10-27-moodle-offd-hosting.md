# Moodle (offd.de) onto servy — Implementation Plan

**Status:** in progress — blank instance being stood up
**Owner:** Christian
**Source:** LeagueSphere v5 sync call 2026-10-27 (`leaguesphere/docs/topics/planning/current/2026-10-27-leaguesphere-v5-sync.md`, section 1 "ORFD (offd.de)")
**Deadline driver:** Lehrgänge are created before the training season starts in **January**; the migration should land well before that.

---

## Goal

Move Christoph's referee-training Moodle (`https://offd.de/offd/moodle`, ORFD/Flag Academy) off €15/month
FTP-only shared hosting onto this repo's infrastructure as a maintained Docker stack on `servy`,
with real backups, deliberate upgrades and plugin preservation.

**Chosen shape (decided 2026-10-27):** *Option A* — a `docker_service` on `servy`, next to LeagueSphere,
data on existing server storage (a dedicated volume only if the measured import needs one).
Not a separate VM.

---

## Verified baseline (2026-10-27, read from the running host)

| Fact | Value |
|---|---|
| Host | `servy` = `servy.lehel.xyz` = `49.13.6.173`, Hetzner CX33, fsn1, instance `122118372` (KVM) |
| Disk | 76 GB root, **65 GB used, 7.7 GB free (90 %)**; `docker system df` reports **23.8 GB reclaimable** images, 5.6 GB volumes |
| RAM | 8 GB nominal (7 GB visible), ~4 GB used, **2 GB swap already in use**, 4 vCPU, load ~2.1 |
| Volumes | **none attached** (`GET /volumes` → empty) |
| Docker root | `/mnt/10g_volume/docker` — a *directory* on the root disk (`has_10g_volume: false`), i.e. a leftover path from a detached 10 GB volume |
| Storage Box | 1 TB, 375 GB used, **625 GB free**, mounted at `/mnt/storagebox` |
| Restic | `home` (hourly, `/home/cda`), `root` (daily, `/etc` + `/var`, **`/mnt` excluded**), `db` (hourly, gated on `leaguesphere_enabled`) |

**The Moodle side (probed live):**

| Fact | Value |
|---|---|
| Real wwwroot | `https://offd.de/offd/moodle` — two path segments, verified from every asset URL on the page |
| DNS / host | `offd.de` → `85.13.146.136`, **All-Inkl KAS** (`ns5/ns6.kasserver.com`), nginx, no AAAA |
| Mail | `MX w00db14b.kasserver.com`, `SPF include:spf.kasserver.com` — **mail must stay at KAS** |
| Version | Moodle 4.5.12 (4.5 **LTS**, security-supported into 2027) |
| Data | ~14 GB, "very large" DB, no video; FTP-only access, no shell, no DB credentials |
| LeagueSphere coupling | `MOODLE_URL=https://offd.de/offd` + `/moodle/...` hardcoded in `MoodleApi`; `MOODLE_WSTOKEN`; reads `customfields` `teamname`/`teamid`/`LandesverbandAuswahl`/`Landesverband`; `core_user_update_users` writes licence numbers back; `login/token.php` with service `moodle_mobile_app` |
| `m.leaguesphere.app` | resolves via **`*.leaguesphere.app` wildcard → servy**, currently unclaimed (traefik serves its default self-signed cert) |

---

## Design decisions

1. **One stack, host swapped at cutover.** The instance rehearsed at `m.leaguesphere.app` *is* the
   production instance. At cutover only `SERVICE_HOST` changes and an `offd.de` router joins it — no
   second volume, no data move, nothing to drift.
2. **Served at the host root, with a one-time wwwroot replace at import.** Superseded decision (see
   below): the first design mirrored the live `/offd/moodle` path inside the docroot so the DB needed
   no search-replace. The prebuilt image owns its docroot and upstream Moodle does not support
   subpath serving, so wwwroot becomes `https://offd.de` and the imported DB needs **one** targeted
   search-replace (Task 5) — rehearsed on `servyy-test.lxd` against the real dump before prod.
3. **Maintained prebuilt image, not a self-built one** (changed 2026-10-27). `moodlehq/moodle-php-apache`
   ships no Moodle code, so "official + pinned" meant building the release tarball into an in-repo
   image — which left us owning the PHP patch cadence with no registry for watchtower to pull from.
   `erseco/alpine-moodle:v4.5.15` is nginx + php-fpm + cron, env-configured, tag per Moodle release,
   and renovate already watches compose image tags. It also ships **PHP 8.3.36**; `v4.5.12` was
   rejected precisely because it is PHP 8.3.15 (Dec 2024) and exposed to known PHP CVEs.
4. **MariaDB sidecar in the project**, no published port, mirroring `bnb-office` / `leaguesphere.db`.
5. **Data on existing server storage** (`<service dir>/data`), never the Storage Box: CIFS is a
   backup target, not a database, and it is the restic destination — it cannot also be the only copy.
   A dedicated volume is a deliberate later decision, taken only if the measured import needs it.
6. **Migration runs on 4.5.12 = the current version.** Migration and the 5.x leap are separate
   projects; combining them before January is how this fails. Moodle 5.1+ additionally moves the
   docroot to `/var/www/html/public`.
7. **`m.leaguesphere.app` is temporary.** The router is removed after cutover. Later rehearsals
   (5.x upgrade, restore drills) run on `servyy-test.lxd` on demand, as LeagueSphere already does.

---

## Task 1: Storage (no dedicated volume — decided 2026-10-27)

**Superseded:** a 100 GB Hetzner volume was created and attached during the first build-out, then
**detached and deleted on 2026-10-27** — no new spend until the real import has been measured.

Current: `moodle_data_root = /home/cda/servyy-container/moodle/data` on the root disk
(`moodledata/` uid 33, `mariadb/` uid 999, ~217 MB for a blank instance). Root disk: 75 GB total,
21 GB free.

**The Storage Box is not an option for these directories.** It is a CIFS mount: no safe `fsync`/
locking semantics for InnoDB, and it is the restic target — using it as primary storage would leave
no independent copy.

**Disk reality for the import:** ~14 GB moodledata + an as-yet-unknown DB against 21 GB free. It fits
with little headroom, so the dry run is also the sizing measurement. If it does not fit, the answers
in order of preference are (a) prune/relocate on the host, (b) buy a volume, (c) look again at
whether the DB can live elsewhere.

The volume path stays in the repo, dormant: set `moodle_volume_device` (+ `moodle_volume_path`) in the
prod inventory and `roles/user/tasks/moodle_volume.yml` formats-if-blank, writes fstab and mounts it;
`moodle_data_root` is the only other value to point at it.

```bash
# only if a volume is bought later
hcloud volume create --name moodle --size 100 --server servy --location fsn1 --format ext4
```
→ `/dev/disk/by-id/scsi-0HC_Volume_<id>`, mounted via `ansible/plays/roles/user/tasks/moodle_volume.yml`
(format-if-unformatted → fstab → mount → `moodledata/` owned by uid 33, `mariadb/` owned by 999).
100 GB ≈ €4.40/month. **Not** `/mnt/10g_volume`: that path already holds docker layers on the root
disk and mounting over it would hide them.

---

## Task 2: The service (`moodle/`, `docker_service`)

```
moodle/
├── docker-compose.yml      moodle (erseco/alpine-moodle) + db, mem limits, traefik labels
└── AGENTS.md               subdirectory guide (repo convention)
```

No Dockerfile, no entrypoint, no cron container and no rendered `config.php`: the image writes
`config.php` from env, installs on first boot, and runs `upgrade.php` when the image is newer than the
database. `moodledata` must be owned by **uid 65534** (`nobody`), not 33 — the image is Alpine.

- **app**: `MOODLE_DATABASE_*` from `db.env`, `MOODLE_DATA_ROOT` bind mounts, `mem_limit: 768m`,
  router `Host(${SERVICE_HOST})`, `letsencrypthttpresolver` (offd.de is at All-Inkl; `m.` is at GoDaddy
  — neither is in Porkbun scope), plus a `-root` middleware redirecting `/` → `/offd/moodle/`.
- **db**: `mariadb:lts` pinned to the digest already running on servy (zero pull), `mem_limit: 768m`,
  `mariadb-backup` friendly.
- **cron**: same image, `admin/cli/cron.php` every 60 s, `mem_limit: 256m`.
- Total worst case ≈ 1.8 GB. That is the real constraint on this host, not disk.

Ansible: `docker_service` block in `ansible/plays/user.yml` + `templates/moodle.env.j2` (base vars via
`{% include 'docker.env.j2' %}`) and `templates/moodle.db.env.j2`; `vault_moodle_db_password` /
`vault_moodle_db_root_password` in `vars/secrets.yml` (`lookup('password', …)` like the rest).

---

## Task 3: Blank instance at `m.leaguesphere.app`

```bash
cd ansible && ./servyy.sh --tags user.docker.moodle --limit servy.lehel.xyz
```

Acceptance: `https://m.leaguesphere.app/` serves the **installer**, the cert is real (HTTP-01),
`docker logs moodle.moodle` is clean, cron ticks (inside the same container), nginx answers on 8080.

### STATUS: DONE (2026-10-27) — blank instance live

| Check | Result |
|---|---|
| Containers | `moodle.moodle` (healthy), `moodle.db` (healthy), `moodle.cron` |
| Volume | **none** — data on existing server storage, `/home/cda/servyy-container/moodle/data` (root disk, 21 GB free); the 100 GB volume was detached and deleted on 2026-10-27 to avoid new spend before the import is measured |
| TLS | Let's Encrypt cert for `m.leaguesphere.app`, valid to 2027-01-25 (HTTP-01) |
| Front page | `200 — Home \| offd` |
| Login | `200 — Log in to the site \| offd`, form present |
| Version | `4.5.15 (Build: 20261005)` on PHP 8.3.36 — a patch ahead of live offd.de's 4.5.12, so the import is a patch-level upgrade the image runs itself |
| Cron | `Cron run completed correctly` every minute |
| URL | served at the host root: `https://m.leaguesphere.app/` → `200 Startseite \| moodle`; `/login/index.php` → `200` with form |
| Memory | app 209 MB / db 223 MB / cron 128 MB (limits 768/768/256); host 3 GB available |

The DB install was done with `admin/cli/install_database.php`, **not** the web installer: the web
installer writes `config.php`, which is the Ansible-rendered bind mount (read-only to uid 33).
The `admin` account created here is throwaway — the real import replaces the database.

### Implementation notes — the prebuilt image (current)

1. **`moodledata` must be owned by uid 65534 (`nobody`).** The image is Alpine and runs unprivileged;
   uid 33 (www-data) was the Debian/Apache value under the previous image. Wrong ownership does not
   fail at start — Moodle breaks later, deep inside an unrelated request.
2. **No subpath.** Upstream Moodle does not support it (erseco docs, issue #127) and the image owns
   its docroot, so `SITE_URL` is host-only and the imported DB needs the one-time replace.
3. **`REVERSEPROXY` stays `false`** on a single-URL deployment, or Moodle answers "Reverse proxy
   enabled so the server cannot be accessed directly". `SSLPROXY=true` is the knob that matters.
4. **`MOODLE_SITENAME` may not contain spaces** — the image passes `--fullname=$MOODLE_SITENAME`
   unquoted, so "Flag Academy" arrives as two argv entries and the first-boot installer aborts with
   "unrecognized options: Academy". The real name comes from the imported DB.
5. **nginx listens on 8080** (unprivileged), so the Traefik service port label is 8080.
6. **First boot takes minutes, not seconds**: the entrypoint installs ~500 tables before it starts
   runit. A healthcheck `start_period` well under that marks the container unhealthy and Traefik
   withdraws the router mid-install (harmless, but confusing when reading logs). It is 120 s here;
   on servy the install took ~260 s.

### Implementation notes — superseded self-built image (kept for the record)

Before 2026-10-27 the stack was a 12-line image built in-repo
(`moodlehq/moodle-php-apache:8.3` + the Moodle release tarball). These were the traps of that shape;
they no longer apply, but they are why the switch happened.

1. **Do not replace the image's ENTRYPOINT.** `moodlehq/moodle-php-apache` ships
   `moodle-docker-php-entrypoint`, which exports `APACHE_DOCUMENT_ROOT` and renders the PHP ini from
   the environment. Bypassing it leaves the vhost's `DocumentRoot` empty → **403 on every request**.
   Our upgrade guard runs first, then hands over to
   `CMD ["moodle-docker-php-entrypoint", "apache2-foreground"]`.
2. **`$CFG->reverseproxy` must stay unset.** Moodle 4.5 throws `reverseproxyabused`
   (`lib/setuplib.php:745`) when the request `Host` equals wwwroot's host — which is exactly what a
   standard proxy does, since Traefik preserves the Host header. Setting it → **500 on the whole
   site**. `$CFG->sslproxy = true` (valid only with an https wwwroot) is the correct knob.
3. **`compose_build` is needed.** `docker_compose_v2` defaults to compose's `missing` build policy,
   so a Dockerfile change silently keeps serving the old `moodle:4.5.12` image. The role now takes an
   opt-in `compose_build` (string `always`/`never`/`policy` — *not* a mapping).
4. **The `docker_service` role cannot see `services`.** That variable is a `set_fact` in the play's
   task list, which runs *after* the roles; role-level includes must read
   `services_enabled.<name>` instead, or they silently skip.
5. **Gate every TLS-dependent setting on `TRAEFIK_TLS`.** wwwroot scheme, `sslproxy` and the
   http→https redirect router all follow it: `servyy-test.lxd` has no https listener, and a redirect
   there blackholes every request.
6. **Never name a proxy-attached service after a generic word.** The compose service name becomes a
   DNS alias on the shared `proxy` network. Named `app`, this stack hijacked LeagueSphere's own
   `app:8000` lookup (its frontend re-resolves every 5 s), 502'd, and took **leaguesphere.app down for
   ~10 minutes** on 2026-10-27. The service is therefore `moodle` (container `moodle.moodle`), an
   alias nothing else claims — not `web`, which `bnb-office.web` and `dontforget.web` already share.
   Details: [moodle/AGENTS.md](../moodle/AGENTS.md).


Then walk the installer and record the generated `config.php` into the image/entrypoint contract
(`$CFG->wwwroot`, `$CFG->dataroot=/var/www/moodledata`, `$CFG->reverseproxy`, `$CFG->sslproxy`).

---

## Task 4: Facts from Christoph — ANSWERED 2026-10-28

The dump arrived: `/var/jail/home/leaguesphere/dump-OFFD-d037491e-202610280831.sql.gz`
(134 MB gz, **1.62 GB** uncompressed, `mysqldump 8.0.19` from a **MariaDB 10.6.23** source,
`mdl_` prefix, no `CREATE DATABASE`/`USE` — it imports into whatever DB you target).
Verified with `gzip -t`, then imported into a scratch database and measured:

| | |
|---|---|
| Tables | 497 |
| DB size | **1.67 GB** |
| Users | **4 248** (4 128 active, non-deleted) |
| Courses | **104** (2 132 course modules) |
| File rows | 39 355 |
| Log rows | 4 647 735 |
| Version in DB | `4.5.12 (Build: 20260608)`, version `2024100712` |
| **Third-party plugins** | **2 only**: `enrol_waitlist`, `qbehaviour_adaptiveallnothing` |
| Custom profile fields | exactly the ones LeagueSphere reads: `teamname`, `teamid`, `Landesverband`, `LandesverbandAuswahl` (+ `Lizenznummer`, `Lizenzstufe`, `rechnung`) |

**Where the 1.67 GB lives:** `mdl_logstore_standard_log` **965 MB** (58 %), question attempts
~360 MB (live exam history — keep), `mdl_messages` 72 MB, `mdl_analytics_predict_samples` 69 MB
(regenerable). So the DB can be trimmed by up to ~1 GB by dropping the *standard log* — a decision for
Christoph, not a technical necessity.

**Sizing:** 1.67 GB DB + ~14 GB moodledata ≈ **15.7 GB** against **21 GB free** on `/` → fits with
~5 GB headroom, no volume needed.

**Plugin preservation is a non-problem:** two plugins, both public. Declare them in `PLUGINS=` in
`moodle.app.env.j2` (installed at every boot) — or install manually before cutover.

## Task 4 (original open items, for the record)

1. **A `mysqldump`** — hoster support ticket, or phpMyAdmin export, or one month of DB access.
   Without it the migration loses quiz attempts, grades and the custom profile fields LeagueSphere
   reads. This is the single hardest dependency in the project.
2. Actual DB size and user count.
3. Plugin list (`Site administration → Plugins → Plugins overview`) — anything abandoned or patched
   will not survive a later 5.x move.
4. Is `offd.de/` (today the Moodle front page) allowed to keep redirecting to `/offd/moodle/`?
5. Who owns/pays — with no volume there is no new line item yet; the Open Question #1 from the sync
   doc (AvD financing) still stands for whoever ends up owning the box.

---

## Task 5: Dry run — DB half DONE on `servyy-test.lxd` (2026-10-28)

Rehearsed on the test box, not prod (the blank instance there is untouched):

1. Imported the 1.62 GB dump into the test box's `moodle` DB — 8 min 17 s.
2. The image detected DB version `2024100712` < its own `2024100715` and ran
   `admin/cli/upgrade.php` automatically; result: `4.5.15 (Build: 20261005)`, maintenance mode
   entered and left cleanly, no plugin complaints despite the two third-party plugins being absent.
3. Front page then rendered **real data**: `Home | Flag Academy`, 4 248 users, 104 courses.
4. **wwwroot replace — measured, not guessed.** Every text/varchar column in the database was scanned
   for `https://offd.de/offd/moodle`. Live content needing the change is **~134 rows**:
   `mdl_question.questiontext` 106, `mdl_question_answers.answer` 13, `mdl_book_chapters.content` 8,
   `mdl_url.externalurl` 6, `mdl_page.content` 1 (+310 `mdl_question_attempts.questionsummary`
   snapshots, optional). Everything else is sent-message history (`mdl_messages`/`mdl_notifications`,
   ~40 k rows), autosave drafts, config logs — leave those alone.
   After the replace: **0 remaining hits** in live content, and a spot check shows the rewritten link
   pointing at the new host.
5. **Still missing: the ~14 GB `moodledata`.** Without it `pluginfile.php` links 404 (images, PDFs,
   SCORM content). The DB half is proven; the file half is not yet exercised.

### Task 5 original detail (still on `m.`)

```bash
lftp -u <user>,<pass> ftp://<host> -e "mirror -c -P 16 --parallel=8 / /moodledata-local; bye"
```

- import the dump into `moodle.db`, then **replace wwwroot** from `https://offd.de/offd/moodle` to
  `https://m.leaguesphere.app` — `SITE_URL` (config.php) covers `$CFG->wwwroot`, but teacher-entered
  absolute links inside course content need the DB search-replace; rehearse it here, on the real
  dump, before prod. Then `admin/cli/purge_caches.php`;
- run at **exactly 4.5.12** first, then `admin/cli/check_database_schema.php` + plugin audit;
- point **stage** LeagueSphere at `https://m.leaguesphere.app/offd` (`secret_stage.yaml`) and run the
  licence report end-to-end — that exercises the web service, the custom fields, `mod_quiz` and the
  write-back path against real data, with prod still untouched.

---

## Task 6: Cutover

1. `offd.de` A record TTL lowered to 300 s ≥ 24 h before.
2. Old site → maintenance mode; final dump + file delta.
3. `SITE_URL=https://offd.de` (inventory: `moodle_service_host`), redeploy, purge caches.
4. DNS A → `49.13.6.173` (**MX untouched** — mail stays at KAS).
5. New `MOODLE_WSTOKEN` into `secret_main.yaml` **and** `secret_stage.yaml`; deploy prod LeagueSphere
   (`--tags ls.app.prod`), verify inside the container: `env | grep MOODLE_`.
6. Smoke test: login, a course, an exam, the officials licence report, cron mail.
7. Keep the old host and DNS as rollback for 2 weeks, then remove the `m.` router.

---

## Task 7: Backups (before any real data lands — Task 5)

New restic scope `restic-moodle` → `sftp://storagebox/…/restic-moodle`:

- **files**: daily snapshot of `/mnt/moodle/moodledata`, retention 7 daily / 4 weekly / 6 monthly;
- **db**: hourly `mariadb-backup` prepared set (same pattern as `restic-ls-db`, including binlogs so a
  PITR drill is possible), retention 24 hourly / 14 daily / 6 monthly;
- seed file `vars/.restic_password_moodle`, vaultwarden item, `restic_seeds` + `restic_vaultwarden_items`
  entries, `system_probe` coverage.

Target: an **executed** restore drill on `servyy-test.lxd` before cutover, not just a documented one.

## Task 8: Upgrades

- **4.5.x patch releases:** automate — rebuild the image against `stable405/moodle-latest-405.tgz`,
  watchtower (scope `prod`, health-check-gated with auto-rollback) swaps it in, the entrypoint runs
  `admin/cli/upgrade.php --non-interactive` when `version.php` ≠ DB version.
- **5.x major:** manual, always. Docroot moves to `/public`, plugins need re-verification. Rehearse on
  `servyy-test.lxd` from a restored snapshot first.

---

## Verification matrix

| Check | Command / place |
|---|---|
| containers up | `ssh lehel.xyz "docker ps \| grep moodle"` |
| blank instance reachable | `curl -sI https://m.leaguesphere.app/` → 200 |
| cert issued | `echo \| openssl s_client -connect m.leaguesphere.app:443 -servername m.leaguesphere.app 2>/dev/null \| openssl x509 -noout -issuer -dates` |
| code + config in place | `docker exec -u 65534 moodle.moodle php /var/www/html/admin/cli/check_database_schema.php` |
| db healthy | `docker inspect -f '{{.State.Health.Status}}' moodle.db` |
| cron runs | `docker logs moodle.cron --tail 20` |
| memory headroom | `ssh lehel.xyz "free -g; docker stats --no-stream moodle.moodle moodle.db"` |
| LeagueSphere integration | stage: `moodle-report/` returns licence rows |
| logs in Grafana | Loki `{container="moodle.moodle"}` |

## Rollback

Additive and cheap at every stage: remove the `moodle` entry from `services_enabled` and
`docker compose -p moodle down`; the data directory survives untouched. Before cutover, rollback is "do nothing
on `offd.de`" — the old host is still authoritative. After cutover it is the DNS record back plus
`wwwroot` flipped, which is why the TTL is lowered first.

## Effort

| Task | Estimate |
|---|---|
| 1–3 storage + service + blank instance | ½ day |
| 4 waiting on Christoph | external |
| 5 dry run (transfer dominant) | 1–2 days |
| 6 cutover window | 2–3 h |
| 7 restic scope + one restore drill | ½ day |
| 8 upgrade automation | ½ day |

## Open decisions

1. `mysqldump` availability (blocks Task 5).
2. Whether `www.offd.de` moves too, and whether anything else lives on that domain.
3. SMTP: no central relay in this repo — services use a Gmail app password. Sending as `@offd.de`
   needs SPF/DKIM at KAS, so likely a transactional provider for Moodle's notification mail.
4. If storage has to be bought later (measured after the import): LeagueSphere-owned or Verband?
