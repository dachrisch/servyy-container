# Moodle signup: the browser now checks before the server has to

**Date:** 2026-11-23
**Branch:** `master` (`dd97ddb4`, `3b62ecab`)
**Services touched:** `moodle.moodle` on servy — new `moodle/assets/signup-validate.js`,
`ansible/plays/vars/default.yml`, `ansible/plays/roles/user/tasks/moodle_signup_picker.yml`
(footer now carries two tags; new password-policy assertion). No container recreate (assets
are a directory bind mount), no downtime.

Follow-on to [the picker entry](2026-11-23_moodle-signup-team-picker.md): that one fixed what
was *broken*, this one fixes what was *missing*.

## Problem, in one measured sentence

On 2026-11-22 only **5 of 31** participants got through the signup form on the first submit, and
**12 of the 22** who retried sent a payload of the same length (±2 bytes) — they had changed
nothing but their password. The reason is in the page itself:

| | |
|---|---|
| Moodle emits `aria-required="true"`, **not** `required` | accessibility hint, not a constraint |
| no `pattern`, no `minlength`, `type="text"` on the e-mail fields | nothing for the browser to enforce |
| the password policy exists only in PHP (`lib/moodlelib.php:4614`) | five rules, one of them a mandatory special character |
| the rules are printed above the password field as *text* | nobody reads a paragraph before typing |

So every rejection cost a 78 kB page, and the form could only be rejected **after** the fact.

## Change

`moodle/assets/signup-validate.js` — vanilla JS, no jQuery, no RequireJS (it must work even if
the picker's libraries could not load):

- mirrors **exactly** what `signup_validate_data()` checks: username lowercase + allowed
  characters, e-mail format, the two e-mail fields matching, and the five password rules.
  The club is deliberately **not** checked, because the server does not check it either.
- writes its hints into its own `<div class="offd-signup-hint">` per field. It never touches
  the server-rendered `#id_error_<name>` div, so "username already taken" survives.
- blocks the submit only when a local rule fails (capture phase, `preventDefault()`, then
  scrolls to and focuses the first offending field and sets `aria-invalid`).
- **fails open**: non-signup page, missing field, the „Abbrechen" button (`data-skip-validation`)
  or any exception leaves the form exactly as before.
- language follows `<html lang>` (the site serves German and English), so hints are
  „Noch offen: 1 Großbuchstabe, 1 Sonderzeichen (z. B. *, -, #)" or the English equivalent.

**The policy is not hard-coded.** `moodle_password_policy` in `plays/vars/default.yml` is
rendered into `data-pw-*` attributes on the `<script>` tag, and the deploy now asserts it
against `minpasswordlength/digits/lower/upper/nonalphanum` in `mdl_config`:

```
TASK [Assert the repo's password policy matches Moodle's] ... ok
```

That is the safety property that makes blocking acceptable: the browser can never block a
password the server would accept, and a policy moved in the UI (or missed in the repo) fails the
deploy instead of drifting silently.

`moodle_signup_picker_version` → `moodle_site_js_version` (it cache-busts two files now), value
`5`.

## Verification (live, read-only — no submission)

| Check | Result |
|---|---|
| footer in `mdl_config` | both tags, `?v=5`, `data-pw-length="8"` … |
| scripts served | `signup-team-picker.js?v=5`, `signup-validate.js?v=5` → 200 |
| username `MaxMustermann` | „Nur Kleinbuchstaben erlaubt" / „Lowercase letters only" |
| username `max mustermann` | „Nur a–z, 0–9 sowie _ - . @" |
| password `fussball2026` | „Noch offen: 1 Großbuchstabe, 1 Sonderzeichen (z. B. *, -, #)" |
| password `kurz` | lists length, digit, uppercase, special |
| password `Fussball2026!` | hint clears, `aria-invalid` removed |
| e-mail ≠ repeat | „Die beiden E-Mail-Adressen stimmen nicht überein" |
| valid form + synthetic `submit` | **not** blocked (`defaultPrevented === false`) |
| weak password + `submit` | blocked, focus lands on `id_password` |
| empty required field | blocked, „Bitte ausfüllen" |
| picker on the same page | still works (select rendered, `teamname` hidden) |
| console | no errors |

## One thing that went wrong (worth remembering)

The rename of the cache-buster variable missed its use inside an `assert`'s `fail_msg` — and
Ansible resolves `fail_msg` **eagerly**, so the deploy failed *after* it had already written the
correct footer. The setting was right, the run was red. Fixed in `3b62ecab`; the second run
reported `changed=0` and both asserts green, which is also the proof that the whole task is
idempotent.

## Not done, on purpose

- **No live "username already taken".** That needs a server round trip and a public endpoint
  Moodle does not expose (`core_user_get_users_by_field` is capability-gated). The server's
  message stays the answer, and the hint above the field at least makes the *format* right
  before submitting.
- **The password policy itself is untouched.** This change removes the *round trip*, not the
  rule. Whether a mandatory special character is the right bar for referee-course participants
  is a decision for the club, not for a deploy — the one-line lever is
  `minpasswordnonalphanum: 1 → 0` in `plays/vars/default.yml` **plus** the same change in the
  Moodle UI (the deploy enforces that both move together).
- **The server-side invoice rule** ("ohne Team" needs an invoice address) still needs the
  `local_` plugin discussed in the picker entry; nothing here changes that.
