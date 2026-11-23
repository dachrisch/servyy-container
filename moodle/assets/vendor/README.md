# Vendored browser libraries for the signup team picker

`moodle/assets/signup-team-picker.js` needs select2. jQuery and select2 are committed
here instead of loaded from a CDN, for the same reason
[`moodle/plugins/`](../../plugins/README.md) vendors the enrolment plugin: **the
registration form is the front door of the site.** A CDN outage, a corporate
proxy or an ad blocker that filters `cdnjs.cloudflare.com` used to leave the
picker dead for that visitor — silently, because the script that hid the plain
text field had already run. Now every asset comes from the same origin as the
page.

Nothing else is vendored: no build step, no package manager, no sass.

**jQuery is rarely fetched at all.** On a Moodle page the picker loads select2
through Moodle's RequireJS (`require(['jquery', 'offdselect2'])`), which reuses
Moodle's own jQuery; the two plain `<script>` files below are the fallback for
the case where RequireJS is not on the page. Both are UMD bundles, and with
`define.amd` present they register as AMD modules instead of attaching to
`window.jQuery` — which is why loading select2 as a plain script on a Moodle
page silently produces `window.jQuery.fn.select2 === undefined`.

| File | Source | sha256 |
|---|---|---|
| `jquery-3.6.0.min.js` | `https://code.jquery.com/jquery-3.6.0.min.js` | `ff1523fb7389539c84c65aba19260648793bb4f5e29329d2ee8804bc37a3fe6e` |
| `select2-4.0.13.min.js` | `https://cdnjs.cloudflare.com/ajax/libs/select2/4.0.13/js/select2.min.js` | `00501810e93307a8882a74d864e7547fd1458deea539361dc1124ac133799a4b` |
| `select2-4.0.13.min.css` | `https://cdnjs.cloudflare.com/ajax/libs/select2/4.0.13/css/select2.min.css` | `15d6ad4dfdb43d0affad683e70029f97a8f8fc8637a28845009ee0542dccdf81` |

jQuery 3.6.0's hash matches the SRI published at <https://releases.jquery.com/>;
select2's matches the file cdnjs serves. `select2.min.css` references no
external images (`grep 'url('` is empty), so the three files are complete.

## Updating one

1. Download the new file, run `sha256sum`, update the row above.
2. Bump `moodle_signup_picker_version` in
   [`ansible/plays/vars/default.yml`](../../../ansible/plays/vars/default.yml) —
   the image's nginx sends `expires 5d` for `*.js`/`*.css` and the file names are
   stable, so without the bump returning visitors keep the old bytes for days.
3. Deploy: `cd ansible && ./servyy.sh --tags user.docker.repo,user.docker.moodle --limit servy.lehel.xyz`.
4. Verify from a browser on the signup page: the picker renders, and
   `getComputedStyle(document.getElementById('id_profile_field_teamname')).display === 'none'`
   (i.e. the plain field was replaced, not left next to it).
