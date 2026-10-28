# AIDE database at the conventional path + molecule coverage for hardening

**Date:** 2026-10-28
**Status:** ✅ Deployed to `servy.lehel.xyz`; molecule scenario validated in CI
**Relates to:** `2026-10-10_host-hardening-aide-scope.md`, `2026-10-28_lynis-profile-abort.md`, `2026-10-28_auditd-rules.md`

## Context

Two loose ends from the 2026-10-28 audit and from the P6 hardening.

### 1. Lynis `FINT-4316` — "No AIDE database was found"

Not a missing database: `/var/lib/aide/aide-hardening.db` had existed since 2026-10-10. The
scoped config deliberately used a non-standard filename so it would not collide with the
distro's `/var/lib/aide/aide.db` — but Lynis (and aide-common) look for the *conventional*
path, so an integrity database that was working perfectly was invisible to both. That is the
same failure mode as the audit bugs fixed earlier today: the tool was right, the interface was
wrong.

While verifying, two more problems surfaced:

- **`dailyaidecheck.timer` was failing every night** — `User=_aide` against
  `/etc/aide/aide.conf` (the heavy distro config, `Full` on `/`), with no database it is allowed
  to read, and `mail(1)` unavailable. Daily red unit, zero coverage.
- **`aide-check.service` reported failure by design** — `ExecMainStatus=7` on 2026-10-25. AIDE
  encodes *findings* in its exit code (1 added, 2 removed, 4 changed, and combinations), so a
  plain `--check` turns "the host changed" into a failed unit every week.

### 2. `hardening.yml` had no molecule coverage

The `system` role's scenarios converge `packages`, `user` and `journald` only. Nothing tested
hardening — which is why a Lynis-rejected profile and an empty auditd ruleset shipped and lived
in production for weeks.

## Decision

**AIDE**

1. Move the database to the conventional path (`/var/lib/aide/aide.db[.new]`) in
   `aide-hardening.conf.j2`, with a task that migrates an existing `aide-hardening.db`
   (`stat` + `mv`, `creates`-guarded, idempotent).
2. **Mask `dailyaidecheck.timer`.** It cannot work as packaged here (wrong user, wrong config,
   no readable database) and the weekly `aide-check.timer` covers the same ground as root with
   the scoped config. Masking rather than disabling so a package update does not re-enable it.
3. `aide-check.service`: `ExecStartPre=/usr/bin/test -s /var/lib/aide/aide.db` (missing
   database fails the unit) and `ExecStart=-/usr/bin/aide …` (differences are findings, not
   failures). Real breakage stays visible, routine drift does not page anyone.
4. **Exclude self-generated churn** from the monitored roots: `/root/.cache`, `/root/.local`,
   `/root/nuclei-templates`. The scoped config monitors `/root` for keys and scripts, but the
   audit tooling itself rewrites those three constantly — the first post-migration check
   reported thousands of changed nuclei templates.
5. **Rebuild the baseline when the monitored scope changes.** A `creates`-guarded init alone
   meant a config edit produced a permanent diff. A second init task now runs when the config
   template changed (and the first init did not just run), because accepting the new scope is
   the only way the weekly check can be meaningful again.

**Molecule**

The gap was narrower than first assumed: the `core` scenario already converges `hardening.yml`,
but with `audit: false` — so the auditd ruleset, the one part that actually broke in
production, was never asserted. A separate `hardening` scenario would have duplicated CI work
for nothing; the first attempt was written, failed CI on the conservative `-D` assertion, and
was replaced by extending `core`.

Changes to `molecule/core`:

- `hardening.audit: true` — auditd is installed and its ruleset deployed even in a container;
  only the service start is skipped there
- `Enable auditd` gained the repo's existing
  `ansible_facts['virtualization_type'] != 'docker'` guard (it could never start in a
  container), which keeps the sysctl drop-in and sshd template guard untouched
- new verify tasks: `/etc/audit/rules.d/99-hardening.rules` exists, is `0640 root:root`,
  carries a rule for every key class, has no global `-D`/`-e 2` **at a line start**, ≥25
  watches and ≥3 syscall rules, and `auditd` is installed

## Consequences

### Positive

- `FINT-4316` is gone: the integrity database is where every tool expects it
- The weekly AIDE check reports success when it works and failure only when it is genuinely
  broken; the nightly broken distro unit is masked
- The largest untested role surface now has coverage — including the exact file whose absence
  caused the auditd defect
- `/root` churn no longer drowns the diff

### Negative / Tradeoffs

- Masking a distro unit can be undone by a package update; the task runs again on every deploy
- A scope change now costs a ~2 minute re-init inside the deploy
- The molecule scenario deliberately does not exercise `aide`, `malware`, `ssh` or `sysctl`,
  so those stay host-verified only

### Known Issues / Open Findings

- `MAIL-8818` (SMTP banner discloses OS/software) is still open — the only warning left apart
  from vulnerable packages
- `FINT-4402` suggests SHA256/SHA512 for AIDE checksums; the config already uses
  `sha256+sha512`, so expect it to clear on the next audit
