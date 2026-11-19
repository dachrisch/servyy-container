# Database restore drills — 2026-11-19

Machine-written by `ansible/plays/restore_drill.yml` on `servy`.
One section per drill, appended in the order the drills ran. Do not hand-edit:
the next run appends, and a correction belongs in the commit that fixes the cause.

Each drill restores the NEWEST snapshot of the tenant's repo into a throwaway
container of the same image as the live server, compares the restored copy with the
live tenant (read-only), and removes the scratch target. **The wall-clock figure is
the measured restore time — from `restic restore` to a verified scratch target — not
an estimate, and it is the number the RTO tables should quote.**

Counts can legitimately lag: the snapshot predates the drill, so a busy table may
have rows live that the restore cannot. The gate is therefore structural equality,
no populated table empty in the restore, and checksum equality wherever the counts
do match ("dbops verify --drill"); the per-table drift is printed below, not hidden.
EMPTY_IN_RESTORE, MISSING or a CHECKSUM difference is a failed drill.

Metrics for the same drill: `db_restore_drill_success{tenant}`,
`db_restore_drill_age_seconds{tenant}`, `db_restore_drill_duration_seconds{tenant}`.
A tenant with `drill: none` in the inventory appears nowhere in this file.

---

## 2026-11-19T08:26:36Z · photoprism (private, mariadb)

**Result:** ok **(monthly cadence)**

| | |
|---|---|
| Snapshot | `daa5e628844bf48587af746ba7f61a5780f1ceb0badc16fc1f0bfa4aadbcaf5b` from repo `db-private`, taken 2026-11-19T00:58:49.34953204+01:00 |
| Scratch target | `drill-photoprism-20261119T082450Z` (mariadb:13.0, network `none`) → removed |
| Restore wall-clock (RTO) | **107.9 s** (restic 3.1 s · target up 13.1 s · import 44.0 s · verify 46.5 s) |
| Counts compared | compared 41 tables, live 580357 rows / restored 580349 rows (restore is 8 rows behind live) |
| Mismatch | none |

Verify output (`dbops verify photoprism --against drill-photoprism-20261119T082450Z --drill`):

```text
dbops: verify photoprism  live(db-private.mariadb) vs live(drill-photoprism-20261119T082450Z)
  -- db-private.mariadb / photoprism
  -- drill-photoprism-20261119T082450Z / photoprism
  structure: 41 objects identical (tables, views, routines, triggers, events)
  compared 41 tables, live 580357 rows / restored 580349 rows (restore is 8 rows behind live)
  per-table differences (drift is expected; EMPTY_IN_RESTORE/MISSING/CHECKSUM is not):
    errors live=35809 restored=35801
dbops: ok  drill check: structure identical, no populated table empty in the restore, equal-count tables checksum-identical
```

Full log: `/home/cda/.restore-drills/logs/photoprism-20261119T082447Z.log`

---

## 2026-11-19T08:26:54Z · queen (business, mongo)

**Result:** ok **(monthly cadence)**

| | |
|---|---|
| Snapshot | `9df133f22fc890866bb25ceeff212abe84d09903594ed1e7dab41f4a9f1bbd0b` from repo `db-queen`, taken 2026-11-19T01:35:49.412461402+01:00 |
| Scratch target | `drill-queen-20261119T082638Z` (mongo:9.0, network `none`) → removed |
| Restore wall-clock (RTO) | **18.1 s** (restic 2.1 s · target up 7.4 s · import 4.6 s · verify 3.2 s) |
| Counts compared | compared 14 collections, live 366 documents / restored 360 documents (restore is 6 documents behind live) |
| Mismatch | none |

Verify output (`dbops verify queen --against drill-queen-20261119T082638Z --drill`):

```text
dbops: verify queen  live(shared.mongo) vs live(drill-queen-20261119T082638Z)
  compared 14 collections, live 366 documents / restored 360 documents (restore is 6 documents behind live)
  per-collection differences (drift is expected; EMPTY_IN_RESTORE/MISSING is not):
    banktransactions live=79 restored=74
    reconcileruns live=58 restored=57
dbops: ok  drill check: collection set identical, no populated collection empty in the restore
```

Full log: `/home/cda/.restore-drills/logs/queen-20261119T082636Z.log`

---

## 2026-11-19T08:48:01Z · dontforget (private, mongo)

**Result:** ok **(monthly cadence)**

| | |
|---|---|
| Snapshot | `e10b59c343fcfb603c7d2d4b59b40775b50db0af6e78b7579d8d3bc2cf24e3ef` from repo `db-private-mongo`, taken 2026-11-19T01:40:49.788397562+01:00 |
| Scratch target | `drill-dontforget-20261119T084740Z` (mongo:9.0, network `none`) → removed |
| Restore wall-clock (RTO) | **21.4 s** (restic 1.8 s · target up 9.0 s · import 5.3 s · verify 3.4 s) |
| Counts compared | compared 14 collections, live 717 documents / restored 717 documents (restore is 0 documents behind live) |
| Mismatch | none |

Verify output (`dbops verify dontforget --against drill-dontforget-20261119T084740Z --drill`):

```text
dbops: verify dontforget  live(shared.mongo) vs live(drill-dontforget-20261119T084740Z)
  compared 14 collections, live 717 documents / restored 717 documents (restore is 0 documents behind live)
dbops: ok  drill check: collection set identical, no populated collection empty in the restore
```

Full log: `/home/cda/.restore-drills/logs/dontforget-20261119T084737Z.log`

---

## 2026-11-19T08:48:22Z · leagues_finance (business, mongo)

**Result:** ok **(monthly cadence)**

| | |
|---|---|
| Snapshot | `985f2ac11604b176a8c19955c92f15b0037c6660375771791d8829b5c39c9bd7` from repo `db-lf`, taken 2026-11-19T01:25:49.434628402+01:00 |
| Scratch target | `drill-leagues_finance-20261119T084803Z` (mongo:9.0, network `none`) → removed |
| Restore wall-clock (RTO) | **20.0 s** (restic 2.2 s · target up 8.6 s · import 4.2 s · verify 3.4 s) |
| Counts compared | compared 11 collections, live 186 documents / restored 186 documents (restore is 0 documents behind live) |
| Mismatch | none |

Verify output (`dbops verify leagues_finance --against drill-leagues_finance-20261119T084803Z --drill`):

```text
dbops: verify leagues_finance  live(shared.mongo) vs live(drill-leagues_finance-20261119T084803Z)
  compared 11 collections, live 186 documents / restored 186 documents (restore is 0 documents behind live)
dbops: ok  drill check: collection set identical, no populated collection empty in the restore
```

Full log: `/home/cda/.restore-drills/logs/leagues_finance-20261119T084801Z.log`

---

## 2026-11-19T09:10:58Z · photoprism (private, mariadb)

**Result:** ok **(monthly cadence)**

| | |
|---|---|
| Snapshot | `daa5e628844bf48587af746ba7f61a5780f1ceb0badc16fc1f0bfa4aadbcaf5b` from repo `db-private`, taken 2026-11-19T00:58:49.34953204+01:00 |
| Scratch target | `drill-photoprism-20261119T090911Z` (mariadb:13.0, network `none`) → removed |
| Restore wall-clock (RTO) | **109.7 s** (restic 2.9 s · target up 11.6 s · import 46.7 s · verify 46.5 s) |
| Counts compared | compared 41 tables, live 580358 rows / restored 580349 rows (restore is 9 rows behind live) |
| Mismatch | none |

Verify output (`dbops verify photoprism --against drill-photoprism-20261119T090911Z --drill`):

```text
dbops: verify photoprism  live(db-private.mariadb) vs live(drill-photoprism-20261119T090911Z)
  -- db-private.mariadb / photoprism
  -- drill-photoprism-20261119T090911Z / photoprism
  structure: 41 objects identical (tables, views, routines, triggers, events)
  compared 41 tables, live 580358 rows / restored 580349 rows (restore is 9 rows behind live)
  per-table differences (drift is expected; EMPTY_IN_RESTORE/MISSING/CHECKSUM is not):
    errors live=35809 restored=35801
    versions live=331 restored=330
dbops: ok  drill check: structure identical, no populated table empty in the restore, equal-count tables checksum-identical
```

Full log: `/home/cda/.restore-drills/logs/photoprism-20261119T090908Z.log`

---

## 2026-11-19T10:07:47Z · leagues_finance (business, mongo)

**Result:** ok **(monthly cadence)**

| | |
|---|---|
| Snapshot | `3879bca09ab56fcdb774cb16bd777d171f78a85dcd2a6f6165a347ad9c238f02` from repo `db-lf`, taken 2026-11-19T11:05:59.317330677+01:00 |
| Scratch target | `drill-leagues_finance-20261119T100729Z` (mongo:9.0, network `none`) → removed |
| Restore wall-clock (RTO) | **19.6 s** (restic 2.1 s · target up 7.9 s · import 4.4 s · verify 3.9 s) |
| Counts compared | compared 11 collections, live 186 documents / restored 186 documents (restore is 0 documents behind live) |
| Mismatch | none |

Verify output (`dbops verify leagues_finance --against drill-leagues_finance-20261119T100729Z --drill`):

```text
dbops: verify leagues_finance  live(db-business.mongo) vs live(drill-leagues_finance-20261119T100729Z)
  compared 11 collections, live 186 documents / restored 186 documents (restore is 0 documents behind live)
dbops: ok  drill check: collection set identical, no populated collection empty in the restore
```

Full log: `/home/cda/.restore-drills/logs/leagues_finance-20261119T100727Z.log`

---

