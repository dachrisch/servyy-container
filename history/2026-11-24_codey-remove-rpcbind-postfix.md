# ADR: Remove unused rpcbind and Postfix from codey

**Date:** 2026-11-24
**Status:** Accepted

## Context

The 2026-11-24 security audit on `codey.lehel.xyz` found two host services that
exposed ports for no reason:

- `rpcbind` was active on `0.0.0.0:111`/`[::]:111`, but there are no NFS mounts in
  `/etc/fstab`, no active mounts, and no RPC programs registered beyond portmapper
  itself. `nfs-common` was the only installed reverse dependency.
- Postfix was active on `0.0.0.0:25` and was the sole source of the audit's only
  Lynis warning (`MAIL-8818` — SMTP banner disclosed Ubuntu + Postfix). Nothing
  needed inbound SMTP: monit alerts go directly to `smtp.gmail.com` via
  `monit.alert.j2`, and no crontab sets `MAILTO`.

## Decision

Add a per-host `system_packages_absent` list under `codey.lehel.xyz` in
`ansible/production` and one idempotent purge task in the `system` role's
`packages.yml`, tagged `system.packages.remove`.

The list is **`[rpcbind, postfix, bsd-mailx]`** — not just Postfix. `bsd-mailx`
has a hard dependency on a `mail-transport-agent`; a simulation of
`apt purge postfix` alone showed apt would install 14 packages and bring in
**Courier MTA** as a replacement. Purging all three removed 4 packages and
installed 0. `monit` and `cron` only *Suggest* an MTA, so they are unaffected.

No separate mask/stop task is needed: dpkg stops and removes the service units
with the package, and `state: absent` is a no-op on re-runs.

## Consequences

### Positive
- ✅ Ports 25 and 111 are no longer exposed on the internet-facing ARM host.
- ✅ No SMTP version/OS disclosure (Lynis warning gone).
- ✅ No replacement MTA crept in; monitored mail still works via external SMTP.

### Negative / Tradeoffs
- ⚠️ Local mail delivery (`mail`, sendmail-compatible `/usr/sbin/sendmail`) is no
  longer available on codey. Verified unused before removal.
- ⚠️ `nfs-common` was removed as a reverse dependency of `rpcbind` — an NFS mount
  added later would need both packages reinstalled.

## Implementation Details

**Files Modified:**
- `ansible/production` (MODIFY) — `system_packages_absent` under `codey.lehel.xyz`
- `ansible/plays/roles/system/tasks/packages.yml` (MODIFY) — purge task with
  `system.packages.remove` tag
- `ansible/plays/roles/system/molecule/core/verify.yml` (MODIFY) — guard asserting
  the list stays empty in the test container

**Commits:**
- `d665b08a` fix(system): drop unused rpcbind and Postfix from codey
- *(this ADR)* docs: record the codey service removal

**Testing & Verification:**
- ✅ Simulated `apt-get -s purge postfix rpcbind` first — caught the Courier MTA
  trap (0 installed only after adding `bsd-mailx`).
- ✅ Local Ansible assertions: var defaults empty, configured set is exactly the
  three intended packages; syntax check, yamllint and ansible-lint pass.
- ✅ Deploy `./servyy.sh --tags system.packages.remove --limit codey.lehel.xyz`:
  `failed=0`, `unreachable=0`, 1 change.
- ✅ Post-deploy: `ss -lntp` shows no listeners on 25 or 111; `dpkg -l` shows no
  postfix/rpcbind/bsd-mailx or replacement MTA; monit active with all checks OK;
  cron active.

**Key Learnings:**
1. `apt-cache rdepends --installed postfix` listing `monit` is misleading: monit
   only *Suggests* an MTA; it is configured with its own SMTP server.
2. Removing a virtual-provider package can **install** its alternatives. Always
   run `apt-get -s purge <set>` before encoding it in Ansible.
3. A per-host var plus one tagged task keeps a host-specific cleanup out of the
   shared package list and safe for Molecule (empty by default).
