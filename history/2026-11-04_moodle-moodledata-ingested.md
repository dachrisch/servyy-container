# Moodle `moodledata` ingested — corrected export verified byte-for-byte

**Date:** 2026-11-04
**Status:** ✅ **Imported** into `m.leaguesphere.app` on `servy.lehel.xyz`; DB untouched
**Relates to:** `2026-11-03_moodle-moodledata-ascii-mangled.md` (the rejected export),
[docs/plans/2026-10-27-moodle-offd-hosting.md](../docs/plans/2026-10-27-moodle-offd-hosting.md) (Task 5)

## The corrected export

Christoph re-exported after the ASCII-mode rejection. This time **every file was verified against
its own content hash before anything was touched** — that check, not the file count, is the gate:

| Check | Result |
|---|---|
| Archive | `moodledata.tar.gz`, 5,960,384,576 B, 2026-11-04 10:48, `gzip -t` rc 0, upload finished |
| sha256 | `4351b115fd6702f945a8dcee1dac2f3d395b45f3a93f47e92cb800bf942f3608` |
| Payload | 11,438 files / 5.77 GiB, 15,934 dirs |
| **sha1 vs filename** | **9,498 / 9,498 `filedir` files OK, 0 bad** (streamed straight out of the tar — no extract needed) |
| Coverage vs prod DB | all 9,317 `mdl_files.contenthash` values present → 0 missing |
| Structure | no symlinks/hardlinks/devices, no absolute or `..` paths; dirs `filedir lang models secret environment diag` + `.htaccess` |
| Orphans | 181 files / 219.5 MiB uploaded after the 2026-10-28 dump (no DB rows yet) |

Two benign surprises, both investigated rather than assumed: `filedir/warning.txt` is Moodle's own
"Do not manually move or rename files here" note, and `moodledata/test.html`
(`<h1>hello world!</h1>`) is Christoph's binary-mode self-test — a reasonable thing to send with a
re-export.

Second tell that the export was fixed: mtimes are the originals (2021/2024/2026). The mangled
archive had every mtime equal to its download time.

## What was done

1. Fresh rollback image of the *current* dataroot (it had 14 h of cache/session activity since
   yesterday's snapshot): `pre-import-dataroot-20261104.tar.gz`; yesterday's was dropped.
   Confirmed nobody had uploaded real content meanwhile — `filedir` still held the same 321 files.
2. Copied the archive to the Storage Box and verified the copy's sha256 matched. **First attempt
   failed**: `mv` died with `Bad address` (kernel cifs writeback trace) after 271 MB; a plain `cp`
   retry completed at 324 MB/s and hashed correctly. Worth remembering — this CIFS mount has thrown
   EFAULT on a large single-stream write before.
3. Source archive removed from the jail home (5.55 GiB freed), then `moodle.moodle` stopped and the
   six content dirs extracted into `…/data/moodledata` — the path that was wrong on 2026-11-03.
4. `chown -R 65534:65534` + dirs `2770`; restarted; `purge_caches.php`; `cron.php` (both clean).

## Verification after the fact

| Check | Result |
|---|---|
| `filedir` files on disk | 9,499 (9,498 imported + `warning.txt`) |
| DB hashes missing on disk | **0** |
| `mdl_files.filesize` cross-check, 9,316 rows | **0 mismatches** (the mangled export showed 9,068/9,316) |
| sha1 of the 10 largest files (up to 338 MB) | 10/10 OK |
| Moodle's own API: `get_file_by_id()` + `get_content_file_handle()` | largest 10: 10/10 · random 40: 40/40 |
| **HTTP end-to-end** | logged in as admin, fetched a `mod_resource` PDF through `pluginfile.php` → **200 `application/pdf`, 29,375,166 B**, `%PDF-1.3`, and the body's sha1 equals the DB `contenthash` exactly |

The last row is the one that matters: `pluginfile.php` served the byte-identical original. The
404s on images/PDFs/SCORM are gone.

## Stopgap backups (restic-moodle still does not exist)

Both written to `/mnt/storagebox/moodle-import/` and integrity-checked by reading them back:

- `moodledata-content-20261104.tar.gz` — 5.6 GB, 27,369 entries, `gzip -t` OK. Persistent dirs only
  (`filedir lang models secret environment diag .htaccess`); caches/sessions/temp excluded on
  purpose.
- `moodle-db-20261104.sql.gz` — 129 MB, `gzip -t` OK, **497 tables** (`mariadb-dump
  --single-transaction --quick --routines --events`). Note this is the *first ever* backup of the
  Moodle database — it had none.
- `moodledata-20261104.tar.gz` — the untouched source archive, kept for provenance.

## Still open

1. **The DB dump is still 2026-10-28.** 181 files on disk (219.5 MiB) have no DB rows, and seven days
   of DB activity (posts, enrolments, exam attempts) are missing. The instance is now complete as a
   *rehearsal*, not as a cutover candidate. A fresh `mysqldump` is required — and when it is
   imported, the targeted wwwroot search-replace from 2026-10-28 (~134 rows in 6 columns) has to be
   re-run against the new dump, because the image only fixes `$CFG->wwwroot`, not teacher-entered
   absolute links.
2. **`restic-moodle` (Task 7)** — the plan's requirement is a real scope with an executed restore
   drill before cutover. Today's two tarballs are a stopgap with no retention policy and no
   automation. This is now urgent: 5.9 GB of production content lives on one disk with only manual
   copies.
3. **`PLUGINS=enrol_waitlist`** — 35 courses use the `waitlist` enrolment method; the plugin is still
   not installed at boot.
4. Disk: 11 GiB free on `/` (86 %) after the import; the 1.62 GB DB plus this content is the floor now.
