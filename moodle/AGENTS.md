# moodle/ — Moodle (OFFD / Flag Academy)

Christoph's referee-training platform, moved off €15/month FTP-only shared hosting
onto servy. Live target: `https://offd.de/offd/moodle`. Rehearsal hostname:
`m.leaguesphere.app` (wildcard `*.leaguesphere.app` → servy, no DNS work needed).

**Plan, verified baseline, cutover runbook:** [docs/plans/2026-10-27-moodle-offd-hosting.md](../docs/plans/2026-10-27-moodle-offd-hosting.md)

## Layout

| Container | Image | Purpose |
|---|---|---|
| `moodle.app` | built from `app/Dockerfile` (`moodle:4.5.12`) | Apache + PHP, Moodle code |
| `moodle.db` | `mariadb@sha256:2bdff15…` (already on the host) | project-internal DB, no published port |
| `moodle.cron` | same as app | `admin/cli/cron.php` every 60 s — not optional |

Data (never in git, never on the root disk): `$MOODLE_DATA_ROOT/{moodledata,mariadb}`,
i.e. `/mnt/moodle` on prod (Hetzner volume `107289254`) and `./data` on
`servyy-test.lxd`. Ansible owns the mount and the ownership:
[`roles/user/tasks/moodle_volume.yml`](../ansible/plays/roles/user/tasks/moodle_volume.yml).

## Load-bearing invariants — do not "clean these up"

1. **The code path mirrors the URL.** Moodle lives at `/var/www/html/offd/moodle`
   because wwwroot is `…/offd/moodle`. Flattening it breaks every link and the
   `$CFG->wwwroot` contract with the live database.
2. **`config.php` is rendered by Ansible, never edited on the host**
   (`roles/docker_service/templates/moodle.config.php.j2`). It carries the DB password
   and derives `$CFG->wwwroot` from `service_host` — which is why cutover to `offd.de`
   is an inventory change, not a DB edit.
3. **`moodledata` must be owned by uid 33** (www-data). Wrong ownership = HTTP 500 on
   every request, with a confusing log line.
4. **The image pin is the migration version.** `4.5.12` is what offd.de runs today, so
   the import needs no upgrade. Bump deliberately (plan, Task 8).
5. **HTTP-01, not DNS-01.** Neither `offd.de` (All-Inkl) nor `leaguesphere.app`
   (GoDaddy) is in Porkbun scope, so `letsencryptdnsresolver` cannot issue.

## Everyday operations

```bash
# deploy / re-render .env, db.env, config.php (after an inventory change)
cd ansible && ./servyy.sh --tags user.docker.repo,user.docker.moodle --limit servy.lehel.xyz

# logs
ssh lehel.xyz "docker logs moodle.app --tail 100"
ssh lehel.xyz "docker logs moodle.cron --tail 50"

# pending upgrade check (exit 2 = upgrade required)
ssh lehel.xyz "docker exec -u www-data moodle.app php /var/www/html/offd/moodle/admin/cli/upgrade.php --is-pending; echo \$?"

# install a blank instance (Task 3 of the plan)
ssh lehel.xyz "docker exec -u www-data moodle.app php /var/www/html/offd/moodle/admin/cli/install.php ..."

# change wwwroot (should not be needed — edit moodle_service_host instead)
ssh lehel.xyz "docker exec -u www-data moodle.app php /var/www/html/offd/moodle/admin/cli/cfg.php --name=wwwroot --set=https://offd.de/offd/moodle"
```

Upgrades: the entrypoint runs `admin/cli/upgrade.php --non-interactive` whenever
`version.php` and the database disagree, and **exits 1** if the upgrade fails so a
health-gated watchtower rollback restores the previous image. Watchtower scope is
deliberately **not** set yet — auto-updates are Task 8, after cutover.

## Not done yet (see the plan)

- restic scope `restic-moodle` + one *executed* restore drill (Task 7) — **before** real data lands.
- `servyy-test.lxd` rehearsal of the 5.x upgrade (docroot moves to `/public`).
- SMTP: no central relay exists in this repo; Moodle's notification mail needs a
  decision (SPF/DKIM at All-Inkl, or a transactional provider).
