# Plan: Fix Docker Socket Bind Mount Race Condition

The current systemd mount unit `var-jail-var-run-docker.sock.mount` can start before `docker.socket` has created the actual socket file at `/var/run/docker.sock`. When this happens, systemd may pre-create the source path as a directory to satisfy mount requirements, which then blocks Docker from starting because it cannot create its socket over a directory.

## Proposed Changes

### 1. Update systemd Mount Unit Template
Modify `ansible/plays/roles/ls_setup/templates/docker.mount.j2` to explicitly depend on `docker.socket`.

- Add `After=docker.socket` and `Requires=docker.socket` to the `[Unit]` section.
- Keep `BindsTo=docker.service` to ensure the mount is managed with the service.

### 2. Refine Ansible Tasks
Ensure the jail-side mount point is handled correctly in `ansible/plays/roles/ls_setup/tasks/add_to_docker.yaml`.

- Ensure the directory `/var/jail/var/run/` exists.
- Ensure `/var/jail/var/run/docker.sock` is a file (using `touch`).

## Verification Plan

### Automated Tests
- Run molecule tests for the `ls_setup` role if available.
- Deploy to `servyy-test.lxd` and verify:
    1. `/var/run/docker.sock` is a socket on the host.
    2. `/var/jail/var/run/docker.sock` is a socket (bind-mounted) in the jail.
    3. Docker starts successfully after a reboot.

### Manual Verification
- Reboot the test container and check `systemctl status var-jail-var-run-docker.sock.mount` and `systemctl status docker`.
- Verify no directory exists at `/var/run/docker.sock` before Docker starts (simulated by stopping docker and removing the socket).
