# Inventory Host Rename: lehel.xyz → servy.lehel.xyz / code.lehel.xyz → codey.lehel.xyz

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rename the two Ansible inventory hosts from their public-domain names (`lehel.xyz`, `code.lehel.xyz`) to their physical server names (`servy.lehel.xyz`, `codey.lehel.xyz`), and add a `domain: lehel.xyz` host var so public services stay `*.lehel.xyz`. This makes the two-server topology explicit in the inventory (servy + codey) while keeping the public `lehel.xyz` domain for services. `code` remains a *service* name (exposed at `code.lehel.xyz`).

**Architecture:** The `docker_service` role already computes `service_host = "{service}.{domain}"` with `domain` defaulting to `inventory_hostname`. We (1) rename the inventory host keys, (2) set `domain: lehel.xyz` on both hosts so `service_host` is unchanged publicly, and (3) sweep every place that still hardcodes `inventory_hostname` for public/URL/guard purposes to use `domain` instead. Restic repo paths and Vaultwarden key names will naturally adopt the new hostnames (no migration — duplicates are acceptable per user decision). Internal Traefik `*_local_qualified` routes are switched to `*.lehel.xyz` via `domain`.

**Tech Stack:** Ansible (inventory YAML, roles `docker_service`, `user`, `opencode`, `restic`, `ls_*`), Jinja2 templates, Molecule (docker_service scenario), Porkbun DNS (already has A/AAAA for `servy.lehel.xyz` + `codey.lehel.xyz`).

**Constraints (from user):**
- Full rename: restic backup path moves to new hostname, Vaultwarden keys are recreated (duplicates OK — no migration).
- Internal routes: stay `*.lehel.xyz` (set `LOCAL_HOSTNAME`/`SERVICE_ROOT_HOST` to `domain`).
- Docs: update operational docs only (CLAUDE.md, AGENTS.md, GEMINI.md, conductor/workflow.md, active skills). Leave history/plans as archival.

---

## Pre-flight (read-only, do before any deploy)

- DNS already has A/AAAA for `servy.lehel.xyz` (49.13.6.173) and `codey.lehel.xyz` (217.217.227.124), plus `*.lehel.xyz` CNAME → servy and `lehel.xyz` ALIAS → servy. So SSH to the new inventory names works.
- No root-domain service exists (`me` is `me.lehel.xyz`); renaming won't orphan a root service.
- `servyy.sh` / `servyy-test.sh` take `--limit` from CLI — no script edits needed.
- CI, monitoring scrape targets, test inventory (`servyy-test.lxd`) are unaffected.

---

### Task 1: Rename inventory hosts + add `domain`

**Files:**
- Modify: `ansible/production:3` and `:28`

**Step 1:** Rename the master host key and add `domain` + `service_root_host`:

```yaml
    servy.lehel.xyz:
        domain: lehel.xyz
        with_docker: true
        with_containers: true
        has_10g_volume: false
        create_swap: true
        services_enabled:
          ... (unchanged) ...
```

**Step 2:** Rename the slave host key and add `domain` (keep `ansible_user: root`, `dns_short_name: "code"`, `dns_expose: true`):

```yaml
    codey.lehel.xyz:
        domain: lehel.xyz
        ansible_user: root
        with_docker: true
        with_containers: true
        has_10g_volume: false
        create_swap: true
        services_enabled:
          traefik: true
          opencode:
            enabled: true
            dns_short_name: "code"     # Public-facing service name (code.lehel.xyz)
            dns_expose: true
          opencode-authgate: true
```

**Step 3:** Syntax check
Run: `cd ansible && ansible-playbook servyy.yml --syntax-check -i production`
Expected: PASS (no errors).

**Step 4:** Commit
```bash
git add ansible/production
git commit -m "refactor: rename inventory hosts to physical server names (servy/codey) + add domain var"
```

---

### Task 2: Make `SERVICE_ROOT_HOST` and `LOCAL_HOSTNAME` domain-aware

**Files:**
- Modify: `ansible/plays/roles/docker_service/templates/docker.env.j2:3-4`
- Modify: `ansible/plays/roles/docker_service/templates/thore/docker.env.j2:3`
- Modify: `ansible/plays/roles/docker_service/templates/finance/docker.env.j2:4`

**Step 1:** In `docker.env.j2` change:
```jinja
SERVICE_ROOT_HOST={{ service_root_host | default(domain) }}
LOCAL_HOSTNAME={{ domain }}
```
(formerly `default(inventory_hostname)` and `ansible_facts['hostname']`).

**Step 2:** In `thore/docker.env.j2` change `LOCAL_HOSTNAME={{ inventory_hostname }}` → `LOCAL_HOSTNAME={{ domain }}`.

**Step 3:** In `finance/docker.env.j2` change `LOCAL_HOSTNAME={{ ansible_facts['hostname'] }}` → `LOCAL_HOSTNAME={{ domain }}`.

**Step 4:** Commit
```bash
git add ansible/plays/roles/docker_service/templates/
git commit -m "fix(docker_service): use domain for SERVICE_ROOT_HOST and LOCAL_HOSTNAME"
```

---

### Task 3: Fix `service_host` overrides in `user.yml`

**Files:**
- Modify: `ansible/plays/user.yml:207,219,231`

**Step 1:** Replace `inventory_hostname` with `domain` so these stay `*.lehel.xyz`:
```yaml
        service_host: "search.{{ domain }}"      # was: search.{{ inventory_hostname }}
        ...
        service_host: "thore.{{ domain }}"       # was: thore.{{ inventory_hostname }}
        ...
        service_host: "jobs.{{ domain }}"        # was: jobs.{{ inventory_hostname }}
```

**Step 2:** Commit
```bash
git add ansible/plays/user.yml
git commit -m "fix(user): use domain (not inventory_hostname) for searxng/thore/job-search service_host"
```

---

### Task 4: Fix Pi-hole DNS entries + ping test (`dns.yml`, `host_ping.yml`)

**Files:**
- Modify: `ansible/plays/roles/user/tasks/dns.yml:9-24`
- Modify: `ansible/plays/roles/user/tasks/host_ping.yml:8`

**Step 1:** In `dns.yml` replace every `{{inventory_hostname}}` with `{{domain}}` (the per-service blockinfile marker, both `{{item.dir}}.` lines, the `pihole.dns` entry, and the server block).
**Step 2:** In `host_ping.yml` change `product([inventory_hostname])` → `product([domain])`.

**Step 3:** Commit
```bash
git add ansible/plays/roles/user/tasks/dns.yml ansible/plays/roles/user/tasks/host_ping.yml
git commit -m "fix(user): register Pi-hole + ping entries under domain (not inventory hostname)"
```

---

### Task 5: Fix LeagueSphere service hosts (`ls_app`, `ls_demo`)

**Files:**
- Modify: `ansible/plays/roles/ls_app/tasks/env.yaml:7`
- Modify: `ansible/plays/roles/ls_demo/templates/docker.env.j2:2`

**Step 1:** `ls_app/tasks/env.yaml` → `host: "{{ 'stage.leaguesphere' if app.name == 'leaguesphere_stage' else app.name }}.{{ domain }}"`
**Step 2:** `ls_demo/templates/docker.env.j2` → `SERVICE_HOST={{ 'demo.leaguesphere' }}.{{ domain }}`
(Note: `ls_demo` has its own `domain: demo.leaguesphere.app` role var; if that should win, switch to `{{ demo_config.domain | default(domain) }}`. Flag for review during implementation.)

**Step 3:** Commit
```bash
git add ansible/plays/roles/ls_app/tasks/env.yaml ansible/plays/roles/ls_demo/templates/docker.env.j2
git commit -m "fix(ls): build LeagueSphere service hosts from domain var"
```

---

### Task 6: Fix opencode-authgate ForwardAuth URL

**Files:**
- Modify: `ansible/plays/opencode_authgate.yml:39`

**Step 1:** Change `https://opencode.{{ inventory_hostname }}/api/session/*` → `https://opencode.{{ domain }}/api/session/*`.
(Also the description lines at `:38/:48` referencing `{{ inventory_hostname }}` are cosmetic; update for consistency.)

**Step 2:** Commit
```bash
git add ansible/plays/opencode_authgate.yml
git commit -m "fix(opencode-authgate): use domain for public ForwardAuth URL"
```

---

### Task 7: Fix host guards that hardcode `'lehel.xyz'`

These silently skip on the renamed host — must be updated or Vaultwarden pushes / restic copy break.

**Files:**
- Modify: `ansible/plays/roles/opencode/handlers/main.yml:12`
- Modify: `ansible/plays/roles/opencode/tasks/vaultwarden_push.yml:13`
- Modify: `ansible/plays/roles/restic/handlers/main.yml:8`
- Modify: `ansible/plays/roles/ls_dbeaver_access/tasks/main.yml:68`

**Step 1:** Change `inventory_hostname == 'lehel.xyz'` → `inventory_hostname == 'servy.lehel.xyz'` (3 files).
**Step 2:** Change the dbeaver allowlist to include the slave:
```jinja
  when: inventory_hostname in ['servy.lehel.xyz', 'codey.lehel.xyz', 'servyy-test.lxd']
```

**Step 3:** Commit
```bash
git add ansible/plays/roles/opencode/handlers/main.yml ansible/plays/roles/opencode/tasks/vaultwarden_push.yml ansible/plays/roles/restic/handlers/main.yml ansible/plays/roles/ls_dbeaver_access/tasks/main.yml
git commit -m "fix: update host guards from lehel.xyz to servy.lehel.xyz (+codey in dbeaver allowlist)"
```

---

### Task 8: TDD — assert domain override in docker_service molecule

**Files:**
- Modify: `ansible/plays/roles/docker_service/molecule/default/converge.yml`
- Modify: `ansible/plays/roles/docker_service/molecule/default/verify.yml`

**Step 1:** Write failing assertion first — in `converge.yml` add `domain: lehel.xyz` to the test host vars so `service_host`/`LOCAL_HOSTNAME`/`SERVICE_ROOT_HOST` render as `lehel.xyz`. In `verify.yml` add greps:
```yaml
- name: Assert LOCAL_HOSTNAME uses domain
  command: grep -q 'LOCAL_HOSTNAME=lehel.xyz' /home/molecule/simple-svc/.env
  ...
- name: Assert SERVICE_ROOT_HOST uses domain
  command: grep -q 'SERVICE_ROOT_HOST=lehel.xyz' /home/molecule/simple-svc/.env
```
**Step 2:** Run `cd ansible/plays/roles/docker_service && molecule test --scenario-name default`. Expect the new greps to PASS (Task 2 already landed).
**Step 3:** Commit
```bash
git add ansible/plays/roles/docker_service/molecule/
git commit -m "test(docker_service): assert LOCAL_HOSTNAME/SERVICE_ROOT_HOST honor domain override"
```

---

### Task 9: Lint + full syntax check

**Step 1:** Run:
```bash
cd ansible && ansible-lint --force-color --show-relpath
cd ansible && yamllint -c ../.yamllint.yml .
cd ansible && ansible-playbook servyy.yml --syntax-check -i production
cd ansible && ansible-playbook servyy.yml --syntax-check -i testing
```
Expected: all clean.

**Step 2:** (no commit; verification only)

---

### Task 10: Update operational docs

**Files:**
- Modify: `CLAUDE.md` (all `--limit lehel.xyz` → `--limit servy.lehel.xyz`; `--limit code.lehel.xyz` → `--limit codey.lehel.xyz`; `-e target_host=lehel.xyz` → `target_host=servy.lehel.xyz`)
- Modify: `AGENTS.md:217`, `GEMINI.md:126`, `conductor/workflow.md:56,95`
- Modify active skills referencing `--limit lehel.xyz`: `.claude/skills/manage-service/SKILL.md`, `.claude/skills/bootstrapping-bumbleflies-subdomain/SKILL.md`, `opencode/skills/opencode-deployment.md`, `opencode/skills/opencode-dependency.md`, `.qwen/skills/auto-skill-infra-deploy/SKILL.md`

> Do NOT change DNS-section docs that describe `lehel.xyz` ALIAS → servy (still accurate). Do NOT rewrite history/ or docs/superpowers/plans/ (archival).

**Step 1:** grep + replace the limit/target_host tokens above.
**Step 2:** Commit
```bash
git add CLAUDE.md AGENTS.md GEMINI.md conductor/workflow.md .claude/skills/ opencode/skills/ .qwen/skills/
git commit -m "docs: update operational --limit references to servy.lehel.xyz / codey.lehel.xyz"
```

---

### Task 11: Pre-deploy ops + test-environment deploy (required by infra policy)

**Step 1 (control machine):** Ensure new SSH host keys are known (old `lehel.xyz`/`code.lehel.xyz` entries remain valid via DNS; add the new names):
```bash
ssh-keygen -R servy.lehel.xyz; ssh-keyscan servy.lehel.xyz >> ~/.ssh/known_hosts
ssh-keygen -R codey.lehel.xyz; ssh-keyscan codey.lehel.xyz >> ~/.ssh/known_hosts
```
**Step 2 (test first, per policy):** Deploy to `servyy-test.lxd` (inventory unchanged there) to confirm molecule/syntax pass, then a no-op prod check:
```bash
cd ansible && ./servyy-test.sh --tags user.docker
cd ansible && ansible-playbook servyy.yml -i production --limit servy.lehel.xyz --check
cd ansible && ansible-playbook servyy.yml -i production --limit codey.lehel.xyz --check
```
Expected: `--check` runs without "Host not found" and no `inventory_hostname ==` skips.

**Step 3:** Commit a history log `history/2026-08-29_inventory-host-rename.md` recording change, verification, and the known side effects (restic repos recreated at new paths; duplicated Vaultwarden keys).

---

### Task 12: Production deploy + verify

**Step 1:** Deploy master then slave:
```bash
cd ansible && ./servyy.sh --limit servy.lehel.xyz
cd ansible && ./servyy.sh --limit codey.lehel.xyz
```
**Step 2:** Verify a sample of public services still resolve & serve:
```bash
curl -sI https://search.lehel.xyz | head -1
curl -sI https://code.lehel.xyz | head -1
curl -sI https://monitor.lehel.xyz | head -1
ssh servy.lehel.xyz "docker ps --format '{{.Names}}' | head"
```
Expected: 200/3xx and containers running. Confirm `*.lehel.xyz` still terminates on servy (wildcard CNAME unchanged).
**Step 3:** Confirm restic re-init created new repos (orphaned old `lehel.xyz/` paths are expected, harmless).

---

## Rollback

Revert Tasks 1–7 (restore `lehel.xyz`/`code.lehel.xyz` host keys, drop `domain`, revert `inventory_hostname` usages) and recommit. Public DNS is untouched so services keep working during rollback. Restic old-path backups and old Vaultwarden keys remain usable.

## Known side effects (accepted)
- Restic repositories move to `.../servy.lehel.xyz/...` and `.../codey.lehel.xyz/...`; previous `lehel.xyz`/`code.lehel.xyz` backups remain on the Storage Box but are no longer referenced (recreated fresh).
- Vaultwarden items named `(servy)`/`(codey)` are created alongside the old `(lehel)`/`(code)` items (duplicates, acceptable).
- Internal `*_local_qualified` Traefik routes now answer on `*.lehel.xyz` instead of `*.servy`/`*.codey` (consistent with public domain, per decision).
