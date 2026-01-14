# PhotoPrism Memory Optimization & Infrastructure Robustness

**Date:** 2026-01-14
**Author:** Claude Code (AI Agent)
**Type:** Optimization, Bug Fix, Robustness
**Status:** ✅ Validated on Test (servyy-test.lxd) | ⏳ Ready for Prod

## Summary

This update focuses on stabilizing the production server by optimizing PhotoPrism's memory footprint and improving the overall robustness and idempotency of the Ansible infrastructure.

**Key results:**
- Reduced PhotoPrism swap usage on test system from ~1.4 GiB to ~74 MiB.
- Achieved full idempotency across all 22 major Ansible tags.
- Resolved long-standing Monit alerting issues.

## Reason for Changes

1.  **Memory Pressure:** PhotoPrism was consuming nearly 100% of available swap (1.9Gi / 2.1Gi) on the production server due to the Go runtime's "lazy" memory management during indexing tasks.
2.  **Infrastructure Noise:** Multiple Ansible tasks were reporting "changed" on every run, making it difficult to spot real configuration drifts.
3.  **Monitoring Failures:** Monit was reporting false negatives for SSH monitoring ("Program does not exist: service") and storagebox mounts on test systems.
4.  **Technical Debt:** Resolved numerous Ansible deprecation warnings regarding top-level facts and internal dictionaries.

---

## Detailed Changes

### 1. PhotoPrism Optimization (`photoprism/docker-compose.yml`)
- Added `GOGC: 50` to trigger more frequent garbage collection.
- Added `GOMEMLIMIT: 1GiB` to encourage the Go runtime to return memory to the OS.
- Implemented Docker resource limits: `memory: 2G` and `reservations: 512M`.

### 2. Monit Robustness Fixes
- **SSH Monitoring:** Created `ansible/plays/roles/system/templates/monit.sshd.check.j2` using absolute paths (`/usr/sbin/service`) to fix "Program does not exist" errors.
- **Storagebox Check:** Updated `ansible/plays/roles/system/templates/monit.storagebox.check.j2` to use `/bin/mountpoint` instead of a hardcoded `cifs` check, making it compatible with both CIFS and bind-mounts.
- **Path Cleanup:** Resolved a duplication bug in `monit.yml` where configuration files and scripts were overlapping in the same directory.

### 3. Project-Wide Idempotency Fixes
- **Submodules:** Added `changed_when` logic to `repository.yml` to only report changes when `git submodule update` actually modifies files.
- **Database Checks:** Added `changed_when: false` to database existence checks in `deploy.yaml`.
- **Log Management:** Added `modification_time: preserve` to `docker_cleanup.yml` log creation to prevent "changed" status on every deployment.
- **SFTP Directories:** Updated restic initialization to handle "Failure" messages from SFTP when directories already exist.
- **Host Resolution:** Refactored `/etc/hosts` updates in `resolve.yml` to use precise negative lookaheads, ensuring only incorrect IPs are removed.
- **Mkcert README:** Added `force: no` to mkcert README deployment to prevent timestamp-based changes.

### 4. Ansible Modernization
- Prefixed all top-level facts with `ansible_facts` (e.g., `ansible_facts['virtualization_type']`, `ansible_facts['user_dir']`).
- Replaced deprecated `vars['variable']` dictionary access with the `lookup('vars', ...)` filter.
- Fixed deprecated Python imports in `ansible/library/json_patch.py`.

---

## Verification (servyy-test.lxd)

### 1. Memory Test
- **Action:** Restored production database backup and ran full index of 48,625 files.
- **Result:** RSS remained at ~284 MiB, and swap usage stayed below 80 MiB. System remained completely stable throughout the 25-minute task.

### 2. Idempotency Test
- **Action:** Executed 22 major tags twice in succession.
- **Result:** All tags reported 0 changes on the second run.

### 3. Monitoring Test
- **Action:** Verified `monit status` output.
- **Result:** All services (SSH, Storagebox, Filesystems, Docker containers) are reporting "OK".

---

## Impact Assessment

### What Changed:
- Dramatically lower memory/swap pressure during PhotoPrism background tasks.
- Clean Ansible deployment logs (no false "changed" reports).
- Reliable Monit alerts (no more false positives for SSH/Mounts).
- Modernized codebase compliant with Ansible 2.24+ standards.

### What Remains Unchanged:
- Production application functionality and data.
- Service naming conventions (`directory.service`).
- Deployment entry points (`servyy.sh`, `servyy-test.sh`).

---

## Rollback Procedure

If issues occur in production:
1. Revert `photoprism/docker-compose.yml` to remove `GOGC` and `GOMEMLIMIT`.
2. Revert `ansible/plays/roles/system/tasks/monit.yml` to use the original symlink for SSH.
3. Deploy via Ansible: `cd ansible && ./servyy.sh --limit lehel.xyz`.

---

## Next Steps

1. **Production Rollout:** Deploy the validated `master` branch to `lehel.xyz`.
2. **Snapshot Validation:** Follow the new protocol in `GEMINI.md` to create Docker snapshots before and after the production deployment.
3. **Continuous Monitoring:** Watch Grafana dashboards for 24 hours to confirm swap usage remains stable.
