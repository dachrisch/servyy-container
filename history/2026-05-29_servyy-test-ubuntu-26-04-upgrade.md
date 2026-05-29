# 2026-05-29_servyy-test-ubuntu-26-04-upgrade.md

## Context
The `servyy-test` LXD container was previously using an older Ubuntu release (likely 24.04). Attempting to run `do-release-upgrade` inside the container proved problematic due to shell syntax errors and potential conflicts with the LXD environment.

The host system is already running Ubuntu 26.04 LTS (Resolute Raccoon).

## Changes
- Modified `scripts/setup_test_container.sh` to support the `UBUNTU_VERSION` environment variable.
- Defaulted the container image to match the host's version (`26.04`).
- Updated the `lxc launch` command to use the specified version.

## Upgrade Plan
To upgrade the test environment to Ubuntu 26.04:

1. **Purge existing container**:
   ```bash
   ./scripts/setup_test_container.sh -x
   ```

2. **Recreate with 26.04**:
   ```bash
   ./scripts/setup_test_container.sh
   ```
   *Note: Since the host is 26.04, it will default to 26.04. You can also force a version via `UBUNTU_VERSION=26.04 ./scripts/setup_test_container.sh`.*

3. **Reprovision**:
   ```bash
   cd ansible && ./servyy-test.sh
   ```

## Verification
- Run `ssh servyy-test.lxd "cat /etc/os-release"` to confirm the version.
- Ensure all microservices start correctly under the new kernel/LTS.
