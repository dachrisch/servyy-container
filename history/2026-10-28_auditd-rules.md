# auditd was running with no rules; CVE counts now split by fixability

**Date:** 2026-10-28
**Status:** ✅ Deployed to `servy.lehel.xyz`
**Relates to:** `2026-10-28_lynis-profile-abort.md`, `2026-10-28_security-audit-trivy-empty-results.md`

## Context

Two findings from the first trustworthy audit in weeks:

1. **`ACCT-9630` — "Audit daemon is enabled with an empty ruleset."** auditd 4.1.2 was installed,
   enabled and running since the P6 hardening, with `/etc/audit/rules.d/` holding only the
   package's `audit.rules` (244 bytes of global settings). `auditctl -l` → `No rules`. Every
   `-k`-keyed event the host would have recorded was simply not recorded.
2. **`fireflyiii/core:latest` + `data-importer:latest`** were reported as *23 CRITICAL each* in
   the 2026-10-09 scan. Re-measured on 2026-10-28 (images pulled 2026-10-26): **3 CRITICAL each,
   all with no fixed version** — `CVE-2026-6653` (libxml2, no Debian fix yet) and
   `CVE-2026-93221` / `CVE-2026-99083` in `linux-libc-dev` (kernel headers, which are not an
   executable surface inside a container; the host itself runs `7.0.0-38-generic`, current).

So the "biggest CVE block in the fleet" was stale data, and what remains is nothing to upgrade —
but the report had no way to say "unfixable" versus "fixable", which is exactly why 23-vs-3 was
invisible.

## Decision

### 1. Real audit rules

`auditd-hardening.rules.j2` → `/etc/audit/rules.d/99-hardening.rules`, loaded by an
`augenrules --load` handler. Curated for a ~50-container host:

- **no global `execve` logging** — it would drown the log within hours
- watches: identity (`passwd`/`shadow`/`group`/`gshadow`/`opasswd`), privilege (`sudoers`),
  auth (`pam.d`, `sshd_config`), cron, `/etc/docker`, `/etc/systemd/system`, `/etc/audit`,
  `/etc/localtime`
- syscalls: module load/unload, time changes, hostname/domain, mounts
- execution (`-p x`) of `sudo`, `su`, `newgrp`, user/group management binaries
- **only paths that exist**: a watch on a missing path fails the whole load, so
  `/etc/containerd` (not installed) and `/etc/at.allow|deny` are deliberately absent
- immutability (`-e 2`) is opt-in via `hardening.audit_immutable` (default `false`): an
  immutable set cannot be changed without a reboot, so a later rule change needs one

### 2. Actionable vs unfixed CVE counts

`run_trivy` now counts `(critical, high, critical_unfixed, high_unfixed)` in one python pass over
the results and publishes them. `SUMMARY.md` reads:

```
- **Trivy findings**: 108 CRITICAL (3 without an upstream fix), 2663 HIGH
```

Rejected: `--ignore-unfixed`. It would have dropped those 3 from the report entirely, so nobody
would know the images contain kernel-header CVEs we cannot patch and cannot fix by rebuilding.
Counting them separately keeps the information and marks it as not actionable.

## Consequences

### Positive

- The host finally records an audit trail: 36 rules loaded, `enabled 1`, `lost 0`
- `SUMMARY.md` distinguishes "3 criticals, none actionable" from "3 criticals to patch today"
- A rule-file contract test (20 checks) fails if a rule becomes malformed or a key class is lost

### Negative / Tradeoffs

- ~4 MB/day of audit log; the packaged rotation (8 MB × 5) keeps ~10 days — fine, but it will
  not keep a month of history
- `ACCT-9630` should disappear from the next Lynis run; if it does not, the rules file is not
  being loaded and the handler needs a look

### Known Issues / Open Findings

- `hardening.yml` still has **no molecule coverage** (pre-existing gap; the `system` scenarios
  converge packages/user/journald only). The rule template is covered by a contract test and by
  `auditctl -l` on the host, not by a container scenario — auditd cannot load rules in one.
- `FINT-4316` (no AIDE database at the distro path) and `MAIL-8818` (SMTP banner) remain open
  from the Lynis audit.
