# Restic Passwords → Vaultwarden (copy)

**Date:** 2026-06-29
**Branch:** claude/restic-vaultwarden-copy → master (fast-forward)

## Problem

The three restic repository passwords (`home`, `root`, `ls_db`) only existed as
Ansible seed files (`ansible/plays/vars/.restic_password_*`). Wanted a
human-readable backup copy in Vaultwarden (`pass.lehel.xyz`) without making
Vaultwarden a hard dependency of every deployment.

## Decision

**Push a copy**, not pull-as-source-of-truth. The seed files remain the source
of truth; Vaultwarden holds a convenience/backup copy. This avoids the
bootstrap chicken-and-egg problem (restic backs up Vaultwarden, so Vaultwarden
must not be required to read the restic password during a bare-metal restore).

## Solution

Initially built as a standalone localhost playbook
(`ansible/plays/restic_to_vaultwarden.yml`), then **integrated into the restic
role and the standalone removed** so the copy is part of normal restic setup.

Final design:

- Shared task file `roles/restic/tasks/vaultwarden_push.yml` (runs on the
  controller via the `bw` CLI, `delegate_to: localhost` + `run_once`):
  - Verifies `bw` targets the expected server (asserts when already logged in,
    `bw config server` only while logged out) to avoid pushing to the wrong vault.
  - Auth: `bw login --apikey` using a personal API key in `secrets.yml`
    (`vaultwarden_api.client_id/secret`) → no 2FA prompt.
  - Idempotent: lists items, creates only missing ones (Login type,
    `username: restic`), reports created-vs-skipped, then `bw lock`.
  - `no_log: true` on every secret-touching task; pipe runs under bash + pipefail.
- **Trigger:** handler `Push restic passwords to Vaultwarden`
  (`roles/restic/handlers/main.yml`), notified by the "Deploy restic environment
  files" task in `init.yml`. Fires **only when an `/etc/restic/env.*` file
  actually changes** and **only on `lehel.xyz`**.
- **Master password:** `vars_prompt` on `plays/restic.yml` (hidden, `default: ""`
  → press enter to skip). Never stored on disk or in git. Handler skips when the
  prompt is empty.
- Item list lives in `roles/restic/defaults/main.yml` (`restic_vaultwarden_items`).

## Files changed

- `ansible/plays/roles/restic/tasks/vaultwarden_push.yml` (new — shared push logic)
- `ansible/plays/roles/restic/handlers/main.yml` (new — handler)
- `ansible/plays/roles/restic/defaults/main.yml` (new — item list + `vw_server`)
- `ansible/plays/roles/restic/tasks/init.yml` — `notify` on the env-file task
- `ansible/plays/restic.yml` — `vars_prompt` for the master password
- `ansible/plays/vars/secrets.yml` — added `vaultwarden_api` block (git-crypt encrypted)
- `ansible/plays/restic_to_vaultwarden.yml` — **removed** (superseded by the handler)

## Verification

- `ansible-playbook --syntax-check` ✅ (`restic.yml`)
- `ansible-lint` production profile ✅ (pipefail added for risky-shell-pipe)
- `bw encode` JSON round-trip ✅
- Live run 2026-06-29 (original standalone): 3 items CREATED,
  `PLAY RECAP ok=9 changed=2 failed=0`, vault re-locked; values verified equal to
  the seed files via `bw get password`.
- Molecule/CI: the restic role's `init.yml` is not run in any scenario (system
  converge only sets a `restic:` vars dict and skips `restic_maintenance`), so the
  new `notify`/handler is never exercised in CI — no breakage.

## Notes / future

- No Molecule scenario: the push is controller-side and hits a live external
  service via the `bw` CLI — nothing role-shaped to converge in a container.
- The handler only fires on env-file change. To force a re-push when nothing
  changed, dirty the env files; there is no standalone playbook anymore.
- The Ansible seed files remain the offline source of truth. Keep them backed up
  (git-crypt) — the Vaultwarden copy is not a substitute during a full restore.
