# WP-8R follow-ups — bnb's dump time, `home` churn, the dump-root layout, the dead PhotoPrism restore, and the drill readiness race (2026-11-19)

Branch `db-tier/wp8r-followups` from master `36128bc6`. All five follow-ups left
open by R7/R8 and the WP-10 work are implemented, deployed to `servy.lehel.xyz`
and measured there. **Nothing is merged** — the coordinator merges, then
re-deploys from master.

Everything below is a measurement, not an estimate. Where a number came from
`restic diff` it is the per-file new-chunk byte count (the bytes actually
uploaded), because `restic 0.18`'s `diff --json` reports per-snapshot totals only.

## 1. bnb's dump moved out of the restic window (02:30 -> 01:05)

**Measured before.** The `bnb_office` row said `daily 02:30`; the plan's schedule
table has said 01:05 since 2026-11-18, and 02:00–04:00 is the nightly restic
window. The per-tenant dump timers were removed by R8, so the row — not a unit —
was the only place the time lived (`dbops dump-due` derives "due" from
`dump_schedule` + `dump_at` + the mtime of `current/`).

**Changed.** `plays/vars/db_tenants.yml`: `dump_schedule`/`dump_at` `02:30` ->
`01:05`. `plays/vars/restic.yml`: `dump_bnb_office` `02:30` -> `01:05` (it
documents the same instant for the schedule rendering) and `backup_db_bnb`
`02:40` -> `01:10` — the snapshot has to follow the dump, and 02:40 was inside
the window too. The wiring guard `dump_at in restic.schedules['dump_bnb_office']`
ties the two files together, so they cannot drift.

**Proof (measured on servy).**

| Check | Result |
|---|---|
| rendered dbops carries the new row | `T_SCHEDULE="daily 01:05"; T_DUMP_AT="01:05"` for `bnb_office` |
| the runner's instant is 01:05, not 02:30 | `current/` mtime set to **today 00:30** -> `dump-due business` prints `bnb_office`; set to **today 01:30** -> prints nothing (it would print `bnb_office` under the old 02:30 row); set to **yesterday 23:00** -> prints `bnb_office`; mtime restored byte-identically afterwards. The pair 00:30/01:30 pins the instant between them. |
| nothing is due right now | `dbops dump-due business` and `... private` both empty; a `db-backup-tier.sh <tier>` tick prints `no tenant due` |
| the probe agrees | `db_dump_age_seconds{tenant="bnb_office"} 599`, `db_dump_threshold_seconds 93 600` (26 h), `db_dump_severity{tier="business"} 1`, `system_log_freshness_seconds{log="dump-bnb_office"} 599` (threshold 93 600) |
| the snapshot follows at 01:10 | `restic-backup-db-bnb.timer` `OnCalendar=*-*-* 01:10:00`, next run 01:12 (timer jitter); a manual run produced snapshot `f3096374` holding `bnb_office-20261119T172412Z.sql.gz` |
| no failures | `systemctl --user --failed` empty |

## 2. The ~20 MB/h of `home` churn — attributed, then split per path

**Measured.** Two consecutive hourly snapshots in a quiet hour (13:02 -> 14:00,
19 changed files, no deploy work in it): `data_added` **19 118 542 B**. Same
hour one cycle earlier for confirmation (16:01 -> 16:49, 17 files):
**19 803 011 B**. Blob-level attribution (compare the file's content-blob list in
both snapshots, then size every new blob):

| Path (under `/home/cda/`) | 13:02 -> 14:00 | 16:01 -> 16:49 | What it is | Decision |
|---|---|---|---|---|
| `servyy-container/waggle/data/db/openpost.db` | 10 825 728 B (20 chunks) | 10 940 416 B (20) | live SQLite DB of the OpenPost/Waggle instance — scheduled posts, accounts, provider credentials sealed with `OPENPOST_ENCRYPTION_KEY` | **keep** — data of record |
| `servyy-container/waggle/data/db/openpost.db-wal` | 4 152 992 B (8) | 4 152 992 B (8) | SQLite WAL: committed transactions not yet checkpointed | **keep** — excluding it would drop up to an autocheckpoint interval of writes |
| `servyy-container/git/logs/access.log` | 2 857 761 B (1) | 2 894 948 B (1) | nginx access log (78 MB, never rotated) | **exclude** — not data of record |
| `servyy-container/achim-hoefer/logs/access.log` | 866 096 B (1) | 915 561 B (1) | nginx access log (106 MB, never rotated) | **exclude** — not data of record |
| `pass/vw-data/db.sqlite3-shm` | 32 768 B | 0 | SQLite shared-memory index | **exclude** — rebuilt on open, never data of record |
| `servyy-container/waggle/data/db/openpost.db-shm` | 32 768 B | 0 | same | **exclude** |
| `pass/vw-data/db.sqlite3-wal` | 16 512 B | 0 | Vaultwarden WAL | **keep** — same argument as OpenPost's |
| total attributed | 18 784 625 B | 18 903 917 B | | |

The remaining ~0.3 MB is tree blobs and ordinary file writes.

**Why OpenPost's ~15 MB/h is not junk, and why it stays.** The database is 11.5 MB
(`page_size 4096`, `page_count 2814`, `journal_mode wal`, `secure_delete 1`,
`auto_vacuum 0`, `wal_autocheckpoint 1000`). It is written continuously, so every
1 MiB restic chunk contains at least one dirty page and all ~11 chunks are
re-uploaded; the WAL is 4 152 992 B because SQLite checkpoints at 1000 pages and
then reuses the file from the start. That is the cost of hourly
content-defined-chunk backup of a live SQLite app — 15 MB/h, ~360 MB/day, for
data that has no other copy. Excluding the `.db` would delete the only backup of
it; excluding the `-wal` would silently lose the most recent committed writes.
The only honest reduction left is a pre-snapshot `wal_checkpoint(TRUNCATE)` hook
(it removes the duplicated 4 MB/h); that changes the writer while the app holds
the database and is **not** done here — see follow-ups.

**Changed** (`vars/restic.yml`, `home.excludes`): `**/logs/access.log` and
`**/*-shm`, with the numbers and the reasoning written next to them. Exactly two
`access.log` files exist under `home` and three `-shm` files (all SQLite), so the
patterns match only what was measured.

**Proof (a real snapshot, not a dry run).** After the deploy, a manual
`restic-backup-home.sh` produced snapshot `68d00a4a` (18:33):
`data_added` **15 732 499 B** (from 19 588 352 B at 18:01, before the excludes);
`restic ls` finds **no `access.log` and no `-shm`** in it; blob attribution
17:01 -> 18:33 shows the two access logs `missing in B, 0 new chunks` and
`openpost.db` 11 010 048 B + `-wal` 4 152 992 B = 15 163 040 B, i.e. the residual
is now exactly the database that must not be excluded.

## 3. The stray dumps outside `current/` — removed, and the layout now enforces itself

**Measured.** The tenant roots held eight loose files that no repo snapshots and
no probe reads (plus one staging dir from the SIGTERMed dump of R8's proof):

| File | Bytes | md5 | What supersedes it |
|---|---|---|---|
| `photoprism/photoprism-20261118T210223Z.sql.gz` | 107 336 594 | `696fe378…` | `current/photoprism-20261119T154058Z.sql.gz` (newer, same 41-table schema, `-- Dump completed`); snapshots `23c0896d` (21:47:54, 107 336 601 B) and `daa5e628` (23:45:48, 107 336 623 B) bracket it. The stray carries a dump date, so it predates the `--skip-dump-date` dbops invocation. |
| `dontforget/*.archive.gz` (2) | 24 045 / 24 712 | `b5edd8d9…` / `0920dce5…` | `current/` archive from 16:43, `gzip -t` clean; manual verification runs of 10:53/10:54 |
| `leagues_finance/*.archive.gz` (2) | 11 598 / 11 644 | `5e00fcb0…` / `5429f760…` | `current/` from 16:40 |
| `queen/*.archive.gz` (2) | 28 617 / 29 486 | `4a3b680e…` / `f6d8653d…` | `current/` from 16:40 |
| `photoprism/new/photoprism-20261119T154330Z.sql.gz` | 107 336 941 | — | never promoted (the killed dump of R8's proof); the next run wipes `new/` |
| `firefly/firefly-20261118T210627Z.dump` | 414 050 | `b291c02e…` | **moved, not deleted** — PostgreSQL custom-format dump from before WP-10. `shared.db` (postgres:15) is stopped but still present, i.e. the rollback window is open. Moved to `/home/cda/db-dumps/.archive/firefly/`, which is inside the excluded `db-dumps` tree and in no backup scope before or after (same status, out of the layout). |

Nothing removed was the only copy of anything: each database has a newer complete
dump in its tenant's `current/`, and the tenants' repos keep dumps on both sides
of the removed files. The only file with a claim to history (the Postgres dump
from before the engine move) was preserved.

**Changed — the layout enforces itself, in two places.**

* **Writer** (`db_tier/templates/dbops.sh.j2`): `dbops dump` now stages into
  `<dump_dir>/new` by default (`dump_write_dir`); the tenant ROOT is reachable
  only by naming it in `DBOPS_DUMP_DIR`. This is how the strays were born: a
  hand-run `dbops dump photoprism` wrote into the root.
* **Reader** (`latest_dump`, used by `dbops verify`): prefers `<dump_dir>/current`
  (`dump_read_dir`) and appends `/current` only when it exists, because
  leaguesphere's `dump_dir` IS the prepared set. A loose root file can no longer
  be read as "the newest dump".
* **Enforcement** (`restic/templates/dbops_dump.sh.j2`): after the swap, every
  scheduled dump fails (exit 1, `dump root holds entries outside new/ and
  current/`) if the root holds anything but `new/` and `current/`. Failing, not
  warning: a warning is what gets ignored, and the file sat there for a day. It
  runs after the swap, so a fresh `current/` is already in place and nothing of
  record is touched.

**Proof (measured on servy).**

* A bare `dbops dump bnb_office` (no `DBOPS_DUMP_DIR`) wrote
  `/home/cda/db-dumps/bnb_office/new/bnb_office-20261119T172358Z.sql.gz` — the
  root stayed clean.
* `dump-bnb_office.sh` on a clean root: rc 0, `current/` refreshed. With a file
  planted in the root (`STRAY-evidence.txt`): rc **1**,
  `[error] dump root holds entries outside new/ and current/ root=… entries=STRAY-evidence.txt`,
  and `current/` still held the complete dump. Stray removed: rc 0 again.
* `db-backup-tier.sh business --force` and `... private --force`: all six tenants
  dumped with clean roots (`dumped=3` each, rc 0); afterwards every root holds
  only `current/`, and `dbops dump-due` for both tiers is empty.
  (`leaguesphere-binlog` is R5's flat binlog ship dir, not a wrapper tenant —
  untouched.)

## 4. The PhotoPrism restore entry is gone, not re-pointed

**Choice: removed.** `roles/restic/tasks/main.yml` restored
`servyy-container/photoprism/database` from `home`. PhotoPrism's database has
lived on `db-private.mariadb` since WP-6, that datadir is the STOPPED pre-cutover
engine (775 MB, still on disk as the WP-6 rollback), and it has been excluded
from `home` since R7 — so the task could only ever skip or restore a dead
database. Re-pointing was rejected: the real copy is a logical dump
(`/home/cda/db-dumps/photoprism/current`, repo `db-private`, `drill: monthly`),
which is restored with `dbops restore photoprism <file>` / `restore-drill.sh`,
not by an `include_tasks: restore.yml` that assumes a datadir. Re-adding it needs
a datadir that is actually backed up, and the comment where it used to be says so.

**Proof.** `--tags restic.restore --list-tasks` now lists Gitea, Vaultwarden,
Moodle dataroot, Moodle DB and LeagueSphere — and no PhotoPrism task. The
photoprism tenant is still drilled from its own repo (below), so the capability
is proven by the mechanism that owns it.

## 5. The drill readiness race — the TEMP init server answers on the same socket

**Measured (mariadb:13.0, `--network none`, from container start, 50 ms probes).**
This is the trace that explains the one-off firefly failure (`readiness ok`, then
`dbops restore` -> `ERROR 2002 … socket '/run/mysqld/mysqld.sock'`, and
`has_tables` — which fails safe — read the empty answer as "already has tables"):

```
+  1.0 s  ERROR 2002   socket does not exist
+ 10.1 s  TEMP init server answers ON THAT SOCKET and reports @@port = 0
+ 12.3 s  ERROR 2002   temp server stopped, final server not listening yet
+ 15.0 s  final server answers, @@port = 3306
```

The old readiness check authenticated and returned on the first success. The temp
server is started by the entrypoint to create the accounts, logs "ready for
connections", listens on the same socket path, and can accept the credential —
so readiness could return for a server that is killed milliseconds later. The
previous comment claimed authentication ruled the temp server out; the failed
drill disproves it.

**Changed** (`restore_drill/templates/restore_drill.sh.j2`): `wait_mariadb_auth`
authenticates **and** requires a non-zero `@@port`, i.e. proof that the server is
the final one (the temp server runs with `skip-networking` and reports 0). It
retries for up to 180 s and captures the client output instead of piping it into
`grep -q` (under `set -o pipefail` an early-exiting grep SIGPIPEs the client and
turns a success into a failure — the trap the mongo check already documents).
The Postgres and Mongo checks already query the target database / authenticate
and needed no change.

**Proof.**

* Regression test `ansible/tests/restore_drill_ready/` renders the real drill
  script, replays that exact timeline with a fake `docker`, and asserts that the
  new check refuses the port-0 server (it accepts attempt 6, not 3) **and** that
  the old authenticate-only predicate would have returned at attempt 3 and then
  failed with 2002 — the defect pinned so it cannot come back.
* The deployed function against a fresh container: returned rc 0 after
  12 688 ms, the accepted server reports `@@port = 3306`, and the 20 immediate
  follow-up queries all succeeded (the old failure was on the first one).
* **8 drills, all ok:** `firefly` 5 runs (57, 58, 58, 58, 60 s) and `bnb_office`
  3 runs (42, 35, 37 s), each from the newest snapshot and verified against the
  live tenant. `systemctl --user --failed` is empty afterwards.

## Files changed

* `ansible/plays/vars/db_tenants.yml` — bnb's row: `daily 01:05` / `01:05`.
* `ansible/plays/vars/restic.yml` — `dump_bnb_office` 01:05, `backup_db_bnb`
  01:10, the two new `home` excludes with the measured table, the PhotoPrism
  comment.
* `ansible/plays/roles/restic/tasks/main.yml` — the dead PhotoPrism restore
  include removed, with the reasoning where it was.
* `ansible/plays/roles/restic/templates/dbops_dump.sh.j2` — the dump-root
  enforcement check.
* `ansible/plays/roles/db_tier/templates/dbops.sh.j2` — `dump_write_dir` /
  `dump_read_dir`, used by `dump`, `verify` and `latest_dump`, plus the usage
  text.
* `ansible/plays/roles/restore_drill/templates/restore_drill.sh.j2` —
  `wait_mariadb_auth` requires `@@port != 0`.
* `ansible/plays/roles/{restic,db_tier}/molecule/default/verify.yml` — the
  rendered dump script must stage into `new/` and carry the layout check; the
  rendered dbops must carry both layout functions.
* `ansible/tests/dbops_dump_layout/`, `ansible/tests/restore_drill_ready/` — new
  Docker-free fixtures; `.github/workflows/ci.yml` runs both.

## Checks run

`ansible-playbook --syntax-check` on `servyy.yml`, `plays/user.yml`,
`plays/restic.yml`, `plays/restore_drill.yml`, `plays/system.yml`; `yamllint` on
every changed YAML; `ansible-lint --profile production` on `roles/restic/`,
`roles/db_tier/`, `roles/restore_drill/`, `plays/restic.yml`,
`plays/restore_drill.yml`, `plays/tasks/restic_wiring.yml`, both vars files
(0 failures); `bash -n` on the rendered `dbops`, `restore-drill.sh`,
`dump-bnb_office.sh` and `zsh -n` on the wrapper; `python -m unittest` on the two
new fixtures (5 + 2 tests). Molecule scenarios were extended but **not run here**
— this workspace has no Docker socket; CI runs them. `restic/*` molecule is
still red on master for the unrelated reason the coordinator is fixing.

## Deployment notes

* Deployed **from this worktree**, with the canonical local-only seeds symlinked
  (`.restic_password_*`, `.dbops_password_*`, `.servyy_container_deploy_key`) —
  see R7/R8's note: rendering `db_tier` from a checkout without them rewrites the
  backup users' passwords.
* Targeted runs only: `plays/user.yml --tags user.docker.db-business.render`
  (dbops), `plays/restic.yml --tags restic.backup` (wrappers, schedules,
  excludes), `plays/restore_drill.yml --tags restore.drill`.
  **`restic.init` was deliberately not run**: it would overwrite `~/.ssh/config`
  with the Storage Box template and delete the managed GitHub deploy-key block.
* No probe re-deploy was needed: `probe_minutes` did not change, so the rendered
  `db_dump_freshness` probe text is identical; the values were read back from the
  Pushgateway instead.

## Follow-ups (not done here)

* **The two nginx access logs are unbounded** (106 MB and 78 MB, never rotated).
  Excluding them from `home` is not a substitute for rotation: that is a writer
  fix in the `achim-hoefer` and `git` services, and it also decides whether their
  access logs should exist at all.
* **A pre-snapshot `wal_checkpoint(TRUNCATE)`** for the SQLite databases under
  `home` would remove OpenPost's duplicated 4 MB/h WAL and make the `.db` a
  complete copy. It needs a hook that opens the live database while the app holds
  it; not attempted in a backup-hygiene change.
* `shared.db` (postgres:15) is still stopped-but-present for the WP-10 rollback;
  delete it and `db-dumps/.archive/firefly/` together when that window closes.

## Do not (measured traps this package hit)

* **Do not restore the PhotoPrism include.** It points at an excluded datadir of
  a dead engine; it can only mislead during an incident.
* **Do not let `dbops dump` write into the tenant root.** Staging into `new/` is
  what keeps the layout honest; the root check in the wrapper then only ever
  fires on a manual mistake.
* **Do not exclude `openpost.db`, `openpost.db-wal` or Vaultwarden's
  `db.sqlite3-wal`** to make the churn numbers look better — those bytes are the
  only copy of live data.
* **Do not replace the `@@port` readiness check with "does the credential work".**
  The TEMP init server answers on the same socket and reports port 0; the failed
  firefly drill is what that costs.
* **Do not add per-tenant dump timers back, and do not deploy `restic.init` for a
  restic change** — both were measured traps in R7/R8.
