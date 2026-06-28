# OpenCode — Antigravity Auth (free Gemini 3 + Claude)

**Date:** 2026-06-29
**Status:** ✅ Deployed to production (lehel.xyz), verified responding
**Commits:** `ca84a2e` (feature), `abdc3ee` (CI lint fix)
**Reference:** https://dev.to/0xkoji/how-to-use-claude-opus-45-gemini-3-for-free-with-opencode-33o2

## Problem

OpenCode's model access used the `opencode-gemini-auth` plugin. Authentication via
Google OAuth succeeded, but every request failed with:

```
Google Gemini requires a Google Cloud project. Enable the Gemini for Google Cloud
API on a project you control, then set provider.google.options.projectId ...
```

The gemini-auth plugin routes through the **Gemini-for-Google-Cloud API**, which bills
and scopes to a GCP project. No project was configured (no `OPENCODE_GEMINI_PROJECT_ID`,
no `GOOGLE_CLOUD_PROJECT`, no `projectId` in config), so models never responded — the
user's "sub is not working" symptom.

## Solution

Switch to the **`opencode-antigravity-auth`** plugin, which authenticates through
Google's "Antigravity" OAuth flow and **does not require a GCP project**. It exposes
free **Gemini 3 Flash** and **Claude Opus/Sonnet 4.5** models.

The container is stateless on first boot, so the OAuth credential is **baked into
secrets** and seeded into `auth.json` on every boot (mirrors the existing
`SERVY_SSH_KEY_B64` / `GIT_CRYPT_KEY_B64` pattern). No browser or GCP project needed
on the server.

### Models enabled (validated working)

| model | notes |
|---|---|
| `google/antigravity-gemini-3-flash` | ✅ responds |
| `google/antigravity-claude-opus-4-5-thinking` | ✅ |
| `google/antigravity-claude-sonnet-4-5` / `-thinking` | ✅ |
| ~~`antigravity-gemini-3-pro`~~ | ❌ deprecated server-side ("switch to Gemini 3.1 Pro") — omitted |

### Auth mechanism

- One-time interactive `opencode auth login` → Google → **OAuth with Google (Antigravity)**
  (run locally; writes the credential to `~/.local/share/opencode/auth.json`).
- The `{"google": {...}}` entry is base64-encoded into `secrets.yml`
  (`opencode.auth_google_b64`), rendered into `opencode.env` as
  `OPENCODE_AUTH_GOOGLE_B64`, and seeded into the container's `auth.json` by
  `seed_auth.py` (called from `provision-dev.sh`).
- The seed is **idempotent and non-clobbering**: if `auth.json` already has a `google`
  entry (e.g. one OpenCode refreshed itself on a persisted volume), it is left untouched.
  Access tokens refresh automatically via the stored refresh token.

## Files changed

| File | Change |
|---|---|
| `opencode/scripts/opencode.json.template` | plugin → `opencode-antigravity-auth`, added working model definitions |
| `opencode/scripts/seed_auth.py` | **new** — decode + merge the Google/Antigravity credential into `auth.json` |
| `opencode/scripts/provision-dev.sh` | call `seed_auth.py` (step 2b) |
| `ansible/.../templates/opencode/.env.j2` | expose `OPENCODE_AUTH_GOOGLE_B64` |
| `ansible/plays/vars/secrets.yml` | add `opencode.auth_google_b64` |
| `ansible/.../docker_service/molecule/default/converge.yml` | CI lint fix (spaces inside braces, pre-existing failure) |

## Deployment

Targeted `--tags user.docker.opencode` alone was **insufficient** — it skipped the
server git-sync, leaving stale mounted scripts. Correct sequence:

```bash
cd ansible
./servyy.sh --tags "user.docker.repo,user.docker.opencode" --limit lehel.xyz
ssh lehel.xyz "docker restart opencode.web"   # bind-mounted script changes only apply on restart
```

(See memory `opencode_deploy_repo_sync_restart` for the two-part gotcha.)

## Verification

```bash
ssh lehel.xyz "docker logs opencode.web 2>&1 | grep 'google auth'"
# [provision-dev] opencode google auth seeded

ssh lehel.xyz "docker exec opencode.web grep plugin /root/.config/opencode/opencode.json"
# "plugin": ["opencode-antigravity-auth@latest"]

ssh lehel.xyz "docker exec opencode.web sh -c 'cd /tmp && opencode run -m google/antigravity-gemini-3-flash \"Reply with exactly: PONG from prod\"'"
# PONG from prod
```

CI on `abdc3ee`: ✅ all jobs green.

## Known issues / future

- **Token longevity:** rides on the Google refresh token; the article warns Google may
  ban accounts using this method. If revoked, re-run `opencode auth login` locally,
  re-bake `opencode.auth_google_b64` into `secrets.yml`, push, redeploy (repo tag) +
  restart.
- **Account:** the baked-in token belongs to `dachrischx@gmail.com`.
- `gemini-3-pro` is deprecated upstream; revisit when a `3.1-pro` Antigravity model id is confirmed.
