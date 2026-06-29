# Restic Seed-Password Recovery Guard — 2026-06-29

## Problem
Restic passwords come from `lookup('password', 'vars/.restic_password_* …')` in
`secrets.yml`. The seed files are gitignored, so a fresh/re-cloned controller has
none, and the lookup **silently generates new random passwords**. These don't match
the encrypted repos; a subsequent `restic.recreate` would wipe and re-init repos with
the wrong password — permanent loss of backup history.

## Solution
A pre-flight `tasks/seed_guard.yml` runs first in the restic role (controller-side),
before any `restic_password_*` is dereferenced. For each missing seed it:
1. Hard-fails if no Vaultwarden master password was supplied (or `bw` is unavailable).
2. Probes Vaultwarden (`bw get password "<item>"`) and restores the seed if found.
3. Otherwise prompts the operator to paste the password; blank = generate (new repo only).

A shared `tasks/bw_unlock.yml` provides the unlocked `bw` session to both the guard
(probe) and `vaultwarden_push.yml` (push). A password-free `restic_seeds` list maps
VW item names to seed paths without triggering the lookup.

## Files changed
- `ansible/plays/roles/restic/defaults/main.yml` — add `restic_seeds`.
- `ansible/plays/roles/restic/tasks/bw_unlock.yml` — new shared bw auth → `bw_session`.
- `ansible/plays/roles/restic/tasks/seed_guard.yml` — new guard.
- `ansible/plays/roles/restic/tasks/main.yml` — include guard first.
- `ansible/plays/roles/restic/tasks/vaultwarden_push.yml` — use shared bw_unlock.
- `CLAUDE.md` — recovery-rules subsection + recreate-playbook note.

## Verification
- `ansible-playbook plays/restic.yml --syntax-check` — clean.
- ansible-lint (production profile) on `seed_guard.yml` + `bw_unlock.yml` — 0 failures, 0 warnings.
- servyy-test.lxd, HAPPY PATH (seeds present, `--tags restic.init --check`):
  `ansible-playbook servyy.yml -i testing --limit servyy-test.lxd --tags restic.init --check`
  — guard runs FIRST (before init), reports "Restic seed guard: 0 missing", the
  Vaultwarden/bw recovery block is skipped, PLAY RECAP `failed=0`.
- servyy-test.lxd, HARD-FAIL PATH (one seed temporarily moved, blank master password):
  `ansible-playbook servyy.yml -i testing --limit servyy-test.lxd --tags restic.init --check`
  — play aborts at the guard's hard-fail task with the recovery message naming the
  missing seed and `pass.lehel.xyz`; `bw` is NOT invoked (fail fires before bw_unlock);
  seed restored afterward and byte-identical to backup.
- Vaultwarden live recovery round-trip: operator-validated (`bw get password` vs the
  live seed — values matched).
- **Wiring bug caught and fixed during verification:** dynamic `include_tasks` did not
  propagate tags, so the guard's inner tasks were skipped under `--tags restic.init` /
  `restic.recreate`. Fixed with `apply.tags` on the include (committed on this branch).

## Known limitation
Greenfield bootstrap (no seeds AND no Vaultwarden) hard-fails by design — place seed
files from the offline copy first. Matches the "keep an offline copy" rule.

## Success criteria
- [x] Missing seed never silently generates a new password.
- [x] Vaultwarden probed before prompting; prompt before generating.
- [x] Existing vaultwarden_push behaviour unchanged.
