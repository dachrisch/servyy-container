# 2026-06-27 — Restic maintenance: include leaguesphere prod db repo in forget + check

## Problem

The MariaDB migration (Phase A) added a dedicated restic repo `restic-ls-db` for the
leaguesphere prod DB, backed up hourly. But the **forget/prune** and **integrity check**
maintenance scripts — owned by the `system` role, not the `restic` role that added the repo —
were never updated to cover it. On prod the db repo had **49 snapshots accumulating since
inception (2026-06-25) with zero pruned**, and was **never integrity-checked**.

Root cause: `roles/system/templates/restic_forget.sh.j2` and `restic_check.sh.j2` hardcoded
only `home` and `root`. The `db` repo lives in `roles/restic` (`vars/restic.yml` `restic.db`
block) and the two roles drifted.

## Solution

Added a `db` entry to both maintenance templates, gated on `restic.db.enabled | default(false)`
so hosts without the db repo are unaffected:

| File | Change |
|------|--------|
| `ansible/plays/roles/system/templates/restic_forget.sh.j2` | `{% if restic.db.enabled %}apply_retention "/etc/restic/env.db" "db"{% endif %}` |
| `ansible/plays/roles/system/templates/restic_check.sh.j2` | `{% if restic.db.enabled %}check_repo "/etc/restic/env.db" "db"{% endif %}` |

Branch: `fix/restic-maintenance-include-ls-db` (container repo). Deploy tag:
`system.restic.maintenance`.

## Test-first validation (servyy-test.lxd)

(Box was STOPPED; started via `lxc start servyy-test` for the test.)

- Deploy: `./servyy-test.sh -u ubuntu --tags system.restic.maintenance` → `ok=18 changed=2`.
- Rendered scripts include the `db` line; both pass `zsh -n`.
- `restic-check`: **`Repository check passed tag=db`** (9/9 snapshots, no errors).
- `restic-forget`: **`Retention applied successfully tag=db`**.
- home/root failed on test due to a pre-existing stale lock (home, from 2026-02-26) and a
  pre-existing root failure already seen on 2026-06-25 — both unrelated to this change.

## Prod deployment (lehel.xyz)

- Deploy: `./servyy.sh --tags system.restic.maintenance --limit lehel.xyz` → `ok=18 changed=2`.
- Rendered scripts include `db` line; pass `zsh -n`.
- `restic-check`: home **passed**, db **passed** (49/49 snapshots, no errors).
- `restic-forget`: db **`Retention applied successfully`** — snapshots **49 → 4**
  (oldest 2026-06-25, newest 2026-06-27), matching GFS `hourly:2/daily:2/monthly:3`.

## ⚠️ Pre-existing issue discovered (NOT this change; separate scope)

On **prod**, the `root` restic repo check/forget fail with
`Fatal: wrong password or no key found`. This predates this change — the same error appears in
`/var/log/restic/check.log` from **2026-06-21**. Means the prod root-filesystem backup repo
(`restic-root`) is currently inaccessible with the configured password, so root backups are
likely failing too. **Needs separate investigation** (verify `restic_password_root` /
`/etc/restic/env.root` vs the actual repo). home and db repos are healthy.

## Status

- Code change: ✅ done, validated test→prod. Uncommitted on branch (deploy reads working tree).
- DB backups now fully **working as designed**: hourly snapshots + retention + integrity check.
- Follow-up: (1) commit/PR the branch; (2) investigate the prod `restic-root` password failure.
