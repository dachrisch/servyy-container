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
 * #id_profile_field_teamname, so jQuery/select2 are fetched on demand — through
 * Moodle's own RequireJS where it exists (it always does in practice), which
 * also means Moodle's jQuery is reused instead of downloading a second copy. If
 * a dependency cannot be loaded, nothing is hidden and the plain Moodle text
 * field stays usable: the participant can still type their club name.
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

  /* "ohne Team" by id (the real list row) or by name (free text / tag). */
  function isNoTeam(name, id) {
    if (String(id) === String(INVOICE_TEAM_ID)) { return true; }
    return String(name || '').trim().toLowerCase() === INVOICE_TEAM_NAME;
  }

  /* jQuery first, then select2, then hand back the instance select2 attached to.
   *
   * Two things make this less obvious than it looks:
   *
   * 1. Moodle's RequireJS is always on the page. Both jQuery and select2 are
   *    UMD bundles that PREFER AMD whenever `define.amd` exists — select2 then
   *    calls `define(["jquery"], …)` and binds to the AMD jquery module, not to
   *    `window.jQuery`. Loading it as a plain <script> after RequireJS is up
   *    therefore leaves `window.jQuery.fn.select2` empty, which is exactly how
   *    the first version of this file failed silently. So: use the AMD path
   *    when it is there, which also means we reuse Moodle's own jQuery instead
   *    of downloading a second copy.
   * 2. The plain-script fallback (no RequireJS) has to keep `window.jQuery`
   *    pinned to our instance for the length of select2's load, because that is
   *    the only jQuery the UMD will find then. The previous value is restored
   *    afterwards.
   *
   * Either way `done` receives the jQuery that select2 actually attached to —
   * never re-read the global, it is a moving target on a Moodle page. */
  function loadPickerLibs(done) {
    var haveAmd = window.require && window.define && window.define.amd;

    if (haveAmd) {
      try {
        window.require.config({
          paths: { offdselect2: ASSET_BASE + 'vendor/select2-4.0.13.min' }
        });
      } catch (e) {
        done(e);
        return;
      }
      window.require(['jquery', 'offdselect2'], function ($) {
        if (!$ || !$.fn || !$.fn.select2) {
          done(new Error('select2 did not attach to the AMD jQuery'));
          return;
        }
        done(null, $);
      }, function (err) {
        done(err || new Error('requirejs could not load jquery + select2'));
      });
      return;
    }

    function withJquery($) {
      if ($ && $.fn && $.fn.select2) { done(null, $); return; }
      var prevJquery = window.jQuery;
      var prevDollar = window.$;
      window.jQuery = window.$ = $;
      loadScript(ASSET_BASE + 'vendor/select2-4.0.13.min.js', function (err) {
        if (window.jQuery === $) { window.jQuery = prevJquery; }
        if (window.$ === $) { window.$ = prevDollar; }
        if (err || !$ || !$.fn || !$.fn.select2) {
          done(err || new Error('select2 did not attach to jQuery'));
          return;
        }
        done(null, $);
      });
    }

    if (window.jQuery) { withJquery(window.jQuery); return; }
    loadScript(ASSET_BASE + 'vendor/jquery-3.6.0.min.js', function (err) {
      if (err) { done(err); return; }
      var $ = window.jQuery;
      if (!$) { done(new Error('jQuery loaded but set no window.jQuery')); return; }
      withJquery($);
    });
  }

  ready(function () {
    if (!document.getElementById('id_profile_field_teamname')) { return; }  // not the signup / profile form.

    loadCss(ASSET_BASE + 'vendor/select2-4.0.13.min.css');
    loadPickerLibs(function (err, $) {
      if (err) {
        /* Leave the plain field alone — worst case the participant types the
         * club name and the invoice rule is not applied. Never hide a field we
         * cannot drive. A broken picker must be visible in the console. */
        if (window.console && window.console.warn) {
          window.console.warn('[offd] team picker disabled:', err.message || err);
        }
        return;
      }
      init($);
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
