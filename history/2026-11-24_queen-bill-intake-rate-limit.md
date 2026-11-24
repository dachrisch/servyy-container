# queen bill intake burned the shared Gmail quota — 5-field Ofelia schedule

**Date:** 2026-11-24
**Status:** ✅ Accepted — deployed to `servy.lehel.xyz` and verified
**Relates to:** [history/2026-11-03_queen-hourly-bill-intake.md](2026-11-03_queen-hourly-bill-intake.md),
[finance/docker-compose.yml](../finance/docker-compose.yml)

## Context

Queen's bill intake kept failing with a raw toast:
`User-rate limit exceeded. Retry after <now + 15 min>`. It is a Gmail API HTTP 429
(per-user quota) on the shared admin Google credential used by all intake jobs —
not a queen intake bug (`describeIntakeError()` in `src/server/jobs/billIntake.ts`
passes the 429 through unchanged). A manual "Fetch now" around 10:04:35 inherited
the same exhausted quota (its retry-after was 10:19:35), which is why the button
looked broken too.

Root cause: the `bill-intake` Ofelia label in `finance/docker-compose.yml` was

```text
ofelia.job-exec.bill-intake.schedule=0 * * * *
```

Ofelia parses **6 fields, seconds first** (as the sibling jobs show:
`0 30 7 * * *` = 07:30 daily, `0 0 5 * * *` = 05:00 daily). A 5-field
`0 * * * *` is read as *second 0 of every minute*, not *minute 0 of every hour*.
The intended hourly expression is `0 0 * * * *`.

Live evidence from `portainer.ofelia` on `servy.lehel.xyz` before the fix:

- jobs started at 09:37, 09:38, … 10:18 — once per minute, ~60× the intended rate;
- every run ended `Bill intake failed: User-rate limit exceeded. Retry after <now + 15 min>`;
- the registered schedule in the Ofelia startup log was `"0 * * * *"`;
- `src/server/cron/billIntake.ts` runs bill intake **and** `expensePass()` in one
  job, so Drive/Gmail were both hammered ~60× more often since `52d5d668`
  (2026-11-03).

The 2026-11-03 history entry recorded the hourly move with the literal expression
`0 * * * *` — wrong for Ofelia. That typo is what introduced the runaway job.

## Decision

1. Change the label in `finance/docker-compose.yml` to the true hourly
   `0 0 * * * *` and add a comment spelling out the 6-field, seconds-first format
   so the next edit does not repeat this.
2. Recreate `finance.queen` so the container carries the new label, then restart
   `portainer.ofelia` — Ofelia reads labels **only at startup** (see the gotcha in
   the 2026-11-03 entry). Check the `New job registered` line before trusting the
   new schedule.
3. No queen-side change: the 429 passthrough is correct behaviour, the quota is
   the thing to fix. A human-readable backoff message remains an optional,
   separate follow-up in queen.

## Consequences

### Positive
- ✅ Bill intake runs once an hour again; the shared Gmail quota is no longer
  burned by the scheduler, so manual "Fetch now" works.
- ✅ The 07:00 pass still precedes the 07:30 reconcile.
- ✅ The format gotcha is documented next to the label.

### Negative / Tradeoffs
- ⚠️ Requires a scheduler restart, not just a container recreate.
- ⚠️ The quota may take up to ~15 min to recover after the last 429.

## Implementation Details

**Files modified:**
- `finance/docker-compose.yml` (MODIFY — label `0 * * * *` → `0 0 * * * *` + format comment)
- `history/2026-11-03_queen-hourly-bill-intake.md` (MODIFY — correction pointer)
- `history/2026-11-24_queen-bill-intake-rate-limit.md` (NEW)

**Commit:**
- `f60a50f0` fix(finance): make queen bill-intake Ofelia schedule truly hourly

## Deployment & Verification (prod, 2026-11-24)

Applied on `servy.lehel.xyz` (the running queue is prod; explicit fix approval given).
The checkbox order matters — recreating the container alone does **not** change the
registered schedule.

1. `git -C /home/cda/servyy-container fetch origin master && git merge --ff-only origin/master`
   → `f60a50f0` (server's tracked tree was clean; untracked `.env` files untouched).
2. `cd finance && docker compose -p finance config` showed the rendered label
   `ofelia.job-exec.bill-intake.schedule: 0 0 * * * *` before touching the container.
3. `docker compose -p finance up -d queen` recreated only `finance.queen`
   (`f7c6463…` → `fc8a385…`, running, `health=healthy`); live label confirmed
   `0 0 * * * *`.
4. `docker restart portainer.ofelia` — after the 10:20:00 restart the log showed:

   ```text
   New job registered "bill-intake" - "node dist/src/server/cron/billIntake.js" - "0 0 * * * *"
   Starting scheduler with 5 jobs
   ```

5. Post-check at 10:22:44Z: last `bill-intake` start was still **10:19:00** — no
   runs at 10:20, 10:21 or 10:22, and no new `User-rate limit exceeded` lines.
   The final 429 was at 10:19 with `Retry after 10:34:06`; the next scheduled run
   is 11:00, by which time the shared quota will have recovered.

   Verification commands:

   ```bash
   ssh servy.lehel.xyz 'docker inspect -f "{{index .Config.Labels \"ofelia.job-exec.bill-intake.schedule\"}}" finance.queen'
   ssh servy.lehel.xyz 'docker logs portainer.ofelia 2>&1 | grep "New job registered" | tail -5'
   ssh servy.lehel.xyz 'docker logs portainer.ofelia 2>&1 | grep "Started - node dist/src/server/cron/billIntake.js" | tail -5'
   ```

## Key Learnings

1. **Ofelia schedules have 6 fields, seconds first** — `0 30 7 * * *` is 07:30,
   `0 0 * * * *` is hourly. A familiar 5-field crontab expression is silently
   misread, and a missing field turns "hourly" into "every minute".
2. **Check the scheduler's own registration log, not just the container label.**
   Ofelia reads labels only at startup; `docker restart portainer.ofelia` is
   mandatory after any `ofelia.*` label change (same trap as 2026-11-03).
3. **A shared credential magnifies a scheduling bug** — one bad label hit Gmail
   and Drive ~60× more often, so even the unrelated manual "Fetch now" path
   inherited the 429. The toast was a symptom, not the cause.
4. **Cross-check sibling labels in the same compose file** — two other jobs
   already used the correct 6-field form; comparing against them identified the
   bad expression immediately.

## Alternatives Considered

- **Add Gmail-429 backoff / friendly message in queen** — useful, but it only
  hides the symptom while the runaway job keeps burning quota. Deferred as a
  separate follow-up, not part of this fix.
- **Disable the Ofelia job until the quota recovers** — unnecessary: correcting
  the schedule stops new calls immediately and the quota self-recovers in ~15 min.

## Related Decisions

- 2026-11-03 `queen: bill intake hourly instead of once a day` — moved intake to
  hourly but recorded the wrong expression; corrected here.
