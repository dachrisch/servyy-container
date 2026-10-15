# 2026-10-15 — opencode service: YouTube upload credentials for unattended record-tutorial uploads

## Goal

Let the server-side opencode container (`codey.lehel.xyz`, container
`opencode.web`) upload `record-tutorial` videos to the **bumble:tube** YouTube
channel unattended, by provisioning the existing OAuth token (currently
`~/.config/leaguesphere/youtube_token.json` on the developer's box) into the
container and teaching `yt_upload.py` to consume it. Plan:
`docs/plans/2026-10-15-opencode-youtube-upload-credentials.md` (Part A here,
Part B in the `leaguesphere` repo).

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
is fixed and shared with the consumer.

### `yt_upload.py` consume behavior (leaguesphere, Part B)

`leaguesphere/.claude/skills/record-tutorial/scripts/yt_upload.py` base64-decodes
`YOUTUBE_OAUTH_TOKEN_B64` and writes it to
`~/.config/leaguesphere/youtube_token.json` on the persistent `opencode_root`
volume, then refreshes non-interactively. A token already present with the same
`refresh_token` is left untouched (so refreshed access tokens are not clobbered);
a genuinely rotated token (different `refresh_token`) replaces it.
`--client-secret` becomes optional when a token is present.

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
once at mode `0600`, that the Vaultwarden item exists, and that the token
materializes + refreshes inside the container (`yt_upload.py channel` printing
`bumble:tube`). See the plan's Task A6 steps 3–5 for the exact commands.

## Impact / rollback

- Enables unattended uploads from `record-tutorial` on the server; the token is
  a live grant to `bumble:tube` and lives in the container at boot.
- **Rotation:** regenerate `~/.config/leaguesphere/youtube_token.json` via
  `record-tutorial`'s `yt_upload.py auth`, replace
  `opencode.youtube_oauth_token_json` in `secrets.yml`, and redeploy. The
  container picks up the new value on recreate; a changed `refresh_token`
  replaces the on-disk token. Vaultwarden is updated by the backup task.
- **Rollback:** remove `opencode.youtube_oauth_token_json` from `secrets.yml`,
  the `YOUTUBE_OAUTH_TOKEN_B64` line from `templates/opencode/.env.j2`, and the
  "Back up opencode YouTube OAuth token to Vaultwarden" task; redeploy
  `--tags user.docker.opencode`. Optionally delete the Vaultwarden item
  `opencode - YouTube OAuth token (bumble:tube)`. The `yt_upload.py` changes are
  backward compatible (var absent → old `--client-secret` flow).

## Follow-up

- Wiring the upload step into LeagueSphere's `record-tutorial` skill (its
  SKILL.md currently states it "does not publish or host anything") — this
  change provisions credentials and the CLI only.
- Container recreate re-installs the Google Python deps (rootfs, not the
  persistent volume); bake them into the base image if that proves slow.
