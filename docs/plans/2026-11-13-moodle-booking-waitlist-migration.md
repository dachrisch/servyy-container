# Switching OFFD's Lehrgang enrolment to Booking — plan

**Status:** planned, **not started**. Nothing in this document has been executed against production.
**Owner:** Christoph (OFD) decides the when; the technical work is ours.
**Relates to:** [history/2026-11-13_moodle-booking-spike.md](../../history/2026-11-13_moodle-booking-spike.md)
(the evidence), [history/2026-11-13_moodle-enrol-waitlist-security-bump.md](../../history/2026-11-13_moodle-enrol-waitlist-security-bump.md)
(why the question came up), [2026-11-13-moodle-final-drop-release.md](2026-11-13-moodle-final-drop-release.md)
(the release this must not collide with), [`moodle/AGENTS.md`](../../moodle/AGENTS.md) (plugin pinning).

**Decision this plan implements:** keep `enrol_waitlist` for the 2027 intake; move to `mod_booking` as
its own project **between two intakes**, not inside an open application window.

**Presentation for the office:** DocStash draft „Warteliste: Was sich für Teilnehmer/innen ändert"
(slug `nx616d`, workspace-private) — before/after screenshots of the same course.

---

## Why not now

| | Today (`enrol_waitlist` 2026051200) | With Booking (10.0.8) |
|---|---|---|
| Promotion latency | up to **3 h** (`update_enrolments`, `hour => '*/3'`) | immediate, inside the cancelling request |
| Queue order | `SELECT * FROM mdl_user_enrol_waitlist`, **no `ORDER BY`** | `timemodified`, then answer id |
| What the referee sees | "booked / not booked", one position number | seats taken, waiting-list size, own bookings, cancellation |
| Offer mechanic to waiters | none | limited-time offers, decline locks, recycling |
| Moodle 5.x | no path | `supported = [405, 503]` |

The 2027 intake (13 courses created 2026-11-12, still `status=1`) opens on the current method. Moving
it now would mean remapping 52 `mdl_enrol` rows and 820 `user_enrolments` inside the go-live window,
with a faculty/phone gate that has no ready-made equivalent.

## Shape of the migration

**Not** a data migration. Between intakes:

1. Old courses keep their `waitlist` instances and become read-only archives (they already are, once
   the course is over) — nothing is remapped, nothing is deleted.
2. The **new** intake is built natively in Booking: one booking instance per course, one option per
   date/cohort, capacity and waiting-list places set explicitly.
3. Account, roles and course content stay identical; only the enrolment method and the entry point
   change.

What does **not** carry over, and must be re-built as configuration:

- the faculty/phone gate (`customchar1`/`customchar2` vs `$USER->phone2`, `ESB/INF/TD` lists in
  `faculty.php`) → Booking profile-field conditions or a custom form;
- the enrolment key per course → booking option visibility rules;
- the office's habits around the `enrol/instances.php` page → Bookings Tracker / option participants.

## Phases

### Phase 0 — decisions before any work (Christoph)

- [ ] Which intake is the first Booking intake (target: the one after 2027's, i.e. winter 2027/28).
- [ ] Seat model: is capacity per **course** or per **date block**? Today it is one `waitlist` instance
      per course with a single cap; a Lehrgang with several blocks may need several options.
- [ ] Waiting-list size per course (a number, not "unlimited") — `maxoverbooking = -1` is a footgun.
- [ ] Does the office want to keep the faculty/phone gate at all? If yes, it needs a rebuild (see above).
- [ ] Cancellation policy: who may cancel, until when (Booking Pro feature for deadlines — costs money).

### Phase 1 — rehearse the three chains on `servyy-test.lxd`

The spike already proved the mechanism; this phase proves **OFFD's configuration**, on a copy of the
live DB, with the real 2027 course names and numbers.

- [ ] Vendor and pin `mod_booking` 10.0.8 + `local_wunderbyte_table` 3.3.5
      (sha256 pins in `ansible/plays/vars/default.yml`, assert in
      `ansible/plays/roles/user/tasks/moodle_plugins.yml`, `PLUGINS=` in
      `moodle.app.env.j2` — same procedure as `enrol_waitlist`, twice).
- [ ] Build one real 2027 Lehrgang as a booking option: real cap (25–170), waiting-list places,
      linked course, manual enrolment instance, `autoenrol = 1`.
- [ ] Walk the three roles end to end: referee books → full → waiting list → office cancels someone →
      promotion → course enrolment → cancellation removes enrolment.
- [ ] Prove `maxoverbooking = 0` rejection is caught by a **pre-flight check**, not by a referee
      (see "Guard rails" below).

### Phase 2 — mails (the part that is currently broken by default)

- [ ] `booking.sendmail = 1` per instance, `uselegacymailtemplates` decided (0 or 1 — it changes which
      template system is used), templates rewritten in German.
- [ ] Replace every literal `{$a->…}` placeholder; test: booking confirmation, waiting-list confirmation,
      promotion, cancellation.
- [ ] Decide the sender: today mail goes through the real KAS mailbox (`moodle.app.env.j2` SMTP);
      Booking must reuse it, not fall back to `noreply`.
- [ ] Verify against the queue (`mdl_task_adhoc` / `mdl_booking_messages`) **and** one real delivery to
      a mailbox we can read.

### Phase 3 — rehearsal with real load

- [ ] Load test at the numbers of an opening minute (today: 13 courses opening together; measure first,
      then reproduce). Booking's capacity lock is per option — confirm it holds under concurrency
      instead of assuming it.
- [ ] Rule checks: one option per person, no double booking across options of the same course,
      no booking after the start date.
- [ ] Bookings Tracker column set for the office (who is booked, who is waiting, attendance, sign-in
      sheet download).

### Phase 4 — cutover (between intakes only)

- [ ] Old intake: nothing to do — courses stay as they are, `waitlist` instances stay disabled.
- [ ] New intake: create instances/options from a CSV import (`importoptions.php`) rather than by hand.
- [ ] Keep the `waitlist` enrolment method **enabled** on the site until the old courses are archived;
      disabling it does not break history but does remove the method from courses that still have it.
- [ ] Point the "Anmeldung" entry at the booking activity in each new course; announce to referees.
- [ ] One intake later: evaluate, then decide whether the old plugin is retired.

### Rollback

Cheap, because nothing is migrated: re-enable the old method on the new intake's courses and recreate
the `waitlist` instances from the previous intake's settings. The cost is the applications already
placed in Booking — export them first (`report2.php` → CSV) if the window has opened.

## Guard rails (learned from the spike)

1. **Waiting list is off by default** and is per option. `maxoverbooking = 0` refuses bookers silently;
   `-1` means unlimited. A pre-flight SQL check over `mdl_booking_options` before an intake opens must
   fail loudly on `0` where a queue is wanted.
2. **Course enrolment is three switches**, and never retroactive: `booking.autoenrol = 1`, option
   `courseid`, manual instance on the target course. `enrolmentstatus = 2` enrols at booking time and
   takes the option out of `enrol_bookedusers_tocourse` (`WHERE enrolmentstatus < 1`).
3. **Option settings are cached** in MUC `bookingoptionsettings` — scripted/DB edits need a purge, and
   two of the spike's first runs were invalid because of it.
4. **Scripted cancellations:** `user_delete_response($userid, true)` sets `$cancelreservation`, not
   `$syncwaitinglist` (4th parameter). It returns `true` and leaves the booking in place.

## Open questions

- Does Booking Pro (offers, decline locks, QR tickets, cancellation deadlines — ~$400/yr) belong in the
  scope, or is the free tier enough? The waiting list itself is free; the offer mechanic is not.
- Can the Bookings Tracker replace the office's current `enrol/instances.php` workflow, including the
  faculty/phone check they do by hand today?
- Is a second parallel instance needed during the first Booking intake (both methods live, one course
  each), or is a clean switch acceptable?
- Who answers referee support in the first week — and from which screen?

## Test-host state (do not confuse with production)

`servyy-test.lxd` has the plugins installed outside git and demo data from the screenshots
(course 116 renamed, option 5 with 25 seats, two demo accounts). Inventory and the restore command are
in [history/2026-11-13_moodle-booking-spike.md](../../history/2026-11-13_moodle-booking-spike.md) →
"Visual walkthrough" / "Implementation Details".
