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

## Not done yet (see the plan)

- restic scope `restic-moodle` + one *executed* restore drill (Task 7) — **before** real data lands.
- The `leaguesphere` side of the URL change: `MOODLE_URL` plus the hardcoded `/moodle/…` segments in
  `officials/service/moodle/`. Not touched yet on purpose — prod LeagueSphere still points at the old
  live offd.de until the search-replace is proven on the test box.
- Plugin list → `PLUGINS` in `moodle.app.env.j2` (installed at every boot, so the code tree stays
  immutable).
- SMTP env (`SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`) once the mail decision is made.
