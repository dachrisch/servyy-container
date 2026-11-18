# Database tier topology — Work packages

> Companion to `docs/plans/2026-11-17_db-tier-topology.md` (the design and per-phase
> runbooks). This file turns the plan into **stoppable units**: after any package is merged,
> the host is in a working, documented state, and nothing is half-migrated.

## Package status

| WP | Status | Evidence |
|---|---|---|
| WP-1 | **done** | `9552f2a` + `9ed1aac`; backup `mongo-all-pre-wp1-20261118T081534Z.archive.gz` (65 609 B, restore-drilled); failure path proven with `SIGSTOP`; volume survived every recreate |
| WP-0 (infra) | **done** | `97729693`; `portainer.watchtower-db` (scope `db`, daily 06:00, health-gated); tags pinned (photoprism 12.3, mongo 9.0); Renovate patch fence; drift guard live, `db_version_drift` 0/0/0 |
| WP-0c | **done** | `5a2fb75b`; guard accumulators reset (6→6), `testing.restic.check_recent` no longer a silent no-op (4 child tasks run) |
| WP-0b (leaguesphere) | **done** | PR #2436 → `b013e3f08`; prod/stage/demo all on `mariadb:13.0` (`54f493ea…`, same digest as before), prod `db` scope `db`; guard now resolves the high tier as `mariadb:13.0` with no "cannot verify" warning |
| WP-0d | **done** | `ebfefb36` + `cc4671d5`; `MARIADB_AUTO_UPGRADE` removed from `ls.env` after the 2026-11-18 outage (`history/2026-11-18_ls-db-upgrade-flag-outage.md`, ~6.5 min public downtime) |
| WP-0e (drills) | **done / partly deferred** | `d5714b3e`; real play-level minor-mismatch refusal (13.0 vs 12.3, `changed=0`, override downgrades to warning); Grafana rule `db_version_drift` loaded+enabled, `for 1d`, medium, queryable. Deferred: digest-drift drill and health-gate rollback (both need a second active server / a non-prod `db` watcher — unblock in WP-4). Found: the guard is blind under `--check` (command module has no check mode) |
| WP-2 | **done** | `82ccf8fd` + `050c120f`; `leagues_finance`/`queen` scoped users created, both apps live as their own users (11/14 collections read with their own credential), no `MONGO_INITDB_ROOT_*` in any app env; mongo root rotated (old rejected, new accepted, role authenticates with the new var) |
| WP-3 | **done** (3a + 3b) | 3a `3028ce02`: `db_tenants.yml` seeds 10 tenants from the running containers (prod is `web35_db8`/`web35_8`), the guard reads it (stage+demo now active → three MariaDB servers compared), `check_mode: false` fixes the `--check` blindness. 3b `17c230fc`: `dbops` (dump/restore/verify/shell/tenants, `.partial`, DEFINER stripping, exact counts), `db_tier` role (profiles, D12 limits, per-tier backup user, per-tier tags, `db_tiers`), `.gitignore`, D16 seed. Nothing runs yet: `db_tiers` is empty on every host. Limits: molecule blocked (no docker on the controller, no molecule on servyy-test) → CI; the SQL templates and `restore` are unexecuted; the backup user appears only on first deploy |
| Follow-ups (not packages) | open | `--tags user.docker.finance` is not self-contained (needs `user.docker.env.finance`); `shared.env` is shared by mongo and postgres, so a mongo credential change also recreates `shared.db`; Renovate dashboard check. From WP-4b (2026-11-18): **`dba.env` destination** — `ls_dbeaver_access` derived the sidecar env dir from the *database* container's compose label, so after the tier pin it wrote `db-nonprod/dba.env` while the sidecar read `container-stage/deployed/dba.env` and ticked `ERROR 2005 … Unknown server host 'mysql'` (fixed by WP-4b3: an explicit `compose_dir` pin + `*/dba.env` in `.gitignore`; needs the post-merge `--tags user.repo.clone,ls.dbeaver` run to move the file); **Vaultwarden backfill** of the `dbeaver_stage`/`dbeaver_tunnel` keys (the push needs an interactive `bw unlock`, which a non-interactive run cannot do); `ls_demo/templates/ls.env.j2` still renders `MYSQL_ROOT_PASSWORD` although the tier has no root account; the nonprod tier is `dump_schedule: none` **by design** — stage is rebuilt nightly from prod and the demo seeds itself nightly, so a tier backup would only duplicate prod |
| WP-4 | **done** (4a + 4b) | 4a `db-nonprod.mariadb` (backend `192.168.16.0/20`, gw `.1`, server `.2`), tier limits, `dba.env`, `ls_stage_access_admin`, reaper entry for the tier; tenant data copied and verified before the move (see `db_tenants.yml`). 4b cutover, 2026-11-18: stage app containers recreated 15:21Z, demo 15:26Z — both `MYSQL_HOST=db-nonprod.mariadb`, healthy, DB-backed pages 200 (`/login/`, `/gamedays/gamedays/`, a gameday page on each). Nightly sync run by hand: **exit 0**, 46.5 s, imported **as the non-root `leaguesphere_stage` user** (`information_schema.processlist` during the run: 12 `Query`/43 `Sleep`, all that user), `gamedays_gameday` `CREATE_TIME` 15:01:27 → 15:43:28, counts **781 / 345 / 42** matching prod at 15:46Z, tier schema 155.7 MB. Guard compares **two** active MariaDB servers (`leaguesphere.db`, `db-nonprod.mariadb`), both `mariadb:13.0`, D8 skips; `db_version_drift` 0/0/0; minted accounts cannot `USE demo_db` (1044/1142) and the deployed reaper drops unledgered ones (`dropping … (no-request-row)`). Rollback: demo container **stopped, not deleted** (`docker start` + revert compose); **stage's container was removed** by `--remove-orphans` before the fix, its datadir `…/container-stage/deployed/mysql-data` is intact, so stage's rollback is revert-compose + redeploy. Deviations: `ls_runs_own_db` still counted stage (fixed `a79e5415`), the widened grant-host assert demanded four octets after `172.16/12` and aborted prod (same commit), and `dba.env` landed in the tier's compose dir (WP-4b3) |
| WP-5 | **done** (5a + 5b) | 5a `374f910b`+`01a117f8`: `db-business.mariadb` (mariadb:13.0, 1.25g/384M pool, default isolation), bnb's account with its existing credential, data copied and verified (30 tables / 2,616 rows). 5b (merge `64c790bb`, 2026-11-18): `bnb_office_db_host: db-business.mariadb` rendered into the compose `.env` (the hardcoded `${COMPOSE_PROJECT_NAME}.db` is gone; `config.php` now says `mysql:host=db-business.mariadb`), app attached to `db_business_backend`, `db:` service + `db.env.j2` + `depends_on` dropped, `bnb_office` row → `db-business.mariadb` / `retiring: false` / guard-only `compose_dir: db-business`+`compose_service: mariadb`. Invoice numbering state **identical before and after** (auftraege `2026-001` → next `2026-002`; the counter bnb actually uses is `MAX(SUBSTRING(nummer,6))` in `AuftragRepository::nextNumber()`, not `nummernkreise` — that table is empty and vestigial, `rechnungen` has no module yet); per-table counts identical; a failed login wrote a `login_versuche` row **on the tier** (then removed, data back at 2,616); both hosts 303→`/login`, 200 before and after. **Three defects found and fixed:** (1) the old daily dump had never written a file — `ExecStart=` is not a shell, so `| gzip > file && find` were literal argv and every run dumped the whole database into the journal (18,136 lines, exit 0, `.backup` empty); it now runs `dbops dump bnb_office` inside `sh -c`; (2) `includes/oneshot.yml` never `daemon_reload`'d, so the rewritten unit stayed unloaded and the next fire would have run the old command; (3) the first prune glob `bnb?office-*` does not match `bnboffice-*` (measured), now `bnb*office-*`. Old container **stopped, not removed** (`Created` unchanged, volume still referenced — which also keeps the daily `prune --volumes` from eating it). Guard: active MariaDB set `leaguesphere.db`, `db-nonprod.mariadb`, `db-business.mariadb`, all `mariadb:13.0`, D8 skips, `db_version_drift` 0/0/0. Only `bnb-office.web` was recreated. Follow-up: bnb-office is in no container-health probe list (WP-8) |
| WP-6 | **done** (6a + 6b) | 6a/6b: `db-private.mariadb` (READ-COMMITTED, 512 conn, PhotoPrism's flags verbatim, seccomp/user dropped), copy 41 tables / 580,332 rows, 0 mismatches; cutover closed the 7-row `checked_at` delta under a stopped app (fingerprints identical); app counters reconcile (47,818 photos / 727 albums are filtered views of 46,690 / 1,014 rows); memory 296/512 MB; old server stopped, 775 MB datadir kept |
| WP-7 | **done** (7a + 7b) | Copy rehearsal 497 tables / 10,350,195 rows, snapshot boundary proven exactly on the 4.7M-row log table; **window 2026-11-18 18:40–19:20Z (39m37s)**: dump 1m48.8s (quiesced, `read_only=ON`, app up), restore 14m16.1s as the tenant user, **497/497 tables, 0 mismatches, 10,351,134 = 10,351,134 rows**; app on `db-business.mariadb`, cron exit 0, dump repointed to the tier *before* the old DB stopped (136 MB, gzip OK, single file in `current/`); old `moodle.db` stopped with its 2.2 GB datadir; guard now compares four 13.0 servers. **Login verified by the owner on 2026-11-18** (AFVD Flag Academy home rendered after a real credential login). Lessons: this image ignores `maintenance_enabled=1` and clears it on every boot — the working mode is `'cli mode'` set *after* boot; and **stopping the app turns the site into a 502 regardless of the flag**, so the window keeps the app up and freezes the DB instead |
| WP-8 … WP-11 | not started | — |

## WP-8R — backup strategy for the tiered fleet (proposed 2026-11-18)

> Design proposal from a read-only session; **owner decisions pending** (four questions at the
> end). Every number below was measured on servy, not estimated. This package must land
> **before** the rollback windows of WP-4…WP-7 close, because those windows are currently part
> of the only protection several tenants have.

**Why it is a separate package:** the existing wiring was built around *per-application*
database sidecars. Under the tier shape the mechanism, cadence and repo layout are properties
of the **tenant row**, not of a hand-written script — and today adding one repo means 12
hand-edited places across 9 files (repo entry, retention, schedules, logs, three `defaults`
lists, the backup task, a hardcoded `apply_retention` block, a hardcoded `check_repo` line, two
probe lists, and a repo name inside the static, non-Jinja `alert-rules.yml`).

### Three measured gaps that predate this migration (nobody created them; nobody could see them)

| Tenant | Reality today | Exposure |
|---|---|---|
| `firefly` (postgres) | **no backup at all** — `PGDATA` is on `/mnt/servy-docker-data`, and the `root` repo excludes `/mnt` (`vars/restic.yml:120`) | 68 MB of financial data, one host loss from total loss |
| `leagues_finance`, `queen`, `dontforget` (mongo) | **no backup at all** — `shared_mongo_data` is a docker volume on `/mnt`, same exclusion; the only artefacts are two ad-hoc archives that happen to sit in `/home` | 481 MB, three tenants |
| `photoprism` | **no dump**; the only protection is the *stopped* pre-cutover datadir (775 MB) riding the hourly `home` repo — and a raw datadir is not a backup | 1 014 albums / 169 links / favourites: a re-index rebuilds derived data, never these |
| `leaguesphere` (high) | "PITR" is **documented but not wired**: `mariadb-backup` runs without `--binlog`, the prepared set contains **0** binlog files, and the only binlog copies are inside the daily `root` snapshot of a *live* datadir (`expire_logs_days=2`) | the high tier's defining promise is currently accidental |

Also measured: tier datadirs are in **no** repo by design (`servyy-container/db-*/data`
excluded; `root` covers `/etc`+`/var`), so a tenant with `dump_schedule: none` has **zero**
protection — which is exactly PhotoPrism's state.

### Strategy

One repo **per business tenant** and **one per tier** (D16 seed), none for nonprod. Cadence
follows *how recoverable the data is otherwise*, not its size:

| Tenant / tier | RPO target | Cadence | Mechanism |
|---|---|---|---|
| `leaguesphere` (high) | 15 min via binlog on a 1 h physical base | hourly physical **+ 5-min binlog shipping** | `mariadb-backup` + `--binlog`, new `ls-binlog` repo (keep previous image pullable — physical sets are version-bound) |
| `moodle` (business) | 1 h | hourly (keep) | logical dump; **stays on `moodle_dump.sh.j2` through its rollback window** |
| `bnb_office` (business) | 24 h | daily 02:30 | `dbops`; needs the owner's answer on files-vs-repo for the contract |
| `leagues_finance`, `queen` (business) | 24 h | daily | `dbops` mongo adapter |
| `photoprism`, `dontforget`, `firefly` (private) | 24 h | daily | `dbops` (postgres adapter is interim, deleted with `shared.db` in WP-10) |
| `leaguesphere_stage`, `_demo` (nonprod) | *until the next sync / reset* — not an RPO | **none**, and **no probe series** (emit nothing, never `-1`, or the alert pages forever) | — |

`dbops` must gain, before any convergence: `--skip-dump-date`, a **fixed** target name with an
atomic `new/`→`current/` swap, `.partial` **outside** the snapshot path, `gzip -t` + a
per-tenant size floor, pruning (globs must match both `bnb_office-*` and `bnboffice-*` — the
lesson from `8e3bd8ce`), and `dump-due` + `flock` so one unit per tier serves many tenants.
Measured reason: two dumps of an *idle* database differ by exactly one line today, and a
timestamped name means restic re-stores the whole file.

**Do not converge Moodle inside its rollback window** — `moodle_dump.sh.j2` is the one job
proven against both servers, and its `CONTAINER` is already rendered from `moodle_db_host`, so
it follows the move in either direction.

### Measured cost, and what would not fit

- Moodle's hourly logical dump costs **126.8 MiB of new data per hour** (2.97 GiB/day, 6.1 GB
  steady). Decompressing two consecutive snapshots shows only ~1 400 scattered rows changed, so
  chunk-level dedup cannot help — `--skip-dump-date` is still right, it just cannot rescue
  Moodle. Per-table dumps would localise it (~20–40 MB/h) but break `dbops verify`'s
  single-file model; **not worth it at 529 GB free**.
- Total: servy 45 GB → **≈ 48.5 GB** of a 974 GB box (≈ 525 GB free). Capacity is not a
  constraint anywhere in this package.
- **What would not fit:** the *current* `dbops` driven hourly for Moodle. Timestamped names and
  no pruning grow the source directory 3.1 GB/day → `/` (27 GB free) is full in **~9 days**,
  and the retained trees reference every file (~90 GB/tenant/year). Those `dbops` changes are
  blocking, not cosmetic.

### Monitoring

Two generated probes, from the same rows: `db_dump_age_seconds{tenant,tier}` (a broken dump)
and the existing `restic_snapshot_age_seconds{repo}` (a broken upload). The probe pushes its
**own threshold and severity**, so `alert-rules.yml` — static and bind-mounted — becomes
name-free and stops needing an edit per tenant. nonprod emits no series at all. Keep the
probe-staleness rule: a dead probe must not look like a healthy fleet.

### Tasks (ordered; additive first, deletions last)

| # | Task | Verification |
|---|---|---|
| R1 | Inventory schema + generator for repos/retention/forget/check/probes (renders the *same* five repos today) | rendered scripts diff clean against the host's current ones |
| R2 | Name-free alert rules + threshold-pushing dump-age probe | a deliberately stale dump alerts < 10 min; `probe: none` removes the series |
| R3 | **`pg_dump` for firefly** (interim, deleted in WP-10) | restore into scratch postgres on servyy-test; counts match |
| R4 | **PhotoPrism dump** daily into its tier repo | restore shows 1 014 albums / 46 690 photos / 169 links |
| R5 | **Make PITR real**: `--binlog` + 5-min `ls-binlog` repo (2-day retention, matching `expire_logs_days`) | replay binlogs into a scratch server between two backups; first end-to-end PITR proof |
| R6 | **Mongo dumps** for all three tenants, cron'd, per repos | `mongorestore` each into scratch; collection counts match |
| R7 | Canonical dump root + repo separation; exclude `db-dumps` and the stopped PhotoPrism datadir from `home` | bnb's dump appears in its own repo and vanishes from `home`; `home` shrinks ~1.1 GB |
| R8 | One `db-backup@<tier>` unit per tier (`dbops dump-due`, lock, stale-source guard) | one timer per tier; a killed dump leaves `current/` untouched |
| R9 | Converge Moodle on `dbops` — **after** its window and after R1…R5 | `restic diff` on an idle period < 5 MiB; `dbops restore`+`verify` accepts |
| R10 | Delete the old surface (moodle-dump, bnb one-liner, superseded restic units, dead `ls_stage_restore`) | no unit outside the inventory; `grep` clean |
| R11 | **Restore drills**: `plays/restore_drill.yml` on servyy-test, evidence in `history/`, `db_restore_drill_*` metrics | a drill runs unattended; a broken repo trips the *drill* alert |

| R12 | **Backups must not depend on `/tmp`.** restic writes its temp pack to `TMPDIR`, which is a 3.8 GB tmpfs here; two stray 1.6 GB dumps filled it and every `home` snapshot failed with `disk quota exceeded` while the unit's failure looked unrelated to backups. Implemented 2026-11-18: every restic script (all five come from `restic_backup.sh.j2`) exports `TMPDIR={{ restic.tmpdir }}` = `~/.cache/restic-tmp` (0700, excluded from every scope; the sudo branch re-exports it because sudo resets the env), and a `system-tmp` probe pushes `system_tmp_usage_pct` every 10 min with alerts at 70 % (medium) / 90 % (high). | `TMPDIR` in the rendered script; an inherited `TMPDIR=/nonexistent` no longer matters; `/tmp` has a metric and two rules |
| R13 | **Wire the memory alert the plan keeps citing.** Corrected 2026-11-18: the **alert rule** has always existed (`uid: container_memory_near_limit`, working set / mem_limit > 0.9 for 15m, capped containers only) and evaluates correctly — the "0 series" was measured against the **Pushgateway** (:9091), not Prometheus (:9090, not published). What was missing is a **series** of that name. Added: Prometheus recording rule `monitor/rules/container-memory.yml` (same expression), `monitor/rules` listed in `world_readable_paths_by_service` (Prometheus runs as `nobody`; an unreadable glob matches nothing **silently**), and `plays/tasks/monitor_reload.yml`, which restarts Prometheus only for `prometheus.yml`/`rules/` changes and Grafana only for `provisioning/alerting/` changes — both otherwise read their config at startup only. Documented in `monitor/AGENTS.md`. | `container_memory_near_limit{name="db-business.mariadb"}` ≈ 0.39, absent for unlimited containers, `rules` group `health=ok` after a clone, no restart when nothing changed |

Datadir deletion stays in WP-8's old last step — it is irreversible and unrelated to wiring.

### Schedules (decided 2026-11-18)

Chosen so that (a) no dump overlaps another on the same host, (b) all daily work finishes
before the 02:00–04:00 nightly restic window, (c) nothing lands in the 06:00 `db` watchtower
patch window or the 05:00 Firefly import, and (d) every dump is followed by its own restic
snapshot, not by a shared one.

| Tenant | Cadence | Dump at | Snapshot at | Retention | RPO | RTO |
|---|---|---|---|---|---|---|
| `leaguesphere` (high) | physical hourly + **binlog every 5 min** | :40 | :55 | physical 24 h + 14 d + 8 w + 6 m; binlog `--keep-within 2d` (matches `expire_logs_days=2`) | **15 min** | ≤ 2 h (manual copy-back + replay) |
| `moodle` (business) | hourly | :40 | :50 | 24 h + 14 d + 8 w + 6 m (~52 snapshots) | 1 h | ≤ 30 min (13m36s measured + smoke) |
| `bnb_office` (business) | daily | 01:05 | 01:10 | 30 dailies + 8 w + 6 m (same as the private tenants) | 24 h | ≤ 5 min |
| `leagues_finance` (business) | daily | 01:15 | 01:20 | 30 dailies + 8 w + 6 m | 24 h | minutes |
| `queen` (business) | daily | 01:25 | 01:30 | 30 dailies + 8 w + 6 m | 24 h | minutes |
| `photoprism` (private) | daily | 00:45 | 00:55 | 30 dailies + 8 w + 6 m | 24 h | ≤ 30 min (103 MB gz) |
| `dontforget` (private) | daily | 01:35 | 01:40 | 30 dailies + 8 w + 6 m | 24 h | minutes |
| `firefly` (private, **interim until WP-10**) | daily `pg_dump -Fc` | 01:45 | 01:50 | 14 dailies + 4 w (it is short-lived by design) | 24 h | minutes |
| `leaguesphere_stage`, `_demo` (nonprod) | **none** | — | — | — | until the 02:00 sync / 00:00 reset | 47 min (re-run the sync) |

Notes on the decisions themselves:

- **Moodle stays hourly.** 2.97 GiB/day is the honest price of a 1 h RPO; 529 GB is free, and a
  lost hour is a lost hour of grades and forum posts. Cadence is now a row, so revisiting it is
  one edit.
- **bnb keeps the same retention as the private tenants** (30 dailies + 8 weekly + 6 monthly),
  owner's decision on 2026-11-18: its own repo is the artefact, and `keep_dumps` stays a row if
  the contract wording ever needs more.
- **Binlog shipping is in**, otherwise "high tier = PITR" remains a documented promise with no
  mechanism behind it.
- **Drills:** weekly (Sun 06:30) for `leaguesphere` and `moodle` — the two with a real RTO;
  monthly (first Sun 06:30) for the other six. Weekly-for-everything would become noise, and
  noise is how a four-week backup gap went unnoticed in 2026-09.
- **Photoprism at 00:45**, not in the crowded 01:00–02:00 slot, because its 103 MB dump is the
  slowest of the dailies.

## The stopping rule

1. **One package = one branch + one PR, merged before anything is deployed.** The order is:
   implement on the branch → static checks → review → **merge to master** → deploy from
   master (test host first, then production) → exit gate. Deploying a branch is never allowed;
   if a merged package misbehaves, revert that one commit or forward-fix. A package that lists
   a dependency cannot start before that dependency is merged.
   **A deploy must sync the checkout on the host:** `--tags user.repo.clone,<service tags>`.
   A tag-scoped run alone deploys whatever commit the host already has — verified in WP-1,
   where the first run "succeeded" against the previous checkout.
2. **Never stop inside a package.** The only unsafe moments are inside a single run: after a
   dump but before the app points at the new server, after pointing but before the smoke
   test, and inside the version hop. Each is minutes, not days — finish the run.
3. **Rollbacks stay available for one week** after a move package (old container stopped,
   old datadir untouched). Deleting the old datadirs is its own package (WP-8), never part
   of a move.
4. **Every package ends with a history entry** (`history/<date>_db-tier-topology.md`,
   appended, one section per package).

## Exit gate (applies to every package)

- The package is **merged to master**, and the deploy that follows ran from master — the
  working tree is clean and `git log -1` is the package's commit.
- `docker ps` shows every container `healthy` (or `running` where it has no healthcheck).
- `systemctl --user list-timers` has no failed unit; `restic snapshots` shows the newest
  snapshot inside its normal window.
- `db_version_drift` is `0` for every engine — or `1` only because a watchtower patch pull is
  still in flight, or inside a documented hop window.
- The package's own verification list from the plan passes on the **test host first**, then
  on production.
- Rollback for the package is still possible, or its window is explicitly recorded as closed.

## Package map

| WP | Title | Plan ref | Depends on | Data at risk | Downtime |
|---|---|---|---|---|---|
| 0 | Fence the versions | Phase 0 | **1** | none (tag/label only) | one restart per DB server, staggered |
| 1 | Disarm the mongo wipe | Phase 1 step 0 | — | none (adds a backup) | none |
| 2 | Take mongo off root | Phase 1 steps 1–3 | **1** | mongo (rotate) | shared.mongo recreate |
| 3 | Inventory, `dbops`, `db_tier` | Phase 2 | 0 | none | none |
| 4 | nonprod tier: LS stage + demo | Phase 3 | 3 | stage/demo (disposable) | stage + demo restart |
| 5 | business tier: bnb office | Phase 4 | 3 | bnb (invoice counter) | bnb web pause |
| 6 | private tier: PhotoPrism | Phase 5 | 3 | photos metadata | PhotoPrism restart |
| 7 | business tier: Moodle | Phase 6 | 5 | 1.6 GB LMS | maintenance mode |
| 8 | Backups, probes, retire the old surface | Phase 7 | 4,5,6,7 | none | none |
| 9 | Mongo into the tiers | Phase 8 | 2,5,6 | mongo tenants | per-tenant restart |
| 10 | Retire Postgres (Firefly) | Phase 9 | 6 | financial data | Firefly restart |
| 11 | MariaDB version hop (recurring) | Phase 10 | all of 0–10 | every MariaDB | one server at a time |

**WP-1 and WP-0 are both no-data packages but they are not freely reorderable:**
a watchtower label is a container label, so changing it recreates that container — and
recreating `shared.mongo` before WP-1 disarms the volume wipe is exactly the hazard WP-1
removes. **Merge WP-1 first, then WP-0.** Everything else in WP-0 (tags, the `db` watchtower
instance, Renovate, the guard) is independent of WP-1. **WP-2 must never be merged before
WP-1** either, for the same reason.

---

## WP-0 — Fence the versions

**Goal.** No floating tags and no unattended database upgrades anywhere; drift becomes a
checked condition instead of a convention.

**Changes.** Tags pin the minor and float the patch: `moodle`/`bnb-office` stay
`mariadb:12.3`, `photoprism` `mariadb:lts` → `mariadb:12.3`, `shared.db` stays
`postgres:15`, `shared.mongo` → `mongo:9.0`; a `watchtower-db` instance (`db` scope, daily
06:00 window, health-gated rollback) and the `db` scope label on every database server —
**including `leaguesphere.db`**, whose label ships in the leaguesphere repo's PR; **each label
change recreates that server, so stagger them one at a time**; `shared.mongo`'s label moves
only after WP-1 (see the ordering note above). **Do not put `MARIADB_AUTO_UPGRADE` in
`ls.env`** — it shares `MYSQL_HOST` with the db container and killed the platform on
2026-11-18 (`history/2026-11-18_ls-db-upgrade-flag-outage.md`); the `db-<tier>` services get
it in their own env files. Renovate patches disabled for database packages and minors/majors behind
dashboard approval; the three LeagueSphere server tags (`mariadb:latest` → `mariadb:13.0`)
in that repo's PR; the drift guard as a shared `pre_task` included from **both**
`plays/user.yml` and `plays/leaguesphere.yml`.

**Exit gate.** Every database server has a minor-pinned tag and the `db` scope — **including
`leaguesphere.db`** (its label ships in the leaguesphere repo's PR; the accepted consequence is
a 06:00 restart of the high tier when a patch lands, health-gated with rollback); no
`:latest`/`:lts` left on a database; Renovate shows no database patch updates and gates
minors; deliberately setting one compose to `mariadb:13.1` fails a run before anything
restarts; a simulated patch (same tag, new digest) gives `db_version_drift=1` without
blocking; a broken image in the `db` scope is rolled back by the health gate.

**Rollback.** Revert the tags and rules. Two containers were recreated, no data touched.

**Stop state.** Six servers, three lines, all fenced. Everything still runs exactly as
before; only the ability to drift silently is gone.

## WP-1 — Disarm the mongo wipe

**Goal.** Remove the one control that can destroy all three mongo tenants from a routine
deploy.

**Changes.** `mongodump --archive` of all three databases to restic; the post_task at
`plays/user.yml:764` (remove container → remove `shared_mongo_data` → restart) replaced by a
`fail` that names the container and its health status; `start_interval: 2s` /
`start_period: 30s` on the `shared.mongo` healthcheck.

**Exit gate.** The mongo archive is in restic and restorable into a scratch mongo; a forced
recreate of `shared.mongo` leaves `shared_mongo_data` intact and a failed healthcheck fails
the play instead of wiping.

**Rollback.** Revert the task block (the archive stays as a bonus).

**Stop state.** Mongo as before, minus the footgun. No config or data change.

## WP-2 — Take mongo off root

**Goal.** No application container holds the mongo root credential.

**Changes.** `leagues_finance` and `queen` users added to `shared_mongo_users`
(`readWrite` + `dbAdmin` on their own database); `MONGO_URI` switched with
`authSource=<own db>`; `MONGO_INITDB_ROOT_*` dropped from the leagues-finance env; root
rotated **in the database first, then in `secrets.yml`**, then a `--tags user.docker.shared`
deploy.

**Exit gate.** Both apps read and write; `docker exec <app> env` shows no root credential;
the old root password is rejected; `shared_mongo_users` authenticates with the new one.

**Rollback.** Revert the two URIs; `changeUserPassword` back and revert the var.

**Stop state.** Same data, same topology, no app on root. Safe to stop here indefinitely.

## WP-3 — Inventory, `dbops`, `db_tier` role

**Goal.** One place that describes every tenant, one tool that dumps/restores any of them,
one role that stands up a tier.

**Changes.** `vars/db_tenants.yml` seeded with current placement (including `retiring: true`
rows); `dbops.sh` with the MariaDB adapter and the DEFINER-stripping restore and
`.partial`-rename dumps; `roles/db_tier` (env + users + backup user, **no compose
rendering**); per-tier invocation tags; `db_tiers` host var; `.gitignore`; restic seed
`vars/.restic_password_db`; molecule scenario; guard switched to the inventory.

**Exit gate.** `dbops dump` + `dbops verify` against every current server produce matching
counts; molecule green in CI and on servyy-test; the guard reads the same list.

**Rollback.** Tooling only — remove the role and the var; nothing was applied to any server.

**Stop state.** No topology change at all. The plan can pause here indefinitely.

## WP-4 — nonprod tier: LS stage + demo

**Goal.** The canary: both disposable LeagueSphere environments on one tier server.

**Changes.** `db-nonprod/docker-compose.yml`; tier secrets; dump/restore under the existing
database names; leaguesphere compose loses its `mysql:` service and points `MYSQL_HOST` at
`db-nonprod.mariadb`; tunnel grants moved to the new subnet and `33062` dropped from
`local_ports`; `db-access` switched to `ls_stage_access_admin`; demo reset credential scoped;
`ls_db_sync` retargeted with a hard failure if the old container name reappears;
`ls_stage_restore` → `dbops restore --from-physical`.

**Exit gate.** Stage smoke test; forced demo reset; nightly sync against the new host; a
physical-backup restore into stage; a DBeaver tunnel login whose minted account cannot `USE`
the demo database.

**Rollback.** Restore the `mysql:` blocks and `MYSQL_HOST`, start the old containers.

**Stop state.** Stage and demo on the new tier; production untouched; old datadirs kept.

## WP-5 — business tier: bnb office

**Goal.** Stand up the business tier with its smallest tenant, sized for Moodle from day one.

**Changes.** `db-business/docker-compose.yml` (1.25g, 384M pool, default isolation); bnb
database moved under the same name; `bnb_office_db_host` var; app attached to
`db_business_backend`; the `db:` service removed; the bnb dump moved onto `dbops`.

**Exit gate.** Invoice-number counter continues without a gap; site loads; dump lands in the
per-tenant directory and its own restic repo.

**Rollback.** Point the app back at the old `db:` service; its datadir is untouched.

**Stop state.** Business tier exists with one tenant; Moodle still on its own server.

## WP-6 — private tier: PhotoPrism

**Goal.** Stand up the private tier and move the photo database onto it.

**Changes.** `db-private/docker-compose.yml` with PhotoPrism's server flags; database moved
under the same name; app attached to `db_private_backend`; `mariadb:` service removed.

**Exit gate.** Library and albums load; a manual index run completes; the next scheduled
index run completes; the **memory alert** `container_memory_near_limit` clean for a week
(PhotoPrism's DB had no limit before). That name is the Grafana alert rule
(`monitor/provisioning/alerting/alert-rules.yml`, uid `container_memory_near_limit`:
working set / `mem_limit` > 0.9 for 15m, capped containers only) **and**, since
2026-11-18, a Prometheus recording rule of the same name (`monitor/rules/container-memory.yml`)
— so it can also be queried directly; before that it was only a rule UID and could not be.

**Rollback.** Restore the `mariadb:` service; `./database` untouched.

**Stop state.** PhotoPrism on the private tier, exactly as stable as before.

## WP-7 — business tier: Moodle

**Goal.** The largest move: 1.6 GB LMS onto the business tier.

**Changes.** Rehearsal on servyy-test; `moodle_db_host` var; maintenance mode; dump →
restore → verify → collation check; app attached to `db_business_backend`; `db:` service
removed; hourly cadence onto the inventory.

**Exit gate.** Login, one course page, cron clean; hourly dump snapshotted; memory alert
clean for a week; buffer-pool hit rate acceptable.

**Rollback.** Maintenance on, revert `moodle_db_host`, redeploy, start `moodle.db` on the
old datadir (kept a week).

**Stop state.** All four move packages done; every MariaDB tenant on its tier; old servers
still parked for rollback.

### WP-7b runbook — the Moodle cutover window (≈30 min, owner-scheduled)

Measured on the WP-7a rehearsal (2026-11-18): dump **1m48s** (130 MB gzip), restore
**13m36s**, 497 tables / 1 671 MB / 10.35 M rows. Copy time alone is ≈15½ min; the rest is
verification and smoke, so book **30 minutes** and tell OFFD beforehand.

**Preconditions.** Master contains WP-7b and the host is at that commit (`--tags
user.repo.clone`); `db-business.mariadb` healthy with the `moodle`@`%` account (WP-7a);
the rehearsal copy is present and may be overwritten with `--force`.

| # | Step | Command / check | Time |
|---|---|---|---|
| 0 | Announce; note the last good dump | `systemctl --user list-timers moodle-dump.timer` — note `current/moodle.sql.gz` and its restic snapshot | — |
| 1 | Maintenance mode **on** | Moodle UI → Site administration → Server → Maintenance mode, or `docker exec -u nobody moodle.moodle php /var/www/html/admin/cli/maintenance.php --enable` | 1 min |
| 2 | **Stop the app** — this is what stops Moodle's cron (it runs inside the app container, not as a host timer), so no writes and no adhoc tasks land between dump and restore | `docker stop moodle.moodle` | 10 s |
| 3 | Final dump (as root from the old container's env; the tier backup user does not exist on the old server) | `DBOPS_USER=root DBOPS_PASSWORD="$(docker exec moodle.db printenv MARIADB_ROOT_PASSWORD)" DBOPS_DUMP_DIR=/home/cda/dbops-dumps ~/.dbops/dbops dump moodle` | **≈1m48s** |
| 4 | Restore over the rehearsal copy, as the **tenant user** (`--force` because tables exist) | `DBOPS_SERVER=db-business.mariadb DBOPS_USER=moodle DBOPS_PASSWORD="$(docker exec moodle.db printenv MARIADB_PASSWORD)" ~/.dbops/dbops restore moodle <file> --force` | **≈13m36s** |
| 5 | Verify before the app starts: per-table counts vs the (now quiescent) source must now match **exactly** — the WP-7a drift is gone because nothing is writing; `dbops verify moodle`; and `SELECT COUNT(*) FROM ibs.aenderungen` still 1 160 (bnb untouched) | see `compare-moodle` script shape in the WP-7a report | 3 min |
| 6 | Deploy the new env (renders `DB_HOST=db-business.mariadb`, recreates `moodle.moodle` on `db_business_backend`) | `./servyy.sh --limit servy.lehel.xyz --tags user.repo.clone,user.docker.moodle` | 2 min |
| 7 | Smoke: `https://offd.de/login/` 200, one real course page loads, then `docker exec moodle.moodle php /var/www/html/admin/cli/cron.php` exits 0 and the log has no new `cron` errors | | 5 min |
| 8 | Maintenance mode **off**; one login as a real user | | 1 min |
| 9 | Retire the old server: `docker stop moodle.db` (keep `${MOODLE_DATA_ROOT}/mariadb`, 1.7 GB, one week) | `docker inspect -f '{{.Created}} {{.State.Status}}' moodle.db` | 10 s |
| 10 | **Repoint the dump — do NOT stop the timer.** The script renders `CONTAINER` from `moodle_db_host`, so deploying it makes it dump the tier; the hourly cadence and the `moodle-db` restic scope stay exactly as they are. Then run it once by hand to prove the target, and delete the now-unused sidecar credentials file (`moodle/db.env`: the compose no longer reads it, the role no longer renders it, it holds the old root password) and any stale `moodle/docker-compose.yml.new` | `./servyy.sh --limit servy.lehel.xyz --tags user.repo.clone,restic.backup` (renders scripts + units, runs **no** backup) → `grep ^CONTAINER ~/.backup-scripts/moodle-dump.sh` = `db-business.mariadb` → `~/.backup-scripts/moodle-dump.sh` → `sudo ls -l …/db-backup/current/` and `sudo gzip -t …/current/moodle.sql.gz` → `rm -f /home/cda/servyy-container/moodle/db.env /home/cda/servyy-container/moodle/docker-compose.yml.new` | 2 min |
| 11 | Post-checks: guard shows `db-business.mariadb` (already, since the row moved) and no `moodle.db`; `db_version_drift` 0; memory watch on `db-business.mariadb` for a week | | — |

**Ordering that must not be broken:** 2 before 3 (a live dump carries the drift), 4 before
6 (`compose up` starts Moodle against whatever is in `moodle` — a half-restored database
boots and "upgrades" it), 5 before 6 (the counts are only exact while both sides are
quiescent), 9 and 10 together (the timer's target disappears with the container).

**Rollback** (any time before WP-8 deletes the old surface, one week): maintenance on →
`docker start moodle.db` → remove `moodle_db_host` from `ansible/production` and restore
the compose (both are one `git revert` of the WP-7b commit) → `--tags user.repo.clone,user.docker.moodle`
→ maintenance off. Everything written to the tier in between is lost with that rollback —
the old server's data is the 17:40Z rehearsal + whatever the final dump captured.

**Memory watch.** `db-business.mariadb` is 1.25 GiB and now carries Moodle (1.7 GB on disk)
**and** bnb; the old setup had a 1 GB Moodle DB server plus the app's own 1.5 GB. 41 % used
right after the copy. Watch the `container_memory_near_limit` alert (working set / `mem_limit`
> 0.9 for 15m; also a Prometheus series of that name since 2026-11-18) and the buffer-pool hit
rate for a week; the business tier is the first candidate to resize if `moodle` + `ibs`
together start evicting pages.

**The two timer questions**

* `moodle-dump` (script `/home/cda/.backup-scripts/moodle-dump.sh`, hourly at :40, restic scope
  `moodle-db`, target `…/data/db-backup/current/moodle.sql.gz`): **closed inside this package**, so
  the cutover leaves no dump gap. The script now renders `CONTAINER` from `moodle_db_host`
  (`roles/restic/tasks/backup.yml`, `roles/restic/templates/moodle_dump.sh.j2`), which is the same
  variable the app's `DB_HOST` comes from — the dump and the app can never point at different
  servers, including through a rollback, and servyy-test keeps dumping its own `moodle.db`. The
  timer is **not** stopped: step 10 redeploys the script and proves it with one manual run.
  What must not change: `--skip-dump-date` + `gzip -n` (an unchanged database must produce a
  byte-identical file so restic deduplicates the hourly 130 MB dump), the prepared `new/`→`current/`
  swap, and the gzip + 10 MB size floor. A naive `dbops dump moodle` has neither flag and no
  pruning, so it would store a fresh blob every hour; WP-8's remaining choice is whether to keep
  this script (fine) or teach `dbops` the same determinism and pruning first.
* No `docker-photo-index`-style pause exists for Moodle: its cron runs **inside** the app
  container, so `docker stop moodle.moodle` (step 2) is the pause. Re-enabling is implicit in
  step 6/8 — the container starts cron with it. Nothing else schedules work against the DB.

## WP-8 — Backups, probes, retire the old surface

**Goal.** One dump/probe wiring for the whole fleet, and delete what the moves made dead.

**Changes.** One `dbops-dump@<tier>` timer per tier (high keeps its two jobs on one timer);
restic repos per tier/business tenant; dump-freshness probes generated from the inventory;
retire `moodle_dump.sh.j2`, `moodle-dump`, `restic-backup-moodle-db`, the bnb one-liner and
the old `ls_stage_restore` task list; delete the old datadirs after a week of green.

**Exit gate.** `dbops verify` for every tenant; one scratch restore per tier; one timer per
tier; a stale dump trips its probe; no orphaned timers or containers.

**Rollback.** The timers/scripts are additive until the deletion step; datadir deletion is
the only irreversible act and happens last, with a final dump already in restic.

**Stop state.** This is the point where the migration is functionally finished.

## WP-9 — Mongo into the tiers

**Goal.** Two tiered mongos, no app on root, `shared.mongo` retired.

**Changes.** Mongo adapter for `dbops`; `db-business.mongo` (leagues-finance, queen) and
`db-private.mongo` (dontforget); app networks and URIs switched; per-tenant repos;
`shared.mongo` + `shared_mongo_data` removed after a week.

**Exit gate.** Each app reads its data; a user from one tier cannot authenticate against the
other; dumps and probes green; `shared` project holds redis only.

**Rollback.** Point the URIs back at `shared.mongo` (kept a week) and restore its volume.

**Stop state.** Engine mix is now MariaDB + Mongo only; Postgres still pending.

## WP-10 — Retire Postgres

**Goal.** Firefly on `db-private.mariadb`, postgres gone.

**Changes.** Mechanism proven on a scratch instance first (table-by-table `data only`
preferred, export/import only as a documented fallback); count/balance gate; Firefly's four
compose vars + `DB_PASSWORD` in the env template; then the cleanup commit a month later.

**Exit gate.** Accounts, transactions, budgets, rules and piggies all present and matching
production counts; daily import runs; postgres snapshot still restorable for a month.

**Rollback.** Point Firefly back at `shared.db` (its data is untouched for a month).

**Stop state.** Two engines, one version line, no Postgres. The original goal of the
exercise.

## WP-11 — MariaDB version hop (scheduled, recurring)

**Goal.** Off an expiring line, without a mixed fleet.

**Changes.** A minor change is `mariadb:13.0` → `mariadb:13.1` in the compose files — a
Renovate minor PR (approval-gated), not a patch. Merge it here first (three tier files), then
run one tier at a time with `--tags user.docker.db-<tier>` and
`-e db_version_guard_allow_drift=mariadb`, followed by the leaguesphere PR and the high-tier
deploy last; fresh physical backup after the high-tier upgrade; the previous minor's tag
stays pullable until its backups age out. Patches inside a line need no package at all —
watchtower applies them daily.

**Exit gate.** All four servers on the new minor tag; `db_version_drift=0` once every server
has been deployed; high-tier PITR backups from the new version exist.

**Rollback.** Previous image is still pullable — but a hop is forward-only for the datadir,
so the real rollback is the pre-hop dump.

**Stop state.** Not a stopping point by design: run it to completion, tier by tier, in one
sitting. Do not start it inside WP-4…WP-7.

---

## Recommended order and stopping points

**The order is a chain, not a menu:**

1. **WP-1** (disarm the mongo wipe) — nothing else may recreate or relabel `shared.mongo`
   before this is merged.
2. **WP-0** (tags, `db` watchtower scope, Renovate, drift guard) — its mongo tag/label change
   needs step 1 already merged.
3. **WP-2** (mongo off root).
4. **WP-3** (inventory, `dbops`, `db_tier`).
5. **WP-4 → WP-5 → WP-7** (nonprod, business with bnb, then Moodle). **WP-6** (PhotoPrism) can
   slot in any time after WP-3 — it is independent of bnb.
6. **WP-8** (backups, probes, delete the old surface) — after 4, 5, 6, 7 are green for a week.
7. **WP-9** (mongo into the tiers) and **WP-10** (Postgres) — either order; both need their
   target tier servers to exist (WP-5 / WP-6).
8. **WP-11** (version hop) — scheduled, once everything else has settled.

**Good places to pause for weeks:** after WP-1, WP-0, WP-2, WP-3, WP-5, WP-6, WP-7, WP-8.
Each leaves the host fully working with no pending cleanup.

**Never pause:** inside WP-2 (root rotated in the DB but not in the var — apps and the
`shared_mongo_users` role disagree), inside a move between dump and smoke test, or mid-hop.

**Ordering notes.**

- WP-7 needs WP-5 merged (the tier server must exist and be sized for Moodle).
- WP-10 needs WP-6 merged (`db-private.mariadb` must exist) and can be done any time after
  that — it does not block WP-9.
- WP-8's datadir deletion must come after WP-4…WP-7 have all been stable for a week.
- WP-9 and WP-10 are independent of each other; either order works.

## Secrets and cross-repo work

| Package | git-crypt `secrets.yml` | leaguesphere repo PR |
|---|---|---|
| WP-0 | — | yes (three server tags + Renovate rule) |
| WP-2 | yes (mongo root var) | — |
| WP-4 | yes (tier + stage/demo users) | yes (compose + `MYSQL_HOST`) |
| WP-5 | yes (tier + bnb user) | — |
| WP-6 | yes (tier + photoprism user) | — |
| WP-7 | yes (moodle user) | — |
| WP-9 | yes (scoped mongo users) | — |
| WP-10 | yes (Firefly DB password) | — |
| WP-11 | — | yes (high-tier tag) |

Coordinate secret edits with any other active session — one editor at a time.
