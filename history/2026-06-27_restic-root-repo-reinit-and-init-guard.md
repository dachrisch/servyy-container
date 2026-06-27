# 2026-06-27 — Prod restic-root repo recovery + init access guard

## Problem

Prod `root` restic backups and checks had been failing **every run since the 2026-06-03
server rebuild** with `Fatal: wrong password or no key found`. Discovered while validating the
db forget/check fix (PR #32).

Root cause (evidence-backed):
- Prod `/etc/restic/env.root` password **matches** the local `plays/vars/.restic_password_root`
  (hash compared) — so it is **not** a deploy/templating drift.
- On the storage box, `restic-root/keys/` held a single key dated **Jan 15** with the last
  snapshot **Jan 28**, and there was **no `restic-root.stale`**. The `restic-home` repo, by
  contrast, had a fresh key dated **Jun 3** with the old one preserved as `restic-home.stale`.
- So during the Jun 3 rebuild the home repo was re-initialised under the current password (works),
  but the root repo was left as the old January repo whose key the current password can no longer
  open. `restic init` cannot re-key an existing repo, and the init task is gated
  (`when: ... .changed`) + `failed_when: false`, so root silently stayed broken.
- The existing "Verify restic password integrity" task only compares env-file vs Ansible
  password (which matched), so it never caught a repo whose *stored key* diverged.

Confirmed it was a true key mismatch, not a stale lock: `restic unlock` + `restic cat config`
on prod root both returned `wrong password or no key found` (a stale lock gives a different
"repository is already locked" error — that was the *separate* issue seen on servyy-test, fixed
with `restic unlock`).

## Fix A — re-init prod root repo (operational, reversible)

Mirrors what was done for home. Validated the procedure on `servyy-test.lxd` first (the
`--tags restic.init` path skips re-init because `sftp_mkdir` reports unchanged when sibling
repos already exist, so a **direct `restic init`** is required):

```bash
# prod (lehel.xyz)
ssh lehel.xyz "sudo mv /mnt/storagebox/backup/lehel.xyz/restic-root \
  /mnt/storagebox/backup/lehel.xyz/restic-root.stale.20260627"          # reversible
ssh lehel.xyz "sudo bash -c 'source /etc/restic/env.root && restic init'"  # created repo 0be99af9
# first snapshot via the existing user timer service:
ssh lehel.xyz "systemctl --user start restic-backup-root.service"
```

- Old repo preserved as `restic-root.stale.20260627` (Jan 15–28 snapshots; can be deleted once
  the new repo has a few days of history). Cost of re-init: those stale snapshots are abandoned;
  root backup is just `/etc`+`/var` config, fully re-captured on the next run.
- New repo accessible with the current password (`restic cat config` → ok).

## Hardening — loud detection of repo/password mismatch (PR: this branch)

`roles/restic/tasks/init.yml`: after init, added two tasks (tag `restic.init`):
1. **Verify each restic repository opens with the configured password** — runs
   `restic cat config` per enabled repo (home/root/db) as root, `failed_when: false`,
   `no_log: true`.
2. **Fail loudly if any restic repository rejects the configured password** — aborts the play
   when a repo's stderr contains `wrong password or no key found`. Deliberately matches **only**
   that string, so transient sftp/network errors (e.g. "connection refused") do **not**
   hard-fail a deploy.

Validation:
- servyy-test `--tags restic.init` (all repos accessible) → `failed=0`, guard ran, no false positive.
- Localhost unit-play feeding synthetic results → guard flags only the key-mismatch repo and
  ignores the transient-error repo (`would_fail = True` only for the real mismatch).

## Status

- Prod root repo: re-initialised, accessible; first backup running, then `restic-check` should
  report `root` passing alongside `home` and `db`.
- Hardening: validated test + unit; PR open.
- Follow-up: delete `restic-root.stale.20260627` after the new repo accrues a few days of
  snapshots and a clean weekly `restic-check`.
