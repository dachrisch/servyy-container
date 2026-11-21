# The rehearsal Moodle mailed nine real OFFD admins — "wrong server address" in the update mail

**Date:** 2026-11-21
**Service:** Moodle — production `https://offd.de` (servy) and the rehearsal instance on
`servyy-test.lxd`
**Reported as:** a forwarded mail — *"Aktualisierungen für Moodle sind verfügbar:
http://moodle.servyy-test.lxd"*, sent from `noreply@offd.de` / "OFFD Admin (über Flag Academy)" to
`kontakt@kaempfe.ch` on 2026-11-20 08:55 — i.e. "our Moodle mails use the wrong server address".

## It was not production

Production is clean, and each piece of evidence for that is independent:

| Check | Production |
|---|---|
| `$CFG->wwwroot` | `https://offd.de` |
| Its own update notification (`mdl_notifications`, `eventtype='availableupdate'`) | 2026-11-18 21:56, **`Aktualisierungen für Moodle sind verfügbar: https://offd.de`** to all 10 site admins |
| Body links of the newest mails (login notice, task failure) | `https://offd.de/…` |
| The plugin named in the forwarded mail (`mod_booking`, "new version 2026110500") | **not installed at all** — `mdl_config_plugins` has 0 `mod_booking` rows (a disk-deleted plugin leaves its rows behind, cf. `qbehaviour_adaptiveallnothing`), so prod's update checker cannot report it |
| `mdl_config_log` / `app.env` mtime | no `wwwroot` change ever logged; `SITE_URL=https://offd.de`, untouched since 2026-11-19 |
| `mdl_task_log` around 2026-11-20 08:55 | no update-check task ran (only login notices, enrol_waitlist, brickfield) |

Every URL in a Moodle mail is `$CFG->wwwroot` **at send time**, so the sender's site URL was
`http://moodle.servyy-test.lxd` — the rehearsal instance. The `[[pluginname]]` placeholder in its
mail is the symptom of that box: the plugin's files were removed during the 2026-11-13 Booking
spike (`history/2026-11-13_moodle-booking-spike.md`) while its version row stayed, so the update
checker keeps offering a newer `mod_booking`.

## Why real people received it

The rehearsal box runs a **copy of the production database**, so its `siteadmins` are the real
nine people (`kontakt@kaempfe.ch`, `admin@offd.de`, …), and until this fix it was rendered with the
**production SMTP credentials** (`support@offd.de` on the KAS relay, visible sender
`noreply@offd.de`) — the same `moodle.app.env.j2` renders for every host. Nothing about that mail
says "test".

Note the env-render is also why the wrong URL is *self-inflicted but legitimate*: on the test host
`service_host` is `moodle.servyy-test.lxd` by design (`ansible/testing`), so its `SITE_URL`, its
Traefik router and every link it mails are that hostname. The bug is the mail, not the URL.

## Fix

`moodle.app.env.j2` grew a `moodle_mail_disabled` branch, and `ansible/testing` sets it:

```
SMTP_HOST=127.0.0.1        # connection refused instantly, nothing leaves the box
SMTP_PORT=25
SMTP_USER= / SMTP_PASSWORD= / SMTP_PROTOCOL=   # the real KAS credentials never land on a test host
MOODLE_MAIL_NOREPLY_ADDRESS=noreply@invalid
```

The image supports exactly this shape (`02-configure-moodle.sh` sets empty user/password/protocol
whenever `SMTP_HOST` is set, upstream #194), and the values are re-applied on **every** boot, so a
rehearsal cannot drift back to the real relay. Production renders unchanged (verified by rendering
the template both ways with Ansible).

## Verification

```bash
# non-prod render
grep -E '^SMTP_' moodle/app.env        # on servyy-test: 127.0.0.1 / 25 / empty creds
# prod render must be untouched
ssh lehel.xyz "grep -E '^SMTP_' /home/cda/servyy-container/moodle/app.env"
```

## Open point

`servyy-test.lxd` is **not reachable from the fleet** (no LXD container on servy or codey, no DNS
entry, and Forgejo's runner list holds only `codey` and `runny`), so the fix above is committed but
not yet deployed to it — it runs wherever that LXD host lives (the branch-deploy skill assumes the
laptop). Until it is redeployed there, that box still holds the production SMTP credentials and can
send as `noreply@offd.de`; it should either be redeployed from `ansible/testing` or be shut down.
Consider rotating the KAS mailbox password once it is gone, since a non-production host has held it.
