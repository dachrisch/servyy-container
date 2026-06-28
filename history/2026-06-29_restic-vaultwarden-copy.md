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

New standalone localhost playbook `ansible/plays/restic_to_vaultwarden.yml`:

- Reads passwords from existing `restic_password_{home,root,ls_db}` vars.
- Auth: `bw login --apikey` using a personal API key in `secrets.yml`
  (`vaultwarden_api.client_id/secret`) → no 2FA prompt.
- **Master password** entered interactively via `vars_prompt` (hidden), like the
  ansible-vault password prompt — never stored on disk or in git.
- Idempotent: lists existing items, creates only missing ones (Login type,
  `username: restic`), reports created-vs-skipped, then `bw lock`.
- `no_log: true` on every secret-touching task; pipe runs under bash + pipefail.

## Files changed

- `ansible/plays/restic_to_vaultwarden.yml` (new)
- `ansible/plays/vars/secrets.yml` — added `vaultwarden_api` block (git-crypt encrypted)

## Verification

- `ansible-playbook --syntax-check` ✅
- `ansible-lint` production profile ✅ (pipefail added for risky-shell-pipe)
- `bw encode` JSON round-trip ✅
- Live run 2026-06-29: 3 items CREATED, `PLAY RECAP ok=9 changed=2 failed=0`,
  vault re-locked.

## Run

```bash
cd ansible/plays && ansible-playbook restic_to_vaultwarden.yml
# prompts for Vaultwarden master password
```

## Notes / future

- No Molecule scenario: controller-side maintenance playbook hitting a live
  external service via the `bw` CLI — nothing role-shaped to converge in a
  container.
- The Ansible seed files remain the offline source of truth. Keep them backed up
  (git-crypt) — the Vaultwarden copy is not a substitute during a full restore.
