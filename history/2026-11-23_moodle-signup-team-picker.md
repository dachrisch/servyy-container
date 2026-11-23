# Moodle signup: team picker out of `mdl_config`, plus two club-picker defects

**Date:** 2026-11-23 (reported 2026-11-22)
**Branch:** `master` (direct: `00c74b81`, `9be27341`, `b96f1dc7`, `c4545c9a`)
**Services touched:** `moodle.moodle` on servy — `moodle/assets/` (new), `moodle/docker-compose.yml`
(one mount), `ansible/plays/vars/default.yml`, `ansible/plays/user.yml`,
`ansible/plays/roles/user/tasks/moodle_signup_picker.yml` (new), and two rows in
`mdl_user_info_field`

Christoph reported that in both "36. Trainer C Tackle" courses new participants could not
submit the registration as soon as they had picked their club ("Verein"); it only worked with
"ohne Team". The PDF half of that report is
[its own entry](2026-11-23_traefik-xfo-sameorigin-moodle-pdf.md).

## What the signup actually is

Moodle core (`/login/signup.php`, `auth_email`), plus a **select2 widget injected through
`mdl_config.additionalhtmlfooter`**: one inline block with jQuery 3.6 + select2 4.0.13 from
two CDNs and ~90 lines of picker code. It replaced the plain `Teamname` text field with a
search box fed by `https://leaguesphere.app/dal/team/`, writing `profile_field_teamname` (3)
and `profile_field_teamid` (7).

Nothing in Moodle validates a team name — `teamname` is an optional free-text profile field —
so the club value itself cannot make the POST fail. Measured instead:

| Evidence | |
|---|---|
| `SELECT … FROM mdl_user` for 2026-11-22 | 24 successful signups **with** club names (`Marburg Mercenaries`, `Wiesbaden Phantoms`, …) |
| signup form page | 78 079 bytes raw, **~13.7 kB gzipped** |
| 69 `POST /login/signup.php` in ~33 h | 26 × ~8.1–8.2 kB = the "check your e-mail" notice, **42 × 13.7–14.06 kB = the form re-displayed with a validation error**, 1 × 404 (the probe below) |
| what can fail server-side (`lib/authlib.php:1151`) | username taken / must be lowercase / invalid chars, e-mail invalid / already registered, e-mail2 mismatch, password policy, required profile fields |

So the failure rate was real (~60 % of attempts) but the club is not the trigger: the widget
was *near* it, and the last thing a participant touched before submitting is the picker. That
is why the report read as "the Verein breaks it".

The two defects that *were* in the picker:

1. **`teamid` had not been stored since ~2026-09-23.** The field had `signup=0`, so it was not
   on the signup form at all and the widget wrote into a non-existent input: 52 signups in the
   30 days before this change have a team name and **no** team id (last stored id: 4226,
   2026-08-22; ids 4235-4241 on 2026-09-23 all carry 213 = "ohne Team").
2. **"ohne Team" behaved differently depending on the path.** Team **213** is the real
   "ohne Team" row in the leaguesphere list, and picking it flipped `Rechnungsadresse mit
   E-Mail` to `required`; typing "ohne Team" as free text did not — although the hint text
   said *"'ohne Team' eingeben und auswählen"*. Further, `required` was set while the row could
   be hidden, the classic "an invalid form control … is not focusable" trap that makes a form
   silently unsubmittable.

Also fixed while in there: with `tags: true`, select2 listed the free-text tag **above** the
real teams, so pressing Enter on "Marburg" stored the fragment instead of
"Marburg Mercenaries".

## Change

- **`moodle/assets/signup-team-picker.js`** — the widget, written clean: IIFE, no
  `console.log`, the API URL and the "ohne Team" id/name as constants at the top, and no
  dependency on the order Moodle happened to emit the old inline block in.
- **`moodle/assets/vendor/`** — jQuery 3.6.0, select2 4.0.13 (js + css) committed with their
  sha256 in [the README](../moodle/assets/vendor/README.md), for the same reason the
  enrolment plugin is vendored: registration must not depend on a CDN or an ad blocker.
- **`moodle/docker-compose.yml`** — `./assets:/var/www/html/moodle-custom:ro`; the image's own
  nginx serves it (that is why it must live inside the docroot) and caches `*.js`/`*.css` for
  five days, hence `?v=` in the URL and `moodle_signup_picker_version` in
  `ansible/plays/vars/default.yml` — **bump it with every picker edit**.
- **`ansible/plays/roles/user/tasks/moodle_signup_picker.yml`** (imported from the compose
  play's `post_tasks`, so it runs against a live container): stats the four assets, reads
  `additionalhtmlfooter` with `admin/cli/cfg.php --no-eol`, writes
  `--set={{ moodle_signup_picker_footer }}` only when it differs, then asserts the read-back.
  `additionalhtmlfooter` is now exactly `<script src="/moodle-custom/signup-team-picker.js?v=N"></script>`
  — a UI edit reverts on the next deploy, like the mail settings.
- **`world_readable_paths_by_service.moodle += assets`** — the checkout leaves files 0660 and
  nginx runs as `nobody`; without it the picker 403s and nothing says so.
- **DB (prod, 2026-11-23):** `UPDATE mdl_user_info_field SET signup=1, visible=2 WHERE id=7;`
  — `visible` too, because `profile_get_signup_fields()` skips `visible=0`
  (`user/profile/lib.php:784`). `visible=2` = private, same as `teamname`. Followed by
  `admin/cli/purge_caches.php`.
- Behaviour: `needsInvoice = (id === 213) || (name.toLowerCase() === 'ohne team')` on both
  paths; `required` is removed *before* the row is hidden; `select2:clear` resets both fields;
  `insertTag` appends the free-text tag after the real matches.

The loader only fetches its libraries on pages that carry `#id_profile_field_teamname`, and
does nothing at all if a dependency fails — the plain Moodle text field stays usable. Before
this change every page of the site pulled ~175 kB of jQuery + select2.

## Two traps found while rolling this out (both cost a deploy)

1. `window.jQuery` is a **moving target**: Moodle's own AMD jQuery replaces the global while
   ours is in flight, so `window.jQuery.fn.select2` was false even though select2 had loaded.
   Fixed by capturing the instance inside the `onload` callback.
2. select2 and jQuery are **UMD** bundles: with `define.amd` present (always, on Moodle) they
   register as AMD modules and **never** attach to `window.jQuery`. Loading select2 as a plain
   `<script>` after RequireJS exists can therefore not work. The picker now loads
   `require(['jquery', 'offdselect2'])` through Moodle's RequireJS — which also means Moodle's
   own jQuery is reused and the vendored copy is only a fallback. A failure now logs
   `[offd] team picker disabled: …` instead of failing silently.

## Deploy

```bash
cd ansible && ./servyy.sh --limit servy.lehel.xyz --tags user.docker.repo,user.docker.moodle
```

The compose spec changed (new mount), so `moodle.moodle` **was recreated** — a few seconds of
502 on offd.de. Both new post-tasks then ran (read → set → assert); the second and later
deploys are no-ops apart from the `?v=` bump.

**servyy-test.lxd could not be used for this**: its Moodle still runs the pre-WP-7b compose
(`moodle.db` sidecar + `moodle_internal`), so `up` fails on the external
`db_business_backend` network before anything is verified. Verification was done on prod,
read-only, in a real browser (nothing was submitted).

## Verification (measured, Chrome on offd.de)

| Check | Result |
|---|---|
| assets | `200` for `/moodle-custom/signup-team-picker.js?v=4`, `vendor/jquery-3.6.0.min.js`, `vendor/select2-4.0.13.min.js`, `vendor/select2-4.0.13.min.css` |
| `cfg.php --name=additionalhtmlfooter` | `<script src="/moodle-custom/signup-team-picker.js?v=4"></script>` |
| `additionalhtmlhead` | unchanged (`<meta name="robots" content="noindex" />`) |
| signup page | picker rendered, `#id_profile_field_teamname` and the whole `teamid` row hidden, invoice row hidden, no console errors |
| search "Marburg" | `["Marburg Mercenaries", "Marburg"]` — real team first, free-text tag last |
| pick the team | `teamname = Marburg Mercenaries`, `teamid = 281`, invoice hidden, not required |
| pick "ohne Team" (row 213 **and** as free text) | invoice row shown, `required`, form blocked until filled |
| unknown club as free text | `teamname = Testverein ZZ`, `teamid = -1` |
| clear (×) | both fields empty, invoice row hidden and not required |
| other pages (home) | only the 7.5 kB picker script, no jQuery/select2 |

## Incident disclosure

While probing the server-side validation with `curl` (to learn which errors the 42 failing
POSTs could be), one probe — `username=probe@example.com` — passed validation and **created
user 4301** (`probe.test.zz99@example.com`); the confirmation mail then failed and Moodle
answered `HTTP 404` (`auth_email::user_signup_with_confirmation()` creates the user *first*,
then throws `auth_emailnoemail`). The account had 0 log rows, 1 preference and 4 profile-data
rows; all of it was deleted on 2026-11-23 (`DELETE FROM mdl_user … WHERE id=4301` plus the
child rows) and `mdl_user` no longer contains it.

That failure mode is worth knowing about: a signup whose confirmation mail cannot be delivered
leaves a half-registered, unconfirmed account behind, and the retry then says "Diese
E-Mail-Adresse ist bereits registriert". It did not occur for real users in the measured
window (1 of 69 POSTs, and that was the probe), but it is the other way "registration does not
work" can present itself.

## Open / deliberately not done

- **The invoice rule is still client-side only.** Moodle knows nothing about teams or
  invoices; enforcing it server-side needs a small `local_` plugin (or a web-service call from
  the picker). Decision on 2026-11-23: keep the rule, accept that a visitor with JavaScript
  disabled is not asked for an invoice address.
- **No backfill** of the 52 users who have a `teamname` but no `teamid` (deliberate, decided
  2026-11-23). If it is ever wanted: match `teamname` against `/dal/team` by exact name.
- `?v=` cache busting is manual by design; a content hash in the file name would remove the
  step, at the cost of rewriting the `additionalhtmlfooter` value from a hash.
- The club list comes from `leaguesphere.app` and is capped/paginated server-side; clubs that
  are not in it can only be entered as free text (`teamid = -1`).
