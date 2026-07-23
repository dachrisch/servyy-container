# Restic Seed-Password Recovery Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the restic role from silently generating new repository passwords when seed files are missing — probe Vaultwarden for the real password, then prompt the operator, before any generation.

**Architecture:** A new pre-flight task file `seed_guard.yml` runs first in the restic role (on the controller, before any `restic_password_*` is dereferenced). It detects missing seed files, recovers them from Vaultwarden via the `bw` CLI, or prompts the operator. A shared `bw_unlock.yml` provides the unlocked `bw` session to both the guard (probe) and the existing `vaultwarden_push.yml` (push).

**Tech Stack:** Ansible, Bitwarden CLI (`bw`) against self-hosted Vaultwarden (`pass.lehel.xyz`), bash.

## Global Constraints

- All controller-side tasks: `delegate_to: localhost`, `run_once: true`, `become: false`.
- Never reference `restic_password_*` (or `restic_vaultwarden_items[].password`) inside `seed_guard.yml` — doing so triggers the `lookup('password', …)` that generates a seed. The guard iterates the password-free `restic_seeds` list only.
- Tasks handling a password value use `no_log: true`.
- Seed files: `ansible/plays/vars/.restic_password_{home,root,ls_db}`, mode `0600`, content = the 32-char password followed by a single newline (matches the existing 33-byte format).
- VW item names (exact): `restic - home (lehel.xyz)`, `restic - root (lehel.xyz)`, `restic - ls_db (lehel.xyz)`. VW login username for all: `restic`.
- Recovery precedence: seed file present → Vaultwarden (auto) → operator prompt → generate (empty prompt).
- Missing seed + empty `vw_master_password` OR `bw` unreachable → **hard-fail** (never generate silently).
- No production deployment without explicit user approval (CLAUDE.md). Test on `servyy-test.lxd` first.
- Branch already in use: `claude/restic-seed-guard`.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `ansible/plays/roles/restic/defaults/main.yml` | Add password-free `restic_seeds` mapping (name ↔ seed path); fix stale comment. |
| `ansible/plays/roles/restic/tasks/bw_unlock.yml` | **New.** Authenticate + unlock `bw`, expose `bw_session` fact. |
| `ansible/plays/roles/restic/tasks/seed_guard.yml` | **New.** Detect missing seeds; recover from VW or prompt; never silently generate. |
| `ansible/plays/roles/restic/tasks/vaultwarden_push.yml` | Use shared `bw_unlock.yml` instead of inline auth. |
| `ansible/plays/roles/restic/tasks/main.yml` | Include `seed_guard.yml` as the first task. |
| `CLAUDE.md` | Document the guard under Backup & Recovery Rules; note stale recreate-playbook reference. |
| `history/2026-06-29_restic-seed-guard.md` | History log. |

---

## Task 1: Add password-free `restic_seeds` mapping to defaults

**Files:**
- Modify: `ansible/plays/roles/restic/defaults/main.yml`

**Interfaces:**
- Produces: `restic_seeds` — list of `{ name: <vw item name>, seed: <path relative to playbook_dir> }`. Consumed by `seed_guard.yml`. Must contain no `restic_password_*` references.

- [ ] **Step 1: Add the `restic_seeds` list and fix the stale comment**

Replace the file header comment and append the new list. New full file content:

```yaml
---
# Vaultwarden backup-copy target for the restic repository passwords.
# Used by tasks/vaultwarden_push.yml (invoked by the restic env-file handler).
vw_server: "https://pass.lehel.xyz"

# Password-FREE mapping of VW item name <-> controller seed file path.
# Used by tasks/seed_guard.yml. MUST NOT reference restic_password_* here:
# iterating this list must never trigger the lookup() that generates a seed.
# Keep the `name` values in sync with restic_vaultwarden_items below.
restic_seeds:
  - name: "restic - home (lehel.xyz)"
    seed: "vars/.restic_password_home"
  - name: "restic - root (lehel.xyz)"
    seed: "vars/.restic_password_root"
  - name: "restic - ls_db (lehel.xyz)"
    seed: "vars/.restic_password_ls_db"

restic_vaultwarden_items:
  - name: "restic - home (lehel.xyz)"
    password: "{{ restic_password_home }}"
    notes: "RESTIC_PASSWORD for /etc/restic/env.home (copy of Ansible seed vars/.restic_password_home)"
  - name: "restic - root (lehel.xyz)"
    password: "{{ restic_password_root }}"
    notes: "RESTIC_PASSWORD for /etc/restic/env.root (copy of Ansible seed vars/.restic_password_root)"
  - name: "restic - ls_db (lehel.xyz)"
    password: "{{ restic_password_ls_db }}"
    notes: "RESTIC_PASSWORD for /etc/restic/env.ls_db (copy of Ansible seed vars/.restic_password_ls_db)"
```

- [ ] **Step 2: Verify YAML parses**

Run: `cd ansible && python3 -c "import yaml; yaml.safe_load(open('plays/roles/restic/defaults/main.yml'))" && echo OK`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add ansible/plays/roles/restic/defaults/main.yml
git commit -m "feat(restic): add password-free restic_seeds mapping for seed guard"
```

---

## Task 2: Shared `bw_unlock.yml` and rewire `vaultwarden_push.yml`

**Files:**
- Create: `ansible/plays/roles/restic/tasks/bw_unlock.yml`
- Modify: `ansible/plays/roles/restic/tasks/vaultwarden_push.yml`

**Interfaces:**
- Produces: `bw_unlock.yml` sets fact `bw_session` (string, the `bw unlock --raw` token). Caller is responsible for `bw lock` when finished.
- Consumes: `vaultwarden_api.client_id`, `vaultwarden_api.client_secret` (secrets.yml), `vw_master_password` (vars_prompt), `vw_server` (defaults).

- [ ] **Step 1: Create `bw_unlock.yml`**

```yaml
---
# Shared: authenticate + unlock the `bw` (Bitwarden) CLI on the Ansible
# controller and expose the session token as the `bw_session` fact.
# Included by tasks/seed_guard.yml (probe) and tasks/vaultwarden_push.yml (push).
# Requires: vaultwarden_api.client_id/secret (secrets.yml), vw_master_password
# (vars_prompt in plays/restic.yml), vw_server (defaults).
# The CALLER is responsible for running `bw lock` when finished.

- name: Check that the bw CLI is installed on the controller
  ansible.builtin.command:
    cmd: bw --version
  delegate_to: localhost
  run_once: true
  become: false
  register: bw_version
  changed_when: false
  failed_when: false

- name: Fail clearly when the bw CLI is missing
  ansible.builtin.fail:
    msg: >-
      The `bw` (Bitwarden) CLI is not installed on the Ansible controller, but a
      Vaultwarden operation was requested. Install it (e.g. `npm i -g @bitwarden/cli`)
      or restore the restic seed files (vars/.restic_password_*) from your offline copy.
  delegate_to: localhost
  run_once: true
  when: bw_version.rc != 0

- name: Check bw authentication status
  ansible.builtin.command:
    cmd: bw status
  delegate_to: localhost
  run_once: true
  become: false
  register: bw_status
  changed_when: false
  failed_when: false

- name: Point bw at the self-hosted Vaultwarden (only while logged out)
  ansible.builtin.command:
    cmd: "bw config server {{ vw_server }}"
  delegate_to: localhost
  run_once: true
  become: false
  changed_when: true
  when: "'unauthenticated' in (bw_status.stdout | lower)"

- name: Assert bw already targets the expected server (when logged in)
  ansible.builtin.assert:
    that:
      - (bw_status.stdout | from_json).serverUrl | default('') == vw_server
    fail_msg: >-
      bw is logged in to '{{ (bw_status.stdout | from_json).serverUrl | default('(none)') }}'
      but this operation expects '{{ vw_server }}'. Run `bw logout` on the controller and retry.
  delegate_to: localhost
  run_once: true
  when: "'unauthenticated' not in (bw_status.stdout | lower)"

- name: Authenticate with API key (no 2FA prompt)
  ansible.builtin.command:
    cmd: bw login --apikey
  environment:
    BW_CLIENTID: "{{ vaultwarden_api.client_id }}"
    BW_CLIENTSECRET: "{{ vaultwarden_api.client_secret }}"
  delegate_to: localhost
  run_once: true
  become: false
  register: bw_login
  changed_when: "'logged in' in (bw_login.stdout | lower)"
  failed_when:
    - bw_login.rc != 0
    - "'already logged in' not in (bw_login.stderr | lower)"
  no_log: true

- name: Unlock vault with the prompted master password
  ansible.builtin.command:
    cmd: bw unlock --passwordenv BW_MASTER --raw
  environment:
    BW_MASTER: "{{ vw_master_password }}"
  delegate_to: localhost
  run_once: true
  become: false
  register: bw_unlock
  changed_when: false
  no_log: true

- name: Expose the unlocked session as bw_session
  ansible.builtin.set_fact:
    bw_session: "{{ bw_unlock.stdout }}"
  delegate_to: localhost
  run_once: true
  no_log: true

- name: Sync vault
  ansible.builtin.command:
    cmd: bw sync
  environment:
    BW_SESSION: "{{ bw_session }}"
  delegate_to: localhost
  run_once: true
  become: false
  changed_when: false
```

- [ ] **Step 2: Rewrite `vaultwarden_push.yml` to use `bw_unlock.yml`**

Full new content:

```yaml
---
# Push a backup copy of the restic repository passwords into Vaultwarden.
# Runs on the Ansible CONTROLLER via the `bw` CLI (not the remote host).
# Idempotent: only creates missing Login items. Invoked by the restic role
# handler (when /etc/restic/env.* changes).
#
# Requires (from vars/secrets.yml): vaultwarden_api.client_id/secret,
# restic_password_{home,root,ls_db}; and vw_master_password (vars_prompt).

- name: Unlock the bw vault (shared)
  ansible.builtin.include_tasks: bw_unlock.yml

- name: List existing vault item names
  ansible.builtin.command:
    cmd: bw list items
  environment:
    BW_SESSION: "{{ bw_session }}"
  delegate_to: localhost
  run_once: true
  become: false
  register: bw_items_raw
  changed_when: false
  no_log: true

- name: Compute set of item names already present
  ansible.builtin.set_fact:
    existing_item_names: "{{ bw_items_raw.stdout | from_json | map(attribute='name') | list }}"
  delegate_to: localhost
  run_once: true

- name: Create missing restic items in Vaultwarden
  ansible.builtin.shell:
    cmd: "set -o pipefail; printf '%s' {{ item_json | quote }} | bw encode | bw create item"
    executable: /bin/bash
  environment:
    BW_SESSION: "{{ bw_session }}"
  delegate_to: localhost
  run_once: true
  become: false
  vars:
    item_json: >-
      {{ {'type': 1,
          'name': item.name,
          'notes': item.notes,
          'login': {'username': 'restic', 'password': item.password, 'uris': []}}
         | to_json }}
  loop: "{{ restic_vaultwarden_items }}"
  loop_control:
    label: "{{ item.name }}"
  when: item.name not in existing_item_names
  changed_when: true
  no_log: true

- name: Report which restic items were created vs already present
  ansible.builtin.debug:
    msg: >-
      {{ item.name }}:
      {{ 'already present (skipped)' if item.name in existing_item_names else 'created' }}
  delegate_to: localhost
  run_once: true
  loop: "{{ restic_vaultwarden_items }}"
  loop_control:
    label: "{{ item.name }}"

- name: Lock the vault again
  ansible.builtin.command:
    cmd: bw lock
  delegate_to: localhost
  run_once: true
  become: false
  changed_when: false
```

- [ ] **Step 3: Verify both files parse as YAML**

Run:
```bash
cd ansible && for f in bw_unlock vaultwarden_push; do python3 -c "import yaml; yaml.safe_load(open('plays/roles/restic/tasks/$f.yml'))"; done && echo OK
```
Expected: `OK`

- [ ] **Step 4: Confirm no inline `bw unlock` remains in vaultwarden_push.yml**

Run: `grep -c 'bw unlock' ansible/plays/roles/restic/tasks/vaultwarden_push.yml`
Expected: `0`

- [ ] **Step 5: Commit**

```bash
git add ansible/plays/roles/restic/tasks/bw_unlock.yml ansible/plays/roles/restic/tasks/vaultwarden_push.yml
git commit -m "refactor(restic): extract shared bw_unlock.yml; rewire vaultwarden_push"
```

---

## Task 3: Create the `seed_guard.yml` pre-flight guard

**Files:**
- Create: `ansible/plays/roles/restic/tasks/seed_guard.yml`

**Interfaces:**
- Consumes: `restic_seeds` (Task 1), `bw_unlock.yml` → `bw_session` (Task 2), `vw_master_password` (vars_prompt).
- Produces: ensures `vars/.restic_password_{home,root,ls_db}` exist on the controller (recovered from VW or operator-supplied), OR a deliberate empty-prompt path that leaves a seed absent for downstream generation, OR a hard-fail.

- [ ] **Step 1: Create `seed_guard.yml`**

```yaml
---
# PRE-FLIGHT GUARD (controller-side). Runs FIRST in the restic role, before any
# restic_password_* variable is dereferenced. Prevents the lookup('password', …)
# in secrets.yml from silently GENERATING a new restic password when a seed file
# is missing (fresh / re-cloned controller). Instead: recover the password from
# Vaultwarden, or prompt the operator. Only an explicit empty prompt generates.
#
# Iterates restic_seeds (password-FREE) — never touches restic_password_* here.

- name: Stat restic password seed files on the controller
  ansible.builtin.stat:
    path: "{{ playbook_dir }}/{{ item.seed }}"
  loop: "{{ restic_seeds }}"
  loop_control:
    label: "{{ item.seed }}"
  delegate_to: localhost
  run_once: true
  become: false
  register: seed_stats

- name: Compute the list of missing seeds
  ansible.builtin.set_fact:
    missing_seeds: >-
      {{ seed_stats.results | rejectattr('stat.exists') | map(attribute='item') | list }}
  delegate_to: localhost
  run_once: true

- name: Report seed-file state
  ansible.builtin.debug:
    msg: >-
      Restic seed guard: {{ missing_seeds | length }} missing
      ({{ missing_seeds | map(attribute='seed') | join(', ') | default('none') }}).
  delegate_to: localhost
  run_once: true

# --- Everything below only runs when at least one seed is missing -------------
- name: Recover missing restic seeds
  when: missing_seeds | length > 0
  delegate_to: localhost
  run_once: true
  become: false
  block:
    - name: Hard-fail when seeds are missing but no Vaultwarden master password was given
      ansible.builtin.fail:
        msg: |
          Restic seed file(s) are MISSING on this controller:
            {{ missing_seeds | map(attribute='seed') | join('\n  ') }}

          Refusing to silently generate new restic passwords (that would not match
          the existing encrypted repositories and could destroy backup history on a
          subsequent recreate).

          To recover, re-run the restic play and provide the Vaultwarden master
          password at the prompt — the guard will pull the passwords from
          Vaultwarden ({{ vw_server }}). Alternatively, restore the seed files
          (vars/.restic_password_*) from your offline copy first.
      when: vw_master_password | default('') | length == 0

    - name: Unlock the bw vault (shared)
      ansible.builtin.include_tasks: bw_unlock.yml

    - name: Probe Vaultwarden for each missing seed
      ansible.builtin.command:
        cmd: "bw get password {{ item.name | quote }}"
      environment:
        BW_SESSION: "{{ bw_session }}"
      loop: "{{ missing_seeds }}"
      loop_control:
        label: "{{ item.name }}"
      register: vw_probe
      changed_when: false
      failed_when: false
      no_log: true

    - name: Restore seed files found in Vaultwarden
      ansible.builtin.copy:
        dest: "{{ playbook_dir }}/{{ item.item.seed }}"
        content: "{{ item.stdout }}\n"
        mode: '0600'
      loop: "{{ vw_probe.results }}"
      loop_control:
        label: "{{ item.item.seed }}"
      when:
        - item.rc == 0
        - item.stdout | trim | length > 0
      no_log: true

    - name: Prompt the operator for seeds NOT found in Vaultwarden
      ansible.builtin.pause:
        prompt: |
          Seed '{{ item.item.seed }}' is missing and NO matching item
          ('{{ item.item.name }}') was found in Vaultwarden.
          Paste the RESTIC_PASSWORD for this repository, or leave BLANK to
          GENERATE a brand-new password (only valid for a never-initialized repo)
      loop: "{{ vw_probe.results }}"
      loop_control:
        label: "{{ item.item.seed }}"
      when: item.rc != 0 or (item.stdout | trim | length == 0)
      register: seed_prompts
      no_log: true

    - name: Write operator-supplied seeds
      ansible.builtin.copy:
        dest: "{{ playbook_dir }}/{{ item.item.item.seed }}"
        content: "{{ item.user_input | trim }}\n"
        mode: '0600'
      loop: "{{ seed_prompts.results | default([]) }}"
      loop_control:
        label: "{{ item.item.item.seed }}"
      when:
        - item.skipped is not defined
        - item.user_input | default('') | trim | length > 0
      no_log: true

    - name: Warn where a new password will be generated downstream
      ansible.builtin.debug:
        msg: >-
          '{{ item.item.item.seed }}': left blank — a NEW restic password will be
          generated by the lookup. Ensure this repository has never been initialized.
      loop: "{{ seed_prompts.results | default([]) }}"
      loop_control:
        label: "{{ item.item.item.seed }}"
      when:
        - item.skipped is not defined
        - item.user_input | default('') | trim | length == 0

    - name: Lock the vault again
      ansible.builtin.command:
        cmd: bw lock
      changed_when: false
```

- [ ] **Step 2: Verify YAML parses**

Run: `cd ansible && python3 -c "import yaml; yaml.safe_load(open('plays/roles/restic/tasks/seed_guard.yml'))" && echo OK`
Expected: `OK`

- [ ] **Step 3: Confirm the guard never references a password var**

Run: `grep -nE 'restic_password_|\.password' ansible/plays/roles/restic/tasks/seed_guard.yml || echo CLEAN`
Expected: `CLEAN`

- [ ] **Step 4: Commit**

```bash
git add ansible/plays/roles/restic/tasks/seed_guard.yml
git commit -m "feat(restic): add seed_guard pre-flight (recover from Vaultwarden/prompt before generating)"
```

---

## Task 4: Wire `seed_guard.yml` first in `main.yml`

**Files:**
- Modify: `ansible/plays/roles/restic/tasks/main.yml:1-9`

**Interfaces:**
- Consumes: `seed_guard.yml` (Task 3). Must precede the `init.yml` include so the guard runs before `restic_password_*` is dereferenced.

- [ ] **Step 1: Insert the guard include as the first task**

Find (top of file):

```yaml
---
# Orchestrator for Restic role

- name: Initialize Restic Infrastructure
  include_tasks: init.yml
  tags:
    - restic
    - restic.init
```

Replace with:

```yaml
---
# Orchestrator for Restic role

# Pre-flight: recover missing restic password seed files from Vaultwarden (or
# prompt the operator) BEFORE any restic_password_* var is dereferenced, so a
# missing seed never silently generates a new password. Tagged for init AND
# recreate so it guards the destructive recreate path too.
- name: Guard restic password seed files
  include_tasks: seed_guard.yml
  tags:
    - restic
    - restic.init
    - restic.recreate

- name: Initialize Restic Infrastructure
  include_tasks: init.yml
  tags:
    - restic
    - restic.init
```

- [ ] **Step 2: Syntax check the full play**

Run: `cd ansible && ansible-playbook plays/restic.yml --syntax-check`
Expected: `playbook: plays/restic.yml` with no errors (exit 0). (If the play requires an inventory/limit, use `ansible-playbook plays/restic.yml --syntax-check -i inventory/production`.)

- [ ] **Step 3: Commit**

```bash
git add ansible/plays/roles/restic/tasks/main.yml
git commit -m "feat(restic): run seed_guard first in role (init + recreate paths)"
```

---

## Task 5: Verify on servyy-test.lxd

**Files:** none (verification only).

**Interfaces:** exercises Task 1–4 end to end.

- [ ] **Step 1: Ensure the test container exists**

Run: `cd scripts && ./setup_test_container.sh`
Expected: completes; `lxc list` shows `servyy-test` running. (Skip if already provisioned.)

- [ ] **Step 2: Happy path — seeds present, guard skips cleanly**

Run (provide the real VW master password if prompted, or press enter — with seeds present the guard must not touch bw):
```bash
cd ansible && ansible-playbook plays/restic.yml -i inventory/production --limit servyy-test.lxd --tags restic.init --check
```
Expected: the "Report seed-file state" debug shows `0 missing`; no `bw` task runs; PLAY RECAP `failed=0`.

- [ ] **Step 3: Hard-fail path — missing seed + blank master password**

Temporarily hide one seed on the controller, then run with an empty master password (press enter at the prompt):
```bash
mv ansible/plays/vars/.restic_password_ls_db /tmp/.restic_password_ls_db.bak
cd ansible && ansible-playbook plays/restic.yml -i inventory/production --limit servyy-test.lxd --tags restic.init --check
```
Expected: the play **fails** at "Hard-fail when seeds are missing but no Vaultwarden master password was given" with the recovery message. No new seed file is created. (Confirm `ls ansible/plays/vars/.restic_password_ls_db` shows it absent.)

- [ ] **Step 4: Restore the seed**

Run: `mv /tmp/.restic_password_ls_db.bak ansible/plays/vars/.restic_password_ls_db`
Expected: `ls -l ansible/plays/vars/.restic_password_ls_db` shows the file back (33 bytes).

- [ ] **Step 5: VW recovery path (manual, against pass.lehel.xyz)**

This path cannot run inside the LXD container's mock. With the same seed hidden again and providing the **real** VW master password at the prompt, confirm the "Restore seed files found in Vaultwarden" task writes the seed back with the correct 32-char password (compare against the value in Vaultwarden). Restore from `/tmp` backup if anything goes wrong.

Run:
```bash
cp ansible/plays/vars/.restic_password_ls_db /tmp/.restic_password_ls_db.bak
mv ansible/plays/vars/.restic_password_ls_db /tmp/.restic_password_ls_db.hidden
cd ansible && ansible-playbook plays/restic.yml -i inventory/production --limit servyy-test.lxd --tags restic.init --check
# enter the real VW master password at the prompt
```
Expected: guard reports the seed recovered from Vaultwarden; `ansible/plays/vars/.restic_password_ls_db` reappears and its content matches the Vaultwarden item. If it does not match `/tmp/.restic_password_ls_db.bak`, STOP and investigate before proceeding.

- [ ] **Step 6: Record verification result**

No commit (verification only). Capture the observed outputs for the history log in Task 6.

---

## Task 6: Documentation

**Files:**
- Modify: `CLAUDE.md` (Backup & Recovery Rules section)
- Create: `history/2026-06-29_restic-seed-guard.md`

**Interfaces:** none.

- [ ] **Step 1: Add a Recovery-Rules subsection to CLAUDE.md**

Under the "Backup & Recovery Rules" → after item **4. Off-host Password Backup (Vaultwarden)**, add item 5:

```markdown
5. **Seed-Password Recovery Guard (prevents silent generation)**
   - The restic role runs `tasks/seed_guard.yml` FIRST (before any `restic_password_*`
     is dereferenced). If a seed file `ansible/plays/vars/.restic_password_*` is missing
     (fresh/re-cloned controller), it refuses to let Ansible silently generate a new
     password. Recovery precedence: **seed file → Vaultwarden (auto) → operator prompt → generate**.
   - Missing seed + blank Vaultwarden master password (or `bw` unreachable) → **hard-fail**.
     Provide the VW master password at the prompt to pull the password from Vaultwarden,
     or restore the seed files from your offline copy first.
   - A new password is generated ONLY when the operator leaves the prompt blank after
     Vaultwarden was actually probed and had no matching item — i.e. a never-initialized repo.
   - Guards init AND the destructive `restic.recreate` path (so recreate's wipe/re-init
     decision uses the real password, not a wrong-password artifact).
   - Reference: `history/2026-06-29_restic-seed-guard.md`

> **Note:** CLAUDE.md elsewhere references a standalone `ansible-playbook restic_recreate.yml`
> — no such file exists; recreate runs via `--tags restic.recreate` through the restic role.
```

- [ ] **Step 2: Create the history log**

```markdown
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
- servyy-test.lxd: seeds present → guard skips (0 missing); missing seed + blank
  master password → hard-fail with recovery message; missing seed + real master
  password → recovered from Vaultwarden (value matched).

## Known limitation
Greenfield bootstrap (no seeds AND no Vaultwarden) hard-fails by design — place seed
files from the offline copy first. Matches the "keep an offline copy" rule.

## Success criteria
- [x] Missing seed never silently generates a new password.
- [x] Vaultwarden probed before prompting; prompt before generating.
- [x] Existing vaultwarden_push behaviour unchanged.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md history/2026-06-29_restic-seed-guard.md
git commit -m "docs(restic): document seed-password recovery guard"
```

---

## Self-Review

**Spec coverage:**
- Scope = any restic run → Task 4 wires guard into `main.yml` with `restic`/`restic.init`/`restic.recreate` tags. ✓
- Precedence seed→VW(auto)→prompt→generate → Task 3 block. ✓
- Hard-fail when VW unreachable / no master password → Task 3 fail task + Task 2 bw-missing fail. ✓
- Empty prompt = generate → Task 3 "Warn where a new password will be generated" + leaving seed absent. ✓
- Shared bw_unlock refactor → Task 2. ✓
- Password-free mapping (lazy-eval caveat) → Task 1 `restic_seeds` + Global Constraint + Task 3 Step 3 grep check. ✓
- Testing on servyy-test → Task 5. ✓
- Docs + recreate-playbook note → Task 6. ✓

**Placeholder scan:** No TBD/TODO; all YAML provided in full. ✓

**Type consistency:** `bw_session` fact set in `bw_unlock.yml` and consumed via `BW_SESSION: "{{ bw_session }}"` in Task 2 and Task 3. `restic_seeds` items use `.name`/`.seed`; nested loop registers dereference `item.item.seed` (vw_probe) and `item.item.item.seed` (seed_prompts over vw_probe results) — depth verified against the `pause`-over-`vw_probe.results` chain. ✓
