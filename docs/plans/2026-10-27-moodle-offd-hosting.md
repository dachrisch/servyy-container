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
2. **Preserve the exact wwwroot path** `/offd/moodle` on both hosts, i.e. Moodle code lives at
   `/var/www/html/offd/moodle` inside the container. The only thing that changes is the hostname, so
   **no search-replace** of the 14 GB DB is ever needed. Content links that are already absolute keep
   pointing at `offd.de/offd/moodle` during the rehearsal — harmless, and it proves content untouched.
3. **Official image + our thin Dockerfile.** `moodlehq/moodle-php-apache` is PHP+Apache with the
   required extensions only — its tags are *PHP* versions, not Moodle releases. We therefore build a
   pinned image (`FROM …:8.3` + the `4.5.12` tarball) in-repo, which is Moodle's documented
   production path.
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
├── docker-compose.yml      app (build) + db + cron, mem limits, traefik labels
├── app/Dockerfile          pinned moodlehq/moodle-php-apache:8.3 + Moodle 4.5.12
├── app/entrypoint.sh       runs admin/cli/upgrade.php when version.php != DB version
└── AGENTS.md               subdirectory guide (repo convention)
```

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

Acceptance: `https://m.leaguesphere.app/offd/moodle/` serves the **installer**, the cert is real
(HTTP-01), `docker logs moodle.app` is clean, cron ticks, `/` redirects to `/offd/moodle/`.

### STATUS: DONE (2026-10-27) — blank instance live

| Check | Result |
|---|---|
| Containers | `moodle.app` (healthy), `moodle.db` (healthy), `moodle.cron` |
| Volume | **none** — data on existing server storage, `/home/cda/servyy-container/moodle/data` (root disk, 21 GB free); the 100 GB volume was detached and deleted on 2026-10-27 to avoid new spend before the import is measured |
| TLS | Let's Encrypt cert for `m.leaguesphere.app`, valid to 2027-01-25 (HTTP-01) |
| Front page | `200 — Home \| offd` |
| Login | `200 — Log in to the site \| offd`, form present |
| Version | `4.5.12 (Build: 20260608)` — identical to live offd.de; `--is-pending` → rc 0 |
| Cron | `Cron run completed correctly` every minute |
| Root redirect | `308` → `https://m.leaguesphere.app/offd/moodle/` |
| Memory | app 209 MB / db 223 MB / cron 128 MB (limits 768/768/256); host 3 GB available |

The DB install was done with `admin/cli/install_database.php`, **not** the web installer: the web
installer writes `config.php`, which is the Ansible-rendered bind mount (read-only to uid 33).
The `admin` account created here is throwaway — the real import replaces the database.

### Implementation notes — what actually bit us

Each of these was a real 403/500 on the first attempt; they are the non-obvious parts of running
Moodle behind this Traefik.

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


Then walk the installer and record the generated `config.php` into the image/entrypoint contract
(`$CFG->wwwroot`, `$CFG->dataroot=/var/www/moodledata`, `$CFG->reverseproxy`, `$CFG->sslproxy`).

---

## Task 4: Facts from Christoph (blocking for Task 5)

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

## Task 5: Dry run (still on `m.`)

```bash
lftp -u <user>,<pass> ftp://<host> -e "mirror -c -P 16 --parallel=8 / /moodledata-local; bye"
```

- import the dump into `moodle.db`, set `wwwroot` to `https://m.leaguesphere.app/offd/moodle`
  (`admin/cli/cfg.php`), `admin/cli/purge_caches.php`;
- run at **exactly 4.5.12** first, then `admin/cli/check_database_schema.php` + plugin audit;
- point **stage** LeagueSphere at `https://m.leaguesphere.app/offd` (`secret_stage.yaml`) and run the
  licence report end-to-end — that exercises the web service, the custom fields, `mod_quiz` and the
  write-back path against real data, with prod still untouched.

---

## Task 6: Cutover

1. `offd.de` A record TTL lowered to 300 s ≥ 24 h before.
2. Old site → maintenance mode; final dump + file delta.
3. `cfg.php --name=wwwroot --set=https://offd.de/offd/moodle` + purge caches.
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
| blank instance reachable | `curl -sI https://m.leaguesphere.app/offd/moodle/` → 200 |
| cert issued | `echo \| openssl s_client -connect m.leaguesphere.app:443 -servername m.leaguesphere.app 2>/dev/null \| openssl x509 -noout -issuer -dates` |
| code path matches wwwroot | `docker exec moodle.app ls /var/www/html/offd/moodle/version.php` |
| db healthy | `docker inspect -f '{{.State.Health.Status}}' moodle.db` |
| cron runs | `docker logs moodle.cron --tail 20` |
| memory headroom | `ssh lehel.xyz "free -g; docker stats --no-stream moodle.app moodle.db"` |
| LeagueSphere integration | stage: `moodle-report/` returns licence rows |
| logs in Grafana | Loki `{container="moodle.app"}` |

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
