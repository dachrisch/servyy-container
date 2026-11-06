# Public-repo secret leak: five live credentials found in committed markdown, all rotated

**Date:** 2026-11-06
**Status:** ✅ All five rotated and verified; docs redacted
**Trigger:** pre-publication review of the repo for Renovate (compose files were already plaintext)

## Context

The 2026-10-29 exposure review (`2026-10-29_exposure-guards.md`) scanned compose
files and env files before making them readable to hosted Renovate. It did not
scan documentation, and git-crypt's rules (`*.yaml`, `*.env`, `*.conf`, `*.pem`,
`secrets.*`, `secret_*`) never match `*.md`. Any secret pasted into a plan,
spec or history entry was therefore plaintext in a **public** repo.

A content scan of the committed tree (not the working tree — git-crypt is
unlocked locally, so the working tree shows decrypted vault files) found five
values that were both committed and still live:

| # | Secret | Location | Public since | Verified live before rotation |
|---|---|---|---|---|
| 1 | `opencode.server_password` | `docs/superpowers/plans/2026-08-08-opencode-api-key-forwardauth.md` | 2026-08-08 | `curl -u opencode:… https://code.lehel.xyz/api/info` → **200** |
| 2 | `finance.db_password` | `docs/superpowers/plans/2026-04-29-finance-production-ready.md` | 2026-05-06 | `psql -h shared.db -U firefly` → `firefly\|1` |
| 3 | `finance.app_key` | same file | 2026-05-06 | matched deployed `finance/.env` |
| 4 | `finance.auto_import_secret` | same file | 2026-05-06 | matched deployed `finance/.env` |
| 5 | `restic_password_home` | `ansible/DISASTER_RECOVERY_ANALYSIS.md` | 2025-12-29 | matched `/etc/restic/env.home` on 3 hosts |

#1 was the worst: `code.lehel.xyz` accepts that password as HTTP Basic, the
agent container runs as root with `/root/.ssh/id_servy` mounted, and
`ssh cda@servy.lehel.xyz sudo -n true` succeeds — i.e. a public credential
reached passwordless root on the production host. `/root/.ssh/id_github` would
also have allowed pushes to the repos.

## What was rotated

Order: opencode (fastest, highest severity) → restic → finance DB → importer
secret → APP_KEY (most disruptive).

### 1. `opencode.server_password` — commit `c63b4b9`

Renders three consumers, all redeployed together:

- `opencode.web` (`OPENCODE_SERVER_PASSWORD`) on codey and servyy-test
- `opencode-authgate.authgate` (`OPENCODE_BASIC_AUTH_B64`, b64 of `opencode:<pw>`)
- `devhub.web` (`OPENCODE_BASIC_PASSWORD`) on both hosts

Verified after deploy: unauthenticated `/api/info` 401, old password **401**,
new password 200, and the `X-Api-Key` ForwardAuth path (`GET /api/model`) still
200. The role also pushed the new value to the Vaultwarden item
`opencode - server password` (verified). API-key clients (job-search,
dontforget, queen, groceries) were never affected — they use `opencode.api_key`.

### 2. `restic_password_home` — no commit (gitignored seed)

The password is a `lookup('password', 'plays/vars/.restic_password_home')`, so
the seed file is the source of truth and is gitignored. Three independent
repos shared the leaked password:

| host | repo |
|---|---|
| servy | `sftp://storagebox/backup/servy.lehel.xyz/restic-home` |
| codey | `sftp://storagebox/backup/codey.lehel.xyz/restic-home` |
| servyy-test | `sftp://storagebox/backup/servyy-test.lxd/restic-home` |

Procedure per repo: `restic key add` (old key stays valid) → verify → update
the seed → re-render `/etc/restic/env.home` → `restic key remove <old>`.
Verified with a write: a tagged throwaway snapshot was created and removed on
all three, and each repo now lists exactly **one** key. Vaultwarden item
`restic - home (lehel.xyz)` updated and compared against the seed.

`restic_password_root` and `restic_password_ls_db` were not leaked and were not
touched.

**Note:** the role's `Verify restic password integrity` guard refuses to
overwrite the host env file while it differs from the Ansible value — by design.
The env file must be updated first, then the guard passes. Doing it the other
way round aborts the play before anything is written.

### 3. `finance.db_password` — commit `b7c1ec4`

`finance.db_password` is both the Firefly app user and the postgres superuser
(`POSTGRES_USER=firefly`), and `pg_hba` enforces `scram-sha-256` on the docker
network. `ALTER USER firefly`, then re-rendered `shared.env` + `finance.env`
(recreating firefly, importer, queen and shared.db). Verified: the new value
authenticates over TCP, the old one gets `password authentication failed`.

### 4. `finance.auto_import_secret` — commit `b389d20`

Compared with `hash_equals($secret, config('importer.auto_import_secret'))` in
`AutoUploadController`, so the old value cannot match once the config changes.
Verified present in both containers that load `finance.env`; `run-import.sh`
reads it from the environment at runtime.

### 5. `finance.app_key` — commit `94cbbb2`

Rotating APP_KEY was not free: Firefly stores its OAuth signing keypair
**encrypted with APP_KEY** (`Support/System/OAuthKeys.php`). On the first boot
with the new key the decrypt failed, the `oauth_private_key`/`oauth_public_key`
rows were deleted and a new pair was generated — every previously issued token
became invalid (confirmed: the stored token returned 401).

Compensation, in the same change:

- minted a new access token for user 1 and stored it as
  `finance.firefly_pam_token` (queen reads it as `FIREFLY_PAT`);
- pointed the data importer at that PAT and blanked `FIREFLY_III_CLIENT_ID`,
  because the importer rejects both auth modes simultaneously
  (`You can't set FIREFLY_III_ACCESS_TOKEN together with FIREFLY_III_CLIENT_ID`).

Verified: `/api/v1/about` 200 with the new token, queen→Firefly 200, and the
real ofelia job (`/import/run-import.sh`) completed with the new token and the
new upload secret. No 2FA enrolments, webhooks or APP_KEY-encrypted
configuration rows existed, so nothing else was lost.

## Documentation redaction

The five values (plus a stale Firefly JWT, an old auto-import secret, a
job-search JWT secret and a retired DuckDNS token) were replaced with
`<redacted: rotated 2026-11-06>` / `<redacted-jwt>` in 6 markdown files.
History rewriting was not attempted: the repo is public, so the values must be
treated as harvested regardless of what HEAD says. Redaction only stops new
copies.

## Consequences / residual risk

- **The values remain in public git history.** Rotation, not deletion, is what
  neutralises them; all five are now invalid.
- **`restic` backup of `/home/cda` has been failing since 06:04** with
  restic exit 3: `/home/cda/servyy-container/moodle/data` is `root:root 0750`
  (8 GB), unreadable by the `cda` user the timer runs as. This predates the
  rotation and is still open — it needs either an exclude plus a separate
  root-owned backup, or read access for the backup user.
- **Stale checkouts on the hosts** still contain the old values in
  `ansible/plays/vars/secrets.yml` and the docs; they refresh on the next
  `user.docker.repo` run and hold nothing live.
- **`bw sync` inside the role failed twice in a one-off playbook** while the
  opencode role's push succeeded; the restic Vaultwarden item was updated
  directly with `bw` and verified instead.
- `servyy-test`'s restic repo had a stale lock from 2026-03-13; `restic unlock`
  cleared it.

## Follow-ups

- Content-based secret scanning (gitleaks/trufflehog) must include `*.md`;
  path-based git-crypt rules cannot cover documentation.
- Decide the Moodle backup fix above.
- Rotate the remaining non-leaked-but-adjacent items on their own schedule:
  `opencode.api_key` (the ForwardAuth key shared by four clients) was not
  exposed by this leak.
