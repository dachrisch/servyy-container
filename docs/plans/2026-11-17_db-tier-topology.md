# Database tier topology — Implementation Plan

> **For agentic workers:** implement phase by phase, in order, on a **branch of this
> checkout** — not a git worktree (`docker.local_dir` in `ansible/plays/vars/secrets.yml:65`
> points at `/home/cda/dev/infrastructure/container`, so a worktree would still deploy this
> checkout's templates).
>
> **Merge before deploy.** A package is implemented and reviewed on its branch, merged to
> master, and only then deployed — test host first, then production. Never run a play against
> servyy-test or servy from a feature branch. If a merged package misbehaves in a deploy,
> revert that commit (one commit per package) or forward-fix; do not deploy a branch.
>
> Do NOT edit `ansible/plays/vars/secrets.yml` or `ansible/plays/roles/ls_app/vars/secret_*.yaml`
> unless no other session is active — they are git-crypt encrypted (binary diff → an
> unresolvable merge conflict). Everything else in this plan is a plain-text change.
>
> **Status:** final (2026-11-18). All decisions are recorded in the decision log at the end;
> none are open.

**Goal:** organise every database on servy by **tier** (whose data it is and how it may be
operated) instead of by owning app: six MariaDB servers on three versions become **four
MariaDB servers on one version line**, one Mongo becomes two *tiered* Mongos with no app on
root, Postgres goes to zero — with one tenant inventory, one dump/restore tool and one
backup/probe wiring for all of them.

**Architecture:** a tier is a *rule* (membership, access, backup, upgrade order). An
*instance* is a (tier, engine) pair and exists only once a tenant of that engine is
classified into the tier. Each tier is one backend-only compose project `db-<tier>` in this
repo with one service per engine (`db-<tier>.mariadb`, `db-<tier>.mongo`) and its own
backend network, so a consumer can only reach the tier it belongs to. LeagueSphere prod
keeps its existing `leaguesphere.db` (leaguesphere repo) as the high tier's only instance.

**Tech Stack:** Ansible (`docker_service`, `restic`, `system_probe` roles; molecule),
Docker Compose, MariaDB 13.0 (`mariadb-dump`, `mariadb-backup`, `mariadb-binlog`),
Mongo 9.0 (`mongodump`), Postgres 15 (until removed), Renovate (docker-compose manager),
restic + systemd **user** timers, Prometheus Pushgateway probes, git-crypt for secrets.

---

## Verified baseline (2026-11-17/18, read from servy and the repo)

| Container | Image / version | Tenants | RAM now |
|---|---|---|---|
| `leaguesphere.db` | `mariadb:latest` → 13.0.2 | LS prod (+ binlog, `server_audit`, db-tunnel, db-access) | 96 MB |
| `leaguesphere_stage.mysql` | `mariadb:latest` → 13.0.2 | LS stage (holds restored prod copies) | 34 MB |
| `leaguesphere-demo.mysql` | `mariadb:latest` → 13.0.2 | LS demo (nightly schema drop/recreate) | 20 MB |
| `moodle.db` | `mariadb:12.3` → 12.3.3 | Moodle / OFFD, 1.6 GB dataset | 309 MB |
| `photoprism.mariadb` | `mariadb:lts` → 12.3.3, **watchtower `scope=prod`** | PhotoPrism (private photos) | 143 MB |
| `bnb-office.db` | `mariadb:12.3` → 12.3.3 | bnb office (another company) | 13 MB |
| `shared.db` | `postgres:15` → 15.20, **watchtower `scope=prod`**, PGDATA on block storage | Firefly III (`finance/`) | 16 MB |
| `shared.mongo` | `mongo:9.0.8`, **watchtower `scope=prod`** | leagues-finance (0.8 MB), queen (1.1 MB), dontforget (1.3 MB) | 57 MB (with redis) |
| `shared.redis` | `valkey:9-alpine` | cache | (above) |

Supporting surface and hazards found:

- **5 dump/backup user timers** (`mariadb-backup-ls`, `restic-backup-ls-db`, `moodle-dump`,
  `restic-backup-moodle-db`, `docker-bnb-office-dump`), declared in three places:
  `restic/tasks/backup.yml`, `roles/user/tasks/docker_extras.yml:189`.
- **2 restic DB repos** (`db` for LS, `moodle-db`), seeds `vars/.restic_password_ls_db` /
  `.restic_password_moodle` (`roles/restic/defaults/main.yml`).
- **3 migration/restore roles**: `ls_db_sync`, `ls_db_migrate`, `ls_stage_restore`.
- **Two things deliver database updates today, neither on a schedule anyone chose.**
  Renovate automerges every minor+patch update (`renovate.json`), so `mariadb:12.3`,
  `postgres:15` and `mongo:9.0.8` can move a minor or a patch unattended at the next deploy;
  and watchtower's prod scope polls every 2 h, so `mariadb:latest` (LS prod/stage/demo) and
  `mariadb:lts` (PhotoPrism) jump to whatever upstream re-points the channel alias to —
  including a new minor, mid-day, with no window.
- **Apps holding database root:** leagues-finance and queen connect to mongo as root
  (`templates/leagues-finance/.env.j2:10-12`, `templates/finance/queen.env.j2:4`,
  `authSource=admin`); `leaguesphere_stage.db-access` and `ls_db_sync` use MariaDB root.
  Only dontforget already has a db-scoped mongo user (`shared_mongo_users`,
  `plays/user.yml:501`).
- **Docker `data-root` is on network block storage** (`/mnt/servy-docker-data`, ~123 MB/s,
  `history/2026-11-05_servy-docker-volume.md`): a named volume lands there. Moodle and
  PhotoPrism datadirs are bind mounts on `/` (gitignored: `moodle/data/`,
  `photoprism/database/`). `/` has ~30 GB free.
- `docker_backend_services` (`vars/default.yml:73`) is the probe list for backend-only
  projects; today it holds only `shared`.

## The four tiers

| Tier | Membership rule | External access | Backups | Upgrade order |
|---|---|---|---|---|
| **high** | LeagueSphere core production — data that needs PITR and audit (LS prod) | db-tunnel/db-access for named DBA accounts | physical (`mariadb-backup`) + binlog PITR + `server_audit` | last |
| **nonprod** | Our own non-production data: may break, be reset, receive prod restores (LS stage, demo) | db-tunnel + db-access; db-access holds a **scoped admin**, never tier root | logical, daily; one restic repo for the tier | **first (canary)** |
| **business** | Business production data that is not LS core — other organisations' (Moodle/OFFD, bnb) and our own business apps (leagues-finance, queen) | none | logical, cadence per tenant; **one restic repo per tenant** (hand-over / deletion without rewriting a shared repo) | after nonprod |
| **private** | Personal data of the operator (PhotoPrism, Firefly, dontforget) | none | logical, daily; one restic repo for the tier | after nonprod |

Rules that hold in every tier:

- One database + one app user per tenant, privileges scoped to it (`ALL ON <db>.*` at
  most). **Apps, sidecars and sync jobs never hold root.**
- **Existing database names are kept** when a tenant moves; only the host changes.
- Datadirs are **bind mounts on `/`** at `db-<tier>/data/<engine>` (gitignored), never
  named volumes (D13).
- One backend network per tier (`db_<tier>_backend`); a consumer joins only its tier's.
- Tags pin the **minor** and float the patch (`mariadb:13.0`, `mariadb:12.3`, `postgres:15`,
  `mongo:9.0`), written literally in each committed compose file (D1). `:latest` and `:lts`
  are banned — both re-point across minors.
- Database servers carry the **`db` watchtower scope**, which delivers patches in a fixed
  daily window (D15), health-check gated with automatic rollback.
- No published port except the nonprod/high tunnels on `127.0.0.1`
  (`check_published_ports.py` already rejects all-interface binds).
- An instance exists only when a tenant of that engine is classified into the tier.

## Target topology

| Tier | Instance | Tenants | Profile |
|---|---|---|---|
| high | `leaguesphere.db` (unchanged container) | LS prod | 512m–1g, binlog PITR, `server_audit`, `mariadb-backup`, tunnel |
| nonprod | **`db-nonprod.mariadb`** | LS stage, LS demo | 512m, 128M pool, utf8mb4_unicode_ci |
| business | **`db-business.mariadb`** | Moodle (OFFD), bnb office | 1.25g, 384M pool, utf8mb4_unicode_ci, default isolation (REPEATABLE READ) |
| business | **`db-business.mongo`** | leagues-finance, queen | 384m, `--wiredTigerCacheSizeGB 0.25` |
| private | **`db-private.mariadb`** | PhotoPrism; Firefly after Phase 9 | 512m, 128M pool, PhotoPrism's server flags |
| private | **`db-private.mongo`** | dontforget | 384m, `--wiredTigerCacheSizeGB 0.25` |
| private | `shared.db` (postgres, **temporary**) | Firefly | unchanged until Phase 9, then removed |
| — | `shared.redis` | cache | stays in `shared` — not a database of record, not tiered |

| Engine | Today | End state |
|---|---|---|
| MariaDB | 6 servers, 3 versions | 4 servers, 1 line |
| Mongo | 1, untiered, 2 of 3 apps on root | 2, tiered, no app on root |
| Postgres | 1 | 0 |

The only remaining lever to reach one Mongo is dontforget (sole tenant of
`db-private.mongo`, 1.3 MB): moving it to business breaks the private/business rule, moving
it to SQLite is an app change in the dontforget repo. Neither is in this plan.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **One version line per engine; the tag pins the minor and floats the patch** (`mariadb:13.0`, `mariadb:12.3`, `postgres:15`, `mongo:9.0`) | Patches are delivered by watchtower (D15), and watchtower can only pull a tag that is re-pointed on release — so the tag must name the minor and let the patch move. `:latest` and `:lts` are banned because both re-point across minors (`latest` already put 13.0.2 on prod unannounced). Renovate does not touch these tags for patches; it only proposes a minor/major change as a reviewed PR. MariaDB line = **13.0 now, hop later**: LS prod's datadir is already 13.0; 13.0 is a *rolling* release (community support ends ~2026-12-31 per endoflife trackers — confirm on mariadb.org before scheduling Phase 10), 12.3 is the current LTS (to 2029-06). Owner rejected a 12.3 fleet and a permanent mix; the only tolerated mix is the migration-time one in D14. |
| D2 | **Tier is the primary axis, engine the secondary** | A new tenant of any engine is a row in `db_tenants.yml`, not a new rule. |
| D3 | **Four tiers: high / nonprod / business / private** | Lifecycle (prod vs non-prod) × owner (LS core / business / personal). Rejected: Moodle with stage+demo (stage has the external `dbeaver_stage` tunnel and takes full prod restores); business and private on one server (mixes business with personal data and forces PhotoPrism's server-wide flags on bnb). **Deliberate reversal:** the earlier rule "Moodle, PhotoPrism and bnb never share" is replaced by "business tenants share with each other, never with private or nonprod". |
| D4 | **Separation by scoped users, per-tier networks and per-tenant dumps, not one server per tenant** | A dedicated server adds no protection against host root and, with D1, no independent upgrades. The crash domain per tier is accepted. No contractual requirement for physical separation exists for OFFD or bnb. |
| D5 | **Every MariaDB server sets charset/collation explicitly** (`utf8mb4` / `utf8mb4_unicode_ci`) | 13.0 changed the default collation; otherwise new tables differ from existing ones and joins fail with `Illegal mix of collations`. |
| D6 | **Each tier is a backend-only compose project `db-<tier>` in this repo**; LS prod stays `leaguesphere.db` in the leaguesphere repo; there is no `db-high` project | Same conventions as `shared`. Moving the prod DB container buys nothing and risks prod. `shared` ends as `redis` only. |
| D7 | **Postgres is removed last** (Phase 9: Firefly → `db-private.mariadb`, mechanism decided on a scratch instance — table-by-table `data only` load preferred, export/import only as a documented fallback) | Never pgloader against the *live* DB, and never an export/import cut-over that silently drops budgets, rules and piggies (see Phase 9's pre-check). `shared.db` is not re-homed first — that would move it twice. |
| D8 | **Drift is checked before anything restarts: a minor mismatch fails, a patch mismatch alerts** | The guard is a `pre_task` tagged `always`, so it runs on every deploy whatever the tag scope. It reads each server's **tag** from the compose file about to be applied (this repo plus the leaguesphere checkout on the host) and its **digest** from the running container, so it can fail *before* a restart rather than report afterwards. **Minor mismatch** among active servers (`13.0` vs `13.1`) **fails the play**. **Digest mismatch on the same tag** — the normal state for a few hours after a watchtower patch pull — only warns and pushes `db_version_drift{engine}=1` (Grafana alert after 24 h); failing on it would block routine deploys with no human in the loop, and the patch mix shares the datadir format. The only override, `-e db_version_guard_allow_drift=<engine>`, exists for the runs of a scheduled hop (Phase 10) and is named in the history entry. |
| D9 | **SQLite apps stay SQLite** | `devhub`, `waggle`, `opencode`: single-writer embedded DBs. |
| D10 | **Physical backups + PITR are high-tier-only** | `mariadb-backup`/binlog assume "the server is LS prod" (`ls_stage_restore` depends on it). |
| D11 | **Moves are logical dump/import onto a fresh server, never an in-place upgrade across a move** | The old datadir is never opened by the new server, so it is an untouched rollback. |
| D12 | **Per-user resource limits are the load guardrail** | `MAX_USER_CONNECTIONS` + `MAX_STATEMENT_TIME` per tenant user. No pooler. |
| D13 | **Datadirs are bind mounts on `/`** (`/home/cda/servyy-container/db-<tier>/data/<engine>`, gitignored) | Avoids landing the write-heaviest tenants on network block storage by accident. Entrypoint takes ownership — no `user:` override. |
| D14 | **Servers awaiting retirement float their own line and are excluded from the equality check** | `moodle.db`, `bnb-office.db`, `photoprism.mariadb` sit on `mariadb:12.3` (already the tag on the first two): they keep receiving 12.3 patches but **cannot cross to 13.x**, because the tag names the minor — the tag is the fence, no Renovate rule needed. `retiring: true` in `db_tenants.yml` keeps them out of the active-server equality check and makes the guard fail if one leaves the 12.3 line. |
| D15 | **Patches come from watchtower; minors and majors come from a reviewed PR** | A database patch is a same-line image refresh: the datadir format is unchanged, and the `openserbia/watchtower` fork is health-check gated — a new image that never reports healthy is rolled back automatically. So patches land unattended, but only in the **`db` scope**, whose schedule is a single daily window at 06:00, clear of the hourly dumps (:30/:40/:50), the 02:00–04:00 restic run and the 05:00 Firefly import. **Every server is in scope, including the high tier** (owner, 2026-11-18): patching would otherwise leave exactly the most critical database as the one with an unpatched window. Minor/major is *not* watchtower's job: Renovate proposes it, `dependencyDashboardApproval` gates it, and it is applied one tier per run (Phase 10). Renovate's patch updates are disabled for these packages, so it cannot replace a floating `13.0` with a concrete `13.0.3`. |
| D16 | **New DB restic repos share one seed** (`vars/.restic_password_db`) | Avoids five new controller-local seeds. Registered in `seed_guard.yml` and the Vaultwarden push like the others. Existing `ls_db` and `moodle` repos keep their seeds — no restic password change is needed. Hand-over of a business tenant is a restored dump, never the repo itself. |

## Non-goals

- Moving LS prod off `leaguesphere.db` or changing its backup model.
- Changing app schemas, ORM settings or the leaguesphere Django `MYSQL_*` contract.
- Moving SQLite apps (D9) or tiering valkey.
- Moving dontforget off Mongo.

---

## Phase 0 — Tag policy, watchtower patch window, drift guard (no data movement)

1. **Pin the minor, float the patch.** `moodle/docker-compose.yml:22` and
   `bnb-office/docker-compose.yml:17` already read `mariadb:12.3` — leave them;
   `photoprism/docker-compose.yml:153` `mariadb:lts` → `mariadb:12.3`;
   `shared/docker-compose.yml:77` stays `postgres:15`; `shared.mongo` → `mongo:9.0`
   (*only after Phase 1 step 0* — the tag change recreates that container too, see step 2).
   No `:latest`, no `:lts`, no exact patch pin anywhere: watchtower can only deliver a
   patch if the tag is re-pointed on release.
2. **A watchtower scope for databases.** Add `watchtower-db` to
   `portainer/docker-compose.yml` next to `watchtower-prod`/`-dev`:
   `openserbia/watchtower:latest`, `WATCHTOWER_SCOPE: db`, `WATCHTOWER_SCHEDULE: "0 0 6 * * *"`,
   `WATCHTOWER_CLEANUP: "true"`, `WATCHTOWER_HEALTH_CHECK_GATED: "true"`,
   `WATCHTOWER_HEALTH_CHECK_TIMEOUT: "2m"`, and the
   `com.centurylinklabs.watchtower.scope=db` label on the instance itself, as its two peers do.
   Move every database server's label from
   `com.centurylinklabs.watchtower.scope=prod` to `=db` (`shared.mongo`, `shared.db`,
   `photoprism.mariadb`; `moodle.db` and `bnb-office.db` have no label today and get `=db`),
   and give every `db-<tier>` service the same label as it is created.
   **`leaguesphere.db` is in scope too** — its label lives in the leaguesphere repo's
   `deployed/docker-compose.yaml`, so it rides that repo's PR together with its tag.
   Accepted consequence: the high tier restarts at 06:00 when a 13.0 patch appears, ~1–2 min,
   health-gated with automatic rollback. That keeps patching universal; a manual high tier
   would be the one server with an unpatched window.
   **A label change recreates the container**, so stagger these one server at a time, and move
   `shared.mongo`'s label **only after Phase 1 step 0 is merged** — recreating it before the
   volume-wipe block is removed is exactly the hazard that step exists to close.
   **06:00 is chosen, not arbitrary:** the hourly dumps fire at :30/:40/:50, restic runs
   02:00–04:00 and the Firefly import at 05:00 — a database restart must fit between them.
3. **Do NOT put `MARIADB_AUTO_UPGRADE` in `ls.env`** (incident 2026-11-18, `history/2026-11-18_ls-db-upgrade-flag-outage.md`).
   The prod `db` service shares `env_file: ls.env` with the app, so `MYSQL_HOST` is present in
   the **database** container's own environment; with the flag set, the entrypoint's
   `mariadb-upgrade` shells out to the `mysql` client, which dials `MYSQL_HOST` instead of the
   temporary socket-only server and aborts the start (`ERROR 2002 (HY000): Can't connect to
   server on 'leaguesphere.db'` → exit 1 → restart loop). It cost ~6.5 minutes of public
   downtime the first time `ls_app` ran it. Patch-level upgrades do not need it. If it is ever
   wanted again: give the `db` service its own env file, or override `MYSQL_HOST=localhost`
   inside that service. The `db-<tier>` servers are unaffected — their env files carry no
   `MYSQL_HOST`, so they keep `MARIADB_AUTO_UPGRADE=1`.
4. **Renovate rules** (`renovate.json`, `packageRules` after the existing automerge rule):
   - `matchPackageNames: ["mariadb", "mongo", "postgres"]`,
     `matchUpdateTypes: ["patch"]` → **`enabled: false`**. Watchtower owns patches, and
     Renovate must never replace the floating `13.0` with a concrete `13.0.3`.
   - same packages, `matchUpdateTypes: ["minor", "major"]` → `automerge: false`,
     `dependencyDashboardApproval: true`, `groupName` per engine.
5. **LeagueSphere repo** (separate PR; deployed by `ls_app` via git pull): the three server
   tags `deployed/docker-compose.yaml:112`, `docker-compose.staging.yaml:4`,
   `docker-compose.demo.yaml:4` → `mariadb:13.0`, **and the `db` watchtower label on the prod
   server block** (owner decision 2026-11-18: high tier is in scope); the db-access client
   sidecars (`docker-compose.yaml:177`, `docker-compose.staging.yaml:61`) to the same tag. Add
   the same "patches disabled, minors need approval" rule to that repo's `renovate.json`.
6. **Drift guard** `ansible/plays/tasks/db_version_guard.yml`, a `pre_task` of
   `plays/user.yml` tagged `always` (D8). Server list: static in Phase 0, `db_tenants.yml`
   from Phase 2. For each listed server it reads the `image:` **tag** from the compose file
   this run will apply (this repo after repo sync; for `leaguesphere.db` the leaguesphere
   checkout on the host) and the **digest** from the running container. Rules per engine:
   - active servers on different **minor tags** (`13.0` vs `13.1`) → **fail**, before any
     service task runs;
   - active servers on the same tag but different **digests** → warn + push
     `db_version_drift{engine}=1` (this is the normal state for a few hours after a
     watchtower pull, which is why the alert waits 24 h);
   - a `retiring: true` server not on its pinned line (`12.3`) → **fail**;
   - otherwise push `db_version_drift{engine}=0`.

   A post-deploy check compares the running digest with the tag's current digest and pushes
   the same metric, which catches a container that was not recreated. The Grafana rule fires
   on `db_version_drift > 0` for 24 h. Messages name both sides and point at
   `leaguesphere/deployed/docker-compose.yaml` when `leaguesphere.db` is the odd one out.
   Only listed servers are read — `db-access` containers are clients. Override:
   `-e db_version_guard_allow_drift=<engine>`, for Phase 10 runs only.

   **The guard is included in `plays/leaguesphere.yml` as well**, not only `plays/user.yml`:
   `leaguesphere.yml` is a separate play with only an enablement `pre_task`, so a
   `--tags ls.app` run would otherwise apply the bumped high-tier tag with no check at all —
   which is exactly the ordering Phase 10 depends on. The task is shared, not duplicated:
   `include_tasks` the same file from both plays.

**Verify** (servyy-test): every database server carries `scope=db` and none carries a
floating `latest`/`lts` tag; `docker inspect` shows one watchtower per scope; Renovate's
dashboard lists no database patch updates at all and any minor/major as awaiting approval;
set one compose to `mariadb:13.1` → `./servyy.sh`, `--tags docker` and
`--tags user.docker.monitor` all fail before a task restarts anything; simulate a patch by
pulling a re-tagged image into one server → `db_version_drift` reads 1 and the alert does not
fire before 24 h; a deliberately broken image in the `db` scope is rolled back by the
health-check gate.

**Rollback:** revert the tags and rules. No datadir is touched.

## Phase 1 — No app on database root (Mongo)

Independent of the tier moves and the cheapest security win, so it goes first.

0. **Disarm the volume wipe first.** `plays/user.yml` post_task "Remove corrupted mongo
   volume and restart if unhealthy" deletes `shared_mongo_data` — all three tenants — when
   `shared.mongo` is not `healthy` after 15 × 2 s. A recreated container stays `starting`
   for ~30 s (healthcheck `interval: 30s`, no `start_interval`), so any deploy that
   recreates it can trigger the wipe. Take a `mongodump --archive` of all three databases
   to restic, then replace the whole block (container removal, volume removal, restart)
   with a `fail` task that names the container and its health status. Add
   `start_interval: 2s` / `start_period: 30s` to the healthcheck.
1. Add `leagues_finance` and `queen` entries to `shared_mongo_users` (`readWrite` +
   `dbAdmin` on their own database only, like dontforget).
2. Switch `MONGO_URI` in `templates/leagues-finance/.env.j2:12` and
   `templates/finance/queen.env.j2:4` to those users (`authSource=<own db>`); drop the
   `MONGO_INITDB_ROOT_*` lines from the leagues-finance env. Verify both apps.
3. **Rotate the root password in the database, then in the var.**
   `MONGO_INITDB_ROOT_PASSWORD` applies only when a datadir is initialised, so changing
   `leagues_finance.mongo_root_password` alone changes nothing in mongo and breaks
   `shared_mongo_users`, which authenticates with it (`defaults/main.yml:27-28`). Order:
   `db.getSiblingDB('admin').changeUserPassword(...)` inside `shared.mongo`, then update
   the var in `secrets.yml` (git-crypt rule), then deploy `--tags user.docker.shared`.

**Verify:** both apps read data; `docker exec ... env` in either app shows no root
credential; the old root password is rejected and the new one is accepted by
`shared_mongo_users`; a forced recreate of `shared.mongo` leaves `shared_mongo_data` intact.

**Rollback:** steps 1–2: revert the two URIs (root still works). Step 3:
`changeUserPassword` back to the old value and revert the var.

## Phase 2 — Tenant inventory, `dbops`, `db_tier` role (no data movement)

1. **`ansible/plays/vars/db_tenants.yml`**, one row per tenant:
   `tenant, tier, engine, server, db, user, dump_schedule, dump_dir, restic_repo,
   max_user_connections, max_statement_time, retiring`. Seeded with the *current* placement;
   later phases only edit rows. The drift guard switches to this list.
2. **`dbops.sh`** (rendered by Ansible; MariaDB adapter now, Mongo adapter in Phase 8):
   `dump | restore | verify | shell | restore --from-physical` (high → nonprod only).
   - **Dump:** `--single-transaction --quick --routines --triggers --events
     --default-character-set=utf8mb4 --hex-blob`, one database per file, as a per-tier
     backup user (`SELECT, SHOW VIEW, TRIGGER, EVENT, LOCK TABLES`). Written to
     `<file>.partial` and renamed when complete, so a concurrent restic run never captures
     a half-written dump.
   - **Restore:** strips `DEFINER=` clauses from views, triggers and routines so a
     non-root tenant user can import; creates the database with D5 charset/collation.
   - **Verify:** compares source and target — table/view set from `information_schema`,
     exact `COUNT(*)` per table, `CHECKSUM TABLE` on the largest tables,
     routine/trigger/event counts, and no definer pointing at a user that does not exist on
     the target. Any mismatch fails the move.
3. **`ansible/plays/roles/db_tier/`**: tier → `{mem_limit, buffer pool, server flags,
   healthcheck cadence (30 s, history/2026-10-30_load-alert-tuning.md), network, dump
   default, restic scope, probe label}`. It **does not render compose files** —
   `db-<tier>/docker-compose.yml` is committed like `shared/docker-compose.yml` so Renovate
   sees the tag (D1). It renders the tier's env files (0600), creates per-tenant users with
   their D12 limits and the per-tier backup user, and absorbs `shared_mongo_users`. Each
   tier is its own invocation in `plays/user.yml`, tagged
   `[user.docker, user.docker.db-<tier>]`, so a single tier can be deployed alone
   (Phase 10 depends on this).
4. **Per-host enablement:** host var `db_tiers: [...]`, shaped like the existing
   `shared_services` / `finance_services` (`ansible/testing:33-34`), so servyy-test renders
   only the tiers it rehearses.
5. **`.gitignore`:** `db-*/data/`.
6. **Restic:** seed `vars/.restic_password_db` (D16), registered in `seed_guard.yml` and the
   Vaultwarden push.
7. **Molecule scenario** for `db_tier`: a tier with two MariaDB tenants — each user reaches
   only its own database; a tier without a mongo tenant has no `mongo:` service; a user of
   one tier cannot reach another tier's network.

**Verify:** `dbops dump` + `dbops verify` against every current server; molecule green on
servyy-test and in CI.

## Phase 3 — nonprod: LS stage + demo → `db-nonprod.mariadb`

1. Commit `db-nonprod/docker-compose.yml` (`mariadb:13.0`, 512m, 128M pool, D5 flags,
   watchtower scope `db`,
   `MARIADB_AUTO_UPGRADE=1`, network `db_nonprod_backend`, bind `data/mariadb`,
   `traefik.enable=false`); add `db-nonprod` to `docker_backend_services`.
2. **Secrets:** tier root + backup user + one user per existing stage/demo database in
   `secrets.yml`. Coordinate the git-crypt edit.
3. `dbops dump` from the old containers → `dbops restore` under the **same database
   names** → `dbops verify`.
4. **leaguesphere repo:** drop the `mysql:` service from `docker-compose.staging.yaml` /
   `docker-compose.demo.yaml`, point `MYSQL_HOST` at `db-nonprod.mariadb`
   (`MYSQL_DATABASE` unchanged), attach the app containers to `db_nonprod_backend`
   (`external: true`), remove the `mysql-conf` / `mysql-init` mounts. `MYSQL_HOST` lives in
   the git-crypt'd `secret_stage.yaml` / `secret_demo.yaml` — same coordination rule.
5. **db-tunnel:** grants for the minted `dbeaver_prod_<person>` and backup accounts move
   from the stage network's subnet (`172.26.x`, `ls_dbeaver_access/defaults/main.yml`) to
   `db_nonprod_backend`'s. The plain publish on `33062` disappears with the `mysql:`
   service — drop it from `dbeaver_stage_tunnel.local_ports` (DBeaver uses `33064`).
6. **db-access off root:** the reap loop (`ls-db-access-reap.sh.j2:24,67,147`) switches from
   container-env root to `ls_stage_access_admin`: `CREATE USER` (global; MariaDB has no
   narrower form), `SELECT ON mysql.user`, `ALL ON <stage db>.* WITH GRANT OPTION`. Residual
   (accepted): it can `DROP USER` any account on the nonprod tier.
7. **Demo reset:** `entrypoint.demo.sh` drops and recreates its database; its credential is
   the demo user with `ALL ON <demo db>.*`, never a server-wide account.
8. **`ls_db_sync`:** retarget from `{{ stage_container }}` (`ls_db_sync/tasks/timer.yml:35`,
   `templates/ls_db_sync.sh.j2:9,36`) to `db-nonprod.mariadb`, importing as the stage user
   via `dbops restore`; **fail if the target container does not exist**, so a resurrected
   `leaguesphere_stage.mysql` can never receive the sync.
9. **`ls_stage_restore`:** becomes `dbops restore <stage tenant> --from-physical <dir>`.

**Verify:** stage smoke test (login, a gameday page, a schedule page); forced demo reset
(`rm /app/.demo_last_reset` + `entrypoint.demo.sh`) then the demo loads; the next nightly
`ls_db_sync` completes against `db-nonprod.mariadb`; a physical-backup restore into stage
completes; a DBeaver login through the stage tunnel works and the minted account cannot
`USE` the demo database; no `server_audit`/binlog on `db-nonprod`.

**Rollback:** restore the `mysql:` blocks and `MYSQL_HOST`, start the old containers; their
volumes are kept for one week.

## Phase 4 — business: bnb office → `db-business.mariadb`

Smallest business tenant first; proves the tier before Moodle's 1.6 GB.

1. **Pre-flight:** `free -m` on servy (≈3 GB of 7.5 GB used at plan time); 1.25g replaces
   today's 1g + 512m ceilings.
2. Commit `db-business/docker-compose.yml` (`mariadb:13.0`, 1.25g, 384M pool, D5 flags,
   watchtower scope `db`,
   default isolation, network `db_business_backend`, bind `data/mariadb`); add it to
   `docker_backend_services`. Sized for Moodle so Phase 6 is not a resize.
3. Secrets: tier root + backup user + bnb user (existing `bnb_office.db_name`).
4. Stop `bnb-office.web`, `dbops dump` from `bnb-office.db` (12.3.x) → restore (13.0.x,
   same database name) → verify → collation check:
   ```sql
   SELECT table_name, table_collation FROM information_schema.tables
    WHERE table_schema = '<db>' AND table_collation NOT LIKE 'utf8mb4%';
   ```
5. The host is hardcoded today (`DB_HOSTNAME: ${COMPOSE_PROJECT_NAME}.db`,
   `bnb-office/docker-compose.yml:43`) and bnb also runs on servyy-test
   (`ansible/testing:24`). Introduce host var `bnb_office_db_host` (default
   `{{ project_name }}.db`), render it into the compose `.env`, override it on servy.
   Attach `bnb-office.web` to `db_business_backend`, drop the `db:` service, rewrite the
   header comment to reference this plan; set the D14 row to the new server.
6. Retire `docker-bnb-office-dump` (`docker_extras.yml:189-202`) — a `dbops dump` timer
   until Phase 7 wires the tier job.

**Verify:** the invoice-number counter continues without a gap (read the counter row
before/after, or one test invoice cancelled per bnb's procedure); site loads; a dump lands
in its directory and its own restic repo.

**Rollback:** point the app back at the old `db:` service; its datadir is untouched (D11).

## Phase 5 — private: PhotoPrism → `db-private.mariadb`

1. Commit `db-private/docker-compose.yml` (`mariadb:13.0`, 512m, 128M pool, watchtower scope
   `db`, network
   `db_private_backend`, bind `data/mariadb`) with PhotoPrism's server flags:
   `--transaction-isolation=READ-COMMITTED --max-connections=512
   --innodb-rollback-on-timeout=OFF --innodb-lock-wait-timeout=120` plus D5 flags. Its
   `seccomp`/`apparmor:unconfined` and `user: UID:GID` existed only for the old bind and are
   not carried over. Add `db-private` to `docker_backend_services`.
2. Secrets: tier root + backup user + `photoprism` user (D12 limit sized for 512).
3. Pause the `docker-photo-index` timer, stop `photoprism.photoprism`, dump → restore →
   verify, point PhotoPrism at `db-private.mariadb` on `db_private_backend`, drop the
   `mariadb:` service. Keep `./database` untouched for a week.

**Verify:** library and albums load; a manual index run completes; the re-enabled timer's
next run completes. PhotoPrism's DB had no memory limit before: watch
`container_memory_near_limit` on `db-private.mariadb` for a week, and again after Phase 9
adds Firefly.

**Rollback:** restore the `mariadb:` service; `./database` was never opened by the new server.

## Phase 6 — business: Moodle → `db-business.mariadb`

1. **Rehearse on servyy-test first** (`vars/default.yml:242`): dump → import → verify →
   login, one course page. The recorded dump/import durations set the maintenance window.
2. Secrets: Moodle user (`MAX_STATEMENT_TIME` generous enough for Moodle's cron).
3. Introduce inventory var `moodle_db_host` (default
   `{{ project_name | default(service_name) }}.db`) in
   `templates/moodle.app.env.j2:25`; servyy-test keeps its local `moodle.db` until its
   rehearsal is switched.
4. Maintenance mode on, disable `moodle-dump`, dump → restore (same database name) →
   verify → collation check → set `moodle_db_host` on servy, attach the app to
   `db_business_backend`, redeploy (the image regenerates `config.php` from env — never
   hand-edit) → maintenance off.
5. Drop the `db:` service; keep `${MOODLE_DATA_ROOT}/mariadb` for a week. The hourly
   cadence moves to Moodle's `db_tenants.yml` row; `moodle-db` becomes its per-tenant repo.

**Verify:** login, one course page, cron clean; hourly dump lands and is snapshotted. For a
week watch `container_memory_near_limit` on `db-business.mariadb` (primary signal) and the
buffer-pool hit rate (secondary).

**Rollback:** maintenance on, revert `moodle_db_host`, redeploy, start `moodle.db` on the
old datadir.

## Phase 7 — One backup and probe wiring; retire the old surface

1. **Timers:** one `dbops-dump@<tier>` user timer per tier, hourly; `dbops` decides per
   tenant whether a dump is due from `dump_schedule`. High keeps its two jobs
   (`mariadb-backup-ls` + `restic-backup-ls-db`) on one timer through `dbops` — end state
   **5 jobs on 4 timers**.
2. **Restic:** one repo per business tenant, one per other tier (D16 seed for new repos).
3. **Probes:** one dump-freshness check per tenant generated from the inventory, replacing
   the per-repo wiring in `system_probe` + `vars/restic.yml`.
4. **Retire** `moodle_dump.sh.j2`, `moodle-dump`, `restic-backup-moodle-db`, the bnb
   one-liner and the old `ls_stage_restore` task list — one commit, timers disabled first,
   after a week of green.
5. **Delete the old datadirs/volumes** (`leaguesphere_stage`, `leaguesphere-demo`,
   `bnb-office`, `photoprism/database`, `${MOODLE_DATA_ROOT}/mariadb`) one week after each
   move, with a final dump of each in restic; remove the retired rows (D14 ends here).

**Verify:** `dbops verify` for every tenant; one scratch restore per tier into a throwaway
database; `systemctl --user list-timers` shows one dump timer per tier; a deliberately stale
dump trips its freshness probe.

## Phase 8 — Mongo into the tiers

Classification: leagues-finance and queen → **business**, dontforget → **private**. (Owner:
leagues-finance and queen may go to business or high, whichever needs fewer databases. Both
give two mongos; business reuses `db-business` and needs no replica set, keyfile or oplog
dumps, high would need a new `db-high` project.)

> **Done 2026-11-19 (WP-9, branch `db-tier/wp9-mongo-tiers`).** `db-business.mongo` and
> `db-private.mongo` exist with their own `mongo:9.0` service, 384m, `0.25` cache, bind
> datadir and `db` watchtower scope; each tenant has a db-scoped user created by
> `roles/db_tier` from the inventory; the three apps were cut over after an exact
> per-collection/index copy proof; `shared.mongo` is stopped (volume kept as the rollback) and
> `shared/docker-compose.yml` no longer defines it. Measurements:
> `history/2026-11-19_db-tier-wp9-mongo-tiers.md`.

1. Mongo adapter for `dbops` (`mongodump`/`mongorestore` per database, same `.partial`
   rename and verify-by-counts).
2. **`db-business.mongo`:** add a `mongo:` service (`mongo:9.0`, 384m,
   watchtower scope `db`,
   `--wiredTigerCacheSizeGB 0.25`, `db_business_backend`, bind `data/mongo`) to
   `db-business/docker-compose.yml`. Move leagues-finance and queen (pattern:
   `dontforget_mongo_migrate.yml`); their scoped users from Phase 1 are recreated by
   `db_tier`. Point URIs at `db-business.mongo`, swap `shared_backend` for
   `db_business_backend`; leagues-finance keeps `leaguesphere_database` for its LS reads.
   Each gets its own restic repo.
3. **`db-private.mongo`:** same in `db-private` for dontforget.
4. **Retire `shared.mongo`** after a week of green: the service, the `shared_mongo_users`
   invocation, the remaining `post_tasks` naming `shared.mongo` (`plays/user.yml:741+`; the
   wipe itself was removed in Phase 1), and `shared_mongo_data` after a final dump is in
   restic.

**Verify:** each app reads its data; a user of one tier cannot authenticate against the
other tier's mongo; each tenant's dump and freshness probe are green.

## Phase 9 — Retire Postgres

**Pre-check — do this before scheduling the cut-over.** `firefly-iii:export-data` writes one
CSV per entity (transactions, accounts, budgets, categories, tags, recurring, rules,
subscriptions, piggies), but the **data-importer only recreates transactions**. Budget
amounts, rules, piggy banks, subscriptions and recurring transactions have no import path
from those files, so a plain export/import cut-over silently loses configuration that was
built up over time. Decide the mechanism on evidence, not by preference:

1. **Preferred: table-by-table load into a fresh schema.** Restore the latest `pg_dump` into
   a throwaway postgres, start a fresh Firefly against `db-private.mariadb` so its migrations
   create the correct MariaDB schema, then load `data only` (pgloader or a typed copy) table
   by table. This is **not** "pgloader against the live DB" — production is never touched —
   and it carries every table, including the ones export/import cannot express.
2. **Gate on the scratch instance:** transaction count, account count, budget count, rule
   count, piggy count and the current balances for each account must match production before
   production is touched. Any mismatch stops the phase.
3. Fall back to export/import only if step 1 proves impractical, and then write down exactly
   which objects will be re-created by hand, with that list in the phase's history entry.
4. Switch Firefly's DB settings — four in `finance/docker-compose.yml`: `DB_CONNECTION`
   `pgsql`→`mysql` (`:14`), `DB_HOST` (`:16`), `DB_PORT` 5432→3306 (`:17`), `DB_USERNAME`
   (`:19`); `DB_DATABASE` (`:18`) stays `firefly`. The password is **not** in that file — it
   is `DB_PASSWORD` in `templates/finance/.env.j2:3`. Attach `firefly` to
   `db_private_backend`. Keep the postgres data for a month.
5. Cleanup, one commit after that month: delete the `db:` service
   (`shared/docker-compose.yml:74-96`); delete `${DOCKER_DATA_ROOT}/finance/db` after a final
   `pg_dump` is in restic; remove `POSTGRES_*` from `shared.env` (template + `secrets.yml`)
   **and** `POSTGRES_PASSWORD` from `templates/finance/.env.j2:4`, which then has no consumer;
   remove `shared.db` from `db_tenants.yml` and `postgres` from the Renovate rules.
   `docker_backend_services` keeps `shared` (redis only).

**Verify:** Firefly loads accounts and the last month's transactions; the daily import job
runs; the counts from step 2 still match; the month's postgres snapshot is still restorable.

## Phase 10 (scheduled, recurring) — MariaDB version hop

13.0 stops receiving fixes around 2026-12-31 (confirm on mariadb.org). Forward upgrades are
supported in place, so a hop does not use D11's dump/import.

1. **This repo first, leaguesphere last.** The change is the **minor tag** (`mariadb:13.0` →
   `mariadb:13.1`) in the compose files — a Renovate minor PR, approval-gated by D15; a
   patch inside a line needs no PR at all, watchtower pulls it in the `db` window. Approve the
   grouped PR here first; it moves the three tier files. The leaguesphere PR
   (`deployed/docker-compose.yaml`, i.e. `leaguesphere.db`) is approved only after step 2 has
   finished, because any LS deploy applies it — merging it first would upgrade the high tier
   first. Until the next LTS exists this is rolling → rolling; switch to the first LTS of the
   13 line once released.
2. **One tier per run, in order:** `--tags user.docker.db-nonprod`, then
   `user.docker.db-private`, then `user.docker.db-business`, each preceded by `dbops dump`
   of every tenant on that server and followed by its phase smoke test. Each of these runs
   passes `-e db_version_guard_allow_drift=mariadb` (D8). No untagged `./servyy.sh` runs
   during the hop — it would apply every bumped file at once. Then merge the leaguesphere
   PR and deploy LS (high, last). `MARIADB_AUTO_UPGRADE=1` runs `mariadb-upgrade` on each
   **tier** server. The **high tier carries no such flag** (Phase 0 step 3: it would break the
   entrypoint through `MYSQL_HOST`), so its hop needs a deliberate `mariadb-upgrade` inside a
   maintenance window, with a fresh `mariadb-backup` full taken first.
3. **High:** fresh `mariadb-backup` full right after the upgrade. Physical backups are bound
   to the server version — keep the previous image pullable until its backups age out.
4. **Never start a hop in the middle of a Phase 3–6 move.** If EOL lands mid-move, finish
   the move first.

---

## What this buys

| Signal | Today | End state |
|---|---|---|
| MariaDB servers / versions | 6 / 3 | 4 / 1 line |
| Mongo servers | 1, untiered, 2 of 3 apps on root | 2, tiered, no app on root |
| Postgres servers | 1 | 0 |
| Floating tags / unattended minor on DB servers | 3 `latest`/`lts` + 2h poll | 0 floating lines; patches via the `db` scope only |
| Database patch delivery | uneven: `12.3` floats, `lts`/`latest` jump lines, two servers have no label | watchtower `db` scope, daily 06:00, health-gated rollback |
| Unattended DB minor/major upgrades via Renovate | possible | impossible (approval only) |
| Dump/backup jobs | 5 jobs on 5 timers, 3 places | 5 jobs on 4 timers, one inventory |
| Bespoke dump scripts / restore procedures | 2 / 3 roles | 1 tool (`dbops`) |
| Where a new database goes | new container + secret + timer | a row in `db_tenants.yml` |

## Risks

| Risk | Mitigation |
|---|---|
| A database patch pull restarts a server mid-dump | D15: dedicated `db` scope, one daily window at 06:00, clear of the :30/:40/:50 dumps, the 02:00–04:00 restic run and the 05:00 import; `dbops` writes `.partial` and renames |
| A bad database patch image is pulled | watchtower health-check gating rolls back to the previous image after 2m; `db_version_drift` fires while servers differ |
| A database minor or major lands unattended | the tag names the minor, so watchtower cannot cross one; Renovate minors are approval-gated (D15) |
| A 12.3 server gets a 13.x bump before its move | D14: the tag names the minor (`mariadb:12.3`); `retiring: true` makes the guard fail if it leaves the 12.3 line |
| A mongo patch pull breaks the daemon as it did on 2026-11-03 | WP-1 closes the wipe path first; the health-check gate rolls the image back and `db_version_drift` stays 1 until fixed |
| A mixed version line is applied before the guard notices | D8: `pre_task`, tag `always`, reads the compose tag and the running digest, included in **both** `user.yml` and `leaguesphere.yml`; a minor mismatch fails before any restart |
| A watchtower patch leaves servers on different digests for a while | D8: a digest mismatch only warns and alerts after 24 h — the pull completes across the fleet within one window |
| A version hop upgrades LS prod first | Phase 10: this repo tier by tier, leaguesphere PR last |
| A deploy recreating `shared.mongo` wipes all mongo data | Phase 1 step 0: dump, wipe replaced by `fail`, healthcheck `start_interval` |
| Mongo root rotation changes nothing or locks out `shared_mongo_users` | Phase 1 step 3: `changeUserPassword` first, var second |
| One crash/OOM takes down a tier | Per-tier `mem_limit`, D12 limits; accepted (D4) |
| Moodle evicts bnb's pages / business runs out of memory | `container_memory_near_limit` primary, hit rate secondary; raise limits before splitting |
| Restore as a non-root user fails on DEFINER | `dbops restore` strips definers; `verify` checks them |
| A renamed database breaks app config or sync jobs | Database names are kept on every move |
| A sidecar or sync job keeps root on a shared server | Phase 1 (mongo), Phase 3 steps 6–8 (db-access, `ls_db_sync`) |
| Restic captures a half-written dump | `.partial` + rename in `dbops dump` |
| A new datadir lands on block storage | D13 bind mounts on `/` |
| Mixed collations after moving to 13.0 | D5 flags; collation check after each import |
| Consumer on the wrong tier's network | Per-tier networks; molecule asserts isolation |
| git-crypt secrets edited concurrently | Secret edits only when no other session is active |
| New restic seeds exist only on one controller | D16: one shared new seed, guarded and pushed to Vaultwarden |
| The Firefly cut-over drops budgets, rules or piggies | Phase 9 pre-check + count gate on a scratch instance before production is touched |
| A tier becomes a dumping ground | Membership rules: LS core → high, ours-to-break → nonprod, business data (ours or others') → business, personal → private |

## Decision log (2026-11-17/18)

- Four tiers high / nonprod / business / private; business tenants share a server (D3).
- MariaDB: 13.0 now, hop later; no permanent version mix (D1, Phase 10).
- Stage db-access keeps a scoped admin; `DROP USER` residual accepted (Phase 3 step 6).
- No contractual requirement for physical separation for OFFD or bnb (D4).
- Mongo: leagues-finance and queen → business, dontforget → private (Phase 8).
- Postgres: kept until Firefly moves, then removed (D7, Phase 9).

## History entry

After each phase, append to `history/<date>_db-tier-topology.md`: tier membership, version
pins and guard results, per move the dump/import durations and `dbops verify` output, the
collation check, what was retired (timers, scripts, datadirs), and for Phases 8–10 the mongo
moves, the Firefly cut-over and each version hop.
