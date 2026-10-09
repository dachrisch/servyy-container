# P6 Host Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Raise the Lynis host-hardening score on `servy.lehel.xyz` (and `codey.lehel.xyz`) by fixing the actionable findings from the 2026-10-09 audit (score 61/100, 1 warning, 43 suggestions), while explicitly documenting the findings that are accepted risks on a Hetzner cloud host.

**Architecture:** Add a new `hardening.yml` task file to the existing `system` role (imported from `main.yml`, tag `system.hardening`) that deploys: a sysctl drop-in, an SSH hardening drop-in alongside the existing `disablePasswordAuth.conf`, login-defs tweaks, legal banners, a modprobe blacklist for rare protocols, and a few hardening packages. Add a Lynis custom profile (`skip-test=` entries) so accepted risks are documented and stop dragging the score, and pass `--profile` from the audit script. All settings live in a new `hardening:` var block in `ansible/plays/vars/default.yml`.

**Tech Stack:** Ansible (`system` role), Jinja2 templates, Molecule (`system` scenarios `minimal`/`core`/`default`), systemd, sysctl, OpenSSH, Lynis.

---

## Constraints & accepted risks (from user / Hetzner)

These are **deliberately NOT implemented**; they go into the Lynis custom profile as `skip-test=` with a rationale comment:

| Code | Finding | Why accepted |
|------|---------|--------------|
| `BOOT-5122` | GRUB bootloader password | Hetzner cloud host — no out-of-band boot-menu access to justify it, and a lost GRUB password risks a non-booting server. **User decision: not an option.** |
| `FILE-6310` | Separate `/home` and `/var` partitions | Single cloud volume; repartitioning is high-risk and out of scope. |
| `KRNL-6000:net.ipv4.conf.all.forwarding` | Disable IP forwarding | **Required by Docker** (container networking). |
| `KRNL-6000:kernel.modules_disabled` | Disable module loading | Would break loading of modules Docker/cloud-init need after boot. |
| `KRNL-6000:kernel.unprivileged_bpf_disabled` | Restrict unprivileged BPF | Current value `2` is already *stricter* than Lynis' preferred `1`. |
| `LOGG-2154` | External logging host | Satisfied via journald → Promtail → Loki (`monitor`). |
| `USB-1000` | Disable USB storage | Cloud VM has no USB bus. |
| `SSH-7408:Port` | Move SSH off 22 | Keep 22 (firewalled; changing it is churn, not security). |
| `BOOT-5180`, `BOOT-5264` | Runlevel/service review | Informational only. |
| `HRDN-7222` | Restrict compiler access | `build-essential` is intentionally present for service builds; revisit later. |

Everything else in the 43 suggestions is either fixed below or investigated.

---

## Baseline (2026-10-09, servy.lehel.xyz)

- Lynis `hardening_index=61`; 1 warning `PKGS-7392` (vulnerable packages); 43 suggestions.
- Effective sshd: `PermitRootLogin yes`, `MaxAuthTries 6`, `MaxSessions 10`, `ClientAliveCountMax 3`, `TCPKeepAlive yes`, `AllowTcpForwarding yes`, `AllowAgentForwarding yes`, `LogLevel INFO`, `PasswordAuthentication no`.
- `/etc/login.defs`: `PASS_MAX_DAYS 99999`, `PASS_MIN_DAYS 0`, no `UMASK`.
- sysctl drift: 15 values (see Task 1).
- Reference command to re-derive: `sudo grep -E '^(warning|suggestion)\[\]=' /var/log/security-audit/$(date +%F)/lynis-report.dat`

---

## Task 1: sysctl hardening drop-in

**Files:**
- Create: `ansible/plays/roles/system/templates/sysctl-hardening.conf.j2`
- Create: `ansible/plays/roles/system/tasks/hardening.yml`
- Modify: `ansible/plays/roles/system/tasks/main.yml` (import `hardening.yml`)
- Modify: `ansible/plays/vars/default.yml` (add `hardening:` block)
- Test: `ansible/plays/roles/system/molecule/core/verify.yml`

**Step 1: Add the var block** to `ansible/plays/vars/default.yml` (after the `security_audit` block):

```yaml
# Host hardening (Lynis-driven). See docs/plans/2026-10-08-host-hardening-p6.md
hardening:
  enabled: true
  # Docker-safe sysctl values. Deliberately excludes net.ipv4.conf.all.forwarding
  # (Docker needs it) and kernel.modules_disabled (breaks dynamic module load).
  sysctl:
    fs.protected_fifos: 2
    fs.suid_dumpable: 0
    kernel.kptr_restrict: 2
    kernel.sysrq: 0
    net.core.bpf_jit_harden: 2
    net.ipv4.conf.all.log_martians: 1
    net.ipv4.conf.all.rp_filter: 1
    net.ipv4.conf.all.send_redirects: 0
    net.ipv4.conf.default.accept_redirects: 0
    net.ipv4.conf.default.log_martians: 1
    net.ipv6.conf.all.accept_redirects: 0
    net.ipv6.conf.default.accept_redirects: 0
  ssh:
    PermitRootLogin: prohibit-password
    MaxAuthTries: 3
    MaxSessions: 2
    ClientAliveCountMax: 2
    LogLevel: VERBOSE
    TCPKeepAlive: no
    # local (not no): blocks remote (-R) forwarding but keeps local (-L) tunnels
    # for admins and the dbeaver_stage Match block.
    AllowTcpForwarding: local
    AllowAgentForwarding: no
  login_defs:
    UMASK: "027"
    PASS_MIN_DAYS: "1"
    PASS_MAX_DAYS: "365"
```

**Step 2: Create the template** `sysctl-hardening.conf.j2`:

```jinja
# Managed by Ansible - system.hardening. Do not edit by hand.
{% for key, value in hardening.sysctl.items() %}
{{ key }} = {{ value }}
{% endfor %}
```

**Step 3: Create `hardening.yml`** with the sysctl task (other tasks added in later steps):

```yaml
---
# Host hardening (Lynis-driven). See docs/plans/2026-10-08-host-hardening-p6.md

- name: Deploy sysctl hardening drop-in
  template:
    src: sysctl-hardening.conf.j2
    dest: /etc/sysctl.d/99-hardening.conf
    mode: '0644'
    owner: root
    group: root
  become: true
  notify: reload sysctl
  tags:
    - system.hardening
    - system.hardening.sysctl
```

**Step 4: Add the handler** to `ansible/plays/roles/system/handlers/main.yml`:

```yaml
- name: reload sysctl
  command: sysctl --system
  changed_when: true
```

**Step 5: Import from `main.yml`** (before `security_audit.yml`):

```yaml
- import_tasks: hardening.yml
  when: hardening.enabled | default(true)
  tags:
    - system.hardening
```

**Step 6: Verify (molecule `core`)**

Add to `molecule/core/verify.yml`:

```yaml
- name: sysctl hardening drop-in deployed
  ansible.builtin.stat:
    path: /etc/sysctl.d/99-hardening.conf
  register: sysctl_dropin
  failed_when: not sysctl_dropin.stat.exists

- name: sysctl hardening applied
  ansible.builtin.command: sysctl -n fs.protected_fifos
  register: fifos
  changed_when: false
  failed_when: fifos.stdout | trim != '2'
```

Run: `cd ansible/plays/roles/system && molecule test --scenario-name core`
Expected: PASS.

**Step 7: Commit**

```bash
git add ansible/plays/roles/system/templates/sysctl-hardening.conf.j2 \
        ansible/plays/roles/system/tasks/hardening.yml \
        ansible/plays/roles/system/tasks/main.yml \
        ansible/plays/roles/system/handlers/main.yml \
        ansible/plays/vars/default.yml \
        ansible/plays/roles/system/molecule/core/verify.yml
git commit -m "feat(hardening): deploy Docker-safe sysctl hardening drop-in"
```

---

## Task 2: SSH hardening drop-in

**Files:**
- Create: `ansible/plays/roles/system/templates/sshd-hardening.conf.j2`
- Modify: `ansible/plays/roles/system/tasks/hardening.yml`
- Test: `ansible/plays/roles/system/molecule/core/verify.yml`

> ⚠️ **Two risks to verify before production** (see Step 5):
> - `AllowTcpForwarding local` blocks remote (`-R`) forwarding but keeps local (`-L`) tunnels — including the LeagueSphere `dbeaver_stage` stage tunnel, whose `Match User dbeaver_stage { AllowTcpForwarding local }` block overrides the global setting (verified with `sshd -T -C user=dbeaver_stage`). Do **not** set this to `no` or admin `ssh -L` tunnels break.
> - `MaxSessions 2` can interfere with SSH ControlMaster multiplexing used by Ansible/`strategy: free`. If Ansible ad-hoc to the host fails after apply, raise to `4`.

**Step 1: Create `sshd-hardening.conf.j2`:**

```jinja
# Managed by Ansible - system.hardening. Sits alongside disablePasswordAuth.conf.
{% for key, value in hardening.ssh.items() %}
{{ key }} {{ value }}
{% endfor %}
```

**Step 2: Append the task** to `hardening.yml`:

```yaml
- name: Deploy SSH hardening drop-in
  template:
    src: sshd-hardening.conf.j2
    dest: /etc/ssh/sshd_config.d/99-hardening.conf
    mode: '0644'
    owner: root
    group: root
  become: true
  validate: 'sshd -t -f %s'
  notify: reload sshd
  tags:
    - system.hardening
    - system.hardening.ssh
```

**Step 3: Add the handler** to `handlers/main.yml`:

```yaml
- name: reload sshd
  service:
    name: ssh
    state: reloaded
```

**Step 4: Verify (molecule `core`)** — assert the effective config:

```yaml
- name: sshd hardening applied
  ansible.builtin.command: sshd -T
  register: sshd_effective
  changed_when: false
  failed_when: >
    'permitrootlogin prohibit-password' not in sshd_effective.stdout or
    'maxauthtries 3' not in sshd_effective.stdout
```

Run: `cd ansible/plays/roles/system && molecule test --scenario-name core`
Expected: PASS.

**Step 5: Production pre-check** (manual, on servy) — after deploy:

```bash
ssh servy.lehel.xyz 'sudo sshd -T | grep -E "permitrootlogin|maxauthtries|allowtcpforwarding"'
# keep the current SSH session open; in a second shell confirm a fresh key login works
ssh -o BatchMode=yes servy.lehel.xyz 'echo ok'
# confirm the LeagueSphere stage tunnel account still gets local forwarding
ssh servy.lehel.xyz 'sudo sshd -T -C user=dbeaver_stage,host=localhost,addr=127.0.0.1,laddr=127.0.0.1 | grep allowtcpforwarding'
# expect: allowtcpforwarding local
```

**Step 6: Commit**

```bash
git add ansible/plays/roles/system/templates/sshd-hardening.conf.j2 \
        ansible/plays/roles/system/tasks/hardening.yml \
        ansible/plays/roles/system/handlers/main.yml \
        ansible/plays/roles/system/molecule/core/verify.yml
git commit -m "feat(hardening): add sshd hardening drop-in"
```

---

## Task 3: login.defs password/umask policy

**Files:**
- Modify: `ansible/plays/roles/system/tasks/hardening.yml`
- Test: `ansible/plays/roles/system/molecule/core/verify.yml`

**Step 1: Append tasks** to `hardening.yml`:

```yaml
- name: Harden login.defs
  ansible.builtin.lineinfile:
    path: /etc/login.defs
    regexp: "^\\s*{{ item.key }}\\s"
    line: "{{ item.key }}\t{{ item.value }}"
    state: present
  loop: "{{ hardening.login_defs | dict2items }}"
  loop_control:
    label: "{{ item.key }}"
  become: true
  tags:
    - system.hardening
    - system.hardening.login_defs
```

**Step 2: Verify (molecule `core`):**

```yaml
- name: login.defs umask hardened
  ansible.builtin.command: grep -E '^UMASK\s+027' /etc/login.defs
  changed_when: false
```

Run: `cd ansible/plays/roles/system && molecule test --scenario-name core`
Expected: PASS.

**Step 3: Commit**

```bash
git add ansible/plays/roles/system/tasks/hardening.yml \
        ansible/plays/roles/system/molecule/core/verify.yml
git commit -m "feat(hardening): set login.defs umask and password age policy"
```

---

## Task 4: Legal banners (`/etc/issue`, `/etc/issue.net`)

**Files:**
- Create: `ansible/plays/roles/system/templates/issue.j2`
- Modify: `ansible/plays/roles/system/tasks/hardening.yml`

**Step 1: Create `issue.j2`** (same content reused for both paths):

```jinja
Authorized access only. This system is monitored and all activity is logged.
Disconnect immediately if you are not an authorized user.
```

**Step 2: Append tasks** to `hardening.yml`:

```yaml
- name: Deploy legal banner
  ansible.builtin.copy:
    src: issue.j2
    dest: "{{ item }}"
    mode: '0644'
    owner: root
    group: root
  loop:
    - /etc/issue
    - /etc/issue.net
  become: true
  tags:
    - system.hardening
    - system.hardening.banner
```

**Step 3: Verify (molecule `core`):** `stat` both files and assert non-empty.

Run: `cd ansible/plays/roles/system && molecule test --scenario-name core`

**Step 4: Commit**

```bash
git add ansible/plays/roles/system/templates/issue.j2 \
        ansible/plays/roles/system/tasks/hardening.yml
git commit -m "feat(hardening): add legal login banners"
```

---

## Task 5: Disable rare network protocols

**Files:**
- Create: `ansible/plays/roles/system/templates/modprobe-disable-protocols.conf.j2`
- Modify: `ansible/plays/roles/system/tasks/hardening.yml`

**Step 1: Create the template:**

```jinja
# Managed by Ansible - system.hardening. Rare protocols not used on this host.
{% for proto in hardening.disabled_protocols %}
install {{ proto }} /bin/true
{% endfor %}
```

Add to the var block: `disabled_protocols: [dccp, sctp, rds, tipc]`.

**Step 2: Append task** to `hardening.yml`:

```yaml
- name: Disable rare network protocols
  template:
    src: modprobe-disable-protocols.conf.j2
    dest: /etc/modprobe.d/disable-rare-protocols.conf
    mode: '0644'
    owner: root
    group: root
  become: true
  tags:
    - system.hardening
    - system.hardening.modprobe
```

**Step 3: Verify (molecule `core`):** `stat` the file and assert it lists all four protocols.

Run: `cd ansible/plays/roles/system && molecule test --scenario-name core`

**Step 4: Commit**

```bash
git add ansible/plays/roles/system/templates/modprobe-disable-protocols.conf.j2 \
        ansible/plays/roles/system/tasks/hardening.yml \
        ansible/plays/vars/default.yml
git commit -m "feat(hardening): blacklist unused network protocols"
```

---

## Task 6: Package hygiene & hardening tools

**Files:**
- Modify: `ansible/plays/roles/system/tasks/hardening.yml`
- Modify: `ansible/plays/roles/system/tasks/packages.yml` (install additions)

Addresses `PKGS-7346` (25 old packages), `PKGS-7370` (debsums), `PKGS-7394` (apt-show-versions), `DEB-0280` (libpam-tmpdir), `AUTH-9262` (libpam-pwquality).

**Step 1: Install tools** — add to the `sys_packages` list in `vars/default.yml` (or a `hardening_packages` var):

```yaml
  hardening_packages:
    - debsums
    - apt-show-versions
    - libpam-tmpdir
    - libpam-pwquality
```

**Step 2: Append tasks** to `hardening.yml`:

```yaml
- name: Install hardening packages
  apt:
    name: "{{ hardening_packages }}"
    state: present
    update_cache: true
    cache_valid_time: 3600
  become: true
  tags:
    - system.hardening
    - system.hardening.packages

- name: Purge obsolete packages
  apt:
    autoremove: true
    purge: true
  become: true
  tags:
    - system.hardening
    - system.hardening.packages
```

**Step 3: Verify** `PKGS-7392` (vulnerable packages): confirm `unattended-upgrades` is enabled and actually upgrading. Inspect the existing `50unattended-upgrades.j2` origins; if security updates are being held, widen `Unattended-Upgrade::Allowed-Origins`. Re-run `sudo apt-get -s upgrade` on the host and confirm no pending security upgrades.

**Step 4: Commit**

```bash
git add ansible/plays/roles/system/tasks/hardening.yml \
        ansible/plays/roles/system/tasks/packages.yml \
        ansible/plays/vars/default.yml
git commit -m "feat(hardening): install verification tools and purge obsolete packages"
```

---

## Task 7: auditd + process accounting (medium risk)

**Files:**
- Modify: `ansible/plays/roles/system/tasks/hardening.yml`

Addresses `ACCT-9628` (auditd), `ACCT-9622` (process accounting).

> On a Docker host auditd is noisy; start with the distro default rules and a sane `max_log_file`/retention, then tune.

**Step 1: Append tasks:**

```yaml
- name: Install auditd and acct
  apt:
    name:
      - auditd
      - acct
    state: present
  become: true
  tags:
    - system.hardening
    - system.hardening.audit

- name: Enable auditd
  service:
    name: auditd
    enabled: true
    state: started
  become: true
  tags:
    - system.hardening
    - system.hardening.audit
```

**Step 2: Verify** `auditctl -s` reports `enabled=1`; `systemctl is-active auditd`.

**Step 3: Commit** `feat(hardening): enable auditd and process accounting`.

---

## Task 8: File integrity monitoring with AIDE (medium risk)

**Files:**
- Modify: `ansible/plays/roles/system/tasks/hardening.yml`
- Create: `ansible/plays/roles/system/templates/aide-check.timer.j2` + `.service.j2` (weekly)

Addresses `FINT-4350`.

**Step 1: Install + init AIDE** (`aide` package, `aideinit`), deploy a weekly `aide --check` systemd timer, and surface results via the existing monit/journald pipeline.

**Step 2: Verify** `aide --version`, timer listed via `systemctl list-timers aide-check.timer`.

**Step 3: Commit** `feat(hardening): add AIDE file-integrity monitoring`.

---

## Task 9: Malware scanner (optional)

Addresses `HRDN-7230`. Install `rkhunter` (lighter than ClamAV for a server), run `rkhunter --propupd`, and schedule `rkhunter --cronjob` weekly. Commit `feat(hardening): add rkhunter malware scan`.

---

## Task 10: Lynis custom profile for accepted risks

**Files:**
- Create: `ansible/plays/roles/system/templates/lynis-custom.prf.j2`
- Modify: `ansible/plays/roles/system/tasks/security_audit.yml`
- Modify: `ansible/plays/roles/system/templates/security-audit.sh.j2`

**Step 1: Create `lynis-custom.prf.j2`** from the accepted-risks table:

```jinja
# Managed by Ansible - accepted risks. Rationale: docs/plans/2026-10-08-host-hardening-p6.md
skip-test=BOOT-5122     # GRUB password - Hetzner cloud, no OOB boot access
skip-test=FILE-6310     # separate /home,/var - single cloud volume
skip-test=KRNL-6000:net.ipv4.conf.all.forwarding  # required by Docker
skip-test=KRNL-6000:kernel.modules_disabled        # would break dynamic module load
skip-test=KRNL-6000:kernel.unprivileged_bpf_disabled # already stricter (2 > 1)
skip-test=LOGG-2154     # external logging - provided by Loki/Promtail
skip-test=USB-1000      # no USB bus on cloud VM
skip-test=SSH-7408:Port # keep SSH on 22
skip-test=BOOT-5180
skip-test=BOOT-5264
skip-test=HRDN-7222     # compilers intentionally present
```

**Step 2: Deploy it** in `security_audit.yml` (template to `/etc/lynis/custom.prf`, mode `0644`).

**Step 3: Wire into the audit script** — change the lynis invocation in `security-audit.sh.j2`:

```
lynis audit system --quick --cronjob --quiet --profile /etc/lynis/custom.prf \
    --report-file "${LOG_DIR}/lynis-report.dat" 2>&1 || true
```

**Step 4: Verify** — re-run the audit; `hardening_index` rises and the skipped codes disappear from `suggestion[]`.

**Step 5: Commit** `feat(hardening): add Lynis profile documenting accepted risks`.

---

## Task 11: Re-scan, compare, document

**Step 1:** Deploy to the test host first:
```bash
cd ansible && ./servyy-test.sh --limit servyy-test.lxd --tags system.hardening
ssh servyy-test.lxd 'sudo systemctl start security-audit.service'
```

**Step 2:** Confirm no regressions (SSH reachable, Docker networking up, `docker ps` healthy, Ansible re-run idempotent).

**Step 3:** Deploy to production:
```bash
cd ansible && ./servyy.sh --limit servy.lehel.xyz --tags system.hardening
ssh servy.lehel.xyz 'sudo systemctl start security-audit.service'
```

**Step 4:** Compare `hardening_index` before/after and list remaining `warning[]`/`suggestion[]`.

**Step 5:** Write `history/2026-10-08_host-hardening.md` with before/after score, what was applied, and what was accepted (with rationale).

---

## Rollback

- Each template is a single file; revert by removing the drop-in and re-running the role (`--tags system.hardening` is additive, so removal needs a manual `file: state=absent` task or a revert commit + redeploy).
- SSH: if locked out, Hetzner rescue mode; the drop-in is at `/etc/ssh/sshd_config.d/99-hardening.conf`.
- sysctl: `/etc/sysctl.d/99-hardening.conf`; `sysctl --system` re-applies defaults after removal.

## Notes for the implementer

- Follow repo conventions: 2-space YAML, tags `system.hardening.*`, idempotent tasks, `become: true`.
- The `system` role is applied on **both** servy and codey — keep everything host-agnostic (no host-specific sysctl/SSH).
- Prefer drop-in files (`/etc/sysctl.d`, `/etc/ssh/sshd_config.d`) over editing main configs.
- Do **not** touch GRUB or partitions (see constraints).
- Every task needs a molecule assertion in `system/molecule/core/verify.yml` where practical.
