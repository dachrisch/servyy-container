# OFFD Moodle — final drop and release (2026-11-13)

**Status:** ready to execute; blockers listed under "Before Friday" (external ones are
Christoph's). Rehearsal host `m.leaguesphere.app`, live target `offd.de`.
**Relates to:** [2026-10-27-moodle-offd-hosting.md](2026-10-27-moodle-offd-hosting.md) (plan),
`moodle/AGENTS.md` (runbook), `history/2026-11-04_moodle-moodledata-ingested.md`,
`history/2026-11-06_moodle-restic-scopes.md`.

Friday delivers the **last** database dump and moodledata export. It is both the final data
import and the release: the site that was rehearsed *is* the production instance, so only
`SITE_URL`, the router and DNS change after the import. DNS is the **last** step, by decision.

---

## Current state (measured 2026-11-10)

| | |
|---|---|
| Instance | `m.leaguesphere.app` — 200, `<title>Startseite \| Flag Academy</title>`, cert valid to 2027-01-25 |
| Content | DB 2026-10-28 (497 tables, 4 248 users, 104 courses, 39 374 file rows), moodledata 2026-11-04 (9 498 filedir files, 5.779 GiB, every file hash-verified) |
| Consistency | 9 317 distinct `contenthash` in DB → all present on disk |
| Moodle | 4.5.15, no pending upgrade |
| Plugins | `enrol_waitlist` 2025072001 installed and enabled (PR #281); `waitlist` on all 14 active Lehrgang courses |
| Backups | `restic-moodle-db` hourly, `restic-moodle-files` daily, `baseline` tags on both, full-loss restore drill done 2026-11-06 |
| Disk | 43 GB free on `/` — a 6 GB archive plus a 1.7 GB import fits with room to spare |
| DNS | `offd.de` + `www.offd.de` → `85.13.146.136` (KAS), **TTL 7200**, MX at KAS (untouched by any of this) |

## Before Friday (do these first)

- [ ] **Christoph: lower the TTL of `offd.de` *and* `www.offd.de` to 300** — at least 24 h ahead,
      i.e. now. Everything else is recoverable; a 2 h TTL on release evening is not.
- [ ] **Christoph: decide `www.offd.de`.** Today it points at the same KAS host. Options: (a) he
      CNAMEs `www` → `offd.de`, we add a router + cert and 301 to the apex; (b) `www` is retired.
      Doing nothing leaves `www.offd.de` serving the dead old site.
- [ ] **SMTP credential** (one KAS mailbox; `spf1 a mx include:spf.kasserver.com` already covers
      KAS submission). Without it, password resets and notifications fail for 4 129 active users.
      Add `SMTP_HOST/PORT/USER/PASSWORD/PROTOCOL` to `moodle.app.env.j2` and deploy.
- [ ] **Christoph: the export order** — old site into maintenance mode **first**, then
      `mysqldump`, then tar `moodledata`. The tar must include `secret/` (the `sodium.key` is the
      only key that decrypts the `leaguemanager` OAuth client secret).
- [ ] **LeagueSphere app change prepared** (separate repo, not deployed until cutover):
      `MOODLE_URL` loses its `/offd` suffix — `ansible/plays/roles/ls_app/templates/ls.env.j2:17`
      in this repo — and `officials/service/moodle/moodle_api.py:263,273` +
      `moodle_service.py:53,54` lose their `/moodle` segment. The two must ship in the same window:
      template without code leaves `https://offd.de/moodle/...` (404), code without template
      leaves `/offd/moodle`.
- [ ] Remove the stale `2026-10-28` dump from `/var/jail/home/leaguesphere/` before the new one
      lands (it is still there, 129 MB — importing it by mistake would lose three weeks).
- [ ] Rehearse `import-offd-release.sh` on `servyy-test.lxd` with any export (the 2026-11-04 pair
      is still on the Storage Box) so the script is not first exercised on release day.
- [ ] Confirm SSH from the release workstation works (`:22` was REJECTed by fail2ban/`loki-blocklist`
      on 2026-11-10; a ban must not surprise us mid-window).

## Friday: import (site stays on `m.leaguesphere.app`)

Everything below is on `servy.lehel.xyz`, from `/home/cda/servyy-container/moodle`.

```bash
# 0. where the files landed, and are they complete?
ls -la /var/jail/home/leaguesphere/           # Christoph uploads here
sha256sum moodledata.tar.gz dump.sql.gz        # against what he reports

# 1. THE GATE — read-only, ~2 min for 6 GB
cd /home/cda/servyy-container/moodle
./scripts/verify-offd-export.sh /var/jail/home/leaguesphere/moodledata.tar.gz \
                               /var/jail/home/leaguesphere/dump-*.sql.gz
#    PASS required. FAIL = stop here, ask for a re-export; the site is untouched.

# 2. rollback point, then import (app down ~12 min: extract + 8 min DB + upgrade)
sudo bash -c 'source /etc/restic/env.moodle-db    && restic tag --add pre-release latest'
sudo bash -c 'source /etc/restic/env.moodle-files && restic tag --add pre-release latest'
./scripts/import-offd-release.sh /var/jail/home/leaguesphere/moodledata.tar.gz \
                                 /var/jail/home/leaguesphere/dump-*.sql.gz --dry-run
#    prints what it resolved (data root, DB name, archive top level, dump tables,
#    rewrite target, age of the rollback dump) and changes nothing — do this first
./scripts/import-offd-release.sh /var/jail/home/leaguesphere/moodledata.tar.gz \
                                 /var/jail/home/leaguesphere/dump-*.sql.gz
#    rewrites https://offd.de/offd/moodle -> the current SITE_URL, so the site is
#    immediately usable on m. and fully verifiable before anything public changes.
```

Note: `data/` is `root:root 0750`, so the script's own `sudo` calls are required —
a hand-run `test -f data/db-backup/current/moodle.sql.gz` answered "no" for a
non-root user and produced a misleading "cannot resolve the data root" on the
first dry run. `/var/jail/home/leaguesphere` is world-readable, the data root is
not.

If the import aborts: the previous dump is at `data/db-backup/current/moodle.sql.gz`
(same-minute) and in both restic repos (`pre-release` tag). Restore with the runbook in
`moodle/AGENTS.md` → "Restore runbook".

### Verification before touching anything public

```bash
curl -sI https://m.leaguesphere.app/ | head -1                       # 200
docker exec -u 65534 moodle.moodle php /var/www/html/admin/cli/upgrade.php --is-pending; echo $?   # 0
docker exec -i moodle.db sh -c 'exec mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" moodle -N' <<'SQL'
SELECT COUNT(*) users FROM mdl_user WHERE deleted=0;
SELECT COUNT(*) courses FROM mdl_course;
SELECT COUNT(*) files FROM mdl_files;
SELECT COUNT(*) FROM mdl_enrol WHERE enrol='waitlist' AND status=0;
SELECT COUNT(*) FROM mdl_question WHERE questiontext LIKE '%offd.de/offd/moodle%';   -- must be 0
SQL
```

- [ ] log in as the admin account, open a course, open a quiz, download a `mod_resource` PDF
      through `pluginfile.php` (sha1 of the body must equal the DB `contenthash`)
- [ ] open one of the 14 waitlist Lehrgänge: the method must be selectable, an application must
      queue, cancelling an enrolment must promote from the queue
- [ ] LeagueSphere **stage** licence report against `m.leaguesphere.app` (proves web service,
      custom fields, quiz read + write-back on the new data)
- [ ] Mail: trigger one password reset — must arrive (only if SMTP landed)
- [ ] `docker logs moodle.moodle | grep -iE "fatal|error"` — clean; cron tasks ticking

## Friday: release (cutover) — after the import is verified

Order matters: **site first, LeagueSphere second, DNS last.**

```bash
# 1. SITE_URL -> offd.de  (one inventory value + the health-probe host)
#    ansible/production:                     moodle_service_host: offd.de
#    ansible/plays/vars/secrets.yml:         docker.services[moodle].host: offd.de
cd /home/cda/dev/infrastructure/container/ansible
./servyy.sh --limit servy.lehel.xyz --tags user.docker.repo,user.docker.moodle
./servyy.sh --limit servy.lehel.xyz --tags user.docker.env.monitor   # repo sync reverts these renders

# 2. rewrite teacher-entered links to the new root (idempotent, measured 134 rows)
cd /home/cda/servyy-container/moodle
./scripts/wwwroot-replace.sh https://offd.de/offd/moodle https://offd.de
docker exec -u 65534 moodle.moodle php /var/www/html/admin/cli/purge_caches.php

# 3. LeagueSphere: drop /offd in ls.env.j2 AND deploy the app code change (no /moodle/),
#    same window, then verify inside the container:
./servyy.sh --limit servy.lehel.xyz --tags ls.app.prod
ssh servy.lehel.xyz "docker exec leaguesphere.app env | grep MOODLE_"
#    expect MOODLE_URL=https://offd.de and the existing token (it comes from the dump,
#    so it survives the import — test it instead of rotating it)

# 4. DNS LAST — Christoph flips the A record to 49.13.6.173 (MX stays at KAS)
dig +short offd.de @1.1.1.1                      # watch it change
curl -sI https://offd.de/ | head -1              # Traefik issues the HTTP-01 cert on first hit
echo | openssl s_client -connect offd.de:443 -servername offd.de 2>/dev/null | openssl x509 -noout -dates
```

Expected transient during step 4: 1–3 minutes of `404`/TLS error on `offd.de` while the record
propagates and the certificate is issued. Announce the window; the old site is in maintenance
mode by then anyway.

### After DNS

- [ ] `https://offd.de/` 200, real front page, no redirect to `m.`
- [ ] log in as a **real, non-admin** account if one can be borrowed (Christoph), open a Lehrgang,
      fetch a file — this is the only check that is not admin-shaped
- [ ] `pluginfile.php` PDF end-to-end again on the new host
- [ ] officials licence report in **prod** LeagueSphere
- [ ] mail: one real notification
- [ ] Grafana: `container_not_running`, `restic_snapshot_age_seconds{repo="moodle-*"}`,
      `moodle` log freshness all green; one request in Loki from offd.de
- [ ] fresh restic pair, tag it `release`, then `restic check --read-data-subset=10%`
- [ ] update `moodle/AGENTS.md` (live host), the plan, and write the history entry

## Rollback

| When | Action |
|---|---|
| Import failed / bad data | restore `data/db-backup/current/moodle.sql.gz` (or the `pre-release` restic snapshot) — content extraction is additive, orphans are harmless |
| Cutover done, something broken, **before** DNS | point `moodle_service_host` back to `m.leaguesphere.app`, deploy, `wwwroot-replace` back — 10 minutes |
| Cutover done and DNS flipped | flip the A record back to `85.13.146.136` (old host still live for 2 weeks) **and** revert `SITE_URL`; TTL 300 makes this minutes |
| Anything worse | the `baseline` restic pair (2026-11-06) plus `pre-release`; full-loss restore runbook in `moodle/AGENTS.md` |

## Known gaps at release (accepted, documented)

- **No point-in-time recovery** — `log_bin` is off; DB granularity is the hourly dump.
- **Capacity**: `pm.max_children = 5` (1.5 G container) is thin for 4 249 users; a simultaneous
  exam start will queue. Raise `php-fpm-limits.conf` + `mem_limit` once the board's memory
  headroom allows (servy had 185–250 MiB free when this was sized).
- `MRBS`-style course custom fields and `qbehaviour_adaptiveallnothing` stay uninstalled
  (no quiz uses that behaviour).
- The two existing blog posts stay invisible (`enableblogs=0` is hardcoded by the image).
- `m.leaguesphere.app` router removed ~2 weeks after a clean release.
