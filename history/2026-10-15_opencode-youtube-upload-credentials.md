# 2026-10-15 — opencode service: YouTube upload credentials for unattended record-tutorial uploads

## Goal

Let the server-side opencode container (`codey.lehel.xyz`, container
`opencode.web`) upload `record-tutorial` videos to the **bumble:tube** YouTube
channel unattended, by provisioning the existing OAuth token (currently
`~/.config/leaguesphere/youtube_token.json` on the developer's box) into the
container. The token is consumed by a **companion change in the separate
`leaguesphere` repo** (its own branch/PR) that teaches `yt_upload.py` to read
it — that change is **not** part of this repo's branch and is not yet merged.
Plan: `docs/plans/2026-10-15-opencode-youtube-upload-credentials.md` (Part A in
this repo; Part B in `leaguesphere`).

The token is self-contained (`client_id` + `client_secret` + `refresh_token` +
`token_uri`), so `google-auth` refreshes it non-interactively; the Desktop
client secret is **not** needed on the server. The token is an upload grant to
`bumble:tube` (`UCbp6-pIVMxhvI7m3tarMK6w`) and is treated as a secret
throughout (git-crypt, `0600`, Vaultwarden backup).

## Change

### Flow: `secrets.yml` → `opencode.env` → container

1. `ansible/plays/vars/secrets.yml` (git-crypt encrypted) — new
   `opencode.youtube_oauth_token_json`, a single-quoted JSON scalar holding the
   whole token object. This is the source of truth for every `opencode.*`
   secret.
2. `ansible/plays/roles/docker_service/templates/opencode/.env.j2` — renders it
   to `opencode.env` (mode `0600`) as
   `YOUTUBE_OAUTH_TOKEN_B64={{ (opencode.youtube_oauth_token_json | default('')) | b64encode }}`.
   The `default('')` guard keeps rendering working on hosts that do not define
   the var (e.g. the molecule stub, other inventory hosts).
3. `opencode/docker-compose.yml` injects `opencode.env` via `env_file`, so the
   container sees `YOUTUBE_OAUTH_TOKEN_B64` as an environment variable.

### `YOUTUBE_OAUTH_TOKEN_B64` convention

The token JSON is **base64-encoded** for transport. This survives `env_file`
quoting/newlines unchanged (raw JSON contains `"`, `{`, `}`). The variable name
is fixed and shared with the consumer. The stored access `token`/`expiry` in
that JSON may be stale and is irrelevant — only `refresh_token` matters
(`google-auth` refreshes the access token non-interactively).

### Companion change — `yt_upload.py` consume behavior (`leaguesphere` repo, NOT in this branch)

**This change lives in the separate `leaguesphere` repo (its own branch/PR) and
is not yet implemented or merged.** It is described here for context only;
nothing in this repo's branch ships it.

When it lands, `leaguesphere/.claude/skills/record-tutorial/scripts/yt_upload.py`
will base64-decode `YOUTUBE_OAUTH_TOKEN_B64`, write it to
`~/.config/leaguesphere/youtube_token.json` on the persistent `opencode_root`
volume, and refresh non-interactively. A token already present with the same
`refresh_token` would be left untouched (so refreshed access tokens are not
clobbered); a genuinely rotated token (different `refresh_token`) would replace
it. `--client-secret` would become optional when a token is present.

**Until that companion change lands,** the container ignores
`YOUTUBE_OAUTH_TOKEN_B64` entirely, uploads still require `--client-secret`, and
the end-to-end in-container verification (`yt_upload.py channel`, below) cannot
yet succeed.

### Vaultwarden backup

`ansible/plays/roles/opencode/tasks/vaultwarden_push.yml` was refactored to take
a caller-supplied `opencode_vaultwarden_items` list (same shape as
`restic_vaultwarden_items`) and delegate to `vaultwarden/tasks/push_items.yml`.
The SSH-key push moved to pass its item from the handler. A new
always-run-on-codey task "Back up opencode YouTube OAuth token to Vaultwarden"
adds the backup item:

- `opencode - YouTube OAuth token (bumble:tube)`

The task is idempotent (`push_items.yml` creates only when missing, updates only
on change) and runs only when `opencode.youtube_oauth_token_json` is non-empty.
It is **not** handler-driven because the token has no change event (unlike the
SSH key).

### Container Python deps

`opencode/scripts/startup.sh` section 1c installs
`google-api-python-client google-auth-oauthlib google-auth-httplib2` at boot.
The install is guarded (no-op when already importable) and non-fatal (a PyPI
failure logs a warning instead of killing the boot). The deps live in the image
rootfs, so they re-install on container recreate.

## Files changed

- `ansible/plays/vars/secrets.yml` — `opencode.youtube_oauth_token_json`.
- `ansible/plays/roles/docker_service/templates/opencode/.env.j2` —
  `YOUTUBE_OAUTH_TOKEN_B64`.
- `ansible/plays/roles/docker_service/molecule/default/{converge,verify}.yml` —
  stub value + assertions for the new var.
- `ansible/plays/roles/opencode/tasks/vaultwarden_push.yml` — item-list wrapper.
- `ansible/plays/roles/opencode/handlers/main.yml` — SSH-key item moved in.
- `ansible/plays/roles/opencode/tasks/main.yml` — token-backup task.
- `opencode/scripts/startup.sh` — install YouTube upload deps at boot.
- `history/2026-10-15_opencode-youtube-upload-credentials.md` (this file).

Part B (`yt_upload.py`) lives in the separate `leaguesphere` repo and is **not**
part of this branch.

## Verification

Local validation on the controller (this branch):

- `git-crypt status` — `secrets.yml` still reported as encrypted.
- `ansible-playbook servyy.yml --syntax-check -i production` — no errors (only
  the pre-existing `Could not match supplied host pattern, ignoring: test`
  warning, identical on the base branch).
- `ansible-lint --force-color --show-relpath` — passes, `0 failure(s),
  0 warning(s)`.
- `yamllint -c ../.yamllint.yml .` — exits non-zero, but **only on pre-existing
  error-level findings** unrelated to this change (`ls_db_migrate` and
  `secrets.yml` `dev_repos` brace/space rules, `ls_demo` empty-lines — all present
  on the base branch). This change set adds no new error-level finding; it adds
  only line-length **warnings** for the new long token value (unavoidable) and
  the Vaultwarden `notes:` lines, matching the existing style (the same warning
  previously sat on `vaultwarden_push.yml` and moved with the refactor).
- `sh -n opencode/scripts/startup.sh` — syntax OK (Task A5).
- Molecule `docker_service/default` asserts `YOUTUBE_OAUTH_TOKEN_B64` is present
  in `opencode.env` and decodes to JSON carrying `refresh_token` (Task A3).

**Not yet done — left to the operator:** the production deploy
(`./servyy.sh --limit codey.lehel.xyz --tags user.opencode,user.docker.opencode`,
entering the Vaultwarden master password so the backup push runs) and the live
verification that the rendered `opencode.env` carries `YOUTUBE_OAUTH_TOKEN_B64`
and is at mode `0600`, and that the Vaultwarden item exists. **Env pickup
requires a recreate, not a restart:** the role's own handler
`restart opencode container` runs `docker compose restart`, which re-execs the
entrypoint without recreating the container and so will **not** pick up a
re-rendered `opencode.env`. On first provisioning and on any rotation, force a
recreate (`docker compose up -d --force-recreate opencode`, or remove/redeploy
the container), then verify the value **inside** the container
(`docker exec opencode.web printenv YOUTUBE_OAUTH_TOKEN_B64`), not just the file
on disk. The in-container `yt_upload.py channel`
check (printing `bumble:tube`) additionally requires the `leaguesphere`
companion change above and cannot succeed before it lands. See the plan's Task
A6 steps 3–5 for the exact commands.

## Impact / rollback

- Once the `leaguesphere` companion change lands, enables unattended uploads
  from `record-tutorial` on the server; the token is a live grant to
  `bumble:tube` and lives in the container at boot.
- **Rotation:** regenerate `~/.config/leaguesphere/youtube_token.json` via
  `record-tutorial`'s `yt_upload.py auth`, replace
  `opencode.youtube_oauth_token_json` in `secrets.yml`, and redeploy. A deploy
  re-renders `opencode.env` but the container must be recreated to pick up the
  new value (see the recreate caveat under Verification); a changed
  `refresh_token` replaces the on-disk token. Vaultwarden is updated by the
  backup task.
- **Operational risk — refresh-token lifetime:** if the Google Cloud OAuth
  client (project `bumble-live`) is not in "In production" publishing status,
  refresh tokens expire after ~7 days and unattended uploads start failing with
  `invalid_grant`. The operator should confirm the client's publishing status
  (or otherwise re-run the token flow periodically). This is the main
  operational risk of committing a static refresh token.
- **Rollback:** remove `opencode.youtube_oauth_token_json` from `secrets.yml`,
  the `YOUTUBE_OAUTH_TOKEN_B64` line from `templates/opencode/.env.j2`, and the
  "Back up opencode YouTube OAuth token to Vaultwarden" task; then redeploy
  `--tags user.opencode,user.docker.opencode`. Delete the materialized token on
  the persistent `opencode_root` volume (`~/.config/leaguesphere/youtube_token.json`)
  — it is a live upload grant — and optionally delete the Vaultwarden item
  `opencode - YouTube OAuth token (bumble:tube)`. The `leaguesphere` companion
  change, once it lands, is expected to be backward compatible (var absent → old
  `--client-secret` flow).

## Follow-up

- Wiring the upload step into LeagueSphere's `record-tutorial` skill (its
  SKILL.md currently states it "does not publish or host anything") — this
  change provisions credentials and the CLI only.
- Container recreate re-installs the Google Python deps (rootfs, not the
  persistent volume); bake them into the base image if that proves slow.
