# ADR: High-tier point-in-time recovery — the binlog tail is now a mechanism

**Date:** 2026-11-19
**Status:** Accepted
**Relates to:** ADR `2026-10-26-mariadb-binlog-and-audit` (enabled `log_bin`),
`2026-11-18_db-tier-topology`, WP-8R work packages R1 (inventory generator),
R2/R2b (name-free alerts, threshold-pushing probes), R5 (this one).

## Context

Before this change, "PITR" for `leaguesphere` — the high tier, the platform's
data of record — was a sentence in a plan with no mechanism behind it. Three
things were measured on the host before touching anything:

1. **The prepared set carried no binlogs.** `mariadb-backup --backup
   --target-dir=/backup/new` ran without `--binlog`, so
   `/var/jail/home/leaguesphere/container/deployed/mysql-backup/current`
   contained **0** files matching `binlog.*` while its
   `mariadb_backup_binlog_info` named `binlog.000028` at position 11522
   (GTID `0-1-1397`) — a start position pointing into a file the set does not
   contain.
2. **The only binlog copies reaching restic were crash-inconsistent and late.**
   The `db` repo snapshots only `current/` (318 MiB, 17 top-level entries, no
   binlogs). The binlogs appeared only inside the daily `root` snapshot of the
   *live* datadir: snapshot `94069076` (2026-11-18 00:05) held **15**
   `binlog.NNNNNN` files — and those were from a *previous* datadir generation
   (the datadir was recreated at 11:08 that morning), so `binlog.000015` in the
   root snapshot is 75 481 B / 2026-11-17 21:43 while today's same-named file is
   85 560 B of different content. Same name, different history: replaying from
   that copy would either fail or splice two server histories together.
3. **The server's own retention is 2 days** — `expire_logs_days=2`,
   `binlog_expire_logs_seconds=172800`, `binlog_format=ROW`,
   `sync_binlog=1`, `max_binlog_size=256 MiB`, 28 live files / 33 216 750 B.

So the recovery story was: an hourly instant, plus a daily crash-inconsistent
copy of the datadir's logs whose retention has nothing to do with the server's.

## Decision

Make the tail a first-class, alerting artefact with its own repo, its own
cadence and its own enforced pairing with the server.

### 1. `--binlog` on the physical backup — and the finding that it is a no-op

`roles/restic/templates/mariadb_backup.sh.j2` now passes `--binlog`. On this
server that changes nothing, and the reason is the tool's own help text
(MariaDB 13.0.2, measured):

```
--binlog  Backup the server binary logs. Only applies to server configured
          with --binlog-storage-engine, old-style binlog is not backed up.
          Enabled by default, specify --skip-binlog to not backup the binlog
          files.
```

This server uses the **old-style file binlog** (`log_bin_basename=/var/lib/mysql/
binlog`; `binlog_storage_engine` empty/NULL), so a prepared set still contains
**0** `binlog.*` files with the flag on, and `--prepare` still succeeds. The
flag stays (it is the documented intent and becomes functional if the server
ever moves to engine-backed binlogs), and the job now has two guards:

* **hard:** the set must contain `mariadb_backup_binlog_info`, otherwise there is
  no replay anchor and the set is not swapped into `current/`;
* **forward-compat:** if `@@binlog_storage_engine` is non-empty and the set still
  has no binlog files, the job fails instead of promoting a set whose PITR shape
  silently changed.

The consequence is structural and is the basis of the whole design: **the set is
an anchor, not a replay source.** The replay source is the shipped tail, and the
`db` repo's set only supplies the position to start from.

### 2. A 5-minute binlog ship into its own repo (`ls-binlog`)

The live binlogs are root/mysql-owned inside the jail datadir, the `db`/`home`
scopes are unprivileged, and restic 0.18 has **no include patterns** (checked:
`--files-from` exists, nothing that filters inside a directory). Pointing a repo
at the datadir would upload the whole 320 MiB InnoDB tree every 5 minutes.

So `roles/restic/templates/binlog_ship.sh.j2` stages the binlog *files* into one
canonical directory and the repo snapshots that directory:

* copies with `docker exec <ctr> cat` (the container process is root, so it can
  read its own binlogs; the redirect is done by the calling shell, so the staged
  file is owned by the backup user and readable by the unprivileged restic job —
  `docker cp` would preserve uid 999 and break that);
* writes every file to `.incoming` and **renames** it into place, so a snapshot
  can never see a half-copied binlog (`.incoming*` is also excluded);
* copies the **active** binlog too — shipping only rotated files would wait for a
  rotation that can take hours on a quiet database (measured: the active file had
  been open ~12 h at 11 KB), which would silently widen the RPO;
* only re-copies a file whose size changed (binlogs only grow, so equal size is a
  valid identity test and a quiet binlog costs nothing per run);
* reads the file list and all sizes in **two** `docker exec` calls, not one per
  file (first cut measured ~12 s/run of pure exec latency on a 5-minute cadence;
  now ~3 s);
* publishes `binlog.index` (the server's own order, verbatim) and
  `shipped.index` (what is actually staged) plus `ship_status.txt`, so a restore
  does not have to guess.

Repo `ls-binlog` (`restic-ls-binlog` on the Storage Box, same password as `db`):
5-minute snapshots, `retention: binlog_5min` = **`--keep-within 2d`**, chosen as
a duration rather than a count because the meaning that must not drift is "two
days", which is exactly the server's own retention.

Timers: `binlog-ship` at `*:01/5`, `restic-backup-ls-binlog` at `*:03/5`, both
with **`RandomizedDelaySec=0`** via a new per-unit `randomized_delay` override on
the shared oneshot timer template. The template's 5-minute jitter would turn this
cadence into 5–10 minutes (double the stated RPO) and could put the snapshot
before the ship it is meant to capture.

### 3. The pairing is enforced, not documented

`binlog_ship.sh.j2` fails (exit 2, `checks=FAILED`, and it does **not** refresh
the marker) on any of:

| check | what it catches |
|---|---|
| **tail** — the newest binlog the server holds is the newest staged one, and every server-listed file is staged with the same size (closed files must match exactly) | a ship that fell behind after a rotation, a truncated copy |
| **window** — the staged set starts no later than the server's oldest file | history the server still considers replayable that was never shipped |
| **retention pair** — `@@binlog_expire_logs_seconds` must not exceed the repo's keep (`2 d`) nor the stage's keep (`3 d`), read from the server every run | the repo quietly keeping less than the server retains, which shrinks the window while every dashboard stays green |
| **base set** — the prepared set's `mariadb_backup_binlog_info` file must be shipped and must not predate the shipped window | an hourly job that stopped: an old set whose start position is outside the tail |
| **generation** — a server binlog SHORTER than its staged copy is never overwritten | a recreated datadir or `RESET MASTER` restarting the numbering at `binlog.000001`, which would otherwise overwrite the pre-reset tail and leave every other check comparing equal (measured on this host: the datadir was recreated at 11:12 today, so `binlog.000001`–`000015` exist in two generations) |

The stage keeps files for **3 days** while the repo keeps **2**: pruning a staged
file at exactly the repo's retention would remove it from the newest snapshots
while the older snapshots still holding it are already being forgotten — the
precise way a window shrinks silently. The stage never prunes a file the server
still lists.

A freshness check based on the newest binlog's **mtime** was deliberately not
used: a database that is simply not being written to has an old newest binlog
and nothing is broken (measured — this DB's last row event before the drill was
22:19 UTC). The "did the ship run" signal is the `last_ship_ok` marker's age; the
"is the tail complete" signal is the file/size comparison.

### 4. Alerting — no new rule, the existing name-free chain

`backup_targets` gained one row (`ls-binlog`: `probe_minutes: 20`,
`severity: high`, `log_key: backup_ls_binlog` 1800 s, `dump_log_key: binlog_ship`
1800 s). Because R2 made the rules comparisons rather than name chains, that row
alone produces:

* `restic_snapshot_age_seconds{repo="ls-binlog"}` + threshold 1200 + severity 1
  → `stale_restic_snapshot_high` when the tail stops landing;
* `system_log_freshness_seconds{log="binlog-ship"}` (1800 s) → the ship timer is
  alive;
* and the snapshot job carries `stale_guard_path: <stage>/last_ship_ok` (15 min),
  which is what turns a *failing* ship into a *missing snapshot*: without it the
  repo would keep producing fresh-looking snapshots of unchanged files and every
  dashboard would stay green. The guard is created before the checks run, so a
  first run that fails still ages out instead of failing open.

Measured after deploy: age 136 s, threshold 1200, severity 1, log ages 127 s / 6 s,
and `age > on(repo) threshold` returns an empty vector (wired, not firing).

## The drill (this is the deliverable)

Scratch only: a throwaway bridge network `pitr-drill-net`, a throwaway
`mariadb:13.0` container (image `54f493ea0d60`, the same tag prod runs), restores
into `/tmp/opencode/pitr`. Prod was never touched beyond the scheduled
`mariadb-backup`.

Baseline restored into scratch (from `db` snapshot `cfed842b`, set created
14:42 UTC): `auth_user.last_login` id 92 = `2026-11-10 14:07:37.532017`,
`journey_journey.ended_at` id 4117 = `NULL`, no `django_session` row for the
key — i.e. **before** the day's only real row burst.

**Drill A — recovery to a timestamp that contains real changes.**
Target `T = 2026-11-18 15:12:00 UTC` (16:12 CET), between two hourly sets. The
burst at 15:10:23 UTC was a login: a `django_session` insert, an `auth_user`
update and three `journey_journey` writes (GTIDs 1363–1367). Replay:

```
mariadb-binlog --start-position=3158 --stop-datetime='2026-11-18 15:12:00' binlog.000028
  | mariadb          # 5 row transactions applied, 6 BINLOG statements
```

Result — prod-at-T vs scratch-at-T, 13 comparisons over 8 tables, all equal:

| table | prod at T | scratch at T |
|---|---|---|
| `gamedays_gameinfo` | 6804 | 6804 |
| `gamedays_team` | 675 | 675 |
| `auth_user` | 345 | 345 |
| `auth_user.last_login` (id 92) | `2026-11-18 15:10:23.129556` | same |
| `journey_journey` | 4154 | 4154 |
| `journey_journey.ended_at` (id 4117) | `2026-11-18 15:10:23.159109` | same |
| `journey_journeyevent` where `created_at <= T` | 86 639 | 86 639 |
| `gamedays_gamelogsubmission` where `created_at <= T` | 0 | 0 |
| `passcheck_passcheckverification` where `created_at <= T` | 2 527 | 2 527 |
| `officials_officialgamedaysignup` where `created_at <= T` | 240 | 240 |
| `django_session` | 7704 | 7704 |
| the burst's session key present | 1 | 1 |
| sessions whose `session_data` holds the burst's login | 1 | 1 |

`prod at T` was derived two ways, deliberately: tables with a creation timestamp
by `created_at <= T`; tables without one by plain `COUNT(*)`, which equals
prod-at-T only because the binlog proves no **row** event exists after T (all
later events are `ddl` GRANT batches, 15:38–22:19 UTC). The drill container's
clock is UTC and the binlog timestamps are UTC, so `--stop-datetime` needs no
conversion.

**Drill B — the tail really continues past a set, including DDL.**
Baseline: `db` snapshot `fe3a2152` (set created 21:42 UTC, recorded position
`binlog.000028:8747`, GTID `0-1-1382`). Target `T = 22:20:00 UTC`. The replay from
8747 applied GTIDs 1383–1397 — the evening's `GRANT` batches, i.e. **statement**
events — and the grants are byte-identical to prod:

```
GRANT CREATE USER ON *.* TO `dbaccess`@`172.25.%` IDENTIFIED BY PASSWORD '*B294…'
GRANT SELECT, INSERT, UPDATE, CREATE ON `web35_db8`.* TO `dbaccess`@`172.25.%` WITH GRANT OPTION
```

All 13 row comparisons matched again. Timed end to end: **RTO 8.82 s**
(set 3.28 · tail 1.58 · staging 0.44 · server up 2.97 · replay 0.37 · verify 0.17).

**Drill C — the operational path, newest set → now.**
`db` snapshot `811378c3` (set at 23:38 UTC, position `binlog.000028:11522`,
GTID `0-1-1397`), `T = now`. Replay applied **0** transactions and every count
still matched: the newest set's position was already at the tail frontier
because the database had written nothing since 22:19 UTC. **RTO 10.04 s.**

**`--stop-datetime` is `>=`, not `>`** (measured): with `T` exactly at the
burst second (15:10:23) the transactions are *excluded* (1 statement = the format
descriptor); at 15:12:00 they are all included (6). A target instant therefore
must be strictly after the last event one wants — worth knowing before someone
picks `T` from a log line.

**`START TRANSACTION` / `--skip-gtids`:** neither was used. `mariadb-binlog`
13.0.2 emits **zero** `SET @@SESSION.GTID_NEXT` statements for these binlogs
(verified with and without `--print-gtid`), so `--skip-gtids` would have nothing
to skip, and the replay starts exactly at the position the set recorded, which is
the start of the next event — no transaction can be applied twice. Wrapping a
ROW-format stream in `START TRANSACTION` is not possible: the events carry their
own BEGIN/COMMIT/Xid. Caveat for a future reader: because GTID statements are not
emitted, replaying a window that *overlaps* the set's range would re-apply rows
silently rather than being refused — the recorded position is the anchor, and the
drill verified the GTID boundary on both sides.

## Achieved window and RTO

* **Window:** every instant up to **5 minutes** before now, for as far back as the
  *prepared sets* reach (3 days of hourly sets in `db`), bounded below by the
  server's own 2-day binlog history. Today the server's binlog history starts at
  11:12 CET (the datadir was recreated), so the *currently reachable* window is
  [11:12 CET today, now−5min]; it grows to the full 2 days as the server keeps
  writing, and the checks fail loudly if the repo ever keeps less than the server.
* **RTO:** 8.8 s (drill B) and 10.0 s (drill C) from `restic restore` to a
  verified scratch database, with the repos in the local restic cache. A cold
  cache adds the download of 318 MiB from the Storage Box.

## Consequences

### Positive

* The high tier's PITR promise is now a measured mechanism: an instant inside a
  minute-window of real data changes, restored and compared row-for-row.
* The tail has its own retention, cadence and alerting, and the three ways it can
  silently rot (behind, short, unpaired) each fail loudly.
* The `db` repo no longer pretends to be self-sufficient: the set is documented
  as an anchor, and the anchor is checked against the tail on every ship run.
* `backup_targets` gained a row, not a file: the probes, retention, env file,
  sftp dir, repo init and log file all follow from the inventory (R1's point).

### Negative / tradeoffs

* ~32 MiB staged on disk and re-uploaded (deduplicated) every 5 min: 576
  snapshots/day of metadata. Cheap, but the forget/prune now walks a repo with
  ~576 snapshots per run.
* The ship costs ~3 s of `docker exec` + `stat` per run, and a growing active
  binlog is re-copied whenever it changes (bounded by `max_binlog_size`, 256 MiB).
* Two repos must be restored for a PITR (set + tail); the drill shows this is
  seconds, but it is two credentials and two `restic restore` commands where
  before there was one.
* `RandomizedDelaySec` is now a per-unit knob; the default stays 5m, so nothing
  existing changed.

### What a future reader must NOT disable

1. **`--keep-within 2d` on `ls-binlog` vs `expire_logs_days=2`.** They are a pair.
   Shortening one without the other means a restore of a still-retained set
   references binlogs nobody ships. The ship script reads the server's live value
   every run and exits 2 on divergence — do not "fix" that by relaxing the check.
2. **The 5-minute cadence and `randomized_delay: '0'`.** The cadence *is* the RPO.
   Adding the template's default jitter back makes it 5–10 minutes and can
   reorder ship and snapshot. `probe_minutes: 20` is four consecutive misses, not
   a tolerance for a stalled ship.
3. **The stale-source guard on the snapshot job.** It is the only thing that turns
   a failing ship into a missing (alerting) snapshot instead of a green dashboard
   over unchanged files. The `last_ship_ok` marker must keep being touched only
   on a fully successful run — including the checks.
4. **`--binlog` and its two guards.** Today the flag is a no-op (old-style binlog),
   but the `mariadb_backup_binlog_info` guard is what keeps the set an anchor at
   all, and the `binlog_storage_engine` guard is what will catch the day the flag
   starts to matter.
5. **`binlog_stage_keep_days: 3` vs the repo's 2 days.** Pruning the stage at the
   repo's retention silently shortens the window; the ship script fails if this
   inverts.

### Implementation details

**Files modified**

* `ansible/plays/roles/restic/templates/mariadb_backup.sh.j2` — `--binlog`, the
  binlog-info guard, the storage-engine guard, honest logging; the `current/`
  swap is unchanged except that `[ -d ] && mv` became `if`, which under `set -e`
  aborted the job on a host with no previous set.
* `ansible/plays/roles/restic/templates/binlog_ship.sh.j2` (**new**) — the ship
  and its four checks.
* `ansible/plays/roles/restic/templates/oneshot.timer.j2`,
  `tasks/oneshot_include.yml` — per-unit `randomized_delay` (default 5m).
* `ansible/plays/roles/restic/tasks/backup.yml` — staging dir, ship script +
  timer, snapshot script + timer, stale guard, and the cleanup list for hosts
  without LeagueSphere.
* `ansible/plays/roles/restic/molecule/{default,no-leaguesphere}/` — the new repo
  and schedules in the scenario dicts, units/scripts in `verify.yml`, stale
  fixtures for the cleanup scenario, and assertions that the binlog timers carry
  `RandomizedDelaySec=0` while an hourly timer keeps its 5m.
* `ansible/plays/vars/restic.yml` — `ls-binlog` transport (excludes
  `.incoming*`), `ship_binlog`/`backup_ls_binlog` schedules,
  `binlog_ship`/`backup_ls_binlog` log paths.
* `ansible/plays/vars/db_tenants.yml` — `retention_profiles.binlog_5min`
  (`keep_within: 2d`) and the `ls-binlog` `backup_targets` row, with the policy
  comments that explain why neither may be relaxed.
* `ansible/plays/tasks/restic_wiring.yml` — two new inventory guards: a
  `dump_log_key` must come with its label and threshold, and a target's log
  threshold must be a usable number.
* `ansible/plays/roles/system/templates/restic_forget.sh.j2` — `keep_within`
  support (it rendered `--keep-keep_within`); verified byte-identical output for
  every pre-existing profile.
* `ansible/plays/roles/system_probe/templates/restic_snapshot_freshness.sh.j2` —
  clamp a negative age to 0 (see below).
* `ansible/tests/system_probe/test_restic_snapshot_probe.py` — fixture test for
  that clamp (fails on the pre-fix template).

**Defect found and fixed while drilling the alerting:** the snapshot-age probe
reported `-2` for `repo="ls-binlog"` on the run that raced the `:03` snapshot.
The probe samples `now` first and then reads the newest snapshot, so a snapshot
created a second or two later yields a negative age — and the R2 rules treat any
negative age as "unverifiable" and page (`(age < bool 0) > 0`). A 5-minute
cadence hits that race 12× more often than an hourly one. Fixed by clamping to 0
*inside the success path only*, keeping `-1` as the "could not read the repo"
sentinel.

**Verification performed**

* `ansible-playbook --syntax-check` on `servyy.yml`, `plays/system.yml`,
  `plays/restic.yml`; `yamllint` and `ansible-lint` clean on every changed file.
* `zsh -n` **and** `bash -n` on every rendered script
  (`binlog-ship.sh`, `restic-backup-ls-binlog.sh`, `mariadb-backup-ls.sh`,
  `restic-forget.sh`, `system-restic-snapshots.sh`); `systemd-analyze --user
  verify` on the four new units.
* Deploy: new repo initialised, env file + log files created, four timers
  running, snapshots every 5 minutes (00:28:49, 00:33:06, 00:38:05, 00:43:01,
  00:48:02…), ship every 5 minutes at ~3 s.
* The generated lists contain the new repo: `restic-forget.sh` has its own
  `--keep-within 2d` block, `restic-check.sh` checks it, the snapshot probe emits
  `{repo="ls-binlog"} 1200 / 1`, the log probe emits both new logs at 1800 s, and
  `restic forget --dry-run --keep-within 2d` marks all 5 snapshots "within 2d".
* Guards: a `retention` typo, a `log_key` typo and a removed `dump_log_label`
  each fail the run with the offending value in the message; the file was
  restored byte-identically afterwards.
* Checks: the retention-pair check fails with exit 2 when the repo keep is
  lowered to 1 day (`server_retention_seconds=172800 repo_keep_days=1`), leaves
  `checks=FAILED` in `ship_status.txt`, and does **not** refresh the marker; a
  marker aged by 1 hour makes the snapshot job exit 1 (no snapshot), and it
  succeeds again once the ship refreshes it.

### Known issues / limitations

* The pieces of a PITR live in two repos with different retention; the drill
  scripts used here are not yet a `plays/restore_drill.yml` (that is R11).
* `mariadb-backup` cannot include old-style binlogs on 13.0, so there is no
  fallback copy inside the set. If the stage were lost between ships, the window
  is bounded by the last shipped file — which is exactly what the checks measure.
* The reachable window today starts at the datadir's creation (11:12 CET), not
  two days back: the *server* has no older binlogs. The window grows with time;
  the checks do not pretend otherwise.
* Restore verification is manual (13 queries in the drill); R11 should automate
  it and publish `db_restore_drill_*` metrics.
* A binlog **generation reset** (datadir recreated, or `RESET MASTER`) stops the
  ship with an error and leaves both generations on disk; a human must move the
  old files aside before shipping resumes. That is deliberate — PITR across a
  reset is impossible and guessing which history to discard is not a backup
  script's decision — but it means such an event needs an operator, not just a
  page.

## Alternatives considered

**Copy the binlogs into the prepared set by hand (self-contained sets).**
Rejected: the set is version-bound and rotated hourly, the tail is a 5-minute
stream with its own retention, and two copies of the same binlogs under two
forget policies is the "restore disagrees with itself" shape this design exists
to avoid. `mariadb-backup` refuses to do it for a reason.

**Snapshot the jail datadir directly with a `--files-from` list.**
Rejected: it requires root for every 5-minute run, uploads whatever the datadir
holds if the list is ever wrong, and gives no place to run the pairing checks.

**One repo for sets and binlogs (`db` with an extra path).**
Rejected: one `restic forget --tag` policy would cover both (3 days of hourly sets
vs 2 days of binlogs), and a 576-snapshot prune would contend with the hourly set
upload for the repo lock.

**A count-based retention (`--keep-last 576`).**
Rejected in favour of `--keep-within 2d`: a count silently means a different
window the moment the cadence changes, and the pairing with `expire_logs_days`
must be legible in the inventory.

**Rotate the binlog every 5 minutes (`FLUSH BINARY LOGS`) and ship only closed
files.**
Rejected: it changes production behaviour (288 rotations/day) to make the backup
simpler, and the active file still would not be covered between rotations.

**mtime-based tail freshness.**
Rejected: a quiet database legitimately has an old newest binlog; the honest
signal is "did the ship run" (marker) plus "is the file set complete" (sizes).
