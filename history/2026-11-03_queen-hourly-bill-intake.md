# 2026-11-03 queen: bill intake hourly instead of once a day

Queen's bill intake got its Ofelia job in #256 (daily, `0 15 7 * * *`, 15 min
before the reconcile). That still leaves a bill that arrives in the morning on
the Belege tab only the next day. `finance/docker-compose.yml` now runs it
hourly, `0 * * * *`, at minute 0 so the 07:00 pass still precedes the 07:30
reconcile.

Intake is idempotent per (message, attachment) and per content hash, so an
hourly pass is one Gmail list call and files nothing twice. A Bull repeat
schedule would keep a worker process alive between runs for no benefit, so the
job stays an Ofelia `job-exec` of `dist/src/server/cron/billIntake.js`
(tsconfig `rootDir: "."` → the path is `dist/src/…`, same trap as #169).

## Queen side

`bumbleflies/queen#242` (merged) sends one summary mail back to
`bills@bumbleflies.de` per run that actually filed something, linking
`…/finance?tab=bills`. A run with nothing new sends nothing, so the hour
interval is quiet.

## Notes

- The mail needs the `gmail.send` scope. The cron credential is the admin who
  last saved the Drive settings, so **that admin must sign in with Google once
  after this deploy**. Until then intake keeps working and only the mail is
  skipped (`Bill intake confirmation not sent: …` in the Ofelia log).
- The job exits non-zero when a bill could not be read (`failed > 0`), so a
  broken attachment shows up as a failed Ofelia run and is retried next hour.
