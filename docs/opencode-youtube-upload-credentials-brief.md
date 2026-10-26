# Brief: provision YouTube upload credentials to the opencode service

**Goal:** let the server-side opencode container (`opencode.web`) upload `record-tutorial`
videos to the **bumble:tube** channel unattended — no local machine in the loop.

**Key fact:** only the OAuth **token** needs provisioning. The token file is
self-contained (`client_id` + `client_secret` + `refresh_token` + `token_uri`), so
`google-auth` refreshes it non-interactively. The OAuth **client secret** is only
needed for the one-time browser flow, i.e. not on the server.

---

## Which token to use

**We already have it — reuse it.** The token we generated for the `bumble:tube` channel
already exists at **`~/.config/leaguesphere/youtube_token.json`** (scopes
`youtube.upload` + `youtube.readonly`). Provision *that file's contents* as the secret;
no new consent is needed. It's self-contained, so nothing else has to be provisioned.

The (re)generation flow below is only needed if that token is lost or the OAuth client
is rotated.

<details>
<summary>Only to (re)generate / rotate the token</summary>

### Where to get the token (one-time OAuth flow, machine with a browser)

The account must own `bumble:tube` (it's a **Brand Account**, so pick it at the account
chooser).

1. **Client secret file** — the Desktop OAuth client for GCP project `bumble-live`:
   - a local copy exists at `docs/guides/client_secret_*.json` in the `leaguesphere`
     checkout, and
   - it can be re-downloaded from GCP → APIs & Services → Credentials → the
     "Desktop client" → Download JSON.
2. **Authorize** (prints a Google URL):
   ```bash
   cd ~/dev/leaguesphere
   .venv/bin/python .claude/skills/record-tutorial/scripts/yt_upload.py \
     --client-secret docs/guides/client_secret_*.json auth
   ```
   Open the URL, sign in, choose **bumble:tube** (not the personal account),
   click through *Advanced → Go to bumble:live (unsafe) → Continue*, then copy the
   resulting `http://localhost/?code=...` URL.
3. **Exchange the code** (writes the token, mode `0600`):
   ```bash
   .venv/bin/python .claude/skills/record-tutorial/scripts/yt_upload.py \
     --client-secret docs/guides/client_secret_*.json \
     channel --code "http://localhost/?code=..."
   ```
   Expected output: `UCbp6-pIVMxhvI7m3tarMK6w   bumble:tube`, and a token saved to
   **`~/.config/leaguesphere/youtube_token.json`**.

</details>

---

## Provisioning (this repo)

Follow the existing pattern (Vaultwarden → Ansible → host env-file → container `env_file`).

1. **Vaultwarden** — store the token as an item, e.g.
   `opencode - YouTube OAuth token (bumble:tube)`, mirroring
   `ansible/plays/roles/opencode/tasks/vaultwarden_push.yml`.
2. **Ansible** — in `ansible/plays/roles/opencode/tasks/main.yml`, render it into the
   opencode env file (mode `0600`), base64 to avoid quoting/newline issues:
   ```
   YOUTUBE_OAUTH_TOKEN_B64={{ <token json> | b64encode }}
   ```
   Target file: `/home/<create_user>/servyy-container/opencode/opencode.env`
   (already injected by `opencode/docker-compose.yml` via `env_file`). No new mount.
3. **leaguesphere `yt_upload.py`** — read the token from `YOUTUBE_OAUTH_TOKEN_B64`
   (base64-decode, write to `~/.config/leaguesphere/youtube_token.json` inside the
   persistent `opencode_root` volume), and make `--client-secret` optional when a
   token is present.

---

## Caveats

- The token grants **upload** to `bumble:tube` — treat as a secret (Vaultwarden,
  `0600`, never commit).
- `yt_upload.py` **re-saves the token after refresh**, so the token must live on a
  **writable** path — hence env-var injection + write into the container's `/root`
  volume, not a read-only bind mount.
- Rotating/replacing the OAuth client invalidates this token; re-run the flow above.
- Client id/project: `bumble-live`; channel: `UCbp6-pIVMxhvI7m3tarMK6w` (`@bumbletube`).
