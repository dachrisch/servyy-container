# OFFD final drop landed, and the instance moved to `offd.de`

**Date:** 2026-11-13
**Status:** ✅ Imported and validated on servy; `SITE_URL`/router cutover in the same window; DNS last
**Relates to:** [docs/plans/2026-11-13-moodle-final-drop-release.md](../docs/plans/2026-11-13-moodle-final-drop-release.md),
[history/2026-11-10_moodle-waitlist-plugin-and-release-tooling.md](2026-11-10_moodle-waitlist-plugin-and-release-tooling.md),
[history/2026-11-04_moodle-moodledata-ingested.md](2026-11-04_moodle-moodledata-ingested.md)

## Context

Christoph put the old KAS site into maintenance mode in the morning and pulled the final pair: a
logical dump and a tarball of `moodledata`. Both landed on servy while we were still serving the
rehearsal hostname `m.leaguesphere.app`, which is what makes the drop safe — the instance can be
imported and verified end to end before anything public changes. DNS is the last step, by decision.

## Measured

| Artifact | Facts |
|---|---|
| `dump-OFFD-d037491e-202611130825.sql.gz` | 136 028 659 B, `sha256 15f67903…`, `gzip -t` OK, 497 tables, `mdl_` schema, 119 lines containing `offd.de/offd/moodle`, release `4.5.12 (Build: 20260608)` |
| `moodledata-2026-11-13.tar.gz` | 5 930 094 595 B, `gzip -t` OK (40 s), 11 445 files / 15 955 dirs, top level `moodledata`, `secret/key/sodium.key` = `c816ed65…` |
| Gate (`verify-offd-export.sh`) | **PASS** — 9 503 filedir files hash to their own name, 0 bad; 9 503/9 503 DB contenthashes present; **missing_on_disk 0, orphans_not_in_db 0** |
| Import | 9 524 filedir files extracted (25 uploads newer than the dump), 497 tables imported, 4.5.12 → **4.5.15** with no pending upgrade, **136 rows** rewritten `offd.de/offd/moodle` → root, → 0 remaining |

After the import: **4 263 users (4 143 active) · 120 courses · 41 002 file rows · 9 503
contenthashes · 14 active waitlist instances**. Christoph's instance had grown by 15 users and 16
courses since the 2026-10-28 dump we rehearsed on, which is why the rewrite count moved 134 → 136.

### Validated on the imported instance (`SITE_URL` still `m.leaguesphere.app`)

| Check | Result |
|---|---|
| Site | `/` 200, `<title>Startseite \| Flag Academy</title>`, `/login/index.php` 200 |
| Upgrade | `upgrade.php --is-pending` rc 0, release `4.5.15 (Build: 20261005)` |
| Plugin | `enrol: manual,guest,self,cohort,waitlist`, **14/14** active waitlist courses expose the method |
| Links | `offd.de/offd/moodle` rows: **0**; 114 rows now point at `https://offd.de/…` |
| Files on disk | 9 503 DB contenthashes vs 9 524 files: **missing_on_disk 0**, 21 orphans (19 pre-existing, 2 newer than the dump) |
| File bytes end to end | 29 375 166 B `mod_resource` PDF over HTTPS as logged-in admin → **200, sha1 == DB `contenthash`**, `%PDF-` |
| Pages | course view, `enrol/waitlist/edit.php`, `admin/plugins.php`, `course/index.php`, scheduled tasks — all 200 |
| Logs | 0 fatal / uncaught in the window |

The gate's `orphans_not_in_db 0` / `missing_on_disk 0` pair is the strongest evidence available that
the dump and the tarball were taken from the same state: every file in the archive is referenced by
the database, and every hash in the database exists in the archive.

## Decisions

1. **`--target-url https://offd.de` at import time.** The script rewrites teacher-entered links at
   the end of the import. Left on its default it targets the *current* `SITE_URL`, which would have
   left a second 136-row content mutation to run inside the DNS window. Pointing it at the final host
   makes the content final at import and turns the cutover step into a verification (`wwwroot-replace`
   → expect 0 rows). The cosmetic cost — those links point at `offd.de` while DNS still answers with
   the old site — is this instance's steady state anyway: 106 questions already reference
   `https://offd.de/pluginfile.php/…` from the earlier migration.
2. **The import ran twice on purpose.** The first pass used the 2026-11-04 archive as filler to start
   the DB chain while Christoph was still tarring; the second used his real tarball. The final state
   is therefore the output of the shipped script on the real pair, not of a hand-run `tar`.
3. **The 4.5.16 image bump goes before the cutover, not with it.** `moodle/docker-compose.yml` pins
   `erseco/alpine-moodle:4.5.16` (renovate, 2026-11-12) while prod ran `v4.5.15`. Deploying that
   together with the host change would put a Moodle upgrade inside the DNS window, where a failure is
   indistinguishable from a routing or certificate problem. Pre-validated on `servyy-test.lxd`:
   4.5.15 → 4.5.16, waitlist plugin keeps version `2025072001`, site 200, `--is-pending` 0.

## What the cutover touches

| Repo | Change |
|---|---|
| servyy-container | `moodle_service_host: offd.de` (`ansible/production`), `docker.services[moodle].host: offd.de` (git-crypt `secrets.yml`), `ls_app/templates/ls.env.j2` drops `/offd` |
| leaguesphere | `/moodle` dropped from the webservice, token, profile and course paths, and from three teacher-facing template/menu links |

## Learnings

1. **A URL split across two repos is a single string.** LeagueSphere built every Moodle URL as
   `MOODLE_URL + "/moodle/…"` and the deployment set `MOODLE_URL=https://offd.de/offd`. The two
   halves compose into the old path, so changing either alone yields
   `https://offd.de/moodle/webservice/rest/server.php` or `https://offd.de/offd/webservice/…`, and
   **neither fails loudly**: `requests` gets an HTML error page, `.json()` raises, and the licence
   report dies with a `JSONDecodeError` that never mentions the URL. Both halves are now guarded by
   unit tests.
2. **`gzip -t` proves the stream, not the content.** A truncated dump fails it, but a complete stream
   whose files do not match their content-addressed names passes. Only the gate's sha1-vs-filename
   pass proves the archive, which is why the gate is a hard stop rather than a report.
3. **Check the path before raising the alarm.** `moodledata/secret/sodium.key` looked absent from the
   new tarball; the key actually lives at `moodledata/secret/key/sodium.key`. All three copies
   (new tar, 2026-11-04 tar, current dataroot) hash to the same `c816ed65…`, so the dump's encrypted
   values — passwords, SMTP creds, MFA secrets — decrypt after the import. Worth the two minutes: a
   genuinely missing key is the most expensive silent failure in this migration.

## Rollback

Content extraction is additive (filedir is content-addressed), so a bad import is undone by restoring
the database alone: `data/db-backup/current/moodle.sql.gz` (same-minute) or the `pre-release`-tagged
restic pair taken at 08:55 today. Before DNS, reverting `moodle_service_host` and redeploying is ~10
minutes; TTL on `offd.de` must be 300 for a DNS rollback to be minutes rather than hours.
