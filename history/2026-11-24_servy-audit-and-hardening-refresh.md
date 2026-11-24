# Refresh servy's audit tooling and managed SSH hardening

**Date:** 2026-11-24
**Status:** Accepted

## Context

The 2026-11-24 security audit baseline was implemented on codey first (arm64 fixes:
Docker Bench from source, arch-aware Nuclei, dynamic host label, tool-failure
reporting). servy could not be refreshed while its audit was still running — the
audit script is a bash file being executed, so overwriting it mid-run risks
corrupting the process. The X11 forwarding value on servy was already `no` from
the base image, but was not managed by Ansible.

## Decision

Gate both deploys on servy's audit writing `SUMMARY.md`, then apply two narrow-tag
deploys to servy only:

1. `./servyy.sh --tags system.hardening.ssh --limit servy.lehel.xyz`
2. `./servyy.sh --tags system.security_audit --limit servy.lehel.xyz`

No full audit re-run: the corrected script takes effect at the next monthly run.
Track A's bumbleflies pilot and this refresh were planned in
`docs/plans/2026-11-24_docker-hardening-and-servy-audit-refresh.md` (removed
2026-11-24, in git history) and recorded in
[2026-11-24 Docker CIS warning triage](2026-11-24_docker-cis-warning-triage.md).
No plan file remains after this change.

## Consequences

### Positive
- ✅ servy's X11 setting is now declared by Ansible, not inherited from the Hetzner image.
- ✅ servy's audit script reports the right host and exposes tool failures, matching codey.
- ✅ Docker Bench on servy now uses the pinned v1.6.1 source checkout like codey.
- ✅ All four bumbleflies containers are hardened with `pids_limit`/`init` (Track A).

### Negative / Tradeoffs
- ⚠️ The completed 2026-11-24 servy report was produced by the **old** script; its
  host label happened to be correct, but its "Tools Run: 7" cannot be cross-checked
  against a failure section. The Dec 6 run is the first fully trustworthy one.
- ⚠️ Docker Bench v1.6.1 uses different check numbering (5.28 vs 5.29) from the
  image-based run that produced the 427-WARN baseline, so raw totals are not comparable.

## Implementation Details

**Files Modified:** none (deploys only; the code was already on master as
`57c57983` for X11 and `4d3c717f` for the audit script).

**Testing & Verification:**
- ✅ Gate checked at 22:21 CET: `/var/log/security-audit/2026-11-24/SUMMARY.md`
  present after 2h38m; service no longer active.
- ✅ Servy audit result: 7 tools, **34/40 images scanned** (6 failures),
  **22 CRITICAL** (1 unfixed), **999 HIGH** (393 unfixed), Lynis **81/100**,
  23+ TLS endpoints graded A+.
- ✅ Combined deploy recap: `failed=0`, `unreachable=0`, 4 changes.
- ✅ On servy: `sshd -T → x11forwarding no`; drop-in line 13 `X11Forwarding no`;
  script renders `- **Host**: servy.lehel.xyz` and contains `tool_failed`;
  bench checkout `v1.6.1`; nuclei `x86-64` ELF (correct for this host).

**Key Learnings:**
- A running audit script must never be overwritten; gating on `SUMMARY.md` avoids
  corrupting a 2h38m scan.
- `docker.local_dir` follows the *controller's* main checkout branch, so any deploy
  from a worktree needs an explicit `-e docker_branch=<ref>` override — including
  the earlier bumbleflies rollout (see the CIS triage entry).
