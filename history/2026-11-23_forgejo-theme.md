# Forgejo theme (ci.lehel.xyz)

A custom "modern developer" theme for the private Forgejo at ci.lehel.xyz:
Space Grotesk headings, Inter body, JetBrains Mono for hashes/metrics/tags,
amber accent (light `#d48a10` / dark `#f2b84b`), rounded cards, status pills,
a faint 24px grid page background, and automatic light/dark via
`prefers-color-scheme`. Self-hosted fonts (SIL OFL), no Google Fonts calls.

## What was done

- Added a tracked `ci/custom/` tree mounted read-only into the container:
  - `public/assets/css/theme-lehel.css` — the theme. `@import`s the built-in
    `theme-forgejo-auto.css` (so every `--color-*` var stays defined) then
    overrides the semantic surface/text/accent variables for light and again
    inside `@media (prefers-color-scheme: dark)`.
  - `public/assets/fonts/*.woff2` + `OFL-*.txt` — Inter (400/500/600), Space
    Grotesk (500/700), JetBrains Mono (400/500), downloaded from Fontsource,
    licensed SIL OFL 1.1.
  - `public/assets/js/theme-lehel.js` — fills the hero's host + Forgejo version
    from `window.config` (never invented), plus keyboard shortcuts (`/` → search,
    `g a` → `/admin/actions`, `g r` → `/explore/repos`).
  - `templates/user/auth/signin.tmpl` — **full-template override** adding the
    sign-in hero column (see upgrade risk below).
  - `templates/custom/body_inner_post.tmpl` — loads `theme-lehel.js` before
    `</body>` (Forgejo's custom template hook; no override needed).
- Registered the theme via `FORGEJO__ui__THEMES` / `FORGEJO__ui__DEFAULT_THEME=lehel`
  in `docker_service/templates/ci/forgejo.env.j2`.
- Bind-mounted `./custom/{templates,public}` read-only in `ci/docker-compose.yml`.
  Only those two subdirs are mounted (not the whole `custom/`): Forgejo writes
  its own effective config to `CUSTOM_PATH/conf/app.ini` at install time, and a
  whole-path read-only mount would shadow that file.
- Added a molecule assertion (forgejo scenario) that the rendered `forgejo.env`
  registers the theme as default.
- Documented the theme in `ci/AGENTS.md`.

## Upgrade risks

- `ci/custom/templates/user/auth/signin.tmpl` is a full-template override
  (Forgejo's `custom/signin_mid.tmpl` hook only injects *inside* the sign-in
  card, not beside it). Re-check this template on every Forgejo upgrade.
- `theme-lehel.css` re-declares a subset of `--color-*` variables; if Forgejo
  adds/renames variables in a future release, the theme degrades to the built-in
  values for those slots (non-fatal) rather than breaking.

## Not included (deliberately — no fake data)

- The design's push heatmap and runner-status card on the sign-in page: those
  APIs are not available to a signed-out user on 17.0.2 (`/user/heatmap` needs
  auth; runner status is admin-only). The hero shows only real data (Forgejo
  version + host from `window.config`, "online", "private instance").
- Live runner/actions cards on the dashboard: the default Forgejo dashboard
  doesn't render them, and reworking that layout would be another full-template
  override. The dashboard keeps Forgejo's own layout, restyled.

## Files changed

- `ci/custom/…` (new tree)
- `ci/docker-compose.yml`, `ci/AGENTS.md`
- `ansible/plays/roles/docker_service/templates/ci/forgejo.env.j2`
- `ansible/plays/roles/docker_service/molecule/forgejo/verify.yml`

## Deployment

- Test (servyy-test only): `cd ansible && ./servyy-test.sh --tags user.docker.repo,user.docker.ci -e docker_branch=claude/forgejo-theme`
- Production: after approval, `cd ansible && ./servyy.sh --tags user.docker.repo,user.docker.ci --limit servy.lehel.xyz`

## Verification (servyy-test)

Deployed with `./servyy-test.sh --tags user.docker.repo,user.docker.ci -e docker_branch=claude/forgejo-theme`
(play recap: `failed=0`, `changed=4`; Forgejo `Up (healthy)` after restart). Verified:

- Theme CSS served: `curl -H 'Host: ci.servyy-test.lxd' http://localhost/assets/css/theme-lehel.css` → HTTP 200.
- Default theme applied: `/user/login` HTML has `data-theme="lehel"` and links `theme-lehel.css`.
- Sign-in hero renders: `.lehel-hero` / `.lehel-tagline` / `.lehel-status` present.
- Mounts: `docker inspect ci.forgejo` shows `ci/custom/{templates,public}` → `/var/lib/gitea/custom/…` (ro).
- No console/template errors in `docker logs ci.forgejo` after restart.
- Layout verified by bounding-box measurement, not just markup: at 1440×900 the hero
  (x=201 w=552) and the card (x=825 w=400, inputs w=370) sit side-by-side and vertically
  centered; at 390×844 the hero and card stack full-width (inputs w=328). Screenshots of
  `/user/login` and the dashboard at 1440×900 and 390×844, light + dark, in the closing
  report (backgrounds sampled: light ≈ `#f4f6f9`, dark ≈ `#0d131b`).

Gotcha (documented, not a bug): the existing admin `cda` keeps their prior
`forgejo-auto` theme — `DEFAULT_THEME` only governs anonymous/new users. To adopt
`lehel` the account switches it in Settings → Appearance (done on servyy-test for
the dashboard screenshots via a temporary `theme-val` API token, deleted afterwards
via `DELETE /api/v1/users/cda/tokens/theme-val`).
