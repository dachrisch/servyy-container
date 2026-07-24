# LeagueSphere — gd874 Stage→Prod Restore (Runbook / Layout)

> Surgical recovery of **gameday 874**'s wiped game data, promoting the dataset
> **already restored and verified on stage** into **prod**. Incident:
> [dachrisch/leaguesphere#1550](https://github.com/dachrisch/leaguesphere/issues/1550).
>
> **Status: DESIGN / layout — not yet executed against prod.** Decisions below are the
> recommended defaults, pending final confirmation before a role is run.
>
> Prerequisite (done): stage holds the pre-wipe snapshot via the `ls_stage_restore`
> role — PR [servyy-container#42](https://github.com/dachrisch/servyy-container/pull/42).

---

## 1. What was lost and what we restore

When user 292 unlocked and re-published gd874, `CanvasPublishService.apply()` ran
`Gameinfo.objects.filter(gameday=self.gameday).delete()`
(`gamedays/service/canvas_publish_service.py:38`) and rebuilt the games from the stale
designer canvas. Everything below `CASCADE`s off `Gameinfo`, so all of it went with the
delete. Prod currently holds **new empty rows (gameinfo 9326–9337)**; the correct data
(old IDs **9184–9193**) lives only in the pre-wipe backup, now on stage.

Complete set of gameday-scoped tables to restore (all Django-default table names):

| Table | Link to gameday 874 |
|---|---|
| `gamedays_gameinfo` | `gameday_id = 874` — the game rows |
| `gamedays_gameresult` | `gameinfo_id IN (…)` — scores + home/away **team** (fixes Schloßberg→Nürnberg) |
| `gamedays_gameofficial` | `gameinfo_id IN (…)` |
| `gamedays_gamesetup` | `gameinfo_id IN (…)` |
| `gamedays_teamlog` | `gameinfo_id IN (…)` |
| `gamedays_playerachievement` | `game_id IN (…)` |

`Team` rows are `on_delete=PROTECT`, so they were never deleted — restoring the old
`gameresult`/`teamlog` rows re-links the correct teams with no team-table changes.

Optionally also restored: `gamedays_gamedaydesignerstate` for gd874 (see Decision 3).

---

## 2. Design decisions (recommended defaults)

1. **Source of truth = stage.** Promote exactly the dataset validated on stage, rather than
   re-reading the raw backup. (Alternative: dump gd874 straight from a throwaway container
   over `/home/cda/ls-recovery-prewipe-c92db866`, the way `ls_stage_restore` does — use this
   only if stage no longer holds the snapshot.)
2. **Preserve original primary keys.** Delete the empty new rows (9326–9337) and re-insert the
   old rows with their original IDs (9184–9193). Child FKs in the dump match as-is; IDs stay
   stable. (Alternative: fresh auto-increment IDs + FK remap — more complex, no benefit.)
3. **Also restore the designer canvas.** Overwrite prod's stale `GamedayDesignerState`
   (shows Nürnberg) with the pre-wipe `state_data` so a future publish can't re-introduce the
   wrong team. [#1546](https://github.com/dachrisch/leaguesphere/issues/1546) (unlock blocked
   when results exist) is the backstop; this removes the latent wrong-team payload too.

---

## 3. Mechanism — `ls_prod_restore` role (tag `ls.prod.restore`)

Mirrors `ls_stage_restore`'s structure. Tag-only; **never** part of a default `ls` run.
Names below use the same `stage_app` / `prod_app` vars loaded from
`roles/ls_app/vars/secret_{stage,main}.yaml`.

### Step 0 — Preconditions (assert, fail fast)
- Prod is in **maintenance mode** (write endpoints frozen) — confirm before starting.
- Stage MySQL container healthy and holds gd874 with the old IDs
  (`SELECT COUNT(*) FROM gamedays_gameinfo WHERE gameday_id=874` on stage > 0, min(id) < 9326).
- Prod `leaguesphere.db` container healthy.

### Step 1 — Rollback snapshot of current prod state
Dump gd874's *current* prod rows (the empty 9326–9337 set + the stale canvas) to a host file
**before** any change, so the operation is reversible:
```bash
# on lehel.xyz
GI=$(docker exec leaguesphere.db mariadb -uroot -p"$ROOT" -N web35_db8 \
  -e "SELECT GROUP_CONCAT(id) FROM gamedays_gameinfo WHERE gameday_id=874")
docker exec leaguesphere.db mariadb-dump -uroot -p"$ROOT" --no-create-info --complete-insert \
  web35_db8 \
  gamedays_gameinfo   --where="gameday_id=874" \
  > /home/cda/ls-gd874-prod-prerestore-$(date +%s).sql
# (repeat --where="gameinfo_id IN ($GI)" for each child table; canvas via gameday_id=874)
```

### Step 2 — Scoped export from stage (source of truth)
Resolve gd874's gameinfo IDs on stage, then dump only those rows, data-only, self-contained
INSERTs (`--no-create-info --complete-insert`):
```bash
GI_STAGE=$(docker exec leaguesphere_stage.mysql mariadb -uroot -p"$STAGE_ROOT" -N <stage_db> \
  -e "SELECT GROUP_CONCAT(id) FROM gamedays_gameinfo WHERE gameday_id=874")

docker exec leaguesphere_stage.mysql mariadb-dump -uroot -p"$STAGE_ROOT" \
  --no-create-info --complete-insert <stage_db> \
  gamedays_gameinfo        --where="gameday_id=874"          > /tmp/gd874.sql
# append, each into the same file:
#   gamedays_gameresult      --where="gameinfo_id IN ($GI_STAGE)"
#   gamedays_gameofficial    --where="gameinfo_id IN ($GI_STAGE)"
#   gamedays_gamesetup       --where="gameinfo_id IN ($GI_STAGE)"
#   gamedays_teamlog         --where="gameinfo_id IN ($GI_STAGE)"
#   gamedays_playerachievement --where="game_id IN ($GI_STAGE)"
#   gamedays_gamedaydesignerstate --where="gameday_id=874"   (Decision 3)
```

### Step 3 — Apply to prod, one transaction, all-or-nothing
Prepend the delete + FK guards, then the stage INSERTs, then commit:
```sql
START TRANSACTION;
SET FOREIGN_KEY_CHECKS=0;
-- clears the empty new rows 9326–9337 and cascades their (empty) children
DELETE FROM gamedays_gameinfo WHERE gameday_id=874;
-- Decision 3: also replace the stale canvas
DELETE FROM gamedays_gamedaydesignerstate WHERE gameday_id=874;
--- <<< contents of /tmp/gd874.sql here >>>
SET FOREIGN_KEY_CHECKS=1;
COMMIT;
```
Piped into the prod container:
```bash
cat /tmp/gd874_apply.sql | docker exec -i leaguesphere.db \
  mariadb -uroot -p"$ROOT" web35_db8
```

### Step 4 — Verify (prod must match stage)
```sql
-- expect old IDs back (min < 9326) and non-zero scored results / teamlog
SELECT COUNT(*), MIN(id), MAX(id) FROM gamedays_gameinfo   WHERE gameday_id=874;
SELECT COUNT(*) FROM gamedays_gameresult gr JOIN gamedays_gameinfo gi ON gr.gameinfo_id=gi.id
  WHERE gi.gameday_id=874 AND (gr.fh IS NOT NULL OR gr.sh IS NOT NULL);
SELECT COUNT(*) FROM gamedays_teamlog tl JOIN gamedays_gameinfo gi ON tl.gameinfo_id=gi.id
  WHERE gi.gameday_id=874;
```
Compare each count to the same query on stage; the role fails if they diverge.

### Step 5 — (separate, manual) lift maintenance mode
`SiteConfiguration` is cached per-process (`LocMemCache`), so toggling `maintenance_mode`
requires an **app restart** to take effect. Do this only after Step 4 passes and a human has
eyeballed gd874 in the UI. Kept out of the role deliberately.

---

## 4. Safety properties

- **Scoped to `gameday_id=874`** everywhere — no other gameday can be touched.
- **Transaction** — delete + all inserts commit together or not at all.
- **Rollback point** — Step 1 dump reconstructs the pre-restore state if needed.
- **No concurrent writes** — prod is frozen in maintenance mode for the duration.
- **Tag-only, prod-explicit** — runs only under `--tags ls.prod.restore --limit lehel.xyz`.
- **Idempotency** — one-shot data fix, not idempotent by nature; the pre-flight ID check
  (Step 0/4) is the guard against double application.

## 5. Usage (once the role exists)

```bash
cd container/ansible && ./servyy.sh --tags ls.prod.restore --limit lehel.xyz
```

## 6. Open items before running

- [ ] Confirm the three Decisions in §2.
- [ ] Fill in the stage DB name (`stage_app.app.db_name`) and confirm stage still holds the snapshot.
- [x] Score columns confirmed: `gamedays_gameresult.fh` / `.sh` / `.pa` (`models.py:194-196`).
- [ ] Build `ls_prod_restore` role from this runbook; dry-run the export/verify on stage first.
- [ ] Human UI check of gd874, then lift maintenance (§Step 5).
