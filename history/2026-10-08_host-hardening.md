# Host Hardening (Lynis P6) — 2026-10-08

## Problem

The security audit's Lynis run scored **61/100** with 1 warning and 43 suggestions
(`/var/log/security-audit/2026-10-09/lynis-report.dat`). The host ran with default
sysctls, permissive SSH options, no legal banner, default password/umask policy, and
no integrity/audit tooling.

## Solution

Added a `system.hardening` task file to the `system` role that deploys, driven by a new
`hardening:` var block in `ansible/plays/vars/default.yml`:

- **sysctl** drop-in `/etc/sysctl.d/99-hardening.conf` — 12 Docker-safe values
  (deliberately excludes `net.ipv4.conf.all.forwarding`, required by Docker, and
  `kernel.modules_disabled`, which would break dynamic module loading).
- **sshd** drop-in `/etc/ssh/sshd_config.d/99-hardening.conf` — `PermitRootLogin
  prohibit-password`, `MaxAuthTries 3`, `MaxSessions 2`, `ClientAliveCountMax 2`,
  `LogLevel VERBOSE`, `TCPKeepAlive no`, `AllowTcpForwarding local`,
  `AllowAgentForwarding no`. `local` (not `no`) keeps local `-L` tunnels working,
  including the LeagueSphere `dbeaver_stage` stage tunnel whose
  `Match User dbeaver_stage { AllowTcpForwarding local }` block overrides the global
  setting (verified with `sshd -T -C user=dbeaver_stage`).
- **login.defs** — `UMASK 027`, `PASS_MIN_DAYS 1`, `PASS_MAX_DAYS 365`.
- **legal banners** `/etc/issue` + `/etc/issue.net`.
- **modprobe** blacklist for `dccp`, `sctp`, `rds`, `tipc`.
- **packages** — `debsums`, `apt-show-versions`, `libpam-tmpdir`, `libpam-pwquality`;
  purge obsolete packages.
- **auditd + acct**, **AIDE** (weekly `aide-check.timer`), **rkhunter** — each toggled
  by `hardening.audit|aide|malware`.
- **Lynis custom profile** `/etc/lynis/custom.prf` documenting accepted risks
  (GRUB password — Hetzner cloud; separate `/var`,`/home` partitions; IP forwarding for
  Docker; `modules_disabled`; external logging via Loki; USB; SSH port 22; compilers).
  The audit script now passes `--profile /etc/lynis/custom.prf`.

## Files Changed

- `ansible/plays/vars/default.yml` — `hardening:` block
- `ansible/plays/roles/system/tasks/hardening.yml` — new
- `ansible/plays/roles/system/tasks/main.yml` — import `hardening.yml`
- `ansible/plays/roles/system/handlers/main.yml` — `reload sshd`, `reload sysctl`
- `ansible/plays/roles/system/tasks/security_audit.yml` — deploy Lynis profile
- `ansible/plays/roles/system/templates/security-audit.sh.j2` — `--profile`
- `ansible/plays/roles/system/templates/{sysctl-hardening.conf,sshd-hardening.conf,issue,modprobe-disable-protocols.conf,lynis-custom.prf,aide-check.service,aide-check.timer}.j2`
- `ansible/plays/roles/system/molecule/core/{converge,verify}.yml` — coverage
- `docs/plans/2026-10-08-host-hardening-p6.md` — plan

## Verification

- `ansible-playbook plays/system.yml --syntax-check` passes.
- Templates render cleanly; `security-audit.sh.j2` passes `bash -n`.
- All 16 tasks reachable via `--tags system.hardening`.
- Molecule `system` scenario `core` extended with hardening coverage (container-safe
  subset: `audit/aide/malware` off, `ssh` skipped). **Not yet run locally** — needs
  `molecule test --scenario-name core`.

## Follow-up

- Run molecule, deploy to `servyy-test.lxd` first, then `servy.lehel.xyz`, and compare
  the Lynis `hardening_index` before/after.
- Validate a fresh SSH key login and the `dbeaver_stage` tunnel after applying.
