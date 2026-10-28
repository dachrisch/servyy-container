# Auditd rules for servy + actionable vs unfixed CVE counts

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give the host a real audit trail (it has been running auditd with an empty ruleset),
and make the monthly report separate CVEs somebody can fix from CVEs waiting on upstream.

**Architecture:** A new `auditd-hardening.rules.j2` snippet in the `system` role's existing
`hardening.yml` (deployed to `/etc/audit/rules.d/99-hardening.rules`, loaded by an `augenrules
--load` handler), plus a second count in `run_trivy` that splits CRITICAL/HIGH by whether
`FixedVersion` is set, surfaced as `mapped`/`unfixed` numbers in `trivy-summary.txt` and
`SUMMARY.md`.

**Tech Stack:** Ansible (`system` role, hand-written rules template), auditd 4.1 on Ubuntu
26.04, bash, Jinja2, trivy JSON.

---

## Context

- **Lynis `ACCT-9630`** ("audit daemon is enabled with an empty ruleset") on the 2026-10-28
  audit: auditd is enabled and running, `/etc/audit/rules.d/` holds only the package's
  `audit.rules` (global settings), `auditctl -l` is empty. Nothing on the host is audited.
- **`fireflyiii/core:latest` and `data-importer:latest`** were reported as "23 CRITICAL each"
  in the 2026-10-09 scan. The 2026-10-28 scan of the same images (pulled 2026-10-26) shows
  **3 CRITICAL each, all with `FixedVersion: ""`** — two in `linux-libc-dev` (kernel headers,
  not an executable surface in a container) and one in `libxml2` with no Debian fix yet.
  There is nothing to upgrade; the report simply could not be read that way.

---

## Task 1: Rule template + contract test

**Files:**
- Create: `ansible/plays/roles/system/templates/auditd-hardening.rules.j2`
- Create: `ansible/plays/roles/system/tests/test_auditd_rules.sh`

Rules are curated for a ~50-container Docker host: no global `execve` logging (it drowns the
log), watches on identity/privilege/auth/cron/docker/systemd/audit configuration, kernel module,
time, hostname and mount syscalls, and execution of the privileged binaries. Only paths that
exist on the target — a watch on a missing path makes the whole `augenrules --load` fail.
Global settings (`-D`, `-b`, `-f`) stay in the package's `audit.rules`; immutability (`-e 2`)
is opt-in via `hardening.audit_immutable`.

**Step 1:** Write the test asserting: every non-comment line is a valid rule prefix, no `-D`,
no duplicate watches, ≥1 entry for each key class, ≥5 exec watches, and `-e 2` only when
`audit_immutable` is true (and then last).

**Step 2:** `bash ansible/plays/roles/system/tests/test_auditd_rules.sh` → RED.

**Step 3:** Write the template. **Step 4:** GREEN (20 checks).

---

## Task 2: Wire it into the role

**Files:**
- Modify: `ansible/plays/roles/system/tasks/hardening.yml`
- Modify: `ansible/plays/roles/system/handlers/main.yml`
- Modify: `ansible/plays/vars/default.yml`

- Task `Deploy auditd rules` (template, `0640`, `notify: reload auditd`, tags
  `system.hardening.audit[.rules]`, guarded by `hardening.audit`).
- Handler `reload auditd` → `augenrules --load`, guarded by
  `ansible_facts['virtualization_type'] != 'docker'` like the other service handlers.
- `hardening.audit_immutable: false` with a comment about the reboot cost.

**Verify:** `--check --diff` shows the file, apply reports `changed` + handler, and on the host
`auditctl -l` lists the rules, `auditctl -s` shows `enabled 1`/`lost 0`.

---

## Task 3: Actionable-vs-unfixed counts (the fireflyiii lesson)

**Files:**
- Modify: `ansible/plays/roles/system/templates/security-audit.sh.j2` (`run_trivy`, `generate_summary`)
- Modify: `ansible/plays/roles/system/tests/test_security_audit_trivy.sh`

**Step 1: Failing test** — stub findings become one CRITICAL without `FixedVersion` plus one
fixable HIGH; assert `critical_unfixed=`/`high_unfixed=` in `trivy-summary.txt` and
`2 CRITICAL (2 without an upstream fix)` in `SUMMARY.md`.

**Step 2:** RED.

**Step 3:** Replace the two `grep -c` counters with one `python3` pass over the results that
counts `(critical, high, critical_unfixed, high_unfixed)`; publish all four; log
`N CRITICAL (M without an upstream fix), K HIGH`.

**Step 4:** GREEN (30 checks).

---

## Task 4: Deploy and verify

```bash
cd ansible && ansible-playbook servyy.yml -i production --limit servy.lehel.xyz \
    --tags system.hardening.audit -e ansible_user=cda
ansible-playbook servyy.yml -i production --limit servy.lehel.xyz \
    --tags system.security_audit.scripts -e ansible_user=cda
```

On the host: `auditctl -l | wc -l` > 30; trigger `sudo true` and grep `key="privilege"` in
`/var/log/audit/audit.log`; measure growth (8 MB × 5 rotation must not roll over in hours).

---

## Task 5: Docs

- `history/2026-10-28_auditd-rules.md`
- Correct the "23 CRITICAL each" claim in `history/2026-10-28_security-audit-trivy-empty-results.md`
  with the 2026-10-28 numbers.
