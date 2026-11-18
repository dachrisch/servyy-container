# Database tier topology — per-package change log

Companion to `docs/plans/2026-11-17_db-tier-topology.md` (design) and
`docs/plans/2026-11-18_db-tier-work-packages.md` (the packages). One section per
package, appended as it lands. WP-0 and WP-1 have their own files
(`2026-11-18_db-tier-wp0-version-fence.md`, `2026-11-18_db-tier-wp1-mongo-wipe.md`);
WP-2…WP-4 are recorded in the plan's status table.

---

## WP-5 — the business tier takes over bnb's office database (2026-11-18)

**Two commits' worth of work, deliberately split.** WP-5a (`374f910b`, `01a117f8`,
merged as `744427d9`) built `db-business.mariadb`, created bnb's account and copied the
data — no cutover. WP-5b (merged as `64c790bb`) points the app at it, retires the
app-owned sidecar, re-points the daily dump and flips the inventory row.

### What moved

`bnb-office/docker-compose.yml` used to run its own `db:` MariaDB 12.3 sidecar
(`mariadb:12.3`, own named volume, own root credential). It now has one service,
`web`, attached to the tier's `db_business_backend` network (the tier's own internal
network, so the database is reachable from attached containers and nowhere else). The
`db:` service, its `db_data` volume declaration, the `depends_on: db` and the internal
`internal` network are gone; `web_backups` stays.

`DB_HOSTNAME` was hardcoded as `${COMPOSE_PROJECT_NAME}.db` in the compose. It is now an
inventory var, `bnb_office_db_host` (default `{{ project_name }}.db`, `db-business.mariadb`
for servy), rendered into the project `.env` and into `app.env` from the same expression,
so the compose's `environment:` block and the env file cannot disagree. The image
regenerates `config.php` at start; it now says
`mysql:host=db-business.mariadb;dbname=ibs`.

`bnb-office/db.env.j2` (the sidecar's `MARIADB_*` init vars) is deleted. The vault's
`bnb_office.mariadb_root_password` is vestigial from here on — kept because the rollback
(a `docker start bnb-office.db`) still wants interactive access to that datadir.

### The dump, and a failure that had been silent for four days

`bricksnbytes#105` requires a daily dump with ≥30 days retention. The old job ran as a
systemd user timer whose `ExecStart` was:

```
docker exec bnb-office.db sh -c 'exec mariadb-dump … ibs' | gzip > …/bnboffice-$(date …).sql.gz && find … -delete
```

`ExecStart=` is **not a shell**: systemd split that line and handed `|`, `gzip`, `>`,
the path and `&&` to `docker exec` as literal arguments. `sh -c` ignored them, dumped to
stdout, and docker forwarded all of it to the journal — **18,136 journal lines over four
runs, no file ever created, exit status 0**, so nothing ever alerted. The only file in
`.backup/` was the 17:17 dump WP-5a took by hand.

The job now runs `dbops dump bnb_office` (the WP-3b tool: tenant's server from the
inventory, the tier's `dbops_backup_business` credential from `~/.dbops/business.env`,
`.partial` rename so restic cannot capture a half-written file) and both the dump and the
35-day prune are wrapped in `sh -c`. Two bugs found while proving it:

* `includes/oneshot.yml` never ran `daemon_reload`, so the rewritten unit stayed
  **unloaded** ("the version systemd has loaded is outdated") and the next fire would have
  run the old command. Fixed there; `system_probe` and `ls_maintenance_probe` already did it.
* The first prune glob, `bnb?office-*`, does **not** match `bnboffice-*` (`?` eats the `o`
  and the pattern then demands a second `office`). Measured by planting one 40-day-old file
  per pattern: only the `bnb_office-*` one went. Now `bnb*office-*`.

### Inventory row (the guard depends on it)

`bnb_office` → `server: db-business.mariadb`, `retiring: false` (it is an ACTIVE server
now, so D8 compares it with the other MariaDB tiers), plus the guard-only
`compose_dir: db-business` / `compose_service: mariadb`. Without those two the guard reads
`bnb-office/docker-compose.yml`, finds no `db` service and resolves an empty tag — which
silently drops the server out of the equality check instead of failing.

### Verification (measured)

* **Counts:** 30 tables / **2,616 rows** on the old server and on the tier, per-table
  identical, before and after the cutover (`dbops verify` also agrees on the object set and
  reports every DEFINER present).
* **Invoice numbering:** bnb's counter is `SELECT MAX(CAST(SUBSTRING(nummer, 6) AS
  UNSIGNED)) FROM auftraege WHERE nummer LIKE '<year>-%'` in
  `src/Modules/Auftraege/AuftragRepository.php::nextNumber()` — **not** `nummernkreise`
  (that table is empty and unused; `rechnungen` has no module in this image yet). State
  before = after = `auftraege` 1 row, `2026-001`, max sequence 1, next **`2026-002`**,
  `rechnungen` 0 rows, `nummernkreise` 0 rows, `aenderungen` 1,160 rows / max id 1,166,
  `AUTO_INCREMENT` of `auftraege`=2, `rechnungen`=1. **No gap, no reuse.** No test invoice
  was created: allocating in the live system would consume `2026-002` permanently (a
  cancelled order keeps its number), and with the counter untouched, identity is the
  stronger proof.
* **Write path:** a failed login through the site inserted a `login_versuche` row **on the
  tier** (ip `172.18.0.3`, the web container on `db_business_backend`) while the old server
  stayed at 0 rows. The probe row was then deleted and the table's `AUTO_INCREMENT` reset,
  so the data is still exactly 2,616 rows.
* **Sites:** `https://ibs.bricksnbytes.de` and `https://ibs.bumbleflies.de` — `/` 303 →
  `/login`, `/login` 200 before and after; both titles
  `Anmelden · Imperiales Sicherheitsbüro`.
* **Dump:** unit run by hand → `bnb_office-20261118T164912Z.sql.gz` (52 KB, gzip valid,
  30 `CREATE TABLE`, `-- Database: ibs`, `CREATE DATABASE … utf8mb4_unicode_ci`), landing in
  `/home/cda/servyy-container/bnb-office/.backup/`, which is inside the `home` restic repo's
  `/home/cda` source and carries no exclusion. Prune proven with planted 40-day-old files
  (both patterns deleted) and a 10-day-old one (kept).
* **Guard:** the MariaDB equality set is now `leaguesphere.db`, `db-nonprod.mariadb`,
  `db-business.mariadb` — all `mariadb:13.0`; D8 skipped, no "cannot verify" warning;
  `db_version_drift{engine=…}` = 0 for mariadb, mongo and postgres.
* **Nothing else moved:** comparing `docker ps -a` before/after, the only container with a
  new id/created time is `bnb-office.web` (recreated 16:42Z, 0 restarts, healthy). No failed
  systemd units.
* **Old container:** `bnb-office.db` **stopped** (`Exited (0)`), `.Id` and `.Created`
  unchanged (`7b8e60e7dd4d`, `2026-11-18T09:30:29Z`), `bnb-office_db_data` still referenced
  by it — which is precisely what keeps `docker system prune --volumes` (daily 02:00) from
  deleting the rollback datadir.

### Rollback

`docker start bnb-office.db` (its volume is intact and still referenced), then revert the
`DB_HOSTNAME`/`bnb_office_db_host` change and the `bnb_office` inventory row. Nothing was
deleted. Window: one week.

### Follow-ups

* `bnb-office` is in **no** container-health probe list (`docker.services` /
  `docker_backend_services`): it has never been watched, which is a pre-existing gap and
  belongs to WP-8's probe wiring.
* `bnb_office.mariadb_root_password` and `bnb-office/db.env` (untracked, on the host) are
  leftovers until WP-8 deletes the old datadir.

---

## WP-8R — backup coverage for the five tenants that had none (2026-11-18)

**The gap this closes.** Three tenants had **no backup of any kind** and two more had a
file-shaped artefact nobody could restore:

| Tenant | Before | Why it was invisible |
|---|---|---|
| `firefly` (postgres) | nothing | `PGDATA` is a bind mount on `/mnt/servy-docker-data`; the `root` repo excludes `/mnt` and the `home` repo never covered it |
| `leagues_finance`, `queen` (mongo) | nothing | `shared_mongo_data` is a docker volume on `/mnt`, same exclusion; the only artefacts were two ad-hoc archives sitting in `/home` |
| `dontforget` (mongo) | nothing | as above |
| `photoprism` (mariadb) | no dump | the only "backup" was the **stopped** pre-cutover datadir (775 MB) riding the hourly `home` repo — a raw datadir is not restorable, and a re-index never rebuilds 1 014 albums |

`dump_schedule: none` in `plays/vars/db_tenants.yml` was accurate for all five, which is
exactly the lie this package exists to remove: nothing else in the fleet claimed to back
them up, so no probe, no timer and no dashboard row was missing either.

### What is now protected, by what

Five `backup_targets` rows, five repos, ten systemd **user** units — all rendered from the
inventory, none hand-wired:

| Tenant | Dump | Snapshot | Repo | Retention |
|---|---|---|---|---|
| `photoprism` | `db-dump-photoprism` 00:45 | `restic-backup-db-private` 00:55 | `restic-db-private` | `db_daily` (30 d / 8 w / 6 m) |
| `leagues_finance` | `db-dump-leagues_finance` 01:15 | `restic-backup-db-lf` 01:20 | `restic-db-lf` | `db_daily` |
| `queen` | `db-dump-queen` 01:25 | `restic-backup-db-queen` 01:30 | `restic-db-queen` | `db_daily` |
| `dontforget` | `db-dump-dontforget` 01:35 | `restic-backup-db-private-mongo` 01:40 | `restic-db-private-mongo` | `db_daily` |
| `firefly` | `db-dump-firefly` 01:45 | `restic-backup-db-private-firefly` 01:50 | `restic-db-private-firefly` | `db_daily_short` (14 d / 4 w) |

All five share the D16 password (`restic_password_db`), so five repos cost no new secret.
`enabled_by: servy` is a new gate: the targets only exist where the applications do.

Two dump mechanisms, deliberately:

* **`roles/restic/templates/dbops_dump.sh.j2`** (the four engine-supported tenants) runs
  `dbops dump <tenant>` into `<dump_dir>/new/`, checks the per-tenant size floor, and only
  then renames `new/` → `current/`. `dbops` keeps ownership of the engine, the
  `.partial` → rename and the "keep the newest two" pruning; the wrapper adds the only
  thing a dump tool cannot know — a floor below which a *successful* dump is a defect.
  restic snapshots `<dump_dir>/current` and nothing else, so a dump in progress cannot be
  captured.
* **`roles/restic/templates/firefly_dump.sh.j2`** (interim) is `pg_dump -Fc` inside
  `shared.db`, validated by `pg_restore --list` in the same container (parseable archive,
  ≥1 `TABLE` entry, 81 today) plus the size floor. There is no postgres adapter in `dbops`
  on purpose: WP-10 moves firefly onto MariaDB and deletes this job with `shared.db`.

**Floors are measured, per tenant** (the WIP had one blanket 1 MiB floor, which four of the
five could never reach — their dumps are 11–414 KB):

| Tenant | Healthy dump | Floor | An *empty* dump is |
|---|---|---|---|
| `photoprism` | 107 336 589 B | 50 MiB | < 1 KB (empty schema) |
| `leagues_finance` | 11 644 B | 4 KiB | 136 B (empty mongo archive) |
| `queen` | 28 812 B | 8 KiB | 136 B |
| `dontforget` | 24 771 B | 8 KiB | 136 B |
| `firefly` | 414 050 B | 128 KiB | 888 B (empty `pg_dump -Fc`) |

### The dumps are deduplicable

`dbops dump` for MariaDB now passes `--skip-dump-date`, and the stream is gzipped with
`gzip -n`. Two consecutive PhotoPrism dumps an hour apart, with nothing changing in between,
are **byte-identical** (`sha256 b602d18f…` both times, measured), so restic stores the
second one as ~0 new bytes instead of 103 MB. The timestamp lives in the file *name*, not
in its content.

### Restore drills (all six run from the finished scripts, 2026-11-18)

Every drill: run the deployed-shape dump script → restore into a **scratch** container of
the same engine/version → compare per-table (or per-collection) counts against the live
server. No live database was written to.

| Tenant | Restored into | Result |
|---|---|---|
| `photoprism` | `scratch-mariadb` (mariadb:13.0) | **41 tables, 580 345 rows — identical per table.** albums 1 014, photos 46 690, `photos_albums` 169 (the plan's "169 links"), files 49 481 |
| `leagues_finance` | `scratch-mongo` (mongo:9.0.8) | **11 collections / 186 documents — identical** (`dbops verify leagues_finance --against scratch-mongo`) |
| `queen` | `scratch-mongo` | **14 collections / 360 documents — identical** |
| `dontforget` | `scratch-mongo` | **14 collections / 717 documents — identical** |
| `firefly` | `scratch-pg` (postgres:15) | **81 tables / 6 430 rows — identical**, `pg_restore` exit 0 |

**`firefly`: the WIP recorded it as "proven unrestorable so far". It was not.** The dump
was complete (706 TOC entries, 81 tables) and restores cleanly; the drill that failed had
used a scratch server whose only superuser is its `POSTGRES_USER` (`firefly`) and then
connected as a role that does not exist — `pg_restore` without `-U` becomes the host OS user
(`role "root" does not exist`), with `-U postgres` it is `role "postgres" does not exist`;
both exit 1 with zero tables restored and look exactly like a corrupt archive. With
`-U firefly --no-owner --no-privileges` the restore is silent and exit 0. The WIP also
guessed the table names (`accounts`/`transactions_journal`); the real ones are
`accounts`, `transactions`, `transaction_journals` (81 tables, listed with `\dt`), and the
drill compares all 81.

Re-run it (the be-all recipe is in the template's header):

```
docker run -d --name scratch-pg -e POSTGRES_PASSWORD=x postgres:15
docker cp /home/cda/db-dumps/firefly/current/<file>.dump scratch-pg:/tmp/f.dump
docker exec scratch-pg createdb -U firefly drill
docker exec scratch-pg pg_restore -U firefly --no-owner --no-privileges -d drill /tmp/f.dump
# per-table counts on both sides, then diff:
#   select c.relname || ':' || (xpath('/row/c/text()',
#     query_to_xml(format('select count(*) as c from %I.%I', n.nspname, c.relname),
#                  false, true, '')))[1]::text::bigint
#   from pg_class c join pg_namespace n on n.oid = c.relnamespace
#   where n.nspname = 'public' and c.relkind = 'r' order by 1;
```

**Failure paths were exercised, not assumed.** A copy of the PhotoPrism dump script with an
impossible floor exits 1, logs `Dump suspiciously small`, deletes `new/` and leaves
`current/` holding the previous good dump — i.e. a broken dump neither replaces the last
good copy nor produces a snapshot that looks fresh.

### Inventory: before → after (`plays/vars/db_tenants.yml`)

| Tenant | `dump_schedule` | `dump_dir` | `restic_repo` |
|---|---|---|---|
| `photoprism` | `none` → `daily 00:45` | `''` → `/home/cda/db-dumps/photoprism` | `''` → `db-private` |
| `leagues_finance` | `none` → `daily 01:15` | `''` → `/home/cda/db-dumps/leagues_finance` | `''` → `db-lf` |
| `queen` | `none` → `daily 01:25` | `''` → `/home/cda/db-dumps/queen` | `''` → `db-queen` |
| `dontforget` | `none` → `daily 01:35` | `''` → `/home/cda/db-dumps/dontforget` | `''` → `db-private-mongo` |
| `firefly` | `none` → `daily 01:45` | `''` → `/home/cda/db-dumps/firefly` | `''` → `db-private-firefly` |

Each row also carries `dump_at`, `size_floor_bytes`, `probe_minutes` (1560 = 26 h) and
`severity`. Those four facts also live on the tenant's `backup_targets` row — deliberate
duplication (the tenant row feeds the dump script, the target row feeds the probe and the
retention) with a guard: `plays/tasks/restic_wiring.yml` fails the run when the two rows
disagree, when `dump_at` is not in the rendered schedule, or when a repo's `source_path` is
not `<tenant dump_dir>/current`. All three guards were verified by breaking them on purpose
and watching the run fail with the offending values.

### The canonical dump root and the `home` exclude

`/home/cda/db-dumps/<tenant>/current` is the single dump root (plan R7). `db-dumps` is now
excluded from the **`home`** repo (`plays/vars/restic.yml`): otherwise a 103 MB PhotoPrism
dump would be re-uploaded into the hourly repo, and one dump would exist in two repos with
two different retentions — two answers to "how old is the newest copy".

**Repo initialisation.** `roles/restic/tasks/init.yml` no longer gates `restic init` on
"an env file changed". That gate worked only by accident (a new repo also brings a new env
file) and silently skipped a repo whose env file already matched — the failure mode being
"repository does not exist" on every snapshot afterwards. The loop is idempotent
(`restic snapshots` fails on a missing repo), so it now always runs; the five new repos are
in `restic_repos_enabled`, which also creates their Storage Box directories and
`/etc/restic/env.<name>`.

**Timers.** `roles/restic/tasks/oneshot_include.yml` now passes `daemon_reload: yes`. A
rewritten unit file is not the one systemd has loaded, so until an unrelated reload the
timer keeps firing the **old** `ExecStart` — measured twice in this repo (WP-5b's
`docker-bnb-office-dump`, and again here). The timers are deployed by one loop over the
`backup_targets` rows, so adding a tenant is a row, not five edits.

### DO NOT DELETE (before WP-10 reads this)

* **`/home/cda/db-dumps/`** and every `<tenant>/current` under it — the source directory of
  five restic repos. Deleting it does not delete the repos, but it is the only thing an
  operator can restore from without decrypting a snapshot first.
* **`db-dump-firefly` + `restic-backup-db-private-firefly` + `restic-db-private-firefly` +
  `/home/cda/db-dumps/firefly`** — the **only** protection firefly has ever had. All four
  are deleted **together with `shared.db` in WP-10** (when firefly becomes a MariaDB
  tenant and `dbops dump` takes over) and by nothing else.
* `scratch-*` containers used by the drills were throwaway and are gone; the dump
  directories above are not.

### Rollback

Disable the ten timers (`systemctl --user disable --now db-dump-* restic-backup-db-*`), or
revert the commit and re-run the restic play. Nothing was deleted, no live database was
touched and no repository has been pruned, so a rollback loses only the dumps taken in the
meantime — which stay on disk.

### Follow-ups (not this package)

* **R2**: the alert rules are still name-free-by-convention; the dump-age probe series
  (`db_dump_age_seconds`) is not wired here — the five dump logs are already in
  `system_probe_log_checks` (93 600 s) and the five repos in `system_probe_restic_repos`.
* **R8**: one `db-backup@<tier>` unit with `dbops dump-due` + flock would replace five
  separate timers; today each tenant has its own, which is what the schedules table decided.
* **R9**: Moodle still runs `moodle_dump.sh.j2` (its own rollback window) and R11's
  unattended drill runner does not exist yet — these drills were run by hand.
