# Booking spike on `servyy-test.lxd`: what a swap would actually change

**Date:** 2026-11-13
**Status:** ✅ Accepted — spike run and verified; **no production change**
**Relates to:** [history/2026-11-13_moodle-enrol-waitlist-security-bump.md](2026-11-13_moodle-enrol-waitlist-security-bump.md),
[history/2026-11-10_moodle-waitlist-plugin-and-release-tooling.md](2026-11-10_moodle-waitlist-plugin-and-release-tooling.md),
[moodle/AGENTS.md](../moodle/AGENTS.md)

## Context

After the `enrol_waitlist` security bump the open question was whether OFFD's waiting-list enrolment
method could be replaced by **Booking** (`mod_booking`), the only candidate from the comparison that is
both Moodle-5-ready and does real automatic promotion. Reading its marketplace description and code is
not evidence of behaviour, so the trial was run against the imported OFFD database on
`servyy-test.lxd`: 104 courses, 35 `waitlist` instances, 4 129 users.

Installed for the trial (nothing vendored, nothing in git):

| | |
|---|---|
| `mod_booking` | `2026110600` = **10.0.8** (tag `v10.0.8`), `supported = [405, 503]` |
| `local_wunderbyte_table` | `2026110200` = **3.3.5** (required, `dependencies = [local_wunderbyte_table => 2026102200]`) |
| Footprint | 108 MB / 2 255 PHP files + 4.2 MB / 406 files, 46 new DB tables |
| Instance | `erseco/alpine-moodle:4.5.16`, PHP 8.3.36 |

A full DB dump was taken first: `/home/cda/moodle-prebooking.sql.gz` (178 MB gzipped).

## Decision

**Keep `enrol_waitlist` for the 2027 intake; migrate to Booking only as its own project, between
intakes, with the course-enrolment and mail chains rehearsed end to end.** The spike found no reason to
doubt Booking's waiting list — it is *better* than what runs today — but it also found three
config-dependent behaviours that would look broken if the swap were done as "install and open the
2027 courses".

## Consequences

### What the spike proved (all on the imported DB, real users, real cancellations)

| Test | Result |
|---|---|
| 2 seats, 5 waiting-list places, 5 users | users 1–2 `BOOKED`, users 3–5 `WAITINGLIST` — FIFO by `timemodified`, tie-broken by answer id |
| booked user cancels | next waiter promoted to `BOOKED` **inside the same request**, no cron involved (option-level capacity lock held for the whole batch) |
| waiting list disabled (`maxoverbooking = 0`, the default) | the 3rd booker is **refused outright** — no row, no queue |
| course enrolment | booking a seat enrolled the user into the linked course via that course's **manual** enrolment instance; promoted waiters are enrolled too; cancelling **removes** the enrolment |
| student UI | free seat → **“Jetzt buchen”**; full option → **“Buchen - auf Warteliste”**; option row shows **“(Warteliste: 0/5)”**; extra tabs “Alle Buchungsoptionen / Aktuelle Buchungsoptionen / Meine Buchungen” |
| mails with factory defaults | **nothing is sent at all** (see below) |

### The three things that would bite if the swap were rushed

1. **The waiting list is off by default and is per option, not per course.** `maxoverbooking = 0`
   disables it (upstream help text: *“Enter -1 for unlimited waitinglist and 0 to disable”*). Today's
   plugin queues every booker of a full course unconditionally. A migrated course whose 14 options
   were created without that number silently rejects the 26th referee instead of queuing them.
2. **Course enrolment is a chain of three switches**, not part of "booking": `booking.autoenrol = 1`
   (default **0**), the option's `courseid` (default 0), and a **manual** enrolment instance on the
   target course. With `enrolmentstatus = 2` (the default) enrolment happens at booking time; only
   `enrolmentstatus < 1` is served by the `enrol_bookedusers_tocourse` task, i.e. **there is no
   retroactive backfill** — the 820 existing `user_enrolments` have to be re-created by a script, not
   by attaching courses to options and waiting.
3. **Mails do not work out of the box.** Queued as adhoc `send_confirmation_mails` tasks, but that task
   returns immediately unless `uselegacymailtemplates` is on (it is **0**), and `booking.sendmail` is
   **0** on a programmatically created instance. When forced on, the default German status-change
   template still shipped literal `{$a->status}`, `{$a->startdate}`, `{$a->gotobookingoption}`
   placeholders in the body. So OFFD's "you got a seat" mail must be built and tested as its own task.

### Positive

- Promotion latency goes from **up to 3 hours** (today: `update_enrolments` cron, `hour => '*/3'`) to
  **immediate on cancellation**.
- Queue order becomes explicit and stable (`timemodified`, then answer id). Today's
  `waitlist::get_wait_list()` is `SELECT * FROM mdl_user_enrol_waitlist` with **no ORDER BY** — the
  order is whatever the engine returns.
- Referees see free places, their own bookings and the waiting-list size *before* deciding, which today
  they cannot (only "booked / not booked").
- 10.0.8 adds a whole offer mechanic the old plugin lacks: limited-time offers to waiters, decline
  locks, "recycling" when everyone on the list has let an offer expire.
- It is the only candidate that runs on Moodle 5.x (`supported = [405, 503]`).

### Negative / tradeoffs

- **Two plugins, 46 tables, 2 661 PHP files** to vendor, pin, sha256-assert and bump — versus one
  53-file archive today. Upstream releases `10.0.x` frequently (10.0.5 → 10.0.8 within the visible tag
  list), so the bump procedure gets exercised more often.
- **The faculty/phone gate has no equivalent.** Today `customchar1`/`customchar2` are checked against
  `$USER->phone2` plus the hard-coded `ESB/INF/TD` lists in `faculty.php`. Booking offers profile-field
  conditions and custom forms, but the rebuild is real configuration work.
- Booking is an **activity**, so the "Warteliste" enrolment method disappears from course settings and
  trainers work in a booking option / the Bookings Tracker instead.
- Option settings are cached in MUC (`bookingoptionsettings`): a direct DB edit does **not** take
  effect until the cache is purged. Two of my first runs were invalid because of that.
- Mail behaviour is a per-instance `sendmail` switch *plus* the global legacy-template switch *plus*
  per-instance templates — three places to get wrong, and no error when any of them is off.

### Implementation Details

**Where the trial lives** (test host only, deliberately not in git):

- Container docroot: `/var/www/html/mod/booking`, `/var/www/html/local/wunderbyte_table`
  (installed with `docker cp` + `tar`, `chown 65534`, then `admin/cli/upgrade.php --non-interactive`).
- Scripts that produced the evidence: `/home/cda/moodle-booking-spike/*.php`
  (`setup.php`, `e2e.php`, `promotion.php`, `courseenrol.php`, `promoteenrol.php`, `mails2.php`,
  `diag.php`).
- Pre-spike DB snapshot: `/home/cda/moodle-prebooking.sql.gz`.

**Restore to the pre-spike state** (the next `docker compose up` on this host would otherwise leave the
DB holding `mod_booking` tables with no files on disk):

```bash
ssh servyy-test.lxd 'docker exec -u 0 moodle.moodle rm -rf /var/www/html/mod/booking /var/www/html/local/wunderbyte_table'
ssh servyy-test.lxd 'zcat /home/cda/moodle-prebooking.sql.gz | docker exec -i moodle.db sh -c \
  "exec mariadb -uroot -p\"\$MARIADB_ROOT_PASSWORD\" moodle"'
```

**Testing & verification (executed)**

- `php /var/www/html/admin/cli/upgrade.php --non-interactive`: both plugins installed, no errors.
- Five booking rounds on two options, printing `mdl_booking_answers` after every step (see table above).
- Real HTTP session as a manually enrolled student: `login/index.php` → `mod/booking/view.php?id=2665`,
  HTML stripped and read; the three strings quoted above come from that page.
- Course enrolment checked against `mdl_user_enrolments` joined on `mdl_enrol.courseid`, before/after
  booking, after promotion and after `enrol_bookedusers_tocourse`.
- Mails inspected by decoding `mdl_task_adhoc.customdata` (subject, `messagetext`, recipient) instead of
  sending to `@example.invalid` addresses.

**Key learnings**

1. **The default is "no waiting list", not "waiting list".** `maxoverbooking = 0` turns it off; the
   comment in `booking_option::sync_waiting_list()` that "limitanswers + maxanswers enables the
   waiting list" is only half the story — capacity on the list is a separate number.
2. **Promotion is synchronous and FIFO.** `user_delete_response(..., $syncwaitinglist = true)` promotes
   under a `bookingoption_capacity_<id>` lock, sorted by `timemodified` then answer id. No task needed,
   no fan-out race. Gotcha for scripted cancellations: `$syncwaitinglist` is the **fourth** parameter —
   `user_delete_response($userid, true)` sets `$cancelreservation` instead, returns `true`, and quietly
   leaves the booking in place.
3. **Course enrolment is opt-in at three levels** (instance `autoenrol`, option `courseid`, target
   course's manual instance) and never retroactive — plan the 820 enrolments as a data migration.
4. **A plugin instance's settings are cached**, so scripted changes must purge
   `mod_booking/bookingoptionsettings` (and `cachedbookinginstances` for instance-level flags).
5. **"Notifications" in 10.x are booking rules, not the legacy adhoc mails.** With defaults the adhoc
   task is a no-op; the default template additionally leaves `{$a->…}` placeholders in the body.
6. Setting `enrolmentstatus` to 2 (enrol now) takes the option out of `enrol_bookedusers_tocourse`
   entirely (`WHERE enrolmentstatus < 1`), which is why the backfill task ignored an earlier booking.

### Visual walkthrough (for the OFFD decision)

A before/after page with screenshots from both states was produced for the office: DocStash draft
`Warteliste: Was sich für Teilnehmer/innen ändert` (slug `nx616d`, workspace-private). It pairs the
current `enrol_waitlist` enrol page with the booking option list, the "on the waiting list" state and
the promoted state, plus a phone-width view.

To produce comparable screenshots the test host now carries demo data that **must not be mistaken for
real configuration**:

- Course 116 was renamed `Lehrgang F3 06.02.2027` (shortname `f3-2027`) and its booking instance to
  `Anmeldung Lehrgang F3`; intro text rewritten so the page reads like a live one.
- Option 5 (`F3 Lehrgang 06.02.2027`) was created for the shots: 25 seats, 5 waiting-list places,
  filled with 25 arbitrary student accounts; `courseid = 0`, so this option enrols nobody into a course.
  The original spike options 2 and 3 are kept but set `invisible = 1`.
- Demo accounts: `demo-referee` (4261, "Sandra Berger", booked after promotion) and `demo-waitlist`
  (4262, "Michael Hofer", on the waiting list), both `DemoPass2026!`.
- Admin's `lang` preference was set to `de` for the German admin screens.

### Known issues & limitations

- The trial ran on the imported dump but with synthetic courses and options (test-host course ids
  116 = booking activity, 117 = linked "Lehrgang" course), so the *numbers* — 2 seats, 5 waiting-list
  places, 5 test users — are mine, not OFFD's. The three throwaway duplicates were deleted again.
- Mail delivery itself was not tested end to end (no SMTP round trip on the test host); only the queue
  content and the two switches that gate it.
- The faculty/phone gate, approvals, cancellation deadlines and QR tickets (Pro, $400/yr) were not
  tested at all.
- The test instance keeps the plugin installed for clicking through; see the restore block above.

## Alternatives Considered

- **Stay on `enrol_waitlist` (chosen for now).** Works, was just patched, and the 2027 courses are
  already configured with it. Its weaknesses: 3-hour promotion latency, unordered queue, no free-seat
  display, no Moodle 5 path.
- **Enrol by Category** — rejected: its "waiting list" emails the next five waiters daily at 14:00 and
  the fastest click wins, which is not FIFO promotion at all.
- **Activity Signup (`mod_signup`)** — rejected as a replacement: per-group capacity only, never enrols
  into the course.
- **"Enrollment Application"** — no such plugin exists; `enrol_apply` stops at Moodle 4.1 and cannot
  run on 4.5.16.

## Related Decisions

- [2026-11-13_moodle-enrol-waitlist-security-bump.md](2026-11-13_moodle-enrol-waitlist-security-bump.md)
  — the bump that made this question urgent.
- [2026-11-10_moodle-waitlist-plugin-and-release-tooling.md](2026-11-10_moodle-waitlist-plugin-and-release-tooling.md)
  — how a third-party plugin is vendored, pinned and installed at boot; the procedure Booking would need
  twice.
