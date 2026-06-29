# Restic seed-password recovery guard — Design

**Date:** 2026-06-29
**Status:** Approved (brainstorming complete)
**Area:** `ansible/plays/roles/restic`

## Problem

Restic repository passwords are sourced in `ansible/plays/vars/secrets.yml` via:

```yaml
restic_password_home:  "{{ lookup('password', 'vars/.restic_password_home  length=32 chars=ascii_letters,digits') }}"
restic_password_root:  "{{ lookup('password', 'vars/.restic_password_root  length=32 chars=ascii_letters,digits') }}"
restic_password_ls_db: "{{ lookup('password', 'vars/.restic_password_ls_db length=32 chars=ascii_letters,digits') }}"
```

The seed files `ansible/plays/vars/.restic_password_{home,root,ls_db}` are the **source of truth** and are **gitignored** (confirmed in `.gitignore`; not tracked by git). They therefore exist only on the Ansible controller.

Ansible's `password` lookup **silently generates a new random password and writes the seed file when it is missing**. On a fresh or re-cloned controller (e.g. bare-metal disaster recovery) the seeds are absent, so:

1. The lookup generates brand-new random passwords.
2. They do not match the already-encrypted repositories on the Storage Box.
3. Normal `init.yml` runs are caught by the existing "Fail loudly if any restic repository rejects the configured password" guard — good.
4. But if an operator then runs the recreate path (`restic.recreate` tag) because the repos look "broken" (inaccessible due to wrong password), `recreate.yml` **wipes and re-initializes** the repositories with the wrong (newly generated) password — **permanent loss of all backup history**.

Vaultwarden (`pass.lehel.xyz`) already holds a human-readable backup copy of these passwords (pushed by `tasks/vaultwarden_push.yml`). It can serve as the recovery source.

## Goal

Before a missing seed file is allowed to trigger generation of a new password, **probe Vaultwarden for the existing copy, or ask the operator** — never silently generate.

## Decisions (from brainstorming)

| Question | Decision |
|----------|----------|
| Scope | Any restic run (init + recreate) — guard at the root, before any `restic_password_*` dereference. |
| Precedence | `seed file → Vaultwarden (auto) → prompt user → generate`. |
| Vaultwarden unreachable when a seed is missing | **Hard-fail**, require `bw` reachable/unlocked. |
| Genuinely-new-repo generation | **Empty prompt = generate** (reached only after VW was actually probed and the operator pressed enter). |

## Solution

### New pre-flight task: `seed_guard.yml`

New file `ansible/plays/roles/restic/tasks/seed_guard.yml`, included as the **first** task in `tasks/main.yml`, tagged `restic`, `restic.init`, `restic.recreate` so it runs on every path — including recreate-only runs (`--tags restic.recreate`) — and **before** any `restic_password_*` variable is dereferenced.

All tasks run on the controller: `delegate_to: localhost`, `run_once: true`, `become: false`.

**Logic:**

1. **Stat** the three seed files on the controller (path `{{ playbook_dir }}/vars/.restic_password_*`) → build `missing_seeds`.
2. If `missing_seeds` is empty → **no-op fast path** (common case; no `bw` calls, no prompts, no changes).
3. If any seed is missing → engage guard:
   1. **Require Vaultwarden.** If `vw_master_password` is empty, or `bw` cannot reach/unlock VW → **hard-fail** with recovery instructions. This is the safety net that prevents silent generation.
   2. **Unlock** the vault (shared `bw_unlock.yml`, see below) to obtain `bw_session`.
   3. **Probe** each missing seed via `bw get item "<vw_item_name>"` (`failed_when: false`):
      - **Found** → extract `(stdout | from_json).login.password`; fail if empty/malformed; otherwise write it to the seed file (`mode 0600`, trailing newline to match the existing 33-byte format). Outcome: *recovered from Vaultwarden*.
      - **Not found** → `pause` prompt: paste the `RESTIC_PASSWORD`, **or leave blank to GENERATE a new password (only valid for a never-initialized repo)**.
        - Non-empty input → write the seed file.
        - Empty input → leave the seed absent; the downstream `lookup('password', …)` will generate a fresh one. Outcome: *will generate*.
   4. **Lock** the vault (`bw lock`).
4. **Report** the per-seed outcome (recovered / prompted-and-written / will-generate).

### Why this makes recreate safe

`recreate.yml` decides `broken_repos` by testing repository access with the configured password. With the guard guaranteeing that password is the *real* one (recovered from VW), a repo that still tests "broken" is genuinely broken — so the destructive wipe/re-init decision is trustworthy instead of being a wrong-password artifact.

### Shared `bw_unlock.yml` refactor (DRY)

Both `seed_guard.yml` (probe) and `vaultwarden_push.yml` (push) need an unlocked `bw` session. Extract the existing bw auth sequence from `vaultwarden_push.yml` — status → `config server` (when logged out) → assert-server (when logged in) → `login --apikey` → `unlock --passwordenv` → `sync` — into a shared `tasks/bw_unlock.yml` that sets a `bw_session` fact. Both task files `include_tasks: bw_unlock.yml` and then use `BW_SESSION: "{{ bw_session }}"`.

- Preserves existing behaviour of `vaultwarden_push.yml` (no functional change to the push).
- Single source of truth for the bw auth contract.

### Data mapping

Extend each entry in `restic_vaultwarden_items` (`defaults/main.yml`) with a `seed:` path so the VW-item-name ↔ seed-file mapping has one source of truth:

```yaml
restic_vaultwarden_items:
  - name: "restic - home (lehel.xyz)"
    seed: "vars/.restic_password_home"
    password: "{{ restic_password_home }}"
    notes: "..."
  - name: "restic - root (lehel.xyz)"
    seed: "vars/.restic_password_root"
    password: "{{ restic_password_root }}"
    notes: "..."
  - name: "restic - ls_db (lehel.xyz)"
    seed: "vars/.restic_password_ls_db"
    password: "{{ restic_password_ls_db }}"
    notes: "..."
```

`seed_guard.yml` iterates `restic_vaultwarden_items` using `seed` + `name`. The push task ignores the extra `seed` key. **Caveat:** `restic_vaultwarden_items` references `restic_password_*` in its `password:` field. `seed_guard.yml` must only read `item.seed` / `item.name` (never `item.password`) so iterating the list does not dereference the lookup before recovery completes. Verify `restic_vaultwarden_items` is itself lazily evaluated (it lives in defaults and is only fully rendered when `.password` is accessed); the guard must avoid touching `.password`.

## Error handling

- **Missing seed + empty `vw_master_password` / VW unreachable** → hard abort with a message pointing to either (a) re-run providing the Vaultwarden master password so the guard can pull the passwords, or (b) restore the seed files from the offline copy mandated by CLAUDE.md.
- **VW item found but password empty/malformed** → fail rather than write a bad seed file.
- **`bw` not installed on the controller** → treated as VW unreachable → hard-fail with the same recovery message.

## Testing

The restic role has **no** molecule scenario (it is validated on `servyy-test.lxd` via `tasks/test_setup.yml`). Match that approach:

1. `ansible-playbook plays/restic.yml --syntax-check`.
2. `--check` dry-run.
3. On `servyy-test.lxd`:
   - **Seeds present** → guard skips cleanly: no `bw` invocation, no prompt, no change reported.
   - **Deliberately-removed seed + empty master password** → guard **hard-fails** with the recovery message (restore the seed afterwards).
4. Manual VW probe paths exercised against `pass.lehel.xyz` (found → recovered; not-found → prompt) — `bw` interactions cannot run in a container.

No production deployment without explicit user approval per CLAUDE.md.

## Known limitation (documented, not coded)

True greenfield bootstrap (no seeds **and** no Vaultwarden yet) hard-fails by design. Resolution: place the seed files from the offline copy first. This matches CLAUDE.md's "keep an offline copy of the master + restic passwords" and the "do not make Vaultwarden the source restic reads from at deploy time" rule.

## Documentation

- Add a subsection to CLAUDE.md "Backup & Recovery Rules" describing the seed guard and its recovery precedence.
- Add `history/2026-06-29_restic-seed-guard.md`.
- Separately flag that CLAUDE.md still references a nonexistent standalone `restic_recreate.yml` playbook (recreate actually runs via the `restic.recreate` tag through the role). Out of scope to fix here beyond a note.

## Files touched

| File | Change |
|------|--------|
| `ansible/plays/roles/restic/tasks/seed_guard.yml` | **New** — pre-flight guard. |
| `ansible/plays/roles/restic/tasks/bw_unlock.yml` | **New** — shared bw auth → `bw_session`. |
| `ansible/plays/roles/restic/tasks/main.yml` | Include `seed_guard.yml` first. |
| `ansible/plays/roles/restic/tasks/vaultwarden_push.yml` | Use shared `bw_unlock.yml`. |
| `ansible/plays/roles/restic/defaults/main.yml` | Add `seed:` to each `restic_vaultwarden_items`. |
| `CLAUDE.md` | Recovery-rules subsection + recreate-playbook note. |
| `history/2026-06-29_restic-seed-guard.md` | New history log. |
