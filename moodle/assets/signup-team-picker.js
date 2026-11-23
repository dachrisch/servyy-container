/* OFFD ("Flag Academy") team picker for the signup and profile-edit forms.
 *
 * WHAT THIS REPLACES
 * Until 2026-11-22 this was an inline <script> in mdl_config.additionalhtmlfooter:
 * unversioned, unreviewable, and it loaded jQuery 3.6.0 + select2 4.0.13 from
 * code.jquery.com / cdnjs on EVERY page of the site (~175 kB) even though the
 * widget only exists on two forms. That is why it now lives here.
 *
 * HOW IT IS WIRED
 * `additionalhtmlfooter` carries exactly one tag — <script src=".../signup-team-picker.js?v=N">
 * — reconciled from git by ansible/plays/roles/user/tasks/moodle_signup_picker.yml.
 * The file is bind-mounted read-only at /var/www/html/moodle-custom (docker-compose.yml)
 * and served by the image's nginx, which caches *.js for 5 days, hence the ?v=N
 * and the rule: bump MOODLE_SIGNUP_PICKER_VERSION in plays/vars/default.yml
 * whenever this file changes, or returning visitors keep the old one.
 *
 * WHY A LOADER AND NOT THREE <script> TAGS
 * Only the signup (/login/signup.php) and profile-edit forms carry
 * #id_profile_field_teamname, so jQuery/select2 are fetched on demand. If any of
 * the three assets fails to load, nothing is hidden and the plain Moodle text
 * field stays usable — the participant can still type their club name.
 *
 * WHAT IT DOES
 * - teamname (profile field 3) is what the participant sees and what Moodle
 *   stores; teamid (field 7) is the leaguesphere team id behind it. Both inputs
 *   are hidden and filled from the picker. teamid = -1 marks a club that is not
 *   in the leaguesphere list (free text / tag); that is deliberate, not a bug.
 * - The list comes from https://leaguesphere.app/dal/team/ (select2 ajax,
 *   server-side `term` filtering).
 * - Team id 213 is the "ohne Team" row. Selecting it — or typing "ohne Team" as
 *   free text — requires the invoice address (field 8). That used to depend on
 *   which of the two paths the participant took, and the required flag could be
 *   left on a hidden input, which makes a form silently unsubmittable.
 */
(function () {
  'use strict';

  var TEAM_API = 'https://leaguesphere.app/dal/team/';
  var ASSET_BASE = '/moodle-custom/';
  var INVOICE_TEAM_ID = 213;
  var INVOICE_TEAM_NAME = 'ohne team';

  function ready(fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn);
    } else {
      fn();
    }
  }

  function loadScript(src, done) {
    var el = document.createElement('script');
    el.src = src;
    el.onload = function () { done(null); };
    el.onerror = function () { done(new Error('failed to load ' + src)); };
    document.body.appendChild(el);
  }

  function loadCss(href) {
    var el = document.createElement('link');
    el.rel = 'stylesheet';
    el.href = href;
    document.head.appendChild(el);
  }

  /* Run `steps` in order; `steps` are functions taking a `next` callback. */
  function chain(steps, onDone) {
    var i = 0;
    (function next(err) {
      if (err) { onDone(err); return; }
      if (i >= steps.length) { onDone(null); return; }
      steps[i++](next);
    })();
  }

  /* "ohne Team" by id (the real list row) or by name (free text / tag). */
  function isNoTeam(name, id) {
    if (String(id) === String(INVOICE_TEAM_ID)) { return true; }
    return String(name || '').trim().toLowerCase() === INVOICE_TEAM_NAME;
  }

  ready(function () {
    var teamName = document.getElementById('id_profile_field_teamname');
    if (!teamName) { return; }          // not the signup / profile form: do nothing.

    var steps = [];

    if (!window.jQuery) {
      steps.push(function (next) {
        loadScript(ASSET_BASE + 'vendor/jquery-3.6.0.min.js', next);
      });
    }
    steps.push(function (next) {
      loadCss(ASSET_BASE + 'vendor/select2-4.0.13.min.css');
      if (window.jQuery && window.jQuery.fn && window.jQuery.fn.select2) { next(null); return; }
      loadScript(ASSET_BASE + 'vendor/select2-4.0.13.min.js', next);
    });

    chain(steps, function (err) {
      if (err || !window.jQuery || !window.jQuery.fn.select2) {
        /* Leave the plain field alone — worst case the participant types the
         * club name and the invoice rule is not applied. Never hide a field we
         * cannot drive. */
        return;
      }
      init(window.jQuery);
    });
  });

  function init($) {
    /* Captured now, in a closure: Moodle's theme deletes the global jQuery on
     * some pages, so re-reading window.jQuery later is not safe. */
    var $teamName = $('#id_profile_field_teamname');
    var $teamId = $('#id_profile_field_teamid');
    var $invoice = $('#id_profile_field_rechnung');
    var $invoiceRow = $('#fitem_id_profile_field_rechnung');

    /* The submitted values live in the two Moodle inputs; the picker is only a
     * view over them (it has no name, so it is never posted). */
    $teamName.hide();
    $teamId.hide();
    $invoiceRow.hide();

    /* Presented as required even though the profile field is optional
     * server-side (kept from the previous inline version, which is what the
     * site looked like before). */
    $('<div class="form-label-addon d-flex align-items-center align-self-start">'
      + '<div class="text-danger" title="Required">'
      + '<i class="icon fa fa-circle-exclamation text-danger fa-fw" title="Required" '
      + 'role="img" aria-label="Required"></i>'
      + '</div></div>').insertAfter($('#id_profile_field_teamname_label'));

    var $select = $('<select id="id_profile_field_teamselect" style="width: 50%;"></select>');
    $select.insertAfter($teamName);
    $select.after($('<div>Du hast kein Team? Dann bitte "ohne Team" eingeben oder auswählen '
      + '– wir brauchen dann eine Rechnungsadresse.</div>'));

    function applyInvoiceRule(needsInvoice, clearValue) {
      if (needsInvoice) {
        $invoiceRow.show();
        $invoice.attr('required', true);
        return;
      }
      /* Order matters: drop `required` BEFORE hiding. A hidden required control
       * makes the browser refuse the submit with only a console message
       * ("An invalid form control ... is not focusable"). */
      $invoice.removeAttr('required');
      if (clearValue) { $invoice.val(''); }
      $invoiceRow.hide();
    }

    var initialName = String($teamName.val() || '');
    var initialId = String($teamId.val() || '');

    $select.select2({
      placeholder: 'Tippen, um den Teamnamen auszuwählen…',
      tags: true,                 // clubs that are not in the leaguesphere list
      allowClear: true,
      /* A free-text tag must come AFTER the matching teams: pressing Enter on
       * "Marburg" used to store the fragment instead of "Marburg Mercenaries". */
      insertTag: function (data, tag) { data.push(tag); },
      ajax: {
        url: TEAM_API,
        dataType: 'json',
        delay: 250,
        cache: true
      }
    });

    if (initialName || initialId) {
      $select.append(new Option(initialName, initialId, true, true)).trigger('change');
    }
    applyInvoiceRule(isNoTeam(initialName, initialId), false);

    $select.on('select2:select', function (e) {
      var data = e.params.data;
      var parsedId = parseInt(data.id, 10);
      var teamId = isNaN(parsedId) ? -1 : parsedId;
      $teamName.val(data.text);
      $teamId.val(teamId);
      applyInvoiceRule(isNoTeam(data.text, teamId), true);
    });

    $select.on('select2:clear', function () {
      $teamName.val('');
      $teamId.val('');
      applyInvoiceRule(false, true);
    });
  }
})();
