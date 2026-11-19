# Database tier programme — close-out (2026-11-19)

Started 2026-11-18, closed 2026-11-19 after ~24 h of continuous work. This entry is the
single place to read what the programme set out to do, what it actually delivered, what it
deliberately did not do, and what is parked with a date.

Design: `docs/plans/2026-11-17_db-tier-topology.md`. Packages and runbooks:
`docs/plans/2026-11-18_db-tier-work-packages.md`. Per-phase evidence lives in the dated
`history/` entries this one links.

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
| **WP-14** | **not started** — its own plan requires a quiet tree and warns against staging unrelated work; it is the last thing on this list for exactly that reason |

## Deliberately not done

| Item | Why | When to revisit |
|---|---|---|
| **WP-11 version hop** | `mariadb` has only `13.1-rc`/`13.1.1-rc` — no stable target | when 13.1 ships GA; runbook is in the work-packages doc, high tier last |
| **R9 Moodle on `dbops`** | `db_tenants.yml` forbids converging inside Moodle's WP-7b rollback window | **after 2026-11-25** |
| **R10's Moodle part** | follows R9 | after R9 |
| **WP-14 graphify removal** | its own plan requires a quiet tree and warns against staging unrelated work | after this programme, when the checkout is quiet |
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
