# OFFD dump arrived — measured, and the DB half of the migration rehearsed

**Date:** 2026-10-28
**Plan:** [docs/plans/2026-10-27-moodle-offd-hosting.md](../docs/plans/2026-10-27-moodle-offd-hosting.md) (Task 4 / Task 5)

## The dump

Christoph's export landed at `/var/jail/home/leaguesphere/dump-OFFD-d037491e-202610280831.sql.gz`
(the `leaguesphere` jail home on servy):

| | |
|---|---|
| Size | 134 MB gzipped → **1.62 GB** uncompressed, `gzip -t` clean |
| Produced by | `mysqldump 8.0.19 (Win64)` against **MariaDB 10.6.23** |
| Shape | 497 tables, prefix `mdl_`, one database, **no** `CREATE DATABASE`/`USE` — imports into whatever DB you target |

Measured by importing into a scratch database (`moodle_import`, dropped afterwards) so the blank
production instance stayed untouched:

| | |
|---|---|
| DB size | **1.67 GB** |
| Users | **4 248** (4 128 active) |
| Courses | **104** / 2 132 course modules |
| File rows | 39 355 |
| Version | `4.5.12 (Build: 20260608)`, `2024100712` |
| Third-party plugins | **2** — `enrol_waitlist`, `qbehaviour_adaptiveallnothing` |
| Custom profile fields | `teamname`, `teamid`, `Landesverband`, `LandesverbandAuswahl` — exactly what LeagueSphere reads |

**58 % of the database is `mdl_logstore_standard_log` (965 MB).** Question attempts (~360 MB) are live
exam history and stay. So the DB could shrink by up to ~1 GB by dropping the standard log — a
content decision for Christoph, not a technical need.

## The rehearsal (servyy-test.lxd)

1. Import into the test box's `moodle` DB: **8 min 17 s**.
2. The image saw DB `2024100712` < its own `2024100715` and ran `upgrade.php` itself → **`4.5.15
   (Build: 20261005)`**, maintenance mode entered and exited, no complaints about the two absent
   third-party plugins.
3. Front page rendered the real site: **`Home | Flag Academy`**, 4 248 users, 104 courses.
4. **wwwroot replace, measured across every text column** rather than assumed. Live content needing
   it is ~134 rows:

   | Table | Rows |
   |---|---|
   | `mdl_question.questiontext` | 106 |
   | `mdl_question_answers.answer` | 13 |
   | `mdl_book_chapters.content` | 8 |
   | `mdl_url.externalurl` | 6 |
   | `mdl_page.content` | 1 |
   | *(optional)* `mdl_question_attempts.questionsummary` | 310 |

   Everything else is history we must **not** rewrite: `mdl_messages` / `mdl_notifications` (~40 k
   sent messages), `mdl_tiny_autosave.drafttext`, `mdl_config_log`, `mdl_adminpresets`. After the
   replace: **0 remaining hits** in live content; a spot check shows a rewritten link
   (`…/pluginfile.php/23606/mod_resource/…`) pointing at the new host.

## What this settles

- **Sizing fits.** 1.67 GB + ~14 GB ≈ 15.7 GB against 21 GB free → ~5 GB headroom, **no volume
  needed** (the earlier volume purchase stays cancelled).
- **Plugin preservation is a two-item problem**, not the risk it looked like. Declare both in
  `PLUGINS=` (installed at every boot) or install them once before cutover.
- **The URL change is cheap**: ~134 rows in six columns, not a 14 GB sweep. The earlier decision to
  move wwwroot to the host root is now measured rather than feared.
- **The upgrade path works**: 4.5.12 → 4.5.15 is handled entirely by the image.

## Still open

- **The ~14 GB `moodledata` has not arrived.** Until it does, `pluginfile.php` links 404 (images,
  PDFs, SCORM). This is the remaining half of the export, and the only unexercised part of the plan.
- Install `enrol_waitlist` + `qbehaviour_adaptiveallnothing` before cutover, or enrolments using the
  waitlist plugin and quizzes using that behaviour will misbehave.
- Decide on the standard log (keep 965 MB for reporting history, or trim it).
- The LeagueSphere side of the URL change (`MOODLE_URL` + the hardcoded `/moodle/…` segments) — still
  deliberately untouched while prod points at the old live site.

## Housekeeping

- Prod's blank instance was **not** touched: the import went to a scratch DB and the rehearsal to the
  test box. Scratch DB dropped, disk back to 21 GB free.
- The test box now holds a full copy of the real data (DB only) with the URL replace applied — a ready
  rehearsal target for the file half.

---

## Prod import (2026-10-28, same day)

Imported the same dump into the **prod** instance at `m.leaguesphere.app`:

1. Stopped the app, emptied the blank dataroot, dropped/recreated the `moodle` DB (grants survive).
2. Import: **13 min 41 s**, 497 tables, then the image auto-upgraded **4.5.12 → 4.5.15**
   (`Command line upgrade … completed successfully`, maintenance mode in and out).
3. wwwroot replace applied **once, with the final URL** (`https://offd.de/offd/moodle` →
   `https://offd.de`) so no second pass is needed at cutover: 106 question texts, 13 answers,
   8 book chapters, 6 URLs, 1 page, 310 attempt snapshots → **0 hits left** in live content.
4. Verified live: `Home | Flag Academy`, login page, course categories, 4 129 users, 104 courses,
   **7 603 enrolments**.

### The image rewrites settings on every boot — including on an installed DB

`02-configure-moodle.sh` runs `configure_moodle_settings` + `update_admin_user.php` on **every**
start. Against the freshly imported database this silently changed:

| Setting | Was (their site) | Now | Handling |
|---|---|---|---|
| first site admin (id 2, the role account `OFFD Admin`) | `admin@offd.de` | `admin@leaguesphere.app` | **fixed** — `MOODLE_EMAIL=admin@offd.de` |
| its password hash | their hash | our generated one | accepted: password is Ansible-managed, reverts on deploy |
| `noreplyaddress` | `noreply@offd.de` | `noreply@localhost` | **fixed** — `MOODLE_MAIL_NOREPLY_ADDRESS` |
| `emailsubjectprefix` | *(empty)* | `[moodle]` | **fixed** — empty env value |
| `smtphosts`/`smtpuser`/`smtppass` | *(all empty)* | `smtp.gmail.com:587`, `your_email@gmail.com`, `your_password` | **not fixable via env** — see below |
| `enableblogs` | `1` | `0` | hardcoded in the image, no override. Two blog posts exist; documented deviation |

**Only id 2 was touched** — the nine other site admins are real people with their own unchanged
credentials, so nobody lost access. But the lesson is sharp: this image treats env as the source of
truth for a set of *site settings*, not just for first boot.

**Mail is the one real casualty.** The old site had no SMTP at all — it used the shared host's local
MTA. This container has no MTA, and the image fills the gap with placeholder Gmail credentials, so
outbound mail (password resets, notifications, reminders) is non-functional until a relay is chosen.

### Still open after the import

- **`enrol_waitlist` plugin** — 35 courses use the `waitlist` enrolment method, so it is functionally
  required, not cosmetic. Expected version `2025072001`. moodle.org's download endpoint returned 404
  to both this machine and servy, so the practical source is Christoph's instance (zip `enrol/waitlist`)
  or his browser. `qbehaviour_adaptiveallnothing` is installed in the DB but **used by no quiz**
  (behaviours in use: deferredfeedback, immediatecbm, immediatefeedback) — optional.
- **The ~14 GB `moodledata`** — still not delivered; `pluginfile.php` links 404 until it is.
- **SMTP decision** (see above) — blocker before users log in.
- The LeagueSphere side of the URL change (`MOODLE_URL` + the hardcoded `/moodle/…` segments).
