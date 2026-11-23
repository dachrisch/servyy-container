/* OFFD ("Flag Academy") — live pre-check for the signup form.
 *
 * WHY
 * The signup form is plain server-rendered HTML: Moodle marks required fields
 * with `aria-required` (an accessibility hint), not `required`, and the password
 * policy exists only inside PHP. So the browser has nothing to enforce, and the
 * first opinion a participant gets is a 78 kB page coming back with red text.
 * On 2026-11-22 only 5 of 31 participants got through on the first submit; 12 of
 * the 22 who retried changed nothing but their password.
 *
 * This file moves exactly that opinion forward. It is a *mirror*, not a second
 * rulebook:
 *
 *   - The password rules are NOT hard-coded here. They arrive as data-*
 *     attributes on the <script> tag, rendered by Ansible from
 *     `moodle_password_policy`, and roles/user/tasks/moodle_signup_picker.yml
 *     asserts that those values equal mdl_config's minpassword* — so the deploy
 *     fails if the policy moves and this file is not updated. The browser can
 *     therefore never block a password the server would accept.
 *   - The checks mirror lib/authlib.php:1151 (username lowercase + allowed
 *     characters, e-mail format, e-mail repeated identically, and the password
 *     policy from lib/moodlelib.php:4614). Nothing the server does not check is
 *     checked here — the club in particular is left alone, on both sides.
 *
 * WHAT IT DOES NOT DO
 *   - No "is this username taken" (that needs a server round trip and a public
 *     endpoint Moodle does not expose); the server's message stays the answer.
 *   - It never clears a server-rendered error (each field's
 *     `#id_error_<name>` div is left untouched); hints go into their own node.
 *   - It fails OPEN: any exception, a missing field, a non-signup page or the
 *     cancel button leaves the form exactly as it was before.
 *
 * No dependencies on purpose (no jQuery, no RequireJS): this must work even if
 * the picker's libraries could not be loaded.
 */
(function () {
  'use strict';

  var passwordField = document.getElementById('id_password');
  var emailAgain = document.getElementById('id_email2');
  /* Only the signup form has an e-mail repetition field. The profile-edit form
   * shares the field ids and must not be validated against a policy it does not
   * enforce. */
  if (!passwordField || !emailAgain) { return; }

  var form = emailAgain.form || document.querySelector('form.mform');
  if (!form) { return; }

  /* ---------------------------------------------------------------- config */

  var cfg = { length: 8, digits: 1, lower: 1, upper: 1, special: 1 };
  var script = document.currentScript;
  if (script && script.dataset) {
    var d = script.dataset;
    cfg.length = parseInt(d.pwLength, 10) || cfg.length;
    cfg.digits = parseInt(d.pwDigits, 10) || 0;
    cfg.lower = parseInt(d.pwLower, 10) || 0;
    cfg.upper = parseInt(d.pwUpper, 10) || 0;
    cfg.special = parseInt(d.pwSpecial, 10) || 0;
  }

  /* ------------------------------------------------------------------ text */

  var de = {
    required: 'Bitte ausfüllen',
    lowerOnly: 'Nur Kleinbuchstaben erlaubt',
    badChars: 'Nur a–z, 0–9 sowie _ - . @',
    badEmail: 'Ungültige E-Mail-Adresse',
    emailMismatch: 'Die beiden E-Mail-Adressen stimmen nicht überein',
    pwPrefix: 'Noch offen: ',
    pwLength: 'mindestens {n} Zeichen',
    pwDigit: '1 Ziffer',
    pwLower: '1 Kleinbuchstabe',
    pwUpper: '1 Großbuchstabe',
    pwSpecial: '1 Sonderzeichen (z. B. *, -, #)'
  };
  var en = {
    required: 'Please fill this in',
    lowerOnly: 'Lowercase letters only',
    badChars: 'Only a–z, 0–9 and _ - . @',
    badEmail: 'Invalid e-mail address',
    emailMismatch: 'The two e-mail addresses do not match',
    pwPrefix: 'Still missing: ',
    pwLength: 'at least {n} characters',
    pwDigit: '1 digit',
    pwLower: '1 lowercase letter',
    pwUpper: '1 uppercase letter',
    pwSpecial: '1 special character (e.g. *, -, #)'
  };
  var t = /^de\b/i.test(document.documentElement.lang || '') ? de : en;

  /* --------------------------------------------------------------- helpers */

  function count(value, re) {
    var m = value.match(re);
    return m ? m.length : 0;
  }

  /* Unicode-aware classes, because Moodle's policy uses POSIX classes with /u:
   * "ü" is a lowercase letter to Moodle, and must not count as a "special"
   * character. Older engines fall back to ASCII, which can only be stricter in
   * the safe direction (it never accepts what Moodle rejects). */
  var RE = { lower: /\p{Ll}/gu, upper: /\p{Lu}/gu, digit: /\p{Nd}/gu, special: /[^\p{L}\p{N}]/gu };
  try { 'ä'.match(RE.lower); } catch (e) {
    RE = { lower: /[a-z]/g, upper: /[A-Z]/g, digit: /[0-9]/g, special: /[^a-zA-Z0-9]/g };
  }

  function hintsFor(id) {
    /* Returns the list of reasons `id` is not acceptable yet (empty = fine). */
    var el = document.getElementById(id);
    if (!el) { return []; }
    var v = el.value == null ? '' : String(el.value);
    var out = [];

    if (id === 'id_password') {
      if (v === '') { return []; }               // don't nag an untouched field
      if (v.length < cfg.length) { out.push(t.pwLength.replace('{n}', cfg.length)); }
      if (cfg.digits && count(v, RE.digit) < cfg.digits) { out.push(t.pwDigit); }
      if (cfg.lower && count(v, RE.lower) < cfg.lower) { out.push(t.pwLower); }
      if (cfg.upper && count(v, RE.upper) < cfg.upper) { out.push(t.pwUpper); }
      if (cfg.special && count(v, RE.special) < cfg.special) { out.push(t.pwSpecial); }
      return out;
    }

    if (id === 'id_username') {
      if (v === '') { return []; }
      if (/[^a-z0-9._@-]/.test(v) && /[A-Z]/.test(v)) { out.push(t.lowerOnly); }
      else if (/[A-Z]/.test(v)) { out.push(t.lowerOnly); }
      else if (/[^a-z0-9._@-]/.test(v)) { out.push(t.badChars); }
      return out;
    }

    if (id === 'id_email' || id === 'id_email2') {
      if (v === '') { return []; }
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v)) { out.push(t.badEmail); }
      if (id === 'id_email2') {
        var first = (document.getElementById('id_email') || {}).value || '';
        if (first && first.toLowerCase() !== v.toLowerCase()) { out.push(t.emailMismatch); }
      }
      return out;
    }

    return out;
  }

  function hintNode(el) {
    var row = el.closest ? el.closest('.fitem') : null;
    if (!row) { return null; }
    var node = row.querySelector('.offd-signup-hint');
    if (!node) {
      node = document.createElement('div');
      node.className = 'offd-signup-hint small text-danger mt-1';
      node.setAttribute('role', 'status');
      node.setAttribute('aria-live', 'polite');
      var target = row.querySelector('.felement') || row;
      target.appendChild(node);
    }
    return node;
  }

  function paint(el, reasons, force) {
    if (!el) { return false; }
    var empty = String(el.value == null ? '' : el.value).trim() === '';
    if (empty && !force) { reasons = []; }
    var node = hintNode(el);
    if (!node) { return reasons.length > 0; }
    if (!reasons.length) {
      node.textContent = '';
      node.hidden = true;
      el.removeAttribute('aria-invalid');
      return false;
    }
    var label = el.id === 'id_password' ? t.pwPrefix + reasons.join(', ') : reasons.join(' · ');
    node.textContent = label;
    node.hidden = false;
    el.setAttribute('aria-invalid', 'true');
    return true;
  }

  /* Fields we judge at all. `firstname`/`lastname`/`username`/`email`/`email2`
   * are "required" server-side too, but only the ones we can judge locally are
   * listed here; an empty required field is handled in blockingCheck(). */
  var live = ['id_username', 'id_password', 'id_email', 'id_email2'];

  live.forEach(function (id) {
    var el = document.getElementById(id);
    if (!el) { return; }
    var handler = function () { paint(el, hintsFor(id), false); };
    el.addEventListener('input', handler);
    el.addEventListener('blur', handler);
  });

  /* ------------------------------------------------------------- submitting */

  function blockingCheck() {
    var problems = [];
    ['id_username', 'id_password', 'id_email', 'id_email2', 'id_firstname', 'id_lastname']
      .forEach(function (id) {
        var el = document.getElementById(id);
        if (!el) { return; }
        if (String(el.value == null ? '' : el.value).trim() === '') {
          paint(el, [t.required], true);
          problems.push(el);
          return;
        }
        var reasons = hintsFor(id);
        if (paint(el, reasons, true)) { problems.push(el); }
      });
    return problems;
  }

  form.addEventListener('submit', function (e) {
    try {
      /* "Abbrechen" is a submit button in Moodle's form; it must always pass. */
      var submitter = e.submitter;
      if (submitter && (submitter.name === 'cancel' || submitter.getAttribute('data-skip-validation') === '1')) { return; }

      var problems = blockingCheck();
      if (!problems.length) { return; }

      e.preventDefault();
      var first = problems[0];
      if (first.scrollIntoView) { first.scrollIntoView({ block: 'center', behavior: 'smooth' }); }
      first.focus({ preventScroll: true });
    } catch (err) {
      /* Fail open: never let this file be the reason a registration cannot be
       * submitted. */
      if (window.console && window.console.warn) { window.console.warn('[offd] pre-check skipped:', err); }
    }
  }, true);
})();
