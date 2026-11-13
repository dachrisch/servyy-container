# OFFD final drop landed, and the instance moved to `offd.de`

**Date:** 2026-11-13
**Status:** ✅ Live — import verified, cutover done, `offd.de` serves with a Let's Encrypt cert, LeagueSphere follows
**Relates to:** [docs/plans/2026-11-13-moodle-final-drop-release.md](../docs/plans/2026-11-13-moodle-final-drop-release.md),
[history/2026-11-10_moodle-waitlist-plugin-and-release-tooling.md](2026-11-10_moodle-waitlist-plugin-and-release-tooling.md),
[history/2026-11-04_moodle-moodledata-ingested.md](2026-11-04_moodle-moodledata-ingested.md)

## Context

Christoph put the old KAS site into maintenance mode in the morning and pulled the final pair: a
logical dump and a tarball of `moodledata`. Both landed on servy while the instance still served the
rehearsal hostname `m.leaguesphere.app`, so the drop could be imported and verified end to end before
anything public changed. DNS moved last, by decision, and the old site stays in maintenance mode as
the rollback target.

## Import — measured

| Artifact | Facts |
|---|---|
| `dump-OFFD-d037491e-202611130825.sql.gz` | 136 028 659 B, `gzip -t` OK, 497 tables, `mdl_` schema, 119 lines with `offd.de/offd/moodle`, release `4.5.12 (Build: 20260608)` |
| `moodledata-2026-11-13.tar.gz` | 5 930 094 595 B, `gzip -t` OK, 11 445 files / 15 955 dirs, top level `moodledata`, `secret/key/sodium.key` = `c816ed65…` (identical to the 2026-11-04 export and the live dataroot) |
| Gate (`verify-offd-export.sh`) | **PASS** — 9 503 filedir files hash to their own name, 0 bad; 9 503/9 503 DB contenthashes present; **missing_on_disk 0, orphans_not_in_db 0** |
| Import | 9 524 filedir files, 497 tables, 4.5.12 → **4.5.15** with no pending upgrade, **136 rows** rewritten `offd.de/offd/moodle` → root, → 0 remaining |

After the import: **4 263 users (4 143 active) · 120 courses · 41 002 file rows · 9 503
contenthashes · 14 active waitlist instances**. Christoph's instance had grown by 15 users and 16
courses since the 2026-10-28 dump we rehearsed on — that is why the rewrite count moved 134 → 136.

`orphans_not_in_db 0` / `missing_on_disk 0` is the strongest evidence available that the dump and the
tarball were taken from the same state: every file in the archive is referenced by the database, and
every hash in the database exists in the archive.

### Verified on the instance before DNS moved

Site 200 (`Startseite | Flag Academy`), `upgrade.php --is-pending` rc 0, `enrol:
manual,guest,self,cohort,waitlist`, **14/14** waitlist courses expose the method, `offd.de/offd/moodle`
rows **0**, 9 503 DB hashes vs 9 524 files (missing 0), and a 29 375 166 B `mod_resource` PDF fetched
over HTTPS as a logged-in admin with **sha1 == DB contenthash**.

## Cutover — what actually ran

1. **Image bump first**, in the calm part of the day: `4.5.15 → 4.5.16`, pre-validated on
   `servyy-test.lxd` (plugin keeps version `2025072001`, site 200, `--is-pending` 0).
2. **Host change** (#294): `moodle_service_host: offd.de`, `docker.services[moodle].host: offd.de`,
   `SITE_URL`/`wwwroot` = `https://offd.de`. Verified on the box with `--resolve` before DNS moved.
3. **DNS**: Christoph changed the apex `A` to `49.13.6.173`; `www` got its own record pointing at us.
   KAS exposes **no TTL control** (zone at 7200), so no pre-lowering was possible — propagation
   happened fast anyway (1.1.1.1, 8.8.8.8, 9.9.9.9 all had it within minutes).
4. **Certificate**: Traefik issued `CN=offd.de` via HTTP-01 on first hit — valid to 2027-02-11.
5. **www** (#296): `www.offd.de` resolved to us but had no router, so it fell through to Traefik's
   default certificate — a "not secure" warning on a site that was otherwise fine. Fixed with a
   dedicated router plus a permanent `redirectregex` middleware: `www.offd.de/* → offd.de/*`
   (301, `verify=0`), same shape `achim-hoefer` uses.
6. **LeagueSphere** (#2382, released as 5.14.17): `/moodle` dropped from the webservice, token,
   profile and course paths; `ls.env.j2` dropped `/offd`, so `MOODLE_URL=https://offd.de`. Both halves
   shipped in the same window because they compose into one URL.

`m.leaguesphere.app` is **retired**: the router matches `offd.de` only, so it resolves through the
wildcard but answers 502. No user ever had that address; it was the rehearsal hostname.

## Decisions

1. **`--target-url https://offd.de` at import time.** Teacher-entered links are final at import, so
   the cutover carries no content mutation — the rewrite step becomes a verification (`0 rows`).
   The cosmetic cost (those links pointed at `offd.de` while DNS still answered with the old site) is
   this instance's steady state anyway: 106 questions already referenced `offd.de/pluginfile.php`.
2. **The import ran twice on purpose**: once with the 2026-11-04 archive as filler to start the DB
   chain while Christoph was still tarring, once with his real tarball. The final state is the output
   of the shipped script on the real pair, not of a hand-run `tar`.
3. **The image bump went in before the cutover**, so a failure during the DNS window could only have
   been routing or TLS — not a Moodle upgrade.
4. **www gets a 301, not a second copy.** One canonical host; a redirect consolidates links, and a
   second served copy would split sessions and bookmarks.
5. **IPv6 left alone.** The KAS zone publishes no AAAA at all, so v6-only clients already fall back
   to IPv4. Adding one opens a second reachability path that has not been exercised end to end; it is
   a separate, low-priority follow-up (`2a01:4f8:c013:f6f4::1`).

## Learnings

1. **A URL split across two repos is a single string.** LeagueSphere built every Moodle URL as
   `MOODLE_URL + "/moodle/…"` while the deployment set `MOODLE_URL=https://offd.de/offd`; the halves
   composed into the old path. Changing either alone yields `/offd/webservice/…` or
   `/moodle/webservice/…` and **neither fails loudly**: `requests` receives an HTML page, `.json()`
   raises, and the licence report dies with a `JSONDecodeError` that never names the URL. Now guarded
   by unit tests on both sides.
2. **`user.docker.repo` deploys the branch checked out on the controller**
   (`main.yml:40`, `git rev-parse --abbrev-ref HEAD`). Deploying a feature branch therefore ships that
   branch — which is how the image bump and the host change landed together once, the exact
   two-changes-at-a-time this runbook exists to avoid. Deploy from `master` only.
3. **Comparing a truncated fingerprint cannot match.** A digest check that cut one side to 19 chars
   and compared it to bare hex fired instantly and reported "image ready" for the old image. Poll for
   the release tag (`v5.14.17`) instead — it is the thing actually meant.
4. **`gzip -t` proves the stream, not the content.** A complete stream whose files do not match their
   content-addressed names passes it. Only the gate's sha1-vs-filename pass proves the archive.
5. **The signup autocomplete was broken for everyone, before the migration.** `CORS_URLS_REGEX` was
   `^/api/snapshot/$`, so `/dal/team/` returned no CORS headers, and the footer called the slashless
   URI, so Django answered `301` with none either. Fixed server-side (#2384, `^/api/snapshot/|/dal/team/?$`)
   — no Moodle content had to change, and the endpoint only exposes public team names.
6. **A Moodle `accessexception` usually means "function not in the service"**, not "unreachable".
   A connectivity test with `core_webservice_get_site_info` failed while the token's service was
   healthy; the real function (`core_course_get_courses_by_field`) returned course 71 immediately.
7. **The export carried no SMTP credentials** — `smtphosts`, `smtpuser`, `smtppass`, `smtpsecure` were
   all empty strings. The old site sent mail through KAS's local MTA via PHP `mail()`; there is no MTA
   in this container, so outbound mail needs a relay. The `smtp.gmail.com` + `your_email@gmail.com`
   values seen in the DB are the image's placeholders, written at every boot by
   `02-configure-moodle.sh` — mail settings edited in the Moodle UI are overwritten on restart, so
   they must come from Ansible.

## Rollback

| When | Action |
|---|---|
| Import bad | restore `data/db-backup/current/moodle.sql.gz` or the `pre-release` restic pair (08:55). Content extraction is additive, orphans are harmless |
| Cutover wrong, before DNS | point `moodle_service_host` back at `m.leaguesphere.app`, deploy, ~10 min |
| Cutover wrong, after DNS | flip `offd.de` A back to `85.13.146.136` **and** revert `SITE_URL`; old site is still in maintenance mode and holds the data |
| Anything worse | `baseline` restic pair (2026-11-06) plus `pre-release`; restore runbook in `moodle/AGENTS.md` |

## Open

- **Email.** Needs SMTP credentials for `noreply@offd.de` (or a KAS mailbox/relay), then
  `SMTP_HOST/PORT/USER/PASSWORD/PROTOCOL` in `moodle.app.env.j2` fed from the vault, so the image
  writes real values at every boot.
- **IPv6**, optional: `AAAA offd.de → 2a01:4f8:c013:f6f4::1` once a v6 client has confirmed the path.
- **Old host cleanup** after ~2 weeks, once nobody has asked for a rollback.
