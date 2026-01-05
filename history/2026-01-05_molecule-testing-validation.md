# Molecule Testing Validation - System Role Scenarios

**Date**: 2026-01-05
**Branch**: `claude/add-github-actions-testing`
**Environment**: servyy-test.lxd (LXD container with Docker)
**Purpose**: Validate all system role Molecule scenarios on real infrastructure before integrating into GitHub Actions CI

## Executive Summary

Successfully validated all 4 system role Molecule scenarios on servyy-test. All scenarios pass with appropriate Docker container limitations handled through conditional task execution.

**Result**: ✅ READY FOR CI INTEGRATION

## Test Matrix

| Scenario | Status | Duration | Converge Tasks | Verify Tasks | Notes |
|----------|--------|----------|----------------|--------------|-------|
| **minimal** | ✅ PASS | 57.7s | 10 ok, 7 changed | 4 passed | Core user + journald config |
| **core** | ✅ PASS | 1m 53s | 24 ok, 17 changed | 10 passed | Adds packages + monit (Docker-aware) |
| **with-docker** | ✅ PASS | 1m 12s | 21 ok, 15 changed, 2 skipped | 12 passed | Cleanup scripts + timers (skip enablement in Docker) |
| **default** | ✅ PASS | 1m 46s | 15 ok, 10 changed | 8 passed | Full system with localization |

**Total Test Time**: ~5 minutes for all scenarios combined

## Scenario Descriptions

### system/minimal
- **Focus**: Minimal system configuration
- **Tasks**: User creation with sudo, journald retention config, logrotate configs
- **Use Case**: Testing basic user and logging setup without additional system components

### system/core
- **Focus**: Core system functionality without Docker runtime dependencies
- **Tasks**: Packages, user, journald, monit configuration
- **Docker Handling**: Monit service checks conditionally skipped when `ansible_virtualization_type == 'docker'`
- **Mock Variables**: monit (email/SMTP), restic (log paths), storagebox (mount point)
- **Use Case**: Testing full system role except Docker-dependent cleanup automation

### system/with-docker
- **Focus**: Docker and kernel cleanup automation
- **Tasks**: All from minimal + Docker cleanup script/service/timer + Kernel cleanup script/service/timer
- **Docker Handling**: Timer enablement conditionally skipped in Docker containers
- **Use Case**: Testing cleanup script deployment and systemd service/timer file creation

### system/default
- **Focus**: Full system configuration with localization
- **Tasks**: Packages (with locale support), user, journald
- **Localization**: Tests de_DE.utf8 locale generation
- **Skipped in Tests**: Timezone setting (tagged `molecule-notest`, doesn't work in Docker)
- **Use Case**: Testing complete system setup including localization features

## Changes Made During Validation

### 1. Docker Container Compatibility Fixes

**File**: `ansible/plays/roles/system/tasks/monit.yml`
**Change**: Added Docker detection to skip monit service checks
```yaml
when: ansible_virtualization_type | default('') != 'docker'
```
**Reason**: Monit can't verify SSH daemon files in Docker containers where SSH isn't running as a service

**Commit**: `af9ad93` - "fix: remove non working tests"

---

**File**: `ansible/plays/roles/system/tasks/docker_cleanup.yml`
**Change**: Skip docker-cleanup.timer enablement in Docker
```yaml
- name: Enable and start Docker cleanup timer
  systemd:
    name: docker-cleanup.timer
    enabled: true
    state: started
  become: true
  when: ansible_virtualization_type | default('') != 'docker'
```
**Reason**: Timer requires docker.service which doesn't exist in Docker test containers

**Commit**: `5f82458` - "fix(molecule): skip cleanup timer enablement in Docker containers"

---

**File**: `ansible/plays/roles/system/tasks/kernel_cleanup.yml`
**Change**: Skip kernel-cleanup.timer enablement in Docker (same pattern as above)
**Commit**: `5f82458` (same commit)

### 2. Template Resolution Fixes

**File**: `ansible/plays/roles/system/molecule/default/converge.yml`
**Change**: Replaced `import_tasks` with `include_role` using playbook_dir pattern
```yaml
# Before:
- name: Import packages tasks
  import_tasks: ../../tasks/packages.yml

# After:
- name: Run packages tasks  # noqa: role-name[path]
  ansible.builtin.include_role:
    name: "{{ playbook_dir }}/../../"
    tasks_from: packages
```
**Reason**: import_tasks breaks template lookup (searches tasks/templates/ instead of role's templates/)

**Commit**: `568109b` - "fix(molecule): use include_role pattern in system/default scenario"

### 3. Verification Adjustments

**File**: `ansible/plays/roles/system/molecule/with-docker/verify.yml`
**Change**: Corrected docker-cleanup script path from `/usr/local/bin/` to `/home/testuser/.cleanup-scripts/`
**Commit**: `c2f5724` - "fix(molecule): correct docker-cleanup script path in with-docker verify"

---

**File**: `ansible/plays/roles/system/molecule/default/verify.yml`
**Change**: Removed timezone verification check (timezone task tagged `molecule-notest`)
**Commit**: `6a9e958` - "fix(molecule): remove timezone verification from system/default"

### 4. Mock Variables Added

**File**: `ansible/plays/roles/system/molecule/core/converge.yml`
**Added Variables**:
- `monit` (email, SMTP settings) - for monit alert configuration
- `restic` (log file paths) - for backup log monitoring
- `storagebox` (mount point) - for storage monitoring

These mock variables satisfy template requirements without needing real infrastructure.

## Known Limitations

### 1. Monit Service Checks
**Limitation**: Monit can't verify SSH daemon in Docker containers
**Impact**: Monit assertions skipped when running in Docker
**Solution**: Conditional execution based on `ansible_virtualization_type`
**Production Impact**: None - monit works correctly on real servers

### 2. Systemd Timer Enablement
**Limitation**: Docker containers can't start timers that depend on docker.service or require full systemd
**Impact**: Timer enablement steps skipped in tests
**Solution**: Files are still deployed and tested; only `systemctl enable/start` is skipped
**Production Impact**: None - timers work correctly on real servers with full systemd

### 3. Timezone Configuration
**Limitation**: Timezone setting is unreliable in Docker containers (inherits from host)
**Impact**: Timezone task tagged `molecule-notest` and not verified
**Solution**: Task has `failed_when: false` and is skipped in tests
**Production Impact**: None - timezone setting works on real servers

### 4. Infrastructure Dependencies Not Tested
**Not Tested in Molecule**:
- fail2ban (requires real log files and network access)
- storagebox mount (requires CIFS server)
- extension_drive (requires real block device)
- swap creation (disabled in tests)
- restic backups (requires real backup infrastructure)

**Reason**: These require external infrastructure that can't be mocked in Docker
**Validation**: These components are tested during actual deployments to lehel.xyz

## Technical Insights

### Docker-in-Docker Considerations
- Tests run in privileged Docker containers with `cgroupns_mode: host` for systemd support
- Python 3.13 virtual environment used for Molecule and Ansible
- Tests use `geerlingguy/docker-ubuntu2204-ansible:latest` base image

### Conditional Execution Pattern
All Docker-incompatible tasks use this pattern:
```yaml
when: ansible_virtualization_type | default('') != 'docker'
```

This allows tests to validate:
- File deployment (scripts, configs, service files)
- Template rendering
- Configuration correctness

While gracefully skipping:
- Service enablement/starting
- System-level checks that require real hardware/services

### include_role vs import_tasks
**Pattern Used**: `include_role` with `playbook_dir` for template resolution
```yaml
ansible.builtin.include_role:
  name: "{{ playbook_dir }}/../../"
  tasks_from: <task_file>
```

**Why Not import_tasks**: Breaks template lookup path (searches relative to task file location)

**Lint Suppression**: `# noqa: role-name[path]` required because path is dynamic

## Recommendations

### For GitHub Actions CI Integration

**Phase 6 Action Items**:

1. **Update `.github/workflows/ci.yml`**:
   - Uncomment molecule-test job
   - Add all 4 validated scenarios to matrix:
     ```yaml
     matrix:
       include:
         - role: system
           scenario: minimal
         - role: system
           scenario: core
         - role: system
           scenario: with-docker
         - role: system
           scenario: default
     ```

2. **Ensure Mock Variables Present**:
   - Verify "Create mock encrypted files" step includes all mock variables
   - Particularly: `monit`, `restic`, `storagebox` configurations

3. **Conservative Approach**:
   - Start with all 4 scenarios (all validated and passing)
   - Monitor CI stability for first few runs
   - If issues arise, can reduce to minimal+core as baseline

4. **Expected CI Behavior**:
   - Each scenario should complete in ~1-2 minutes
   - Total matrix run time: ~5-8 minutes (parallel execution)
   - No failures expected based on servyy-test validation

### Maintenance Recommendations

1. **New System Tasks**:
   - Add `when: ansible_virtualization_type != 'docker'` for tasks requiring:
     - Real systemd services (not mocked in Docker)
     - Hardware access (block devices, network interfaces)
     - System-level permissions Docker doesn't provide

2. **Template-Using Tasks**:
   - Always use `include_role` with `playbook_dir` pattern in Molecule scenarios
   - Never use `import_tasks` for tasks that use templates

3. **Verification Tests**:
   - Only verify what was actually configured (respect `molecule-notest` tags)
   - Test file existence and content, not runtime behavior in Docker
   - Use `check_mode` where possible to avoid state changes in verify phase

## Files Modified

### Task Files (Production Code)
- `ansible/plays/roles/system/tasks/monit.yml` - Added Docker skip conditions
- `ansible/plays/roles/system/tasks/docker_cleanup.yml` - Added Docker skip for timer enablement
- `ansible/plays/roles/system/tasks/kernel_cleanup.yml` - Added Docker skip for timer enablement

### Molecule Scenario Files (Test Code)
- `ansible/plays/roles/system/molecule/core/converge.yml` - Added mock variables
- `ansible/plays/roles/system/molecule/default/converge.yml` - Changed to include_role pattern
- `ansible/plays/roles/system/molecule/with-docker/verify.yml` - Fixed script path
- `ansible/plays/roles/system/molecule/default/verify.yml` - Removed timezone check

## Success Criteria - All Met ✅

- ✅ At least 2 system role scenarios (minimal + core) pass completely on servyy-test
  - **Actual**: All 4 scenarios pass
- ✅ All mock variables documented and working
  - **Documented**: In this file and in converge.yml files
- ✅ Test results documented in history/
  - **This file**: history/2026-01-05_molecule-testing-validation.md
- ✅ GitHub Actions workflow ready for update with validated scenarios
  - **Ready**: All scenarios validated, recommendations provided
- ✅ CI should pass on first run after integration
  - **Expected**: High confidence based on servyy-test validation

## Next Steps

1. ✅ **Phase 5 Complete**: Documentation created
2. ⏳ **Phase 6 Pending**: Update GitHub Actions workflow
   - Uncomment molecule-test job in `.github/workflows/ci.yml`
   - Add validated scenarios to matrix
   - Commit and push changes
   - Monitor first CI run

## Conclusion

All system role Molecule scenarios are now production-ready for CI integration. The validation process identified and resolved critical issues:

1. **Docker container limitations** properly handled through conditional execution
2. **Template resolution** fixed by standardizing on include_role pattern
3. **Mock variables** correctly configured for infrastructure dependencies
4. **Verification tests** aligned with what's actually tested

**Confidence Level**: HIGH - All scenarios pass cleanly with appropriate Docker handling.

**Risk Assessment**: LOW - Changes are defensive (skip when can't work) and don't affect production behavior.

**Recommendation**: Proceed with Phase 6 (CI integration) immediately.
