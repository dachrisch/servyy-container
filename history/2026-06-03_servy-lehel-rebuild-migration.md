# servy.lehel.xyz Rebuild and Migration - June 3, 2026

## Overview
Rebuilt servy.lehel.xyz during migration from previous `bigservy.lehel.xyz` infrastructure. Encountered and resolved multiple infrastructure and automation issues.

**Status:** ✅ Complete - All services deployed and backups running

---

## Issues Encountered & Solutions

### 1. Git-Crypt Submodule Recursion with Hardcoded Variables

**Problem:**
- Ansible deployment tried to clone submodules (`me/website` from git.lehel.xyz) even when git.lehel.xyz was unreachable
- The `clone_submodules: true` variable was hardcoded in caller (main.yml), overriding the reachability check
- Result: Deployment failed trying to clone from unreachable git server

**Root Cause:**
```yaml
# In repository.yml (line 35):
recursive: "{{ clone_submodules | default(git_servyy_reachable) }}"

# In main.yml caller:
clone_submodules: true  # ← Always true, ignores reachability!
```

**Solution:**
Updated the condition to respect reachability even when `clone_submodules` is set:
```yaml
# Fixed line 35 in repository.yml:
recursive: "{{ clone_submodules | default(true) and git_servyy_reachable == 'yes' }}"
```

**Learning:** Variable defaults in conditionals are overridden by explicit values. When a variable controls behavior conditionally, AND it with the dependency check, not OR.

---

### 2. SSH Chroot Jail Path Formatting Issues

**Problem:**
- Handler tried to copy libraries to `/var/jail//lib/x86_64-linux-gnu/` (double slash)
- Directory creation failed because the parent path `/var/jail/lib/x86_64-linux-gnu/` didn't exist
- Result: ssh-chroot-jail role failed during handler execution

**Root Cause:**
Paths in `extra_ssh_chroot_jail_dirs` started with `/`, causing double slashes when concatenated:
```yaml
extra_ssh_chroot_jail_dirs:
  - /usr/lib/x86_64-linux-gnu  # Starts with /
  - /etc/ssl                    # Starts with /
```

When used in task: `{{ ssh_chroot_jail_path }}/{{ item }}` → `/var/jail//usr/lib/x86_64-linux-gnu/`

**Also:** The `/lib/x86_64-linux-gnu` directory was missing entirely from the jail directories list.

**Solution:**
```yaml
# Fixed ssh_jail.yaml:
extra_ssh_chroot_jail_dirs:
  - lib/x86_64-linux-gnu        # Relative path, no leading /
  - usr/lib/x86_64-linux-gnu
  - etc/ssl
  - usr/libexec/docker
  - tmp
```

**Learning:** Directory paths in Ansible should be relative when they'll be concatenated with a base path. Leading slashes cause double-slash issues and confusion.

---

### 3. Restic Backup Configuration Pointing to Old Server

**Problem:**
- Restore succeeded but restored empty git/repos directory
- Investigation showed git/repos backed up as empty directory
- Root cause: `env.home` restic configuration pointed to old `bigservy.lehel.xyz` backup location

**Why This Happened:**
During migration from `bigservy.lehel.xyz` to `lehel.xyz`:
- Server DNS/hostname changed
- Restic env files needed to be updated to point to correct backup location
- Ansible deployment didn't catch this configuration dependency

**Solution:**
User manually updated `/etc/restic/env.home` to point to correct lehel.xyz backup repository location, then re-ran restore with correct backup source.

**Learning:** 
- Server migrations require audit of configuration files that reference hostname/location
- Restic backup configurations are critical path - must validate after migration
- Consider adding pre-deployment validation checks for backup configuration consistency

---

### 4. Ansible Boolean String Handling in Conditions

**Problem:**
When passing `-e "with_containers=true"` on CLI, Ansible received string `"true"` not boolean
- Conditional `when: with_containers | default(false)` expected boolean
- Error: "Conditional result (True) was derived from type 'str'"

**Solution:**
Updated all restore task conditions to use `| bool` filter:
```yaml
# Before (failed with string):
when: with_containers | default(false)

# After (handles strings):
when: (with_containers | default(false)) | bool
```

**Learning:** CLI `-e` parameters are always strings. Use `| bool` filter to convert when conditionals need boolean values. Alternatively, pass as `-e 'with_containers=True'` (capital T for YAML boolean).

---

### 5. Force Restore Feature Development

**Feature Added:**
Created `force_restore` option to override "directory not empty" safety check and automatically stop running containers.

**Implementation:**
- Added `force_restore | default(false) | bool` to restore decision logic
- Added task to `docker compose down` when `force_restore=true` and containers are running
- Added re-verification of container status after stopping
- Logs warning: `⚠️ FORCING RESTORE: Target directory is not empty`

**Usage:**
```bash
./servyy.sh --limit lehel.xyz -t restic.restore -e "with_containers=true" -e "force_restore=true"
```

**Safeguards:**
- Still respects "containers running" check (won't restore while services are active)
- Automatically stops containers before attempting restore
- Logs all decisions for audit trail

---

### 6. User-Scoped vs System-Scoped Systemd Services

**Discovery:**
Backup timers created during deployment were in user scope (`~/.config/systemd/user/`), not system scope (`/etc/systemd/system/`)

**Why This Design:**
Restic backups run as the `cda` user (not root), so systemd services are user-scoped:
- `restic-backup-home.timer` (user scope, hourly)
- `restic-backup-root.timer` (user scope, daily)

Check with: `systemctl --user list-timers` (not `sudo systemctl list-timers`)

**Learning:** Different services have different privilege requirements. User-scoped systemd services are appropriate for user backup tools. Know which scope to check when debugging.

---

## Deployment Verification

**Full Deployment Results:**
```
lehel.xyz: ok=339  changed=56  unreachable=0  failed=0  skipped=134
```

**Restore Tasks:** Correctly skipped (directories already had data)
```
⏭️  SKIPPED: git/repos (manually restored earlier)
⏭️  SKIPPED: photoprism/database (not empty)
⏭️  SKIPPED: vaultwarden/pass/vw-data (not empty)
```

**Backup Status:** ✅ Running
```
restic-backup-home.timer:   Every hour at :00  (last: 12:01 UTC)
  └─ Last backup: 6391 files, 1.381 GiB, +1.079 GiB added
restic-backup-root.timer:   Nightly at 00:01 UTC (next run tonight)
```

---

## Code Changes Made

### 1. Git-Crypt Submodule Recursion Fix
**File:** `ansible/plays/roles/user/tasks/includes/repository.yml`
```yaml
# Line 35: Changed from:
recursive: "{{ clone_submodules | default(git_servyy_reachable) }}"
# To:
recursive: "{{ clone_submodules | default(true) and git_servyy_reachable == 'yes' }}"
```
**Commit:** fb547e2

### 2. SSH Chroot Jail Path Fix
**File:** `ansible/plays/vars/ssh_jail.yaml`
```yaml
# Removed leading slashes and added missing lib/x86_64-linux-gnu directory
extra_ssh_chroot_jail_dirs:
  - lib/x86_64-linux-gnu           # NEW
  - usr/lib/x86_64-linux-gnu       # Changed: /usr → usr
  - etc/ssl                        # Changed: /etc → etc
  - usr/libexec/docker             # Changed: /usr → usr
  - tmp                            # Changed: /tmp/ → tmp
```
**Commit:** bf8b6f9

### 3. Boolean String Handling in Restore
**File:** `ansible/plays/roles/restic/tasks/main.yml`
```yaml
# Lines 35, 46, 57: Added | bool filter
when: (with_containers | default(false)) | bool
```
**Commit:** be8462b

### 4. Force Restore Feature
**File:** `ansible/plays/roles/restic/tasks/restore.yml`
- Updated restore decision logic to include `force_restore` override
- Added container stopping task with force_restore condition
- Added force override logging
- Added re-verification of container status
**Commit:** c18ebc0, 0c7a68f

---

## Key Learnings Summary

1. **Variable Defaults**: When combining multiple boolean conditions, use AND operators to respect dependencies, not defaults
2. **Path Construction**: Relative paths prevent double-slash issues when concatenated with base paths
3. **Server Migrations**: Audit all configuration files that reference hostname, domain, or server location
4. **Restic Backups**: Backup configuration changes require validation - test restore against correct source after migration
5. **CLI Parameters**: Always string; use `| bool` filter or capital-T `True` for booleans in conditions
6. **Force Options**: Implement with care - include safety checks (logging, warnings, guard conditions)
7. **Systemd Scopes**: User-scoped services check with `--user` flag, system-scoped with `sudo`

---

## Deployment Checklist for Similar Migrations

- [ ] Update restic env files to point to correct backup location
- [ ] Validate git-crypt configuration and unlock status on both old and new servers
- [ ] Audit configuration files for server hostname/location references
- [ ] Test restore from correct backup source before full deployment
- [ ] Run full deployment with `-e "with_containers=true"` to trigger restore tasks
- [ ] Verify backup timers are running: `systemctl --user list-timers | grep restic`
- [ ] Check recent backup logs: `tail -30 /var/log/restic/backup-home.log`

---

## Files Modified
- `ansible/plays/roles/user/tasks/includes/repository.yml` (git-crypt fix)
- `ansible/plays/vars/ssh_jail.yaml` (chroot jail paths)
- `ansible/plays/roles/restic/tasks/main.yml` (boolean filtering)
- `ansible/plays/roles/restic/tasks/restore.yml` (force restore feature)

**Total Commits:** 4
**All Changes Reviewed:** ✅ Yes
**Deployment Status:** ✅ Successful
