# runc LXC/Docker Compatibility Fix

**Date:** 2025-12-01
**Author:** Claude Code
**Type:** Security Workaround
**Status:** Deployed

## Problem Statement

A security fix for CVE-2025-52881 in runc 1.3.3 breaks Docker inside LXC containers due to AppArmor profile conflicts with detached procfs mounts.

**Affected Version:** runc 1.3.3-0ubuntu1~25.04.3
**Environment:** Docker running inside LXC containers (servyy-test.lxd)

### Symptoms

- Docker containers fail to start
- AppArmor permission denied errors related to procfs mounts
- `net.ipv4.ip_unprivileged_port_start` errors

## Root Cause

The CVE-2025-52881 fix in runc 1.3.3 introduced stricter AppArmor profile handling that conflicts with LXC's nested container environment. The fix prevents certain procfs mount operations that are required for Docker to function inside an LXC container.

## Solution Applied

### Manual Fix

1. Downgrade runc from 1.3.3-0ubuntu1~25.04.3 to 1.2.5-0ubuntu1:
   ```bash
   sudo apt install runc=1.2.5-0ubuntu1
   ```

2. Hold the package to prevent automatic upgrades:
   ```bash
   sudo apt-mark hold runc
   ```

### Ansible Automation

The fix is now automated via Ansible for the test environment:

- **Task file:** `ansible/plays/roles/testing/tasks/runc_lxc_fix.yml`
- **Target:** servyy-test.lxd (LXC test container)
- **Behavior:**
  - Downgrades runc to 1.2.5 if problematic version detected
  - Holds the package to prevent upgrades
  - Auto-unholds when safe version (>= 1.4.0) becomes available

## Verification

```bash
# Check runc version and hold status
ssh servyy-test.lxd "dpkg -l runc && apt-mark showhold | grep runc"

# Verify Docker works
ssh servyy-test.lxd "docker run --rm hello-world"
```

## Rollback Procedure

When a fixed version of runc is available that works with LXC:

```bash
ssh servyy-test.lxd "sudo apt-mark unhold runc && sudo apt update && sudo apt upgrade runc"
```

Or simply update the `runc_safe_version` variable in Ansible - the automation will auto-unhold.

## Sources

- https://forum.proxmox.com/threads/docker-inside-lxc-net-ipv4-ip_unprivileged_port_start-error.175437/
- https://github.com/opencontainers/runc/issues/4968
- https://github.com/lxc/incus/issues/2623

## Impact Assessment

| Component | Impact |
|-----------|--------|
| Production (lehel.xyz) | None - not an LXC environment |
| Test (servyy-test.lxd) | Fixed - Docker now works |
| Security | Temporary use of older runc version |

## Next Steps

- Monitor upstream runc releases for LXC-compatible fix
- Update `runc_safe_version` when fixed version is released
- Consider removing this workaround entirely once fix is stable
