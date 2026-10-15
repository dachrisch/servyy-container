# OpenCode YouTube Upload Credentials Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let the server-side opencode container (`opencode.web`) upload `record-tutorial` videos to the **bumble:tube** channel unattended, by provisioning the existing OAuth token (from `~/.config/leaguesphere/youtube_token.json`) into the container as `YOUTUBE_OAUTH_TOKEN_B64` and teaching `yt_upload.py` to consume it.

**Architecture:** The token JSON is a normal opencode secret: stored in the git-crypt-encrypted `ansible/plays/vars/secrets.yml`, rendered into `opencode.env` (mode `0600`, base64) by the existing `docker_service` env-template mechanism, injected into the container via compose `env_file`, and backed up to Vaultwarden via the existing `vaultwarden_push.yml` pattern. Inside the container, `yt_upload.py` (leaguesphere repo) base64-decodes the env var into `~/.config/leaguesphere/youtube_token.json` on the persistent `opencode_root` volume, and `--client-secret` becomes optional when a token is present.

**Tech Stack:** Ansible (roles `opencode`, `docker_service`, `vaultwarden`), Molecule (docker driver), git-crypt, Bitwarden/`bw` CLI, Python 3 (`google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2`), pytest, Alpine container.

**Scope:** Two repos:
- **Part A** — `servyy-container` (`/home/cda/dev/infrastructure/container`)
- **Part B** — `leaguesphere` (`/home/cda/dev/leaguesphere`)

**Key facts / decisions (already settled):**
- Only the **token** must be provisioned — it is self-contained (`client_id` + `client_secret` + `refresh_token` + `token_uri`), so `google-auth` refreshes it non-interactively. The Desktop client secret is NOT needed on the server.
- Source of truth = git-crypt `secrets.yml` (like every other `opencode.*` secret), with a Vaultwarden **backup** copy (not a pull).
- The brief's "render in `opencode/tasks/main.yml`" is wrong: `opencode.env` is rendered by the `docker_service` role from `ansible/plays/roles/docker_service/templates/opencode/.env.j2`. That is where the var goes.
- Container Python deps for `yt_upload.py` are installed by `opencode/scripts/startup.sh`.
- Token is a **secret** (upload grant to `bumble:tube`): Vaultwarden, `0600`, never committed in the clear.

---

## Part A — servyy-container

### Task A1: Add the token JSON to git-crypt `secrets.yml`

**Files:**
- Modify: `ansible/plays/vars/secrets.yml` (the `opencode:` mapping, ~lines 126-146)

**Step 1: Generate the exact YAML line from the existing token**

Run (on the controller, where the token already exists):

```bash
python3 - <<'PY'
import json, pathlib
tok = pathlib.Path.home() / ".config/leaguesphere/youtube_token.json"
data = json.loads(tok.read_text())
assert data.get("refresh_token"), "token has no refresh_token"
print("  youtube_oauth_token_json: '" + json.dumps(data, separators=(",", ":")) + "'")
PY
```

Expected: one line starting `  youtube_oauth_token_json: '{"token": "ya29...`.

**Step 2: Insert it into `secrets.yml`**

Add the printed line under the `opencode:` key, next to `opencode_go_api_key`. Keep it a **single-quoted** YAML scalar (the JSON contains no `'`). Example shape (do not hand-type the token — paste the generated line):

```yaml
  opencode_go_api_key: "sk-..."
  # YouTube OAuth token (channel bumble:tube, UCbp6-pIVMxhvI7m3tarMK6w).
  # Self-contained: google-auth refreshes it non-interactively from refresh_token.
  # Regenerate via leaguesphere record-tutorial yt_upload.py auth/channel if rotated.
  youtube_oauth_token_json: '{"token":"ya29...","refresh_token":"1//...","token_uri":"https://oauth2.googleapis.com/token","client_id":"...apps.googleusercontent.com","client_secret":"GOCSPX-...","scopes":["https://www.googleapis.com/auth/youtube.upload","https://www.googleapis.com/auth/youtube.readonly"]}'
```

**Step 3: Confirm the file is still git-crypt encrypted (never commit plaintext)**

Run: `git check-attr filter -- ansible/plays/vars/secrets.yml`
Expected: `ansible/plays/vars/secrets.yml: filter: git-crypt`

**Step 4: Commit**

```bash
git add ansible/plays/vars/secrets.yml
git commit -m "feat(opencode): add YouTube OAuth token to secrets"
```

---

### Task A2: Render `YOUTUBE_OAUTH_TOKEN_B64` into `opencode.env`

**Files:**
- Modify: `ansible/plays/roles/docker_service/templates/opencode/.env.j2:12`

**Step 1: Add the env var (default-guarded so unrelated hosts never break rendering)**

Append after the `GIT_SSH_COMMAND=` line:

```jinja
# YouTube upload token (bumble:tube), JSON base64-encoded to survive env_file
# quoting/newlines. Consumed by leaguesphere record-tutorial yt_upload.py.
YOUTUBE_OAUTH_TOKEN_B64={{ (opencode.youtube_oauth_token_json | default('')) | b64encode }}
```

**Step 2: Syntax-check the playbooks**

Run:
```bash
cd ansible && ansible-playbook servyy.yml --syntax-check -i production
```
Expected: no errors.

**Step 3: Commit**

```bash
git add ansible/plays/roles/docker_service/templates/opencode/.env.j2
git commit -m "feat(opencode): render YOUTUBE_OAUTH_TOKEN_B64 into opencode.env"
```

---

### Task A3: Molecule coverage for the new env var

**Files:**
- Modify: `ansible/plays/roles/docker_service/molecule/default/converge.yml:18-29` (the `opencode:` stub)
- Modify: `ansible/plays/roles/docker_service/molecule/default/verify.yml` (near the other `opencode.env` assertions, ~line 169)

**Step 1: Add the stub value to the `opencode:` var in converge.yml**

Inside the existing `opencode:` mapping add:

```yaml
      youtube_oauth_token_json: '{"refresh_token":"test-refresh-token","token_uri":"https://oauth2.googleapis.com/token"}'
```

**Step 2: Add the verification assertion**

In verify.yml, after the DEV_REPOS_B64 assertion, add:

```yaml
    - name: Verify opencode.env carries YOUTUBE_OAUTH_TOKEN_B64
      ansible.builtin.command:
        cmd: grep -q '^YOUTUBE_OAUTH_TOKEN_B64=.\+$' /home/molecule/opencode/opencode.env
      changed_when: false

    - name: Verify YOUTUBE_OAUTH_TOKEN_B64 decodes to JSON carrying refresh_token
      ansible.builtin.command:
        cmd: >-
          python3 -c "import base64,json,sys;
          raw=[l for l in open('/home/molecule/opencode/opencode.env') if l.startswith('YOUTUBE_OAUTH_TOKEN_B64=')][0].split('=',1)[1].strip();
          assert json.loads(base64.b64decode(raw))['refresh_token']=='test-refresh-token'"
      changed_when: false
```

**Step 3: Run the scenario**

Run: `cd ansible/plays/roles/docker_service && molecule test --scenario-name default`
Expected: PASS (converge + verify green).

**Step 4: Commit**

```bash
git add ansible/plays/roles/docker_service/molecule/default/
git commit -m "test(opencode): assert YOUTUBE_OAUTH_TOKEN_B64 in opencode.env"
```

---

### Task A4: Back up the token to Vaultwarden

Mirror `vaultwarden_push.yml`; refactor the opencode wrapper to take caller-supplied items (same shape as `restic_vaultwarden_items`).

**Files:**
- Modify: `ansible/plays/roles/opencode/tasks/vaultwarden_push.yml`
- Modify: `ansible/plays/roles/opencode/handlers/main.yml:20-23`
- Modify: `ansible/plays/roles/opencode/tasks/main.yml:79` (area after the SSH-key copy task)

**Step 1: Make the wrapper accept a caller item list**

Replace `ansible/plays/roles/opencode/tasks/vaultwarden_push.yml` with:

```yaml
---
# Push OpenCode secrets to Vaultwarden as backup copies.
# Caller sets opencode_vaultwarden_items: list of {name, secret, notes}.
- name: Push OpenCode secrets to Vaultwarden
  ansible.builtin.include_tasks: ../../vaultwarden/tasks/push_items.yml
  vars:
    vaultwarden_items: "{{ opencode_vaultwarden_items }}"
    vaultwarden_item_username: "opencode"
  when: vw_master_password | default('') | length > 0
```

**Step 2: Update the SSH-key handler to pass its item**

Replace the `push opencode ssh key to vaultwarden` handler in `handlers/main.yml` with:

```yaml
- name: push opencode ssh key to vaultwarden
  ansible.builtin.include_tasks: vaultwarden_push.yml
  listen: push opencode ssh key to vaultwarden
  vars:
    opencode_vaultwarden_items:
      - name: "opencode - GitHub SSH key (lehel.xyz)"
        secret: "{{ opencode_github_ssh_key }}"
        notes: "SSH private key for git@github.com authentication in OpenCode (copy of Ansible seed vars/.opencode_github_ssh_key). Public key: {{ opencode_github_ssh_pubkey }}"
  when: inventory_hostname == 'codey.lehel.xyz'
```

**Step 3: Add an idempotent token-backup task in main.yml**

After the "Write GitHub SSH private key to container mount point" task (line ~79), add:

```yaml
- name: Back up opencode YouTube OAuth token to Vaultwarden
  # Idempotent: push_items.yml only creates the item when missing and updates
  # it when the secret changed, so running on every deploy is safe. Not
  # handler-driven because the token has no change event (unlike the SSH key).
  ansible.builtin.include_tasks: vaultwarden_push.yml
  vars:
    opencode_vaultwarden_items:
      - name: "opencode - YouTube OAuth token (bumble:tube)"
        secret: "{{ opencode.youtube_oauth_token_json }}"
        notes: "OAuth token JSON (client_id/client_secret/refresh_token) for unattended uploads to bumble:tube (UCbp6-pIVMxhvI7m3tarMK6w). Source: secrets.yml opencode.youtube_oauth_token_json."
  when:
    - inventory_hostname == 'codey.lehel.xyz'
    - opencode.youtube_oauth_token_json | default('') | length > 0
```

**Step 4: Lint + syntax-check**

Run:
```bash
cd ansible && ansible-lint --force-color --show-relpath
cd ansible && ansible-playbook plays/user.yml --syntax-check -i production
```
Expected: no errors.

**Step 5: Commit**

```bash
git add ansible/plays/roles/opencode/tasks/ ansible/plays/roles/opencode/handlers/main.yml
git commit -m "feat(opencode): back up YouTube OAuth token to Vaultwarden"
```

---

### Task A5: Install Python deps for `yt_upload.py` at container boot

**Files:**
- Modify: `opencode/scripts/startup.sh` (after section 1b, the chromium block)

**Step 1: Add a guarded, non-fatal pip install**

Insert after the chromium block:

```sh
# 1c. Python deps for LeagueSphere's record-tutorial yt_upload.py (server-side
# YouTube upload). google-* live in the image rootfs (not the persistent
# volume), so this re-installs on recreate; the import guard makes it a no-op
# within a boot and keeps the whole boot alive if PyPI is unreachable.
if ! python3 -c 'import googleapiclient, google_auth_oauthlib' 2>/dev/null; then
    echo "🐍 [Startup] Installing YouTube upload Python deps..."
    pip install --no-cache-dir --break-system-packages \
        google-api-python-client google-auth-oauthlib google-auth-httplib2 \
        && echo "📍 [Startup] YouTube upload deps installed" \
        || echo "⚠️ [Startup] YouTube upload deps install failed (yt_upload.py unavailable)"
else
    echo "📍 [Startup] YouTube upload deps already present"
fi
```

**Step 2: Shellcheck / syntax sanity**

Run: `sh -n opencode/scripts/startup.sh`
Expected: no output (syntax OK).

**Step 3: Commit**

```bash
git add opencode/scripts/startup.sh
git commit -m "feat(opencode): install YouTube upload Python deps at boot"
```

---

### Task A6: History log + full validation + deploy verification

**Files:**
- Create: `history/2026-10-15_opencode-youtube-upload-credentials.md`

**Step 1: Write the history entry**

Document: goal, the secrets.yml→`opencode.env`→container flow, the `YOUTUBE_OAUTH_TOKEN_B64` convention, `yt_upload.py` consume behavior, Vaultwarden backup item name, rotation procedure, and rollback (remove the var + items, redeploy `--tags user.docker.opencode`).

**Step 2: Run the repo validators**

```bash
git-crypt status
cd ansible && ansible-playbook servyy.yml --syntax-check -i production
cd ansible && yamllint -c ../.yamllint.yml .
cd ansible && ansible-lint --force-color --show-relpath
```
Expected: all clean.

**Step 3: Deploy to codey**

```bash
cd ansible && ./servyy.sh --limit codey.lehel.xyz --tags user.opencode,user.docker.opencode
```
(Enter the Vaultwarden master password at the prompt so the backup push runs; blank skips it.)

**Step 4: Verify the rendered env + vault item**

```bash
ssh codey.lehel.xyz "grep -c '^YOUTUBE_OAUTH_TOKEN_B64=' /home/cda/servyy-container/opencode/opencode.env"
ssh codey.lehel.xyz "sudo stat -c '%a' /home/cda/servyy-container/opencode/opencode.env"
```
Expected: `1` and `600`.

**Step 5: Verify deps + token materialization inside the container**

```bash
ssh codey.lehel.xyz "docker exec opencode.web sh -c 'python3 -c \"import googleapiclient\" && echo deps-ok'"
docker exec opencode.web sh -c 'python3 /root/dev/dachrisch/leaguesphere/.claude/skills/record-tutorial/scripts/yt_upload.py --help' 2>&1 | head
```
Expected: `deps-ok`; `--client-secret` shown as optional (Part B).

**Step 6: Commit**

```bash
git add history/2026-10-15_opencode-youtube-upload-credentials.md
git commit -m "docs: history for opencode YouTube upload credentials"
```

---

## Part B — leaguesphere

Repo: `/home/cda/dev/leaguesphere`. Test runner is pytest:
`cd .claude/skills/record-tutorial && python -m pytest scripts/tests/test_yt_upload.py -v`.

### Task B1: Make `--client-secret` optional

**Files:**
- Modify: `.claude/skills/record-tutorial/scripts/yt_upload.py` (`build_parser` ~line 170, `_flow` ~line 41)
- Test: `.claude/skills/record-tutorial/scripts/tests/test_yt_upload.py`

**Step 1: Write the failing tests**

Append to `tests/test_yt_upload.py`:

```python
from yt_upload import _flow, build_parser


def test_client_secret_is_optional_for_upload():
    args = build_parser().parse_args(["upload", "--file", "x.mp4"])
    assert args.client_secret is None


def test_flow_requires_client_secret():
    with pytest.raises(SystemExit):
        _flow("")
```

**Step 2: Run to verify failure**

Run: `cd .claude/skills/record-tutorial && python -m pytest scripts/tests/test_yt_upload.py -v`
Expected: FAIL (`--client-secret` still required / `_flow` has no guard).

**Step 3: Implement**

In `build_parser()` change:
```python
    parser.add_argument("--client-secret")
```
In `_flow()` add as the first statement (before the lazy import):
```python
    if not client_secret:
        raise SystemExit("--client-secret is required for the interactive auth flow.")
```
Update the module docstring to note the token lives at `~/.config/leaguesphere/youtube_token.json` (seeded from `YOUTUBE_OAUTH_TOKEN_B64`).

**Step 4: Run to verify pass**

Run: `cd .claude/skills/record-tutorial && python -m pytest scripts/tests/test_yt_upload.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add .claude/skills/record-tutorial/scripts/yt_upload.py .claude/skills/record-tutorial/scripts/tests/test_yt_upload.py
git commit -m "feat(record-tutorial): make --client-secret optional when a token exists"
```

---

### Task B2: Seed the token from `YOUTUBE_OAUTH_TOKEN_B64`

**Files:**
- Modify: `.claude/skills/record-tutorial/scripts/yt_upload.py`
- Test: `.claude/skills/record-tutorial/scripts/tests/test_yt_upload.py`

**Step 1: Write the failing tests**

Append to `tests/test_yt_upload.py`:

```python
import base64
import json

from yt_upload import TOKEN_ENV_VAR, _seed_token_from_env


def _env_token(refresh="rt-1"):
    payload = {
        "refresh_token": refresh,
        "client_id": "cid",
        "client_secret": "sec",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


def test_seed_ignores_absent_env(tmp_path, monkeypatch):
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    token = tmp_path / "youtube_token.json"
    _seed_token_from_env(token)
    assert not token.exists()


def test_seed_writes_absent_token(tmp_path, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV_VAR, _env_token())
    token = tmp_path / "youtube_token.json"
    _seed_token_from_env(token)
    assert json.loads(token.read_text())["refresh_token"] == "rt-1"
    assert (token.stat().st_mode & 0o777) == 0o600


def test_seed_preserves_refreshed_token(tmp_path, monkeypatch):
    token = tmp_path / "youtube_token.json"
    token.write_text(json.dumps({"refresh_token": "rt-1", "token": "fresh-access"}))
    monkeypatch.setenv(TOKEN_ENV_VAR, _env_token(refresh="rt-1"))
    _seed_token_from_env(token)
    assert json.loads(token.read_text())["token"] == "fresh-access"


def test_seed_overwrites_rotated_token(tmp_path, monkeypatch):
    token = tmp_path / "youtube_token.json"
    token.write_text(json.dumps({"refresh_token": "old"}))
    monkeypatch.setenv(TOKEN_ENV_VAR, _env_token(refresh="new"))
    _seed_token_from_env(token)
    assert json.loads(token.read_text())["refresh_token"] == "new"


def test_seed_rejects_bad_base64(tmp_path, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV_VAR, "!!!not-base64!!!")
    with pytest.raises(SystemExit):
        _seed_token_from_env(tmp_path / "youtube_token.json")
```

**Step 2: Run to verify failure**

Run: `cd .claude/skills/record-tutorial && python -m pytest scripts/tests/test_yt_upload.py -v`
Expected: FAIL (ImportError: `TOKEN_ENV_VAR` / `_seed_token_from_env`).

**Step 3: Implement**

Add near the top (after `DEFAULT_TOKEN`):

```python
import base64

TOKEN_ENV_VAR = "YOUTUBE_OAUTH_TOKEN_B64"
```

Refactor `_save_token` to use a shared low-level writer:

```python
def _write_private(path: Path, text: str) -> None:
    """Write text to path with owner-only permissions (0600)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


def _save_token(token_path: Path, creds) -> None:
    _write_private(token_path, creds.to_json())


def _seed_token_from_env(token_path: Path) -> None:
    """Materialize the token file from YOUTUBE_OAUTH_TOKEN_B64 (server-side).

    The env var is the base64 of the self-contained OAuth token JSON. It is
    written into the (writable) token path — the persistent /root volume in the
    opencode container — so google-auth can refresh it non-interactively. A
    refreshed token (same refresh_token) is left untouched; a genuinely rotated
    token (different refresh_token) replaces it.
    """
    raw = os.environ.get(TOKEN_ENV_VAR, "").strip()
    if not raw:
        return
    try:
        incoming = json.loads(base64.b64decode(raw, validate=True))
    except (ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{TOKEN_ENV_VAR} is not valid base64-encoded JSON: {exc}") from exc
    if token_path.exists():
        try:
            existing = json.loads(token_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        if existing.get("refresh_token") and existing.get("refresh_token") == incoming.get("refresh_token"):
            return
    _write_private(token_path, json.dumps(incoming))
```

Call it first thing in `_credentials`:

```python
def _credentials(args):
    token_path = Path(args.token)
    _seed_token_from_env(token_path)
    ...
```
(remove the now-duplicated `token_path = Path(args.token)` line if it was the first line).

**Step 4: Run to verify pass**

Run: `cd .claude/skills/record-tutorial && python -m pytest scripts/tests/ -v`
Expected: PASS (all tests).

**Step 5: Commit**

```bash
git add .claude/skills/record-tutorial/scripts/yt_upload.py .claude/skills/record-tutorial/scripts/tests/test_yt_upload.py
git commit -m "feat(record-tutorial): seed yt_upload token from YOUTUBE_OAUTH_TOKEN_B64"
```

---

## End-to-end verification (after both parts)

Run inside the container after Part A is deployed and Part B is merged + pulled into the checkout:

```bash
ssh codey.lehel.xyz "docker exec opencode.web sh -c '
  cd /root/dev/dachrisch/leaguesphere &&
  YOUTUBE_OAUTH_TOKEN_B64=\$YOUTUBE_OAUTH_TOKEN_B64 \
  python3 .claude/skills/record-tutorial/scripts/yt_upload.py channel
'"
```
Expected: prints `UCbp6-pIVMxhvI7m3tarMK6w	bumble:tube` (channel lookup needs only `youtube.readonly`, and proves the token was materialized + refreshed non-interactively).

Then a real upload smoke test with a tiny mp4, `--privacy unlisted`, and delete the result.

## Rollback

- Remove `opencode.youtube_oauth_token_json` from `secrets.yml`, the `YOUTUBE_OAUTH_TOKEN_B64` line from `templates/opencode/.env.j2`, and the `Back up opencode YouTube OAuth token` task; redeploy `--tags user.opencode,user.docker.opencode`.
- `yt_upload.py` changes are backward compatible (env var absent → old behavior with `--client-secret`).
- Delete the Vaultwarden item `opencode - YouTube OAuth token (bumble:tube)` if desired.

## Open follow-ups (out of scope)

- Wiring the upload step into LeagueSphere's `record-tutorial` skill (SKILL.md currently states it "does not publish or host anything") — this plan only provisions credentials and the CLI.
- Consider a dedicated recording service if the shared headless browser becomes contended.
