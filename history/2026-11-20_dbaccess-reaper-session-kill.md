# db-access reaper cut live sessions whose request was `active`

**Date:** 2026-11-20
**Branch:** `fix/dbaccess-reaper-session-kill`

## Symptom

`https://www.leaguesphere.app/dbaccess/requests/5/` (prod, `5eradmin`): the tunnel and
the minted account worked, but a session was cut a couple of minutes after it opened,
over and over:

| when (UTC) | what |
|---|---|
| 08:00:49 | requested, ttl 8 h — hard cap 16:00:49 |
| 10:18:44 | sidecar re-activated after a manual reset (new password) |
| 10:59:17 / 10:59:30 | `FAILED_CONNECT … 1045` from the tunnel — the client still held the pre-reset password |
| 11:08:11 | client reconnected successfully (pids 42386/42388) |
| 11:10:05 | reaper **killed both** as `no running request` — the request was `active` |
| 11:10:05 | journal logs the same pid twice; the second `KILL` answers `1094 Unknown thread id` |

So "cannot access" was two things: one stale credential right after the re-mint, and an
ongoing 5-minute kill loop for everyone with a request older than their first one.

The 1045 at 10:59 is client-side only (DBeaver saved credentials, account password had
been re-minted at 10:18:44); after re-revealing, the same credentials connected. TLS is
not required and was not the problem. A separate `1045` from `172.24.0.3` at 11:09:01 is
the `leaguesphere.app` container: the minted account only exists at `172.25.%`, so a test
from the app network always gets 1045 — it is not a supported path.

## Root cause

`roles/ls_dbeaver_access/templates/ls-db-access-reap.sh.j2`, the session-kill pass:

```sql
SELECT p.id, p.user
  FROM information_schema.processlist p
  LEFT JOIN `${DB}`.`dbaccess_request` r ON r.db_user = p.user
 WHERE p.user LIKE 'dbeaver\_prod\_%'
   AND (r.id IS NULL OR r.state IN ('revoke_requested','expired','dropped','failed'));
```

`db_user` is deterministic (`dbeaver_prod_<handle>`) and stays on every historical row,
so it is not a key. The join fanned one live session out into one row per past request,
and a single old `dropped` row satisfied the kill predicate. Measured on prod: request 3
(`dropped`, 2026-11-13) and request 4 (`dropped`, 06:05Z) made the live session of
request 5 (`active`) killable. The verdict query was already fixed to judge only the live
row (commit `f75a3e33`); this pass was not.

## Fix

The kill decision is now an existence test, not a join — a session survives if *any* row
backing the account is live:

```sql
SELECT p.id, p.user
  FROM information_schema.processlist p
 WHERE p.user LIKE 'dbeaver\_prod\_%'
   AND NOT EXISTS (
         SELECT 1 FROM `${DB}`.`dbaccess_request` r
          WHERE r.db_user = p.user
            AND r.state IN ('approved','active')
       );
```

A session whose every row is `dropped`/`failed`/`expired`/`revoke_requested`, or whose
rows are gone, is still killed. `reap_one`'s ledger `UPDATE` was narrowed from
`state <> 'dropped'` to the same live set, so a `failed` row is no longer overwritten as
`dropped` when an account is reaped.

## Test

`ansible/tests/dbaccess_reap/test_reap_verdict.py` renders the real template and adds
`SessionKillQueryTest`: the kill query must be `NOT EXISTS` (no `JOIN`), must read exactly
`('approved','active')` as live, must not mention the terminal states, and `reap_one`'s
update must target only live rows. CI already runs this suite (`test-custom-modules`).

Run: `cd ansible/tests/dbaccess_reap && python -m unittest -v test_reap_verdict`.

## Rehearsal against the deployed script (prod)

2026-11-20 11:20Z, timer paused, throwaway account `dbeaver_prod_rehearsal@172.25.%` and
two ledger rows: one `dropped` created 200 h ago (the poison) and one `active` created
now. A real session was held from `leaguesphere.db-access` (172.25.0.4).

```text
=== old deployed script ===
ls-db-access-reap[web35_db8]: killing session dbeaver_prod_rehearsal (pid 42689): no running request
after: no session                                        (bug reproduced)

=== new script, same rows ===
no drop, no kill
after: 42701 dbeaver_prod_rehearsal 172.25.0.4 Query     (session survives)

=== live row flipped to dropped, new script ===
ls-db-access-reap[web35_db8]: dropping dbeaver_prod_rehearsal@172.25.% (no-request-row)
after: no session, no account                            (safety net intact)
```

Rows and account were removed afterwards; the timer was restarted.

## Rollout — done

```bash
cd ansible && ./servyy.sh --limit servy.lehel.xyz --tags ls.dbeaver.reap   # changed=1
ssh servy.lehel.xyz 'sudo systemctl start ls-db-access-reap.service'
```

The deployed `/usr/local/sbin/ls-db-access-reap` carries `NOT EXISTS`; the manual sweep
finished clean and the timer is active. Request 5 was not touched: it stays `active`
until its 16:00:49Z cap, so no one lost or gained a session in the change.

## Do not undo

- Never judge a session by joining `dbaccess_request` on `db_user`. It is one person's
  history, not a key; any old row can then decide a live session.
- Keep `approved` in the live set: it is the window between `CREATE USER` and the row
  update.
- Keep the terminal states out of the existence test: the account must still be killed
  when no row backs it.

## Follow-up

Row 5 is `state='active'` but still carries `dropped_at=2026-11-20 08:55:05` from the
wrong `past-cap` drop; the manual reset path does not clear it. It does not affect access
(the reaper never reads `dropped_at`) but makes the ledger confusing; clear it in the app's
reset flow when that code is touched next.
