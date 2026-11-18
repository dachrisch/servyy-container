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
