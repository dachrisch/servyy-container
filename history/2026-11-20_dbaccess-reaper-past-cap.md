# db-access reaper dropped every new session as `past-cap` within 5 minutes

**Date:** 2026-11-20
**Branch:** `fix/dbaccess-reaper-past-cap`

## Symptom

`https://www.leaguesphere.app/dbaccess/requests/5/` (prod, `5eradmin`):

| when (UTC) | what |
|---|---|
| 08:00:49 | requested, ttl 8 h — UI says "hard cap 20.11.2026 17:00" |
| 08:51:00 | approved by `chrisd` |
| 08:51:15 | sidecar activated `dbeaver_prod_5eradmin` |
| 08:54:38 | revealed |
| 08:55:05 | **`reaper` dropped — `past-cap`** |

54 minutes after the request, 3 m 50 s after activation. Request 4 that morning died the
same way (activated 06:04:04, dropped 06:05:05 `past-cap`), and again after a re-mint
(activated 07:18:27, dropped 07:20:05 `not-active`).

## Root cause

The reaper judged the account by **every row the person had ever filed**, not by the row
that backs it:

```sql
SELECT CASE
         WHEN COUNT(*) = 0 THEN 'no-request-row'
         WHEN SUM(state IN ('active','revoke_requested','expired')) = 0 THEN 'not-active'
         WHEN MIN(created_at) < NOW() - INTERVAL ${CAP_H} HOUR THEN 'past-cap'
         ELSE 'ok'
       END
  FROM `${DB}`.`dbaccess_request`
 WHERE db_user='${user}';          -- ← whole history
```

`db_user` is deterministic (`dbeaver_prod_<handle>`) and **stays on dropped rows**, so the
ledger keeps one person's entire history under one key. `MIN(created_at)` therefore returned
request 3, filed **2026-11-13 10:41:29** — 166 h old — and the cap check fired no matter how
young the live session was. Measured on prod after the fact, with request 5 treated as live:

```text
old query → past-cap        (driven by MIN(created_at) = 2026-11-13 10:41:29)
new query → ok
```

This is why the feature looked healthy on 13.11. and failed from the second session on: the
first session for a person has no older row to be judged by.

The second failure mode in the same query: a row in `approved` counted as "not active", so
an account could also be dropped in the window between `CREATE USER` and the sidecar's
`UPDATE … state='active'` — which is what request 4's 07:20:05 `not-active` drop was. The
session-kill pass in the same script already spares `approved`; the verdict did not agree
with it.

## Fix

`roles/ls_dbeaver_access/templates/ls-db-access-reap.sh.j2` — the cap is measured only over
rows that currently back the account, and `approved` is part of that live set:

```sql
  FROM `${DB}`.`dbaccess_request`
 WHERE db_user='${user}'
   AND state IN ('approved','active','revoke_requested','expired');
```

Consequences worth knowing:

- the cap still starts at `created_at` (request time), so approval latency comes out of the
  TTL — unchanged and intended: the host owns the clock, never `expires_at`;
- an account whose every row is `dropped` still reports `no-request-row` (nothing live), the
  same wording as an account with no row at all;
- no production data was touched: request 3's row stays as audit history and simply stops
  being considered.

## Test

`ansible/tests/dbaccess_reap/test_reap_verdict.py` renders the real template and pins the
regression without a database: the verdict's `WHERE` must restrict rows to the live states
before `MIN(created_at)` is applied, `approved` must be in that set, and the cap must remain
`${CAP_H}`. Wired into CI (`test-custom-modules`). `bash -n` on the rendered script for both
prod and stage stacks passes.

Run: `cd ansible/tests/dbaccess_reap && python -m unittest -v test_reap_verdict`.

## Rehearsal against the deployed script (stage)

`db-nonprod.mariadb` / `leaguesphere_stage`, 2026-11-20 10:15Z, after the play ran. Two
ledger rows for one handle: a `dropped` row created **200 h ago** (the poison) and an `active`
row created now; account `dbeaver_prod_rehearsal@192.168.16.%` created by hand.

```text
=== sweep 1: live row fresh, poison row 200 h old ===
no drop logged
after sweep 1: account=1 state=active

=== sweep 2: live row aged to 9 h ===
ls-db-access-reap[leaguesphere_stage]: dropping dbeaver_prod_rehearsal@192.168.16.% (past-cap)
after sweep 2: account=0 state=dropped
```

The old query drops sweep 1 as `past-cap` (that is the bug); the deployed one keeps the
session and still ends it at the cap. Rehearsal rows and the account were removed afterwards
(`rehearsal_rows_left 0`, `rehearsal_account_left 0`).

## Rollout — done

```bash
cd ansible && ./servyy.sh --limit servy.lehel.xyz --tags ls.dbeaver.reap
ssh cda@lehel.xyz 'sudo systemctl start ls-db-access-reap.service; sudo journalctl -u ls-db-access-reap -n 20'
```

`changed=1` (the reap script only; service/timer already current). Subsequent 5-minute sweeps
(11:00-11:14Z) finished clean, `mysql.user` holds no `dbeaver_prod_*` account, and no drop was
logged. Rollback is the previous revision of the same template — the role copies one file.

## Do not undo

- Do not put `MIN(created_at)` back over unfiltered rows "for the cap": that is the bug, and
  it silently neuters the feature for anyone with a session older than 8 h.
- Do not remove `approved` from the live set: it is the mint window, and the kill pass in the
  same script depends on that reading.
