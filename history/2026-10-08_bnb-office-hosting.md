# bnb-office — hosting the BricksnBytes office app (IBS) (2026-10-08)

Realizes the offer from `bumbleflies/bricksnbytes#105`: their internal PHP
back office (customers/children/GDPR consents; bookings/invoices later)
runs as the `bnb-office` service. Requirements she confirmed in #105:
MariaDB (27 InnoDB tables — not mongo), login-only, `ibs.bricksnbytes.de`
(Subdomain at Strato — Option B), daily dump backups ≥30d off-host,
watchtower OK, light load. She asked us to build the image (PR #110/#113):

## bumbleflies repo side (bumbleflies/bricksnbytes, PR #110/#113)

- `backoffice/Dockerfile` (php:8.3-apache, pdo_mysql+opcache, MariaDB
  client, DocumentRoot → `public/` via sed) + `docker/ibs-apache.conf`
  (FallbackResource front controller), `public/healthz.php` (DB-independent
  200 for CI smoke), `docker/entrypoint.sh` + `make-config.php`
  (env→config.php, bounded 90s DB wait then start-anyway, pre-migration
  `mariadb-dump` → `/backups` volume, `bin/migrate.php`).
- CI: `.github/workflows/backoffice.yml` publishes `bumblecode/ibs:latest`
  + `master-<sha>` (org DOCKER_TOKEN). CI caught two real bugs pre-deploy:
  `/healthz` had to be `/healthz.php` (FallbackResource), and docroot had
  to become `public/`. Image live on Docker Hub after PR #112 (fix1) +
  #113 (fix) sequences — `/healthz` = front controller 404 diagnosis from
  build #37827061683, then docroot from #37827729279.

## servyy-container side (branch `claude/bnb-office`, PR dachrisch/servyy-container#185)

- `bnb-office/docker-compose.yml`: `web` (bumblecode/ibs:latest) +
  `db` (MariaDB digest-pinned to the image already on servy,
  `2bdff153…`, 12.3.3 via photoprism) on `internal`, no host port;
  web joins `proxy` only; mem_limit 192m/512m; named volume
  `db_data`; dump volume `web_backups` for /backups.
- Traefik: `Host(ibs.bricksnbytes.de)`, certresolver
  **letsencrypthttpresolver** (Strato domain — NOT in Porkbun, so the
  default DNS-01 resolver cannot issue; dontforget/bf precedent);
  HTTPS-redirect router keyed to `TRAEFIK_HTTP_REDIRECT_HOST` (blank on
  test, dontforget pattern). `watchtower scope=dev` per dachrisch
  (queen-style 5-min poll choice).
- Templates `.env.j2` (TRAEFIK_*, service_host override
  (`bnb_office_service_host`), `app.env.j2` (DB_/APP_ env for the image
  entrypoint w/ `IBS_REGENERATE_CONFIG=1`), `db.env.j2`
  (MARIADB_* creds). New secrets `bnb_office:` in `secrets.yml`
  (git-crypt): db `ibs`, user `ibs_app`, app/db passwords generated.
- user.yml docker_service block (tag `user.docker.bnb-office`);
  docker_extras: daily `docker-bnb-office-dump.timer` 02:30 —
  `mariadb-dump` → `bnb-office/.backup/` (restic→storage box off-host,
  local prune 35d); forall list entry.
- Inventories: testing deploys bnb-office under
  `ibs.bricksnbytes.servyy-test.lxd`, TLS off, entrypoint `web`;
  production enabled (flagged: needs her Strato record alive before the
  first deploy so cert issuance can succeed).

## Validation status

- ansible syntax-check: servyy.yml on testing + production ✅ (had to
  locally install collections: community.general/docker, gcrypto,
  ansible.posix because this new dev env lacked them)
- yamllint on changed files ✅ (pre-existing production indentation
  warnings NOT introduced by this branch — file historically at 8 spaces)
- CI green for the image (build+healthcheck+push)
- **servyy-test deploy pending** — blocked in the dev container: no LXD
  here and servyy-test.lxd does not resolve (test environments live on
  the operator side). Per plan: operator (cda) runs:
  `./servyy-test.sh --tags "user.docker.repo,user.docker.bnb-office"`.
  After that: PR #185 review/merge, prod deploy (`user.docker.bnb-office`
  on servy — explicit approval), then she flips Strato record and logs in.
