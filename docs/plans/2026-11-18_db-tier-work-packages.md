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
| Follow-ups (not packages) | open | `--tags user.docker.finance` is not self-contained (needs `user.docker.env.finance`); `shared.env` is shared by mongo and postgres, so a mongo credential change also recreates `shared.db`; Renovate dashboard check |
| WP-4 … WP-11 | not started | — |

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
index run completes; `container_memory_near_limit` clean for a week (PhotoPrism's DB had no
limit before).

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
