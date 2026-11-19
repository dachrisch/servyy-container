# Database tier programme — close-out (2026-11-19)

Started 2026-11-18, closed 2026-11-19 after ~24 h of continuous work. This entry is the
single place to read what the programme set out to do, what it actually delivered, what it
deliberately did not do, and what is parked with a date.

Design and package plans (`docs/plans/2026-11-17_db-tier-topology.md`,
`docs/plans/2026-11-18_db-tier-work-packages.md`) were removed on 2026-11-19 and live in git
history; the tiers, decisions D1–D16 and the WP-11 runbook are kept under *Design reference*
at the end. Per-phase evidence lives in the dated `history/` entries this one links.

## The goal, restated

Six per-application MariaDB servers, one untiered MongoDB and an accidental PostgreSQL
became: **four MariaDB servers on one version line, plus two tiered mongos, and no
Postgres.** Organised by *whose data it is* (high / nonprod / business / private), with one
tenant inventory (`ansible/plays/vars/db_tenants.yml`), one dump/restore/verify tool
(`dbops`), one backup layer (restic, inventory-driven) and one alerting layer (name-free
rules driven by the probes).

## Final state, measured 2026-11-19 18:00Z

| | |
|---|---|
| MariaDB servers | 4 — `leaguesphere.db` (high), `db-nonprod`, `db-business`, `db-private`, **all `mariadb:13.0`** |
| Mongo servers | 2 — `db-business.mongo` (leagues_finance, queen), `db-private.mongo` (dontforget) |
| Postgres | **none running** — `shared.db` stopped, 69 MB datadir kept until 2026-12-19 |
| Untiered leftovers | `shared.mongo` stopped (rollback until 2026-11-26); the `shared` project is `redis` only |
| `db_version_drift` | **0 / 0 / 0** (mariadb / mongo / postgres) |
| Containers | 52 running, 0 failed user units |
| Disk | `/` 65%, Docker data volume 80% (10.7 GB of drill volumes reclaimed during the run) |

### Backups

* **12 restic repos**, all inventory-generated; **7 tenants** publish a dump-age series
  (the 8th, `moodle`, cannot: its dump dir is `0750 root:root` and the probe is an
  unprivileged user timer — covered indirectly by the `moodle-db` stale-source guard).
* Dumps now run from **two tier units** (`db-backup@business`, `db-backup@private`) instead
  of eight per-tenant timers; `dbops dump-due` decides from the row, and the wrapper fails
  if a tenant root holds anything but `new/` and `current/`.
* **High tier PITR**: hourly physical set + a 5-minute binlog tail into `ls-binlog`
  (`--keep-within 2d`, paired with `expire_logs_days=2`). Drilled to a chosen instant
  between backups: 13 comparisons across 8 tables, **RTO 8.8–10.0 s**.
* **8/8 restore drills green**, measured restore times: dontforget 19.3 s, queen 19.0 s,
  leagues_finance 20.3 s, bnb_office 34.9 s, firefly 58.3 s, leaguesphere 95.8 s,
  photoprism 109.4 s, moodle 1 566.6 s (10.37 M rows / 497 tables).
  Cadence: weekly (leaguesphere, moodle), monthly (the rest), none (nonprod).

### Alerting

57 Grafana rules, all `health=ok`, **none firing** at close. The backup/drill rules carry no
tenant, repo or threshold literal — the probes publish the policy
(`restic_snapshot_threshold_seconds`, `db_dump_threshold_seconds`, `db_dump_severity`,
`db_restore_drill_threshold_seconds`, `system_log_threshold_seconds`), so a new tenant is a
row, never an edit. Four drill rules exist including `db_restore_drill_probe_stale`, because
a dead probe freezes every age and would look like a healthy fleet.

## What it cost

One planned 40-minute LeagueSphere maintenance window (Moodle's move), of which ~6.5 minutes
were an unplanned outage caused by a `MARIADB_AUTO_UPGRADE` flag colliding with an app env
file (`history/2026-11-18_ls-db-upgrade-flag-outage.md`). Otherwise: restarts of
single-purpose containers, seconds each, at points the owner approved in advance.

## The defects were the deliverable

The migration exposed a consistent failure mode — **silent no-ops**: something reported
success while doing nothing. Every one is now fixed, tested and commented where a future
reader would otherwise repeat it:

| Class | Examples |
|---|---|
| A dump that never wrote | bnb's one-liner wrote into a directory nothing read; a bare `dbops dump` filled a tenant root |
| A guard blind under `--check` | `db_version_guard` compared an empty list in check mode |
| A rule that could never fire | `.grafana` cannot map `-1` to "not met", so `< 0` never paged (`< bool 0` now) |
| A verification that agreed with itself | `dbops verify --against` ignored its server argument and compared live with live |
| A probe reading the wrong sample | `restic snapshots --latest 1` returns one entry per (host, paths) *group*; a stray `localhost` snapshot dominated the age |
| A deploy that loads nothing | a monitor-tag deploy restarted Grafana but never synced the host clone |
| A readiness probe that races init | MariaDB/Postgres/Mongo images all run a **temporary init server**; MariaDB's answers on the same socket with `@@port = 0` |
| A credential that regenerates | `lookup('password')` seeds silently generated new tier root passwords in a fresh clone |
| A file written wholesale | `restic.init` templated `~/.ssh/config` and deleted the host's GitHub deploy-key block |

Two policies came out of these and are now enforced:

1. **Never let a probe answer a question it cannot ask.** `-1` is data.
2. **A wrong value must fail before the change, not after.** `db_tier`'s root-password guard
   fails the deploy with the server untouched; the deploy-key guard refuses to overwrite a
   differing host key; the drill guard fails a drill that leaves a volume behind.

## The three folded-in packages

| WP | Outcome |
|---|---|
| **WP-12** | **done** — `moodle.moodle` carries `io.portainer.accesscontrol.teams=leaguesphere`; verified through Portainer's own API (`ResourceControl` + `TeamAccesses`, the same shape `leaguesphere.app` has). The recreate cost ~6 minutes of `offd.de` downtime, not seconds, because a fresh worktree regenerated the app seeds — the incident that produced the seed guard above |
| **WP-13** | **done** — the `searxng.valkey` sidecar, its volume and network removed after confirming `dbsize=0` and nothing else attached; `search.lehel.xyz` 200, caches SQLite as they always were |
| **WP-14** | **done 2026-11-19** — graphify retired from the container role and from codey: the skill list entry plus a retired-skills pruning task, three `startup.sh` blocks, `install-graphify.sh`, `PYTHONPATH`, and `/root/.graphify-pkgs` (141 MiB freed on the container volume). setup-home `5b917d5` removed the canonical skill tree in the same change, because it is the `copy` source for that list. Verified on codey: no binary, no import, no skill dir, healthy, `code.lehel.xyz` 200. It ran last for the reason its plan gave — a quiet tree |

## Deliberately not done

| Item | Why | When to revisit |
|---|---|---|
| **WP-11 version hop** | `mariadb` has only `13.1-rc`/`13.1.1-rc` — no stable target | when 13.1 ships GA; runbook under *Design reference* below, high tier last |
| **R9 Moodle on `dbops`** | `db_tenants.yml` forbids converging inside Moodle's WP-7b rollback window | **after 2026-11-25** |
| **R10's Moodle part** | follows R9 | after R9 |
| Moodle dump-age series | the probe cannot `stat()` a `0750 root:root` path; a row would page `-1` forever | if a root-run probe or an ACL is added |
| `shared.mongo` deletion | rollback for WP-9 | **on/after 2026-11-26**, checklist in `history/2026-11-19_db-tier-wp9-mongo-tiers.md` |
| `shared.db` deletion | rollback for WP-10 | **on/after 2026-12-19**, 8-step checklist in `history/2026-11-19_db-tier-wp10-postgres.md` |
| Old datadirs (moodle, photoprism, stage, demo) | rollback is now datadir-based, not `docker start` | after the rollback weeks; the containers are already gone (nightly prune, owner decision 2026-11-19) |

## Resuming after the break

1. `cd /home/cda/dev/infrastructure/container && git pull` — **always deploy from this
   checkout**: the tier root passwords are literal in `secrets.yml` and the deploy-key seed
   is machine-local; a clone fails the root guard by design.
2. Targeted deploys only (`--tags user.docker.db-<tier>`, `user.restic`, `system.probe`,
   `restore.drill`, `user.repo` when files must reach the host). The full playbook exceeds
   30 minutes and was never needed.
3. Before touching a database: `dbops verify <tenant>` and a drill. Before deleting
   anything: read the tenant row's own comment — most of them name the trap.
4. The two dated deletions above are the only work with a deadline.

## Files worth knowing

* `ansible/plays/vars/db_tenants.yml` — the single source of truth; each row carries its own
  why-nots.
* `ansible/plays/vars/secrets.yml` — literal tier root passwords (encrypted), with the
  regeneration incident written above them.
* `ansible/plays/roles/db_tier/` — tier role, `dbops`, guards.
* `ansible/plays/roles/restic/` — backup, dumps, probes, tier units.
* `ansible/plays/roles/restore_drill/` — recurring drills, evidence, metrics.
* `monitor/provisioning/alerting/alert-rules.yml` — every rule, with the reasoning inline.
* `history/2026-11-19_db-restore-drills.md` — machine-written drill evidence.

## Design reference (kept from the removed plan)

The plan `docs/plans/2026-11-17_db-tier-topology.md` was removed on 2026-11-19 once the
programme closed (it stays in git history). Code comments cite its decision numbers (D1–D16)
and the WP-11 runbook is still future work, so those sections are kept here verbatim.

### The four tiers

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

### Target topology

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

### Decisions

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

### Phase 10 (scheduled, recurring) — MariaDB version hop

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
