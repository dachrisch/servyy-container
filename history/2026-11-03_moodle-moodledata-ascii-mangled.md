# Moodle `moodledata` arrived — and was rejected: the export is ASCII-mangled

**Date:** 2026-11-03
**Status:** ❌ **Import rejected, ingest rolled back** — servy is back to its pre-ingest state
**Relates to:** [docs/plans/2026-10-27-moodle-offd-hosting.md](../docs/plans/2026-10-27-moodle-offd-hosting.md)
(Task 5), `2026-10-28_offd-dump-measured-and-rehearsed.md`

## What arrived

`moodledata.tar.gz` in the `leaguesphere` jail home on servy (5,951,748,293 B, 2026-11-03 21:58,
sha256 `2e16bcbf…f3e9`) — the file half of Christoph's OFFD export that has been missing since the
DB import. Measured before touching anything:

| | |
|---|---|
| Container integrity | `gzip -t` rc 0, tar readable end to end, no uploader session still open |
| Payload | 11,434 files / 5.71 GiB: `filedir` 9,496, `lang` 1,937, plus `models`, `secret`, `environment`, `diag` |
| Transient dirs | none (`cache`, `sessions`, `temp`, `trashdir` absent) — safe to merge into a live dataroot |
| **Coverage vs DB** | all 9,317 distinct `mdl_files.contenthash` values present **by name** → 0 missing |
| Newer than the DB | 178 files (135 MiB) uploaded after the 2026-10-28 dump (orphans today) |

## The finding

The green coverage check was misleading. Every `filedir` file is named after the **SHA1 of its
content**, so hashing each file against its own name tests the bytes, not just the set. That test
fails on **9,247 of 9,496 files**:

| category | files | note |
|---|---|---|
| intact | 249 | no LF in the content at all |
| exactly repairable | 6,100 | CRLF→LF reproduces the expected sha1 (text/lang) |
| **damaged beyond repair** | **3,147** | 2,980 DB-referenced = **5.63 GiB** |

Cause: the export was downloaded over FTP in **ASCII / "auto" mode**, so every bare LF (0x0A)
became CRLF (0x0D 0x0A) *before* the tar was created. Evidence: for a 4,034-byte JSON file the DB
says 3,910 and the archive has 124 CRs; a 14-page PDF has 15,806 CRs and hashes to
`51cf4770…` instead of its filename `00178b7c…`.

The unrepairable 5.63 GiB is exactly the payload that matters — 1,688 PNG (291 MiB), 938 PDF
(821 MiB), 84 MP4 (1.8 GiB), 25 PPTX (1.8 GiB), 41 `.mbz` (138 MiB), 7 ZIP (537 MiB) — dominated by
`assignfeedback_editpdf` (1,846) and `assignsubmission_file` (575), i.e. student submissions and
graded PDF annotations. LF→CRLF cannot be inverted when the original already contained CR bytes
(true of every image/PDF/ZIP/MP4/PPTX), so these cannot be rebuilt from this archive by any script.

## What was done, in order

1. Snapshotted the live dataroot (67 MB) to `/mnt/storagebox/moodle-import/`.
2. Moved the archive to the Storage Box — `/` was at **7.8 GiB free (90 %)**; extracting in place
   needed 11.3 GiB. (Note: `docker system df` advertises 27.5 GB "reclaimable" but only ~1.3 GB is
   genuinely unused — shared layers account for the rest. Do not plan a prune as a space fix.)
3. Stopped `moodle.moodle`, extracted `filedir lang models secret environment diag` from the archive
   on the Storage Box (51 s), `--no-same-owner`, then `chown -R 65534:65534` + dirs `2770`.
   *(First attempt used `-C .../data` with `--strip-components=1` and landed the trees one level too
   high; caught by the file counts, removed, re-extracted against `.../data/moodledata`.)*
4. Verified: 9,496 files on disk, 0 DB hashes missing, 0 files with the wrong owner — and then the
   per-file SHA1 check above, which is what caught the corruption. A `mdl_files.filesize`
   cross-check showed 9,068 of 9,316 mismatching, which is what sent me looking.
5. **Rolled back**: removed the extracted trees, restored `pre-import-dataroot-20261103.tar.gz`
   (321 filedir files, 1,722 lang files, 67 MB, original ownership including the pre-existing
   `sodium.key`), restarted the container. `m.leaguesphere.app` → 200, healthy. The DB was never
   touched by any of this.

## What Chris needs to send instead

Binary end-to-end, plus verification on his side before upload — instructions and a check script are
in `/mnt/storagebox/moodle-import/README-CORRUPT-EXPORT.md` on servy:

- create the tarball **on the hosting server** (KAS file manager → Compress, or SSH `tar -czf`) and
  download the `.tar.gz` itself; or FTP-mirror in **Binary** mode (never "Auto");
- verify `sha1sum(<file>)` == its filename for every file in `filedir/*/*/*` → must be 0 bad;
- **also send a fresh `mysqldump`** — the DB dump is 2026-10-28, the files 2026-11-03: five days of
  posts/enrolments/attempts are missing, and 178 archive files postdate the dump.

## Side findings worth keeping

- **`sodium.key` differs from the source site.** Prod's blank-instance key replaced nothing of value
  (prod `filedir` is a 320/321 subset of the archive; no locally-created DB-referenced files), but
  the imported `mdl_oauth2_issuer` row `leaguemanager` stores an encrypted `clientsecret` that only
  **Christoph's** key can decrypt — so the correct ingest must also restore
  `moodledata/secret/key/sodium.key` from the export. Today that secret is undecryptable.
- **`restic-moodle` still does not exist** (Task 7). Home restic explicitly excludes
  `servyy-container/moodle/data`, so once real data lands it has zero backup until that scope is
  built. Take a one-off tarball to the Storage Box immediately after a successful import.
- Disk is not the constraint it looked like: 5.71 GiB of files + 1.62 GB DB fit comfortably once the
  archive lives on the Storage Box (7.6 GiB free afterwards); no volume purchase needed.

## Cleanup (same day)

- **No repair was attempted.** The CRLF→LF fix would have recovered 6,100 small text/lang files and
  still left 5.63 GiB of the payload corrupt; a mixed, half-working dataroot is worse to reason about
  than a clean pre-import one, and the whole tree is replaced by the corrected export anyway. The
  recipe stays documented in `README-CORRUPT-EXPORT.md` in case it is ever needed for a subset.
- **The invalid archive was deleted** from the Storage Box
  (`/mnt/storagebox/moodle-import/moodledata.tar.gz`, 5.6 GB) to make room for the corrected export
  — its sha256 and every measurement in this entry are retained, and the file has no further use
  (nothing in it is losslessly recoverable). Storage Box back to ~618 GB free.
- Verification scratch files removed from `/tmp` on servy; nothing was left in the jail home.
- Kept: `pre-import-dataroot-20261103.tar.gz` (13 MB, exact image of the current dataroot — cheap
  insurance) and `README-CORRUPT-EXPORT.md` (the instructions to send Christoph).

End state for the day: `m.leaguesphere.app` healthy on the pre-ingest dataroot (67 MB, 321 filedir
files), DB untouched at 1.62 GB, `/` at 14 GiB free, and the ball with Christoph for a binary-safe
re-export plus a fresh `mysqldump`.
