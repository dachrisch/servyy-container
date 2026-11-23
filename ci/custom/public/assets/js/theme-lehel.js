// theme-lehel.js — small client-side touches for the ci.lehel.xyz theme.
//
// Only ever reads what Forgejo already puts in the page (window.config); it
// never invents or fakes data. Two jobs:
//   1. Sign-in hero: fill the real instance host + Forgejo version.
//   2. Keyboard shortcuts: "/" focuses search, "g a" -> Actions, "g r" -> repos.
(function () {
  "use strict";

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  // 1. Sign-in hero: real host + version from window.config (fallback stays as
  //    the static text in the template if anything is missing).
  function populateHero() {
    var cfg = window.config || {};
    var host = document.getElementById("lehel-host");
    if (host && cfg.appUrl) {
      try {
        host.textContent = new URL(cfg.appUrl).hostname;
      } catch (e) { /* keep the static fallback */ }
    }
    var ver = document.getElementById("lehel-version");
    if (ver && cfg.assetVersionEncoded) {
      // "17.0.2~gitea-1.22.0" -> "17.0.2"
      ver.textContent = decodeURIComponent(cfg.assetVersionEncoded).split("~")[0];
    }
  }

  // 2. Keyboard shortcuts.
  function keyboardShortcuts() {
    var sub = (window.config && window.config.appSubUrl) || "";
    document.addEventListener("keydown", function (e) {
      // Never steal keys while the user is typing.
      var t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) {
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      // "/" focuses Forgejo's search. It is a dropdown, so focus the input and
      // leave opening it to Forgejo's own handler (opening a dropdown is a
      // click/JS behaviour we do not want to fake).
      if (e.key === "/") {
        var search = document.getElementById("search") || document.querySelector(".navbar-right input[name='q'], #navbar input[type='text']");
        if (search) {
          e.preventDefault();
          search.focus();
        }
        return;
      }

      // "g a" / "g r" chords (a second key within ~1.2s of "g").
      if (window.__lehelG && Date.now() - window.__lehelG < 1200) {
        window.__lehelG = 0;
        var k = e.key.toLowerCase();
        if (k === "a") {
          e.preventDefault();
          // Actions overview (the single-admin instance is an admin, so the
          // global Actions/runners page is the honest target).
          window.location.assign(sub + "/admin/actions");
          return;
        }
        if (k === "r") {
          e.preventDefault();
          window.location.assign(sub + "/explore/repos");
          return;
        }
      }
      if (e.key === "g" || e.key === "G") {
        window.__lehelG = Date.now();
      }
    });
  }

  ready(function () {
    populateHero();
    keyboardShortcuts();
  });
})();
