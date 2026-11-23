# Traefik sent `X-Frame-Options: DENY`: Moodle's embedded PDFs were blocked

**Date:** 2026-11-23 (reported 2026-11-22)
**Branch:** `master` (direct, `dd88f359`)
**Services touched:** `traefik.traefik` on **servy and codey** — `dynamic.yaml` only, applied
in place (no recreate, no downtime), plus a repo-sync deploy on both hosts

Christoph reported that some participants of "36. Trainer C Tackle" could not open PDFs on a
laptop: Chrome showed its PDF-viewer error page, `ERR_BLOCKED_BY_RESPONSE`, with "offd.de ist
gesperrt / offd.de hat die Verbindung abgelehnt" inside the resource page. The same link
worked on a phone. He suspected `X-Frame-Options` and was right.

## Cause

`security-headers@file` (`traefik/dynamic.yaml`, on both entrypoints) set `frameDeny: true` —
`X-Frame-Options: DENY` on **every** response, `Header().Set()`, so it replaces what the
backend sends. It had been that way since `history/2026-10-29_traefik-security-headers.md`,
whose own comment said: *"Watch moodle after rollout: if any of its views frame same-origin
content, switch to `customFrameOptionsValue: SAMEORIGIN` instead."*

Moodle does exactly that, and deliberately:

| Fact | Where |
|---|---|
| Moodle sends `X-Frame-Options: sameorigin` itself | `lib/weblib.php:1581` (`send_headers()`) |
| A resource on "Eingebettet" renders `<iframe id="resourceobject" src="pluginfile.php/…">` | `lib/resourcelib.php:232` (`resourcelib_embed_pdf()`), reached from `mod/resource/view.php:100` |
| "Automatisch" does **not** embed PDFs — it opens them top-level | `mod/resource/locallib.php:495-517` (`RESOURCELIB_DISPLAY_OPEN` for a PDF) |

`DENY` forbids *same-origin* framing too, so Chrome refused the frame and its PDF viewer
rendered the error page in it. Mobile never frames the PDF: it navigates to the file
top-level or downloads it, where XFO does not apply. That is why it looked like a
browser/OS problem.

Only **20** resources are on "Eingebettet" (449 are on "Automatisch", 5+4+7 on the
new-window/popup variants), which is why Christoph wrote "einige Teilnehmer:innen" and why the
Timetable/`Folien` activities broke while the "Automatisch" PDFs did not.

Live proof before the change: `curl -sI https://offd.de/login/index.php` →
`x-frame-options: DENY`.

## Change

`traefik/dynamic.yaml`: `frameDeny: true` → `customFrameOptionsValue: SAMEORIGIN` (Traefik
rejects both keys at once), comment rewritten with the measurement above.

`customFrameOptionsValue` still *replaces* the backend's value, so the apps that send `DENY`
themselves (photoprism, leaguesphere, monitor, firefly) now receive `SAMEORIGIN` from the
edge. Not a weakening in practice: `DENY` and `SAMEORIGIN` differ only for same-origin
framing, which an app can always do to itself. Cross-site clickjacking stays blocked, and the
duplicate XFO pairs that testssl flagged on firefly stay collapsed.

## Deploy

The config is a single-file bind mount, so the repo sync alone does nothing (new inode):

```bash
cd ansible && ./servyy.sh --limit servy.lehel.xyz   --tags user.docker.repo,user.docker.traefik
cd ansible && ./servyy.sh --limit codey.lehel.xyz   --tags user.docker.repo,user.docker.traefik
# on each host, keeps the inode so `watch` reloads in ~3 s (no recreate):
docker exec -i traefik.traefik sh -c 'cat > /etc/traefik/dynamic.yaml' < ~/servyy-container/traefik/dynamic.yaml
```

`traefik.traefik` was **not** recreated (servy's container had been up since 2026-11-21);
`docker exec traefik.traefik grep customFrameOptionsValue /etc/traefik/dynamic.yaml` is the
check that matters, never the host checkout.

## Verification (measured)

| Check | Result |
|---|---|
| `curl -sI https://offd.de/login/index.php` | `x-frame-options: SAMEORIGIN` |
| `curl -sI https://monitor.lehel.xyz/` (codey) | `x-frame-options: SAMEORIGIN` |
| same-origin `<iframe src="/login/signup.php">` injected into offd.de, read from the parent | loaded, `title="New account \| Flag Academy"`, 3 834 chars of text |
| offd.de / leaguesphere.app / monitor | 200 / 301 / 302 — routing unaffected |

A frame that renders now is the exact condition that failed; before the change the same
injection produced Chrome's blocked-frame page.

## Rollback

`git revert` the commit, re-sync, `cat >` again (or `docker compose up -d --force-recreate
traefik`). Expect every "Eingebettet" resource to break again on desktop — including on
mobiles that render PDFs in an in-app frame.

## Follow-ups (not done)

- The 5 resource variants on "In neuem Fenster"/"Popup" and the 449 "Automatisch" ones were
  never affected; only "Eingebettet" needs the header. Changing them was the workaround we
  did **not** take (it would have hidden the real bug for those 20 activities only).
- `X-Frame-Options` is old technology: if a CSP is ever introduced fleet-wide, the same
  decision becomes `frame-ancestors 'self'`.
