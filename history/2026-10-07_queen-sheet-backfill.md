# 2026-10-07 queen: Sheet backfill (plan Task 10) on prod

Ledger Sheet `1yLKEp-dQw7Etz6n-XVoRi8nPXGhLqFcDVcTN6nVrLlk` imported into prod
queen (`queen.bumbleflies.de`) without renumbering or re-filing PDFs.

## Problem

queen had no import path: `invoices.createDraft` always allocates a new
`YYYYMMDD-NN` number and `markSent` enqueues PDF filing, so clicking the Sheet
into the UI would have renumbered every invoice (breaking Verwendungszweck
reconcile for open ones) and duplicated PDFs in Drive.

## Solution

| PR | Change |
|----|--------|
| bumbleflies/queen#11 (v0.4.0) | `admin.importSheet` — CSV per tab → plan (German amounts/dates, `%` VAT, period normalisation), idempotent apply (skip existing by `customerNumber`/`invoiceNumber`), totals recomputed + compared, parity report, counters advanced with `$max`, `Invoice.importedPaid` |
| dachrisch/servyy-container#176 | queen on **dev** watchtower scope (5 min poll instead of 2 h) |
| bumbleflies/queen#15 (v0.5.1) | Drive lookup: year subfolders + `Gebucht - ` prefix |
| bumbleflies/queen#17 (v0.6.0) | `admin.linkDriveFiles` — attach known Drive file ids (never overwrites) |

CSVs were moved from the Sheet tab to the queen tab via `postMessage` in the
browser (user-approved) and posted to the endpoint with the user's session;
no customer data on disk or in git. Browser tabs closed afterwards.

## Results (prod)

- Import: 15 clients, 25 invoices, 39 lines; 0 errors, 0 total mismatches,
  `parity.ok: true` (counts + gross per year/state identical to the Sheet).
- States: 14 paid (`importedPaid`, no `paidAt`), 7 sent, 3 draft, 1 canceled.
- Warnings: `20230511-01` empty positions numbered 1–6; `20250821-01` canceled
  in the Sheet without a credit note (imported as canceled, no Storno).
- Drive: 22/22 issued invoices linked via `linkDriveFiles` (ids looked up with
  the Drive connector). Duplicates resolved: `20240821-01` → "Mercateo" file
  (matches Sheet name), `20250106-01` → booked (`Gebucht - `) copy.

## Known issues / follow-ups

- OAuth scope is `drive.file`: queen cannot see PDFs it did not create, so the
  automatic lookup in `importSheet` will never resolve legacy PDFs.
  Re-imports need `linkDriveFiles` again for new Sheet invoices.
- Imported paid invoices have no `paidAt` → excluded from
  `reports.revenueByYear` (by design, plan Task 10).
- Sheet stays source for LeagueSphere invoices until Task 11; re-run the
  import (idempotent) to pick up new Sheet rows.
- `docker_service` role never pulls images and servyy-test has no
  watchtower → test stays on cached `:latest` unless pulled manually.
- Ofelia may need a restart after watchtower recreates `finance.queen`
  (known quirk) for the 07:30 reconcile job.

## Verification

```
ssh servy.lehel.xyz 'docker exec finance.queen grep version package.json'   # 0.6.0
curl -s https://queen.bumbleflies.de/health                                 # ok
# UI: /invoices shows 25 invoices; 22 with Drive link, 3 drafts without
```
