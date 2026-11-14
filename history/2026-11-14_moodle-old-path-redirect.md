# Old `/offd/moodle/…` links now answer with a permanent 301

**Date:** 2026-11-14
**Status:** ✅ Accepted — deployed to `servy.lehel.xyz` (production)
**Relates to:** [history/2026-11-13_offd-cutover.md](2026-11-13_offd-cutover.md),
[docs/plans/2026-11-13-moodle-final-drop-release.md](../docs/plans/2026-11-13-moodle-final-drop-release.md),
[moodle/AGENTS.md](../moodle/AGENTS.md)

## Context

The OFFD cutover moved the instance from `https://offd.de/offd/moodle` to the host root. The import
rewrote the five live-content columns (136 rows), but that is not where all old URLs live. A status
check one day after the release measured, in 24 h of access logs:

| Signal | Measured |
|---|---|
| `/offd/moodle/…` responses | **1 667 × 404** |
| — of which the old KAS host's web cron | 1 307 (`admin/cron.php?password=…`, from `85.13.146.136`) |
| — of which real user/bot misses | **360** |
| Top missed paths | `course/view.php` 70, `mod/book/view.php` 68, `mod/forum/view.php` 44, `mod/forum/discuss.php` 31 |
| External referrers | `safv.ch` (40), `5erdffl.de` (15) |
| Old path still stored in the DB | `mdl_messages` 13 552, `mdl_notifications` 507, `mdl_question_attempts` 310, `mdl_tiny_autosave` 97 |

So three populations were broken: other sites' links, user bookmarks, and old links inside message
history/notifications that no content rewrite had touched. The redirect is exact by construction —
the old wwwroot *was* the prefix, so stripping it maps every URL 1:1 onto the new site.

## Decision

Add a second Traefik router + `redirectregex` middleware to the moodle stack:

```
Host(offd.de) && (Path('/offd/moodle') || PathPrefix('/offd/moodle/'))
  && !Path('/offd/moodle/admin/cron.php')
  → 301 https://offd.de/<rest>
```

Three details are load-bearing:

1. **`!Path('/offd/moodle/admin/cron.php')` is excluded.** The old KAS host still calls that URL every
   minute with the old site's cron password. A blanket redirect would aim an unknown password at our
   real `admin/cron.php`; the request keeps answering 404 until the old host is decommissioned.
2. **The match is gated on `TRAEFIK_HTTP_REDIRECT_HOST`** (the same sentinel the http→https router
   uses: empty on the TLS-less test host falls back to `moodle-http-redirect.invalid`). Without the
   gate, `servyy-test.lxd` would redirect plain-HTTP requests to an https listener that does not exist.
3. **The regex captures the query string** (`/offd/moodle/?(.*)` → `/$1`), so `?id=123` survives.

Not chosen: rewriting the remaining ~14,5k rows in place. It cannot reach external links or browser
bookmarks, and it would rewrite user message history — a redirect covers all three and is reversible
by deleting labels.

## Consequences

### Positive

- One rule fixes external links (search engines, `safv.ch`, `5erdffl.de`), user bookmarks, and old
  links inside already-delivered messages/notifications — no content mutation.
- 301 (not 302) consolidates link equity instead of leaving duplicate 404s in search indexes.
- The rule lives in `moodle/docker-compose.yml` next to the existing `www → apex` redirect, so it is
  git-tracked and deployed by Ansible like every other label.

### Negative / Tradeoffs

- One more router whose priority depends on Traefik's rule-length tie-break (the longer rule wins, so
  `/offd/moodle/…` is matched before the plain `Host()` router). A future simplification to a bare
  `PathPrefix` would silently start redirecting the old host's cron.
- Changing labels recreates the app container (~30 s), i.e. the redirect ships as a deploy, not a hot
  reload.
- The redirect keeps legacy URL shapes alive forever. It is intentionally cheap, but it is also
  permanent-looking: nothing will ever tell us when it can go.

### Implementation Details

**Files modified:**

- `moodle/docker-compose.yml` — router `${SERVICE_NAME}-oldpath` + middleware
  `${SERVICE_NAME}-oldpath-redirect`, with the exclusion and gating comments inline
- `moodle/AGENTS.md` — documents the redirect and the cron exclusion; fixes the stale image tag
  (`v4.5.15` → `4.5.16`, drifted since #293)
- `ansible/plays/roles/docker_service/molecule/default/{converge,verify}.yml` — see learnings 2

**Commits:**

- `a72ab42` feat(moodle): 301 old /offd/moodle/… links to the root
- `0e7fae8` test(docker_service): pass the moodle SMTP vault vars to the molecule scenario

**Testing & Verification:**

- Rendered with the production `.env` on the host (`docker compose -f … config`): rule, regex,
  replacement and certresolver all interpolate as intended.
- `curl -sI` on old paths (with and without query string) → `301` + correct `Location`; the excluded
  `admin/cron.php` still `404`; front page still `200`; `upgrade.php --is-pending` still `0`.
- Post-deploy: container healthy, no OOM, backups unaffected. 24 h later the old-path 404 count should
  collapse to the cron hits only.

### Key Learnings

1. **A `wwwroot` search-replace is not a URL migration.** It fixes the five columns that render page
   bodies; message history, notifications and question attempts keep their stale links. The cheapest
   complete answer is an edge redirect, not a bigger `UPDATE`.
2. **Yesterday's release left CI red and nobody noticed.** #298 added `SMTP_*` to
   `moodle.app.env.j2` without adding the five `vault_moodle_smtp_*` test values to the
   `docker_service` molecule scenario, so `molecule test` failed with
   `'vault_moodle_smtp_host' is undefined` on every run since — a required check on every PR. The
   fix also asserts the rendered `app.env` carries the SMTP wiring, because the image overwrites
   `mdl_config` from those vars on every boot and a missing line breaks mail silently.
3. **The old host keeps talking to us.** Its web cron still fires every minute at the old path; that
   traffic is both the largest source of 404s and a reason not to build a catch-all redirect for the
   prefix.

### Known Issues & Limitations

- The redirect covers the apex host only. `www.offd.de/offd/moodle/…` hits the `www → apex` router
  first, which already strips `www` and then lands on the redirect, so it works — but it is two hops.
- The old KAS host's cron requests remain in the logs (and its password in them) until that host is
  decommissioned, which is the open post-cutover cleanup item.

## Alternatives Considered

### Alt A: Rewrite the remaining old-path rows in the database

- **Pros:** no edge rule, canonical URLs in stored content.
- **Cons:** cannot fix external sites or bookmarks; rewrites user message history (13 552 rows) for a
  cosmetic gain; another `UPDATE` to get wrong.
- **Rejected.**

### Alt B: nginx `map`/`return 301` inside the container

- **Pros:** closest to the app, no Traefik label.
- **Cons:** the image owns nginx.conf and the docroot is immutable by design; the change would live
  outside git and die at the next image bump.
- **Rejected.**

### Alt C: Catch-all `/offd/*` redirect

- **Pros:** also catches stray paths.
- **Cons:** would swallow the old host's cron call into the real endpoint, and nobody knows what else
  lives under `/offd/`.
- **Rejected** — the prefix is deliberately exact.

## Related Decisions

- [2026-11-13_offd-cutover.md](2026-11-13_offd-cutover.md) — the import that made the old path stale.
- [2026-11-13_moodle-enrol-waitlist-security-bump.md](2026-11-13_moodle-enrol-waitlist-security-bump.md)
  — same release window, same "fix it at the edge, not in user data" reasoning for the waitlist pages.
