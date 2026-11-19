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

