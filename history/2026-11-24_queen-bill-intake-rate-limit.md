# queen bill intake burned the shared Gmail quota — 5-field Ofelia schedule

**Date:** 2026-11-24
**Status:** Proposed
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

## Deployment

To be filled in after rollout on `servy.lehel.xyz`.
