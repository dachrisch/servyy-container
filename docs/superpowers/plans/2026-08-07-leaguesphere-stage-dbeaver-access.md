# LeagueSphere Stage DB Access via DBeaver — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an operator connect DBeaver to LeagueSphere's stage database through a stable, SSH-enforced, stage-only tunnel — with no public exposure — plus a nightly prod→stage refresh and off-host backup of the SSH keys involved.

**Architecture:** A new, deliberately unprivileged Linux account (`dbeaver_stage`) on `lehel.xyz` holds one SSH key restricted (via `authorized_keys` `permitopen`) to forward only to a loopback-bound port that stage's `mysql` container now publishes. A new systemd user-timer runs the existing dump/restore logic nightly. Both the new key and the existing LeagueSphere deploy key are mirrored into Vaultwarden via a generalized version of the mechanism the `restic` role already uses.

**Tech Stack:** Ansible (this repo, `ansible/plays/`), Docker Compose (separate `leaguesphere` app repo), OpenSSH `authorized_keys` restrictions, systemd user timers, Bitwarden/Vaultwarden CLI (`bw`).

## Global Constraints

- Test on `servyy-test.lxd` before `lehel.xyz`; production deploy requires explicit user approval (repo policy, CLAUDE.md § "CRITICAL DEPLOYMENT RULES").
- No manual file edits on servers — everything through this repo's Ansible.
- `ls_dbeaver_access` and `vaultwarden` are new roles in a family (`ls_access`, `ls_setup`, `restic`) that this repo does **not** cover with Molecule — verified: none of `ls_access`, `ls_setup`, `ls_db_sync`, `ls_app`, `restic` have a `molecule/` directory. Follow that precedent; verification is the `servyy-test.lxd` deploy in Task 6, not a Molecule scenario.
- Never commit private key material or plaintext DB passwords to git. `~/.ssh/*` stays on the operator's machine (matches the existing `ls_ssh_key_*` convention).
- The `leaguesphere` app repo (`~/dev/leaguesphere`, `github.com/dachrisch/league-manager`) is a **separate git repository** with its own workflow — Task 1 touches it, everything else touches this repo.

## Stack Structure (`gh stack`, this repo only)

Tasks 2–5 touch this repo (`dachrisch/servyy-container`, `gh-stack` extension confirmed installed and authenticated) and are genuinely ordered: Task 3 calls `include_role: vaultwarden` (from Task 2), and Task 5 references the `ls_dbeaver_access` role (from Task 3). Task 4 doesn't strictly depend on 2/3, but it's the same feature/story, so it's kept in the same linear stack rather than split into a second one (`gh-stack` only supports strictly linear stacks — see "One stack, one story" in the gh-stack skill). Branches, bottom to top:

```
master (trunk)
 └── vaultwarden-shared-role        → Task 2
  └── ls-dbeaver-access-role        → Task 3
   └── ls-db-sync-nightly-timer     → Task 4
    └── ls-dbeaver-leaguesphere-wiring → Task 5
```

`gh stack init`/`gh stack add` replace plain `git checkout -b` for branch creation in each task below; `git add`/`git commit` stay exactly as written (the skill's recommended approach, for deliberate per-branch staging). Task 1 (the separate `leaguesphere` repo) is **not** part of this stack — `gh stack` operates within a single repository, and that repo keeps its own normal branch/PR flow.

Before starting Task 2, run once:
```bash
cd /home/cda/dev/infrastructure/container
git config rerere.enabled true
git config remote.pushDefault origin
gh stack init vaultwarden-shared-role
```
This creates and checks out `vaultwarden-shared-role` off `master`.

---

### Task 1: Stage DB stable loopback port (`leaguesphere` app repo)

**Files:**
- Modify: `~/dev/leaguesphere/deployed/docker-compose.staging.yaml` (the `mysql` service)

**Interfaces:**
- Produces: a host-loopback endpoint `127.0.0.1:33062` → stage `mysql` container's `3306`, additive to its existing `backend`-network reachability.

- [ ] **Step 1: Create a feature branch**

`~/dev/leaguesphere/CLAUDE.md` § "Git & Branching Protocol" requires this explicitly: "Create a feature branch; never commit directly to `master`." That repo's `master` currently has unrelated untracked files from other in-progress work — leave those alone, touch nothing but the one file below.

```bash
cd ~/dev/leaguesphere
git checkout -b feat/stage-db-loopback-port
```

- [ ] **Step 2: Add the port mapping**

In `~/dev/leaguesphere/deployed/docker-compose.staging.yaml`, the `mysql` service currently reads (lines 3–26 today):

```yaml
  mysql:
    image: mariadb:latest
    container_name: ${COMPOSE_PROJECT_NAME}.mysql
    restart: unless-stopped
    command: >
      --character-set-server=utf8mb4
      --collation-server=utf8mb4_unicode_ci
    volumes:
      - "./mysql-data:/var/lib/mysql"
      - "./mysql-init:/docker-entrypoint-initdb.d:ro"
    env_file: ls.env.staging
    networks:
      - backend
```

Add a `ports:` key right after `env_file: ls.env.staging`:

```yaml
    env_file: ls.env.staging
    ports:
      - "127.0.0.1:33062:3306"
    networks:
      - backend
```

- [ ] **Step 3: Validate compose syntax locally**

Run: `cd ~/dev/leaguesphere/deployed && docker compose -f docker-compose.staging.yaml config --quiet`
Expected: no output, exit code 0 (fails loudly on any YAML/compose schema error).

- [ ] **Step 4: Commit in the `leaguesphere` repo**

```bash
cd ~/dev/leaguesphere
git add deployed/docker-compose.staging.yaml
git commit -m "feat: publish stage mysql on loopback-only 127.0.0.1:33062

Stable endpoint for an SSH-tunneled DBeaver connection; not reachable
from the network (loopback bind), additive to existing internal
backend-network reachability."
```

Do **not** push yet — hold until Task 6 passes on `servyy-test.lxd`, since this repo's own deploy (next tasks) is what actually rolls the stage container.

---

### Task 2: Extract the Vaultwarden push mechanism into a shared role, and migrate `restic` onto it

**Files:**
- Create: `ansible/plays/roles/vaultwarden/defaults/main.yml`
- Create: `ansible/plays/roles/vaultwarden/tasks/unlock.yml`
- Create: `ansible/plays/roles/vaultwarden/tasks/push_items.yml`
- Delete: `ansible/plays/roles/restic/tasks/bw_unlock.yml` (moved into the new role)
- Modify (not delete): `ansible/plays/roles/restic/tasks/vaultwarden_push.yml` — becomes a thin `include_tasks` (not `include_role`) pointed at the shared role by path (see Step 4 — `include_role`/`import_role` don't work anywhere in a handler's execution chain, even transitively; only `include_tasks`/`import_tasks` do)
- Modify: `ansible/plays/roles/restic/tasks/seed_guard.yml:61-62`
- Modify: `ansible/plays/roles/restic/defaults/main.yml`

**Interfaces:**
- Consumes (caller must set before `include_role: {name: vaultwarden, tasks_from: push_items.yml}`):
  - `vaultwarden_items`: list of `{name: str, secret: str, notes: str}`
  - `vaultwarden_item_username`: str (login-item username field; e.g. `"ansible"`, `"restic"`)
  - `vw_master_password`: str (from the calling playbook's `vars_prompt`)
  - `vaultwarden_api.client_id` / `.client_secret` (from `vars/secrets.yml`, already exists)
- Produces: idempotent creation of Bitwarden Login-type items in Vaultwarden (`type: 1`, `login.username`/`login.password`, `notes`) — one per entry in `vaultwarden_items`, skipping any `name` that already exists.

This **does** consolidate `restic`'s existing usage onto the new role rather than leaving a parallel duplicate — `restic/tasks/bw_unlock.yml` is deleted outright; `vaultwarden_push.yml` is gutted down to a thin `include_tasks` (pointed at the shared role by path) rather than deleted, because `include_role`/`import_role` don't work anywhere in a handler's execution chain — not just when written directly in a handler, but at any depth reached from one — and `restic/handlers/main.yml` calls it via `include_tasks: vaultwarden_push.yml`; that filename and mechanism stay, only its *contents* change. `seed_guard.yml`'s call site (not a handler) uses `include_role` directly with no such restriction. The `vw_server` duplication (both `restic/defaults/main.yml` and the new role's defaults) is now required on both paths for independent reasons — see Step 4's file-level comments.

- [ ] **Step 1: Create the role's defaults**

`ansible/plays/roles/vaultwarden/defaults/main.yml`:

```yaml
---
# Shared Vaultwarden (self-hosted Bitwarden) push mechanism.
# Mirrors restic/tasks/{bw_unlock,vaultwarden_push}.yml but generalized for
# any caller with a list of secrets to mirror as Login items.
vw_server: "https://pass.lehel.xyz"
```

- [ ] **Step 2: Create the shared unlock task**

`ansible/plays/roles/vaultwarden/tasks/unlock.yml`:

```yaml
---
# Authenticate + unlock the `bw` (Bitwarden) CLI on the Ansible controller and
# expose the session token as the `bw_session` fact.
# Requires: vaultwarden_api.client_id/secret (vars/secrets.yml), vw_master_password
# (vars_prompt in the calling playbook), vw_server (this role's defaults).
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
      Vaultwarden operation was requested. Install it (e.g. `npm i -g @bitwarden/cli`).
  delegate_to: localhost
  run_once: true
  become: false
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
  become: false
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
  become: false
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
  no_log: true
```

- [ ] **Step 3: Create the generalized push task**

`ansible/plays/roles/vaultwarden/tasks/push_items.yml`:

```yaml
---
# Push a list of secrets into Vaultwarden as Login items.
# Runs on the Ansible CONTROLLER via the `bw` CLI (not the remote host).
# Idempotent: only creates missing Login items.
#
# Caller must set before including this file:
#   vaultwarden_items: list of {name, secret, notes}
#   vaultwarden_item_username: string

- name: Unlock the bw vault (shared)
  ansible.builtin.include_tasks: unlock.yml

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
  become: false

- name: Create missing items in Vaultwarden
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
          'login': {'username': vaultwarden_item_username | default('ansible'), 'password': item.secret, 'uris': []}}
         | to_json }}
  loop: "{{ vaultwarden_items }}"
  loop_control:
    label: "{{ item.name }}"
  when: item.name not in existing_item_names
  changed_when: true
  no_log: true

- name: Report which items were created vs already present
  ansible.builtin.debug:
    msg: >-
      {{ item.name }}:
      {{ 'already present (skipped)' if item.name in existing_item_names else 'created' }}
  delegate_to: localhost
  run_once: true
  become: false
  loop: "{{ vaultwarden_items }}"
  loop_control:
    label: "{{ item.name }}"

- name: Lock the vault again
  ansible.builtin.command:
    cmd: bw lock
  delegate_to: localhost
  run_once: true
  become: false
  changed_when: false
  failed_when: false
```

- [ ] **Step 4: Migrate `restic` onto the shared role**

Delete the one file fully superseded by the `vaultwarden` role:

```bash
git rm ansible/plays/roles/restic/tasks/bw_unlock.yml
```

**Do not delete or touch `restic/handlers/main.yml`.** It currently reads:

```yaml
---
# Fires only when init.yml actually writes/updates an /etc/restic/env.* file.
# Skips silently unless this is the production host AND a master password was
# entered at the vars_prompt (empty = user chose to skip the backup copy).
- name: Push restic passwords to Vaultwarden
  ansible.builtin.include_tasks: vaultwarden_push.yml
  when:
    - inventory_hostname == 'lehel.xyz'
    - (vw_master_password | default('')) | length > 0
```

Leave every line of this file exactly as-is. **Revision (the first version of this step was still wrong — caught in final whole-branch review, not by either task-scoped review):** `ansible.builtin.include_role` is documented as **not working inside a handler**, and — verified by direct reproduction against the `ansible-core` installed in this environment — that restriction follows the *entire* execution chain reached from a handler, not just literal top-level handler content. A wrapper task file that itself does `include_role`, reached via the handler's `include_tasks:`, still fails with `Using 'include_role' as a handler is not supported`, with the error's `Origin:` pointing at the wrapper file itself. `include_role`/`import_role` are unusable anywhere in a call chain that originates from a handler; only `include_tasks`/`import_tasks` work there, at any depth.

So instead of a wrapper that does `include_role`, **replace the contents of `ansible/plays/roles/restic/tasks/vaultwarden_push.yml`** (same filename, same `include_tasks` target the handler already calls) with a plain `include_tasks` pointed directly at the shared role's task file by path — no `include_role` anywhere in this chain:

```yaml
---
# restic/handlers/main.yml reaches this via include_tasks (handlers cannot
# use include_role/import_role anywhere in their execution chain, even
# transitively through an intermediate include_tasks — verified by direct
# reproduction, not just the "not written directly in a handler" case).
# So this includes the shared role's task file directly by path rather
# than via include_role. Its own further include_tasks: unlock.yml (inside
# push_items.yml) still resolves correctly, relative to push_items.yml's
# own directory once Ansible is executing it — that resolution doesn't
# depend on how push_items.yml itself was reached.
#
# Requires (unchanged from before the vaultwarden extraction):
# vaultwarden_api.client_id/secret (vars/secrets.yml), restic_password_*
# (vars/secrets.yml), vw_master_password (vars_prompt in restic.yml).
- name: Push restic passwords to Vaultwarden
  ansible.builtin.include_tasks: "{{ playbook_dir }}/roles/vaultwarden/tasks/push_items.yml"
  vars:
    vaultwarden_items: "{{ restic_vaultwarden_items }}"
    vaultwarden_item_username: "restic"
```

(This file goes from ~75 lines — the full unlock+push logic it had before — down to these ~20. That's expected: everything it used to do now lives in `vaultwarden/tasks/{unlock,push_items}.yml`, reached transitively through this file's `include_tasks`.)

One consequence of this revision: the `vw_server` duplication below (already adjudicated as intentional) changes from *defensive* to *strictly required*. Because this path now reaches the vaultwarden role via `include_tasks` (never `include_role`), the vaultwarden role's own `defaults/main.yml` is never loaded on this path at all — `restic`'s own copy of `vw_server` isn't just a hedge against load-order timing anymore, it's the only copy that exists on this path. The comment below reflects this.

`ansible/plays/roles/restic/tasks/seed_guard.yml:61-62` currently reads:

```yaml
    - name: Unlock the bw vault (shared)
      ansible.builtin.include_tasks: bw_unlock.yml
```

Change to:

```yaml
    - name: Unlock the bw vault (shared)
      ansible.builtin.include_role:
        name: vaultwarden
        tasks_from: unlock.yml
```

`ansible/plays/roles/restic/defaults/main.yml` currently reads (in full):

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

Replace it with (two changes: the `vw_server` comment, and `password:` → `secret:` in `restic_vaultwarden_items` to match the shared role's `push_items.yml` interface, which reads `item.secret` — this is the one real behavior-affecting edit in this step, not just a rename: without it, restic's push would silently create items with an **empty** password field):

```yaml
---
# Vaultwarden backup-copy target for the restic repository passwords.
# Also defined in vaultwarden/defaults/main.yml. Duplicated here on purpose,
# for two independent reasons:
#  1. seed_guard.yml's early fail message references {{ vw_server }} before
#     it dynamically include_role's the vaultwarden role for the *unlock*
#     path, and dynamic include_role defaults aren't guaranteed loaded that
#     early.
#  2. The *push* path (vaultwarden_push.yml) reaches the vaultwarden role via
#     plain include_tasks, not include_role (required — see that file's
#     comment) — which means the vaultwarden role's own defaults/main.yml is
#     never loaded on this path at all. This role's own copy isn't optional
#     here, it's the only one that exists on that path.
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

# Field is `secret` (not `password`) to match vaultwarden/tasks/push_items.yml's
# generic item shape {name, secret, notes}.
restic_vaultwarden_items:
  - name: "restic - home (lehel.xyz)"
    secret: "{{ restic_password_home }}"
    notes: "RESTIC_PASSWORD for /etc/restic/env.home (copy of Ansible seed vars/.restic_password_home)"
  - name: "restic - root (lehel.xyz)"
    secret: "{{ restic_password_root }}"
    notes: "RESTIC_PASSWORD for /etc/restic/env.root (copy of Ansible seed vars/.restic_password_root)"
  - name: "restic - ls_db (lehel.xyz)"
    secret: "{{ restic_password_ls_db }}"
    notes: "RESTIC_PASSWORD for /etc/restic/env.ls_db (copy of Ansible seed vars/.restic_password_ls_db)"
```

- [ ] **Step 5: Syntax-check and verify `restic`'s behavior is unaffected**

Run: `cd ansible && ansible-playbook servyy.yml --syntax-check && ansible-playbook plays/restic.yml --syntax-check` (note: `restic.yml` lives at `ansible/plays/restic.yml`, not `ansible/restic.yml` — there's no shell wrapper for it alone, unlike `servyy.yml`/`servyy-test.sh`)
Expected: both print their playbook name, exit code 0.

Run: `cd ansible && yamllint plays/roles/vaultwarden/ plays/roles/restic/`
Expected: no errors.

Run: `cd ansible && ansible-playbook plays/restic.yml -i testing --tags restic.init --check --diff 2>&1 | tail -40` against `servyy-test.lxd`, with all seed files present (the normal case). (`seed_guard.yml`'s tasks have no tags of their own — they're reached only via `main.yml`'s `include_tasks: {file: seed_guard.yml, apply: {tags: [restic, restic.init, restic.recreate]}}`, so `--tags restic.init` is the right filter to exercise them, matching the existing code comment at `restic/tasks/main.yml:8-11` explaining why `apply` is required there.)
Expected: the play reaches "Restic seed guard: 0 missing" and does **not** enter the `Recover missing restic seeds` block (since nothing is missing) — confirming the guard's early logic still runs without an undefined-`vw_server` or broken-include error. This is a check-mode dry run; full confirmation that a *triggered* recovery still works (missing-seed path, `bw_unlock` via the new role, `bw get password`) happens in Task 6, which already deploys to `servyy-test.lxd`.

- [ ] **Step 6: Commit**

```bash
cd /home/cda/dev/infrastructure/container
git add ansible/plays/roles/vaultwarden/ ansible/plays/roles/restic/
git commit -m "feat: extract Vaultwarden push mechanism into a shared role

Generalizes restic's bw_unlock/vaultwarden_push into vaultwarden/tasks/
{unlock,push_items}.yml, parameterized by an item list, for reuse by the
upcoming DBeaver-tunnel SSH key backup. seed_guard.yml is repointed at the
new role via include_role directly; vaultwarden_push.yml is gutted to a
thin include_role wrapper (handlers can't use include_role directly, so
the handler keeps calling it via its existing include_tasks unchanged).
restic_vaultwarden_items' password field is renamed to secret to match
the shared interface. vw_server stays duplicated in both roles' defaults
on purpose (see comment)."
```

---

### Task 3: `ls_dbeaver_access` role — dedicated, restricted SSH account

**Files:**
- Create: `ansible/plays/roles/ls_dbeaver_access/defaults/main.yml`
- Create: `ansible/plays/roles/ls_dbeaver_access/tasks/main.yml`

**Interfaces:**
- Consumes: `local_user` (existing, `vars/default.yml`), `inventory_hostname_short` (Ansible fact), `vw_master_password` (from the `leaguesphere.yml` vars_prompt added in Task 5), `ls.user`/`ls.ssh_key_filename` (existing, `vars/secret_leaguesphere.yaml` — used to locate the existing LeagueSphere deploy key for its Vaultwarden backup), `vaultwarden` role's `push_items.yml` (Task 2).
- Produces: Linux account `dbeaver_stage` on the target host; local file `~/.ssh/dbeaver_stage_key_{{ inventory_hostname_short }}` (+ `.pub`) on the controller; that key restricted in the account's `authorized_keys` to `permitopen="127.0.0.1:33062"` only.

- [ ] **Step 1: Create and check out the next stack branch**

```bash
cd /home/cda/dev/infrastructure/container
gh stack add ls-dbeaver-access-role
```
(Must be run from the top of the stack — i.e., right after Task 2's commit, still on `vaultwarden-shared-role`.)

- [ ] **Step 2: Create the role's defaults**

`ansible/plays/roles/ls_dbeaver_access/defaults/main.yml`:

```yaml
---
dbeaver_stage_user: dbeaver_stage
dbeaver_stage_ssh_key_filename: "dbeaver_stage_key_{{ inventory_hostname_short }}"
dbeaver_stage_local_port: "33062"
```

- [ ] **Step 3: Create the role's tasks**

`ansible/plays/roles/ls_dbeaver_access/tasks/main.yml`:

```yaml
---
- name: Create dedicated dbeaver_stage account (no shell, no extra groups)
  user:
    name: "{{ dbeaver_stage_user }}"
    state: present
    shell: /usr/sbin/nologin
    create_home: true
  tags:
    - ls.dbeaver

- name: Generate dedicated SSH keypair for the DBeaver stage tunnel
  openssh_keypair:
    path: "~/.ssh/{{ dbeaver_stage_ssh_key_filename }}"
    type: rsa
    size: 4096
    state: present
    force: no
  delegate_to: localhost
  become_user: "{{ local_user }}"
  tags:
    - ls.dbeaver

- name: Restrict the DBeaver tunnel key to stage-only port forwarding
  authorized_key:
    user: "{{ dbeaver_stage_user }}"
    state: present
    key: "{{ lookup('file', '~/.ssh/' + dbeaver_stage_ssh_key_filename + '.pub') }}"
    key_options: >-
      command="/bin/false",no-pty,no-agent-forwarding,no-X11-forwarding,permitopen="127.0.0.1:{{ dbeaver_stage_local_port }}"
  tags:
    - ls.dbeaver

- name: Push operator SSH keys to Vaultwarden (dbeaver tunnel key + leaguesphere deploy key)
  include_role:
    name: vaultwarden
    tasks_from: push_items.yml
    apply:
      tags:
        - ls.dbeaver
  vars:
    vaultwarden_item_username: "ansible"
    vaultwarden_items:
      - name: "dbeaver stage tunnel key ({{ inventory_hostname_short }})"
        secret: "{{ lookup('file', '~/.ssh/' + dbeaver_stage_ssh_key_filename) }}"
        notes: >-
          Private key for the dbeaver_stage account on {{ inventory_hostname }}.
          authorized_keys restricts it to permitopen=127.0.0.1:{{ dbeaver_stage_local_port }}
          (LeagueSphere stage DB only) and command="/bin/false" (no shell access).
      - name: "leaguesphere deploy key ({{ inventory_hostname_short }})"
        secret: "{{ lookup('file', '~/.ssh/' + ls.ssh_key_filename) }}"
        notes: >-
          Private key for the jailed leaguesphere deploy account on {{ inventory_hostname }}.
          Used by ls_access/jail_ssh.yaml for app deployment (SSH chroot jail;
          AllowTcpForwarding disabled for this account's group).
  when: vw_master_password | default('') | length > 0
  tags:
    - ls.dbeaver
```

**On the `apply: tags:` block:** `include_role` is a *dynamic* include — per the existing, already-solved instance of this exact problem at `restic/tasks/main.yml:8-11`, tags placed directly on a dynamic include only gate whether the include itself runs; they do **not** propagate into the tasks it pulls in (here, `vaultwarden/tasks/push_items.yml` and, transitively, its own nested `include_tasks: unlock.yml`) unless `apply` is used. Without it, running this role under a selective `--tags ls.dbeaver` deploy (exactly what Task 6/7 do) would silently no-op the Vaultwarden push — the include step would run, but every task inside it would be skipped as untagged. `restic`'s existing handler-based path doesn't need this (`notify`-triggered handlers aren't gated by `--tags` selection the same way), which is why it wasn't already a pattern to copy from there — but `seed_guard.yml`'s modification in Task 2 Step 4 is covered already, since it inherits its tags from `main.yml`'s pre-existing `apply` on the include that reaches it.

**Note on `ls.ssh_key_filename`:** this already resolves to `ls_ssh_key_{{ inventory_hostname_short }}` via `vars/secret_leaguesphere.yaml` (loaded by `leaguesphere.yml`'s `vars_files`), so no new variable is needed to locate the existing deploy key.

- [ ] **Step 4: Syntax-check**

Run: `cd ansible && ansible-playbook servyy.yml --syntax-check`
Expected: exit code 0 (role isn't wired into a playbook yet — this just confirms the YAML parses; full wiring verified in Task 5).

Run: `cd ansible && yamllint plays/roles/ls_dbeaver_access/`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add ansible/plays/roles/ls_dbeaver_access/
git commit -m "feat: add ls_dbeaver_access role for restricted stage DB tunnel

Dedicated, unprivileged Linux account whose sole SSH key is restricted via
authorized_keys permitopen to the stage DB's loopback port only, plus
command=/bin/false to block shell access. Both this key and the existing
leaguesphere deploy key get backed up to Vaultwarden."
```

---

### Task 4: Nightly prod → stage sync timer (`ls_db_sync` role)

**Files:**
- Create: `ansible/plays/roles/ls_db_sync/templates/ls_db_sync.sh.j2`
- Create: `ansible/plays/roles/ls_db_sync/tasks/timer.yml`
- Modify: `ansible/plays/roles/ls_db_sync/tasks/main.yml` (append one import)

**Interfaces:**
- Consumes: `remote_user_home`/`remote_user_systemd` (existing, `vars/default.yml`), `create_user` (existing, `vars/secrets.yml`), `ls_db_sync_local_container` (existing role default, `leaguesphere.db`), `restic` role's `oneshot_include.yml` (existing, reused as-is — takes a `service: {name, description, schedule, command}` var and deploys a systemd user timer).
- Produces: `~/.backup-scripts/ls-db-sync-nightly.sh` and a `ls-db-sync-nightly.timer`/`.service` systemd user unit pair on the target host, firing daily at 02:00 UTC.

Not implemented as a literal `ansible-playbook` invocation from cron — this repo has no precedent for a target host running Ansible against itself, and none of the existing nightly jobs (`mariadb-backup-ls`, `restic-backup-*`) work that way. Instead this mirrors the *shell command sequence* `ls_db_sync/tasks/main.yml` already runs (dump prod via `docker exec`, wait for stage health, drop/recreate/import, restart stage app), as a standalone script deployed the same way the existing backup scripts are.

- [ ] **Step 1: Create and check out the next stack branch**

```bash
cd /home/cda/dev/infrastructure/container
gh stack add ls-db-sync-nightly-timer
```
(Run from the top of the stack — right after Task 3's commit, still on `ls-dbeaver-access-role`.)

- [ ] **Step 2: Create the sync script template**

`ansible/plays/roles/ls_db_sync/templates/ls_db_sync.sh.j2`:

```bash
#!/bin/zsh
# Nightly prod -> stage DB sync (mirrors ls_db_sync role's 'local' source path)
set -euo pipefail
source "/home/{{ create_user }}/.zprezto/custom/functions/logdy" 2>/dev/null || true

PROD_CONTAINER="{{ prod_container }}"
PROD_DB="{{ prod_db_name }}"
PROD_ROOT_PASSWORD="{{ prod_root_password }}"
STAGE_CONTAINER="{{ stage_container }}"
STAGE_DB="{{ stage_db_name }}"
STAGE_ROOT_PASSWORD="{{ stage_root_password }}"
STAGE_APP_CONTAINER="{{ stage_app_container }}"

DUMP_FILE="/tmp/leaguesphere_prod_$(date +%s).sql"
cleanup() { rm -f "$DUMP_FILE"; }
trap cleanup EXIT

IGNORE=$(docker exec "$PROD_CONTAINER" mariadb -u root -p"$PROD_ROOT_PASSWORD" -N \
  -e "SELECT CONCAT('--ignore-table=$PROD_DB.', table_name) FROM information_schema.views WHERE table_schema='$PROD_DB'")
docker exec "$PROD_CONTAINER" mariadb-dump -u root -p"$PROD_ROOT_PASSWORD" \
  --single-transaction --quick --lock-tables=false $=IGNORE "$PROD_DB" > "$DUMP_FILE"

STATUS=""
for i in $(seq 1 30); do
  STATUS=$(docker inspect "$STAGE_CONTAINER" --format={% raw %}'{{.State.Health.Status}}'{% endraw %})
  [ "$STATUS" = "healthy" ] && break
  sleep 2
done

if [ "$STATUS" != "healthy" ]; then
  echo "ERROR: $STAGE_CONTAINER did not become healthy in time" >&2
  exit 1
fi

docker exec "$STAGE_CONTAINER" mariadb -u root -p"$STAGE_ROOT_PASSWORD" \
  -e "DROP DATABASE IF EXISTS $STAGE_DB; CREATE DATABASE $STAGE_DB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

docker cp "$DUMP_FILE" "$STAGE_CONTAINER:/tmp/dump.sql"
docker exec -i "$STAGE_CONTAINER" mariadb -u root -p"$STAGE_ROOT_PASSWORD" "$STAGE_DB" < "$DUMP_FILE"
docker exec "$STAGE_CONTAINER" rm -f /tmp/dump.sql

docker restart "$STAGE_APP_CONTAINER"

echo "Nightly stage DB sync completed: $PROD_DB -> $STAGE_DB"
```

Note `$=IGNORE` (not `$IGNORE`): this is zsh's explicit word-splitting flag. zsh does not word-split unquoted variables by default (unlike the `shell:`-module's `/bin/sh` that `ls_db_sync/tasks/main.yml` runs under) — `$=IGNORE` is required so each `--ignore-table=...` entry becomes its own argument to `mariadb-dump`, and correctly yields zero arguments when there are no views to ignore.

- [ ] **Step 3: Create the timer deployment task**

`ansible/plays/roles/ls_db_sync/tasks/timer.yml`:

```yaml
---
- name: Load production variables (for nightly sync script)
  include_vars:
    file: "{{ playbook_dir }}/roles/ls_app/vars/secret_main.yaml"
    name: prod_app
  tags:
    - ls.db.sync.timer

- name: Load staging variables (for nightly sync script)
  include_vars:
    file: "{{ playbook_dir }}/roles/ls_app/vars/secret_stage.yaml"
    name: stage_app
  tags:
    - ls.db.sync.timer

- name: Deploy nightly stage DB sync script
  template:
    src: ls_db_sync.sh.j2
    dest: "{{ remote_user_home }}/.backup-scripts/ls-db-sync-nightly.sh"
    mode: '0750'
  become_user: "{{ create_user }}"
  vars:
    prod_container: "{{ ls_db_sync_local_container }}"
    prod_db_name: "{{ prod_app.app.db_name }}"
    prod_root_password: "{{ prod_app.app.db_root_password }}"
    stage_container: "{{ stage_app.app.name }}.mysql"
    stage_db_name: "{{ stage_app.app.db_name }}"
    stage_root_password: "{{ stage_app.app.db_root_password }}"
    stage_app_container: "{{ (stage_app.app.name ~ '.staging-app') if stage_app.app.name == 'leaguesphere_stage' else (stage_app.app.name ~ '.app') }}"
  no_log: true
  tags:
    - ls.db.sync.timer

- name: Deploy nightly timer for stage DB sync
  import_tasks: "{{ playbook_dir }}/roles/restic/tasks/oneshot_include.yml"
  become_user: "{{ create_user }}"
  vars:
    service:
      name: ls-db-sync-nightly
      description: 'Nightly LeagueSphere prod -> stage DB sync'
      schedule: '*-*-* 02:00:00'
      command: "{{ remote_user_home }}/.backup-scripts/ls-db-sync-nightly.sh"
  tags:
    - ls.db.sync.timer
```

`become_user: "{{ create_user }}"` is explicit here (not inherited from the play) because `leaguesphere.yml` (where `ls_db_sync` is invoked from) runs as root by default — the systemd user-timer and its backing script must be owned by `create_user` to be manageable via `systemctl --user`, matching how the existing `mariadb-backup-ls`/`restic-backup-ls-db` timers are owned (those run under the separate `restic.yml` playbook, which already sets `become_user: create_user` at the play level).

- [ ] **Step 4: Wire the timer into the role's existing task list**

In `ansible/plays/roles/ls_db_sync/tasks/main.yml`, append at the very end (after the existing `Cleanup dumps` task):

```yaml

- import_tasks: timer.yml
  tags:
    - ls.db.sync.timer
```

- [ ] **Step 5: Syntax-check and tag-listing verification**

Run: `cd ansible && ansible-playbook servyy.yml --syntax-check`
Expected: exit code 0.

Run: `cd ansible && ansible-playbook servyy.yml --list-tasks --tags ls.db.sync.timer 2>&1 | grep -A5 "ls_db_sync"`
Expected: shows `Load production variables (for nightly sync script)`, `Load staging variables (for nightly sync script)`, `Deploy nightly stage DB sync script`, and the tasks inside `oneshot_include.yml` (`Create the systemd directory...`, `Create ls-db-sync-nightly service`, `Create timer for ls-db-sync-nightly`, `Start timer for ls-db-sync-nightly`) — and does **not** show the on-demand sync tasks (`Export prod DB...`, `Drop and recreate staging database`, etc.), confirming the tag correctly isolates the timer-only path.

- [ ] **Step 6: Commit**

```bash
git add ansible/plays/roles/ls_db_sync/
git commit -m "feat: add nightly systemd timer for prod -> stage DB sync

Deploys a standalone script mirroring the existing local-source sync logic,
scheduled at 02:00 UTC via the same oneshot systemd-timer pattern already
used for the mariadb-backup-ls/restic-backup-ls-db timers. Reachable
independently via the ls.db.sync.timer tag."
```

---

### Task 5: Wire `ls_dbeaver_access` and the Vaultwarden prompt into `leaguesphere.yml`

**Files:**
- Modify: `ansible/plays/leaguesphere.yml`

**Interfaces:**
- Consumes: `ls_dbeaver_access` role (Task 3).
- Produces: running `./servyy.sh --tags ls.dbeaver --limit <host>` (or `./servyy-test.sh --tags ls.dbeaver`) deploys the dedicated tunnel account end-to-end, including the Vaultwarden push when a master password is supplied.

- [ ] **Step 1: Create and check out the next stack branch**

```bash
cd /home/cda/dev/infrastructure/container
gh stack add ls-dbeaver-leaguesphere-wiring
```
(Run from the top of the stack — right after Task 4's commit, still on `ls-db-sync-nightly-timer`.)

- [ ] **Step 2: Add the `vw_master_password` prompt**

In `ansible/plays/leaguesphere.yml`, insert a `vars_prompt` block after `vars_files` and before `roles:` (currently lines 6–12):

```yaml
  vars_files:
    - vars/secret_leaguesphere.yaml
    - vars/ssh_jail.yaml
    - vars/secrets.yml
    - vars/default.yml
  vars_prompt:
    - name: vw_master_password
      prompt: "Vaultwarden master password (enter to skip SSH-key backup copy)"
      private: true
      default: ""
      confirm: false
  roles:
```

- [ ] **Step 3: Add the `ls_dbeaver_access` role invocation**

Immediately after the existing `- ls_access` line (currently line 26), add:

```yaml
    - ls_access

    - role: ls_dbeaver_access
      tags:
        - ls.dbeaver
```

- [ ] **Step 4: Syntax-check and tag-listing verification**

Run: `cd ansible && ansible-playbook servyy.yml --syntax-check`
Expected: exit code 0.

Run: `cd ansible && ansible-playbook servyy.yml --list-tasks --tags ls.dbeaver`
Expected: lists the four `ls_dbeaver_access` tasks (`Create dedicated dbeaver_stage account...`, `Generate dedicated SSH keypair...`, `Restrict the DBeaver tunnel key...`, `Push operator SSH keys to Vaultwarden...`) and nothing from `ls_app`/`ls_demo`/`ls_db_sync`. Note: `--list-tasks` shows the `include_role` line itself but does not reliably expand what's *inside* a dynamic include (that's resolved at runtime, not at this static-preview stage) — so this confirms the four tasks are reached under this tag, but not yet that the `apply` fix from Task 3 correctly threads down into `vaultwarden`'s nested tasks. That's confirmed for real in Task 6 Step 2 (deploying with exactly this tag) + Step 6 (the Vaultwarden items existing afterward) — the only way to prove a dynamic include's *contents* actually ran.

- [ ] **Step 5: Commit**

```bash
git add ansible/plays/leaguesphere.yml
git commit -m "feat: wire ls_dbeaver_access into the leaguesphere playbook

Adds the vw_master_password prompt (mirrors restic.yml's UX — press enter
to skip) and the ls.dbeaver-tagged role invocation."
```

- [ ] **Step 6: Submit the stack (draft PRs)**

```bash
gh stack submit --auto
```
Expected (stderr): `Created PR #N for vaultwarden-shared-role`, `Created PR #N for ls-dbeaver-access-role`, `Created PR #N for ls-db-sync-nightly-timer`, `Created PR #N for ls-dbeaver-leaguesphere-wiring`, each chained to the one below it, plus a stack-linking confirmation. PRs are created as **drafts** (no `--open`) — deliberately, since Task 6's validation hasn't run yet.

If this exits with code 9 ("Stacked PRs unavailable"), stacked PRs aren't enabled on `dachrisch/servyy-container` yet — stop and tell the user, since enabling it is a repo-settings change outside this plan's scope, not something to work around silently.

---

### Task 6: Validate end-to-end on `servyy-test.lxd`

**Files:** none (verification only).

**Interfaces:** none — this task exercises Tasks 1–5 together.

Run this task from the **top of the stack** (`ls-dbeaver-leaguesphere-wiring`, already checked out at the end of Task 5 — confirm with `gh stack view --json | jq -r '.currentBranch'`). Testing the top layer exercises everything below it too, since each branch's diff is cumulative on top of its base.

- [ ] **Step 1: Ensure the test box has the stage stack with the new port**

The `leaguesphere` repo's Task 1 commit must be reachable from `servyy-test.lxd`'s checkout (push the `leaguesphere` branch used for testing, or point the test deploy at your local branch per that repo's own workflow — this is that repo's deploy mechanism, not this one).

Run: `cd ansible && ./servyy-test.sh --tags ls.app.stage`
Expected: `PLAY RECAP` shows `failed=0 unreachable=0`; deploys/refreshes the stage stack including the new `ports: ["127.0.0.1:33062:3306"]` mapping.

- [ ] **Step 2: Deploy the new tunnel account and nightly timer**

Run: `cd ansible && ./servyy-test.sh --tags ls.dbeaver`
Expected: `PLAY RECAP` shows `failed=0 unreachable=0`. When prompted for the Vaultwarden master password, either supply it (to also verify the push) or press enter to skip.

Run: `cd ansible && ./servyy-test.sh --tags ls.db.sync.timer`
Expected: `PLAY RECAP` shows `failed=0 unreachable=0`.

- [ ] **Step 3: Verify the loopback port is listening and reachable only locally**

Run: `ssh servyy-test.lxd "ss -tlnp | grep 33062"`
Expected: a line showing `127.0.0.1:33062` LISTEN — and specifically **not** `0.0.0.0:33062` or `*:33062`.

- [ ] **Step 4: Verify the tunnel key can reach stage and nothing else**

From your workstation (using the newly generated `~/.ssh/dbeaver_stage_key_servyy-test`):

Run: `ssh -i ~/.ssh/dbeaver_stage_key_servyy-test -L 3307:127.0.0.1:33062 dbeaver_stage@servyy-test.lxd -N &`
Expected: the tunnel opens without error (backgrounds silently).

Run: `mariadb -h 127.0.0.1 -P 3307 -u leaguesphere_stage -p'<stage db password from secret_stage.yaml>' leaguesphere_stage -e "SELECT 1;"`
Expected: prints `1` — proves the tunnel + DB connection works end-to-end.

Run: `kill %1` (stop the backgrounded tunnel from the previous step), then attempt a forward to a disallowed destination:

Run: `ssh -i ~/.ssh/dbeaver_stage_key_servyy-test -L 3308:127.0.0.1:3306 dbeaver_stage@servyy-test.lxd -N`
Expected: SSH reports the forward request was rejected (e.g. `channel 2: open failed: administratively prohibited`) — proves `permitopen` blocks any destination other than `127.0.0.1:33062`.

Run: `ssh -i ~/.ssh/dbeaver_stage_key_servyy-test dbeaver_stage@servyy-test.lxd`
Expected: connection is accepted but no interactive shell is produced (the forced `command="/bin/false"` exits immediately) — proves the account can't be used for anything beyond the one permitted forward.

- [ ] **Step 5: Verify the nightly sync script runs cleanly on demand**

Run: `ssh servyy-test.lxd "systemctl --user start ls-db-sync-nightly.service && sleep 5 && systemctl --user status ls-db-sync-nightly.service --no-pager"`
Expected: `Active: inactive (dead)` with the last run showing success (exit code 0); `journalctl --user -u ls-db-sync-nightly -n 20 --no-pager` shows `Nightly stage DB sync completed: ... -> ...`.

- [ ] **Step 6: Verify Vaultwarden items (only if a master password was supplied in Step 2)**

Run: `bw list items --search "servyy-test" | jq -r '.[].name'`
Expected: includes `dbeaver stage tunnel key (servyy-test)`, `leaguesphere deploy key (servyy-test)`, and — proving Task 2's `restic` migration wasn't broken by this stack — the existing `restic - home (servyy-test.lxd)` / `restic - root (servyy-test.lxd)` / `restic - ls_db (servyy-test.lxd)` items (already present from prior runs, or created now if this is the first run with a master password supplied).

- [ ] **Step 7: Verify `restic`'s init path still runs cleanly through the migrated code**

Run: `cd ansible && ./servyy-test.sh --tags restic.init`
Expected: `PLAY RECAP` shows `failed=0 unreachable=0` — exercises `seed_guard.yml`'s now-`include_role`-based unlock path (Task 2 Step 4) for real, on a host where no seeds are actually missing, confirming the swap from `include_tasks: bw_unlock.yml` didn't break the guard's normal (non-recovery) path.

If any step fails, fix the root cause in the relevant task's files (do not patch servyy-test by hand — see repo policy) and re-run from Step 2.

- [ ] **Step 8: Mark the stack ready for review**

```bash
gh stack submit --auto --open
```
Expected (stderr): `PR #N for <branch> is up to date` for all four, now flipped from draft to ready-for-review. Share the PR chain with the user for review before Task 7's merge.

---

### Task 7: Deploy to production (after explicit user approval)

**Files:** none (deployment only).

**Interfaces:** none.

- [ ] **Step 1: Push the `leaguesphere` app repo change**

```bash
cd ~/dev/leaguesphere
git push origin feat/stage-db-loopback-port
gh pr create --repo dachrisch/leaguesphere --base master \
  --title "feat: publish stage mysql on loopback-only 127.0.0.1:33062" \
  --body "Stable endpoint for an SSH-tunneled DBeaver connection to stage; not reachable from the network."
```
(Follow that repo's own PR/merge process before this is deployable to `lehel.xyz`.)

- [ ] **Step 2: Get PR review, then merge the stack**

The four PRs were opened ready-for-review at the end of Task 6. Wait for review/approval on each (or on the stack as a whole, per however this repo's reviewers work), then merge the entire stack atomically, bottom to top:

```bash
cd /home/cda/dev/infrastructure/container
gh stack merge --yes
```
Expected (stderr): each PR reported merged in order (`vaultwarden-shared-role` → `ls-dbeaver-access-role` → `ls-db-sync-nightly-timer` → `ls-dbeaver-leaguesphere-wiring`). This repo has no branch-protection/merge-method preference recorded in this plan — if `gh stack merge` prompts for a method the first time, confirm with the user which of `--squash`/`--rebase`/`--merge` matches how this repo normally merges (check recent merged PRs with `gh pr list --state merged --limit 5` if unsure) rather than guessing. The merge is all-or-nothing: if any PR can't merge (e.g. a failed required check), none do, and `gh stack merge` reports why — fix that PR and retry rather than merging around it.

- [ ] **Step 3: Sync local `master`**

```bash
git checkout master
git pull origin master
```
Expected: fast-forwards to the merged commits from all four PRs; `git log --oneline -6` shows them. This repo's own policy (CLAUDE.md: "branch on prod must always be master after rollout") is why production deploys from `master`, not from the stack's branches directly, even though `./servyy.sh` would technically work from any local checkout.

- [ ] **Step 4: Ask for explicit production-deploy approval**

Show the user exactly which tags will run and confirm before proceeding — per this repo's CRITICAL DEPLOYMENT RULES, production deployment is never automatic.

- [ ] **Step 5: Deploy to `lehel.xyz`**

Run: `cd ansible && ./servyy.sh --tags ls.app.stage --limit lehel.xyz` (rolls the stage stack with the new port mapping)
Run: `cd ansible && ./servyy.sh --tags ls.dbeaver --limit lehel.xyz` (creates the account, supply the Vaultwarden master password when prompted)
Run: `cd ansible && ./servyy.sh --tags ls.db.sync.timer --limit lehel.xyz`

Expected: each `PLAY RECAP` shows `failed=0 unreachable=0`.

- [ ] **Step 6: Repeat the Task 6 verification steps against `lehel.xyz`**

Same commands as Task 6 Steps 3–7, with `servyy-test.lxd` replaced by `lehel.xyz` and the key filename `dbeaver_stage_key_lehel`.

- [ ] **Step 7: Configure the operator's DBeaver connection**

| Tab | Field | Value |
|---|---|---|
| SSH | Host | `lehel.xyz` |
| SSH | User | `dbeaver_stage` |
| SSH | Auth | `~/.ssh/dbeaver_stage_key_lehel` |
| Main | Host | `127.0.0.1` |
| Main | Port | `33062` |
| Main | Database / User | `leaguesphere_stage` / `leaguesphere_stage` (password from `ansible/plays/roles/ls_app/vars/secret_stage.yaml`) |

- [ ] **Step 8: Write the history log**

Create `history/2026-08-07_leaguesphere-stage-dbeaver-access.md` documenting: problem, solution, files changed, deployment results, verification commands run, and the Vaultwarden item names — per this repo's CLAUDE.md documentation convention.
