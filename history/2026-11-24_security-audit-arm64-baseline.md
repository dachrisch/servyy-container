# ADR: Make the security audit baseline complete and correctly labelled on arm64

**Date:** 2026-11-24
**Status:** Accepted

## Context

The first security audit on `codey.lehel.xyz` (Oracle A1, aarch64) completed but
its baseline was incomplete and mislabelled:

- Docker Bench pulled `docker/docker-bench-security:latest`, whose manifest is
  **amd64-only** → `exec /usr/bin/dumb-init: exec format error`. No CIS Docker
  benchmark ran.
- `/usr/local/bin/nuclei` was a **x86-64 ELF** — `security_audit.yml` hardcoded
  `_linux_amd64.zip` in the download URL → `Exec format error`. No web-vuln scan ran.
- `security-audit.sh.j2` hardcoded `- **Host**: servy.lehel.xyz`, so codey's
  report claimed to be servy's.
- `generate_summary()` counted every enabled tool in "Tools Run" regardless of
  whether it succeeded, so the report claimed 7 tools when 2 produced nothing.

servy (x86_64) was unaffected by the two architecture issues but shared the wrong
host label and the overstated tool count.

## Decision

- Deploy Docker Bench from a **pinned source checkout** (`v1.6.1`) and run
  `docker-bench-security.sh` with the host's native Docker CLI. This removes both
  the amd64-only image dependency and the ancient bundled Docker client that
  previously needed a `DOCKER_API_VERSION` workaround.
- Map `ansible_architecture` → release arch (`aarch64`→`arm64`, `x86_64`→`amd64`)
  for the Nuclei download, and add a `nuclei -version` verification task so a
  wrong-arch binary fails the deploy loudly.
- Render the report host from `inventory_hostname` instead of a hardcoded string.
- Record `tool_failed=<name>` in `.tool-status` on non-zero tool exit and emit a
  "Tool Failures" section in the summary, so a silent failure can't read as coverage.

## Consequences

### Positive
- ✅ codey's baseline now covers all 7 tools on arm64, with the right host name.
- ✅ A wrong-arch nuclei binary or a failing tool can no longer masquerade as coverage.
- ✅ Docker Bench uses the host's current Docker client (no API-version workaround).

### Negative / Tradeoffs
- ⚠️ Docker Bench is now a root-owned git checkout under `/opt/security-audit`
  refreshed on each deploy (network dependency at deploy time).
- ⚠️ Same-day re-runs append to tool logs (e.g. `docker-bench.log` still contains
  the earlier failed image attempt), even though the report is regenerated.

## Implementation Details

**Files Modified:**
- `ansible/plays/vars/default.yml` (MODIFY) — `security_audit.docker_bench_version`
- `ansible/plays/roles/system/tasks/security_audit.yml` (MODIFY) — git checkout of
  the pinned bench source, arch map for nuclei, `nuclei -version` verification
- `ansible/plays/roles/system/templates/security-audit.sh.j2` (MODIFY) — source-run
  bench, `tool_failed` recording, dynamic host label, Tool Failures section
- `ansible/plays/roles/system/tests/test_security_audit_trivy.sh` (MODIFY) — host
  label assertion

**Commits:**
- `4d3c717f` fix(system): make security audit work on arm64 and report its real host
- *(this ADR)* docs: record the arm64 security-audit baseline fix

**Testing & Verification:**
- ✅ `test_security_audit_trivy.sh`: 33/33 checks (incl. new host-label assertion)
- ✅ Local Ansible assertions: arm64→`arm64`, x86_64→`amd64`; both release assets HTTP 200
- ✅ `ansible-playbook servyy.yml --syntax-check -i testing`; yamllint; ansible-lint
- ✅ Docker Bench from source proven on codey before deploy: 117 checks, exit 0
- ✅ Deploy to codey: `failed=0`, `unreachable=0`, 4 changes
- ✅ On codey after deploy: nuclei is an ARM aarch64 ELF running v3.11.1; bench
  checkout is `v1.6.1`; script reports `- **Host**: codey.lehel.xyz`
- ✅ Fresh codey audit finished 20:41: **all 7 tools ran**, **11/11 images scanned**,
  **0 CRITICAL / 73 HIGH**, Lynis **82/100** (up from 81), no Tool Failures section,
  Docker Bench logged 117 checks and Nuclei has no exec-format error.
- ⚠️ Molecule not run locally (no Docker socket); the baseline `system/core`
  scenario covers the change in CI.

**Key Learnings:**
1. The deploy checkout on codey sits on `master` at an older commit, while the
   Ansible templates are rendered from the controller — config changes apply even
   when the server's git checkout is stale.
2. `security-audit` runs as root, so a root-owned git checkout under
   `/opt/security-audit` is correct; a plain `cda` SSH check gets "Permission denied".
3. A fresh worktree lacks the gitignored `ansible/plays/vars/.*` seed files; the
   secret-seed guard correctly aborted the first deploy. Seeds must be copied from
   the owning checkout before deploying from a worktree.

## Alternatives Considered

### Alt A: Register qemu binfmt + run the amd64 image under emulation
Pros: keeps the container-based bench.
Cons: persistent kernel-level binfmt registration, slower emulated run, and still
the too-old bundled Docker client. **Rejected**

### Alt B: Skip Docker Bench / Nuclei on arm64
Pros: trivial.
Cons: silently leaves the baseline incomplete — the original problem. **Rejected**

### Alt C: Run the pinned upstream script from source (chosen)
Pros: native, arch-independent, current Docker CLI, pinned version. **Accepted**
