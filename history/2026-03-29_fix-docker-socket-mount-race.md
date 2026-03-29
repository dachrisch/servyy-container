# 2026-03-29 Fix Docker Socket Bind Mount Race Condition

## Problem

On LXD containers with systemd 257, the SSH chroot jail's Docker socket bind mount
(`var-jail-var-run-docker.sock.mount`) would intermittently leave `/run/docker.sock`
as an empty **directory** on the host, which permanently blocked Docker from starting.

### Root Cause (confirmed by boot journal)

**Exact failure sequence on Mar 28 boot:**
1. `sysinit.target` reached at 21:27:37
2. Mount unit (`WantedBy=multi-user.target`) fired at 21:27:37
3. `docker.socket` had NOT yet activated — `containerd.sock` was only created at 21:27:38
4. `/run/docker.sock` did not exist when systemd 257 processed the mount unit
5. **systemd 257 auto-creates the `What=` bind-mount source path as a directory** when
   the path does not exist
6. `/run/docker.sock` became an empty directory on tmpfs
7. Bind mount failed: `mount: /var/jail/var/run/docker.sock: mount point is not a directory`
   (kernel rejects binding a directory onto a regular file)
8. `docker.socket` then failed permanently: `Failed to create listening socket
   (/run/docker.sock): Address already in use` (the directory blocks socket creation)

### Why the previous partial fix (workdir) didn't recover

The workdir had already added `After=docker.socket` + `Requires=docker.socket` to the
mount unit (correct prevention), but the Ansible run deployed this fix AFTER the directory
was created during the Mar 28 boot. Since `/run/docker.sock` persists on tmpfs until
reboot and no cleanup was added, `docker.socket` remained broken.

### Secondary issues found

**`creates:` Ansible bug:** The task used:
```yaml
command: "rm -rf .../docker.sock && touch .../docker.sock"
args:
  creates: "{{ ssh_chroot_jail_path }}/var/run/docker.sock"
```
The `creates:` check skips the task when the path exists — even as a directory. This
prevented Ansible from self-healing a broken jail-side mount point.

**`BindsTo=docker.service` shutdown cycle:** Combining `BindsTo=docker.service` with
`After=docker.service` on a `.mount` unit creates an ordering cycle on shutdown:
`docker.service/stop → mount/stop → local-fs.target/stop → sysinit.target/stop →
basic.target/stop → docker.service/stop`. systemd broke this cycle by deleting the
`docker.service/stop` job, leaving Docker un-stopped cleanly.

## Fix

### 1. Mount unit (`templates/docker.mount.j2`)
- Keep `After=docker.socket` + `Requires=docker.socket` — ensures docker.socket has
  already created the real socket file before the mount unit runs
- Replace `BindsTo=docker.service` + `After=docker.service` with `PartOf=docker.service`
  — propagates stop/restart one-way without the shutdown ordering cycle
- Add `DefaultDependencies=no` — removes implicit `.mount` unit deps on
  `local-fs.target`/`umount.target` that caused the shutdown cycle

### 2. Ansible task (`tasks/add_to_docker.yaml`)
- **Host-side cleanup:** Detect and remove `/run/docker.sock` if it is a directory,
  stop/reset docker.socket, then restart it
- **Jail-side fix:** Replace `creates:`-gated command with `stat` check + `file: state:
  touch` — always ensures the mount point is a regular file, not a directory
- **Reset failed state:** Run `systemctl reset-failed` after cleanup so
  `systemctl start` succeeds

## Files Changed

- `ansible/plays/roles/ls_setup/templates/docker.mount.j2`
- `ansible/plays/roles/ls_setup/tasks/add_to_docker.yaml`

## Verification

After deploying to `servyy-test.lxd`:
1. `/run/docker.sock` should be a Unix socket (not a directory)
2. `systemctl status docker.socket` should show `active (listening)`
3. `systemctl status var-jail-var-run-docker.sock.mount` should show `active (mounted)`
4. Reboot and verify both units start correctly on the next boot
