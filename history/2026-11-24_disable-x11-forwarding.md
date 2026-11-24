# ADR: Make X11Forwarding an explicit global hardening setting

**Date:** 2026-11-24
**Status:** Accepted
**Relates to:** Host Hardening (2026-10-08)

## Context

The 2026-11-24 status check found `X11Forwarding yes` on `codey.lehel.xyz` and
`X11Forwarding no` on `servy.lehel.xyz`. Neither value was managed by Ansible:

- `hardening.ssh` in `ansible/plays/vars/default.yml` set `PermitRootLogin`,
  `MaxAuthTries`, `MaxSessions`, `ClientAliveCountMax`, `LogLevel`, `TCPKeepAlive`,
  `AllowTcpForwarding` and `AllowAgentForwarding` — but **not** `X11Forwarding`.
- The two values came from each host's base image `/etc/ssh/sshd_config` line 113.
  servy (Hetzner image) shipped `no`; codey (Oracle A1 cloud image) shipped `yes`.
- The only `X11Forwarding no` directives in the repo were inside narrow `Match`
  blocks (`ls_dbeaver_access`, `forgejo_bootstrap`) that do not apply to the
  general SSH login path.

Because `/etc/ssh/sshd_config` includes `/etc/ssh/sshd_config.d/*.conf` at the top
and sshd uses the **first** value obtained, the drop-in wins. The gap let the
base-image default survive on codey, so a hardening setting was effectively
host-dependent and neither host was covered by a regression test.

## Decision

Added `X11Forwarding: no` to `hardening.ssh` so the Ansible drop-in declares one
global value on every host and overrides whichever distro default the image
shipped. Extended the existing `system/core` Molecule regression guard to assert
both that the rendered drop-in contains `X11Forwarding no` **and** that the real
`hardening.ssh` defaults still declare it (so deleting it fails CI).

No new role, no new Molecule scenario and no inventory changes were needed.
Existing `Match` blocks keep their own `X11Forwarding no` and remain unaffected.

## Consequences

### Positive
- ✅ SSH forwarding policy is identical on both production hosts.
- ✅ The base-image difference can no longer reintroduce `yes`.
- ✅ Rendered drop-in and the declaring default are both covered by the baseline
  `system/core` scenario (runs on every Ansible change).

### Negative / Tradeoffs
- ⚠️ Any workflow that genuinely needs X11 forwarding over SSH would now need an
  explicit `Match` block; none is known to exist (local `-L` tunnels are preserved
  independently by `AllowTcpForwarding local`).

## Implementation Details

**Files Modified:**
- `ansible/plays/vars/default.yml` (MODIFY) — `hardening.ssh.X11Forwarding: no`
- `ansible/plays/roles/system/molecule/core/converge.yml` (MODIFY) — sample var
- `ansible/plays/roles/system/molecule/core/verify.yml` (MODIFY) — two assertions

**Commits:**
- `57c57983` fix(system): declare X11Forwarding no globally in SSH hardening

**Testing & Verification:**
- ✅ Local render test failed before the change ("X11Forwarding is not globally
  declared") and passed after (`X11Forwarding no` present in rendered drop-in).
- ✅ `ansible-playbook servyy.yml --syntax-check -i testing`
- ✅ `yamllint` on all three changed files; `ansible-lint` on the Molecule files
- ✅ Local Ansible assertion playbook: "All assertions passed" against the real defaults
- ✅ Deploy `./servyy.sh --tags system.hardening --limit codey.lehel.xyz`:
  `failed=0`, `unreachable=0`, `changed=2`
- ✅ On codey: `sshd -T` → `x11forwarding no`, and drop-in line 13 → `X11Forwarding no`
- ⚠️ Molecule itself could not run locally (no Docker socket); CI runs the
  baseline `system/core` scenario on this change.

**Key Learnings:**
1. `sshd` takes the **first** value for a keyword. The top-of-file `Include` means
   drop-ins override the base image's main config — which is how
   `PermitRootLogin prohibit-password` already overrode `PermitRootLogin yes` on
   servy, and how this fix overrides the Oracle image's `X11Forwarding yes`.
2. A "render the template with sample vars" test only proves the template works;
   a second assertion reading the real `default.yml` is what catches deletion of
   the declaring setting.
3. The hardening drop-in is rendered from the **controller's** checkout, so it
   applies even though codey's `/home/cda/servyy-container` checkout sits on an
   older `master` commit with local modifications (pre-existing state, not created
   by this change).

## Alternatives Considered

### Alt A: Edit `/etc/ssh/sshd_config` on codey by hand
Pros: one-line immediate fix.
Cons: violates the no-manual-server-edits rule, untracked, reverted on deploy.
**Rejected**

### Alt B: Add a codey-only host var
Pros: targets the affected host.
Cons: leaves the policy host-dependent — the exact failure mode being fixed.
**Rejected**

### Alt C: Declare it in `hardening.ssh` (chosen)
Pros: one source of truth, all hosts, covered by an existing baseline test.
**Accepted**
