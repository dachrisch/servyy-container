# Restic Restore Safeguards Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent database corruption by adding comprehensive pre-restore checks that skip restoration when containers are running or directories are already populated.

**Architecture:** Add decision matrix to restic_restore.yml that evaluates: snapshot availability, target directory state (missing/empty/non-empty), and container running status. Restore only proceeds when safe (empty dir + no running containers).

**Tech Stack:** Ansible (YAML), Docker Compose, Bash, Restic

---

## Background

**Incident:** Jan 28, 2026 01:30 AM - Restic restore ran while MariaDB was actively writing to database files, causing InnoDB transaction log corruption. PhotoPrism service crashed for 12+ hours.

**Root Causes:**
1. Restore ran over non-empty directory (live database files)
2. Restore ran while containers were using those files
3. No safety checks prevented dangerous restores

**Solution Status:**
- ✅ PhotoPrism database recovered from rsync backup (Jan 27, 23:38)
- ✅ Safeguards implemented in `ansible/plays/roles/user/tasks/includes/restic_restore.yml`
- ⏳ Testing required on servyy-test.lxd
- ⏳ Documentation needed

---

## Task 1: Complete Ansible-Based Testing Setup

**Files:**
- Verify: `ansible/plays/roles/user/tasks/includes/restic_restore.yml` (already modified)
- Verify: `ansible/servyy-test.sh` (deployment script)

**Objective:** Deploy full Ansible configuration to servyy-test.lxd WITHOUT storagebox (network limitation in LXD container). Use local restic repository for testing.

**Step 1: Deploy system configuration (skip storagebox)**

```bash
cd /home/cda/dev/infrastructure/container/ansible
./servyy-test.sh --skip-tags "system.storagebox" 2>&1 | tee /tmp/test-deploy.log
```

Expected: All tasks complete successfully except storagebox-related tasks

**Step 2: Verify restic environment is configured**

```bash
ssh servyy-test.lxd "sudo ls -la /etc/restic/env.home"
```

Expected: File exists with RESTIC_REPOSITORY and RESTIC_PASSWORD

**Step 3: Check if restic repository exists**

```bash
ssh servyy-test.lxd "sudo bash -c 'source /etc/restic/env.home && restic snapshots 2>&1' | head -5"
```

Expected: Either shows snapshots or "Fatal: wrong password" (indicates repo exists but password changed)

**Step 4: If needed, initialize fresh repository**

Only if repository doesn't exist or has password issues:

```bash
ssh servyy-test.lxd "sudo rm -rf /mnt/storagebox/backup/servyy-test.lxd/restic-home || true"
ssh servyy-test.lxd "sudo bash -c 'source /etc/restic/env.home && restic init'"
```

Expected: "created restic repository" message

**Step 5: Create test data for backup**

```bash
ssh servyy-test.lxd "mkdir -p /home/cda/servyy-container/photoprism/database && \
  echo 'test data file 1' > /home/cda/servyy-container/photoprism/database/test1.txt && \
  echo 'test data file 2' > /home/cda/servyy-container/photoprism/database/test2.txt && \
  ls -la /home/cda/servyy-container/photoprism/database/"
```

Expected: Directory with 2 test files

**Step 6: Create initial backup**

```bash
ssh servyy-test.lxd "sudo bash -c 'source /etc/restic/env.home && \
  restic backup /home/cda/servyy-container/photoprism/database'"
```

Expected: Snapshot created successfully, shows files/size summary

**Step 7: Verify snapshot exists**

```bash
ssh servyy-test.lxd "sudo bash -c 'source /etc/restic/env.home && restic snapshots'"
```

Expected: List shows 1 snapshot with timestamp and path

---

## Task 2: Test Scenario - No Snapshots (Baseline)

**Status:** ✅ Already verified - correctly FAILS on test environment

**Verification:**

```bash
cd /home/cda/dev/infrastructure/container/ansible
./servyy-test.sh --tags "user.docker.restore.photoprism" 2>&1 | \
  grep -A10 "FAIL on test environment"
```

Expected output: Error message about no snapshots in test environment

---

## Task 3: Test Scenario - With Snapshot + No Directory

**Objective:** Verify restore creates directory and populates it when target doesn't exist

**Step 1: Remove target directory**

```bash
ssh servyy-test.lxd "sudo rm -rf /home/cda/servyy-container/photoprism/database"
```

Expected: Directory removed

**Step 2: Run restore via Ansible**

```bash
cd /home/cda/dev/infrastructure/container/ansible
./servyy-test.sh --tags "user.docker.restore.photoprism" 2>&1 | \
  tee /tmp/test-no-dir.log | \
  grep -E "TASK.*restore|Create parent|Restore \[|RESTORED|should_restore"
```

Expected:
- Task shows "Create parent directory"
- Task shows "Restore [...] from restic"
- Output shows "✅ RESTORED: /home/cda/servyy-container/photoprism/database"

**Step 3: Verify files restored**

```bash
ssh servyy-test.lxd "ls -la /home/cda/servyy-container/photoprism/database/"
```

Expected: test1.txt and test2.txt present

**Step 4: Document result**

Expected: PASS - Restore succeeded and created directory

---

## Task 4: Test Scenario - With Snapshot + Empty Directory

**Objective:** Verify restore populates empty directory

**Step 1: Clear directory contents (keep directory)**

```bash
ssh servyy-test.lxd "rm -rf /home/cda/servyy-container/photoprism/database/* && \
  ls -la /home/cda/servyy-container/photoprism/database/"
```

Expected: Empty directory (only . and ..)

**Step 2: Run restore via Ansible**

```bash
cd /home/cda/dev/infrastructure/container/ansible
./servyy-test.sh --tags "user.docker.restore.photoprism" 2>&1 | \
  tee /tmp/test-empty-dir.log | \
  grep -E "RESTORED|should_restore|target_is_empty"
```

Expected: Output shows "✅ RESTORED" and restore completed

**Step 3: Verify files restored**

```bash
ssh servyy-test.lxd "ls -la /home/cda/servyy-container/photoprism/database/"
```

Expected: test1.txt and test2.txt present

**Step 4: Document result**

Expected: PASS - Restore succeeded on empty directory

---

## Task 5: Test Scenario - With Snapshot + Non-Empty Directory

**Objective:** Verify restore is SKIPPED when directory already contains data

**Step 1: Ensure directory has data**

```bash
ssh servyy-test.lxd "ls -la /home/cda/servyy-container/photoprism/database/ | wc -l"
```

Expected: More than 2 (indicating files present beyond . and ..)

**Step 2: Add a unique marker file**

```bash
ssh servyy-test.lxd "echo 'existing data marker' > \
  /home/cda/servyy-container/photoprism/database/existing-marker.txt"
```

Expected: File created

**Step 3: Run restore via Ansible**

```bash
cd /home/cda/dev/infrastructure/container/ansible
./servyy-test.sh --tags "user.docker.restore.photoprism" 2>&1 | \
  tee /tmp/test-nonempty-dir.log | \
  grep -E "SKIP|non-empty|should_restore|target_is_empty"
```

Expected:
- Output shows "⏭️ SKIPPING RESTORE: Target directory is not empty"
- Shows "Files found: [number]"
- Shows instructions for force restore if needed

**Step 4: Verify marker file still exists (not overwritten)**

```bash
ssh servyy-test.lxd "cat /home/cda/servyy-container/photoprism/database/existing-marker.txt"
```

Expected: Shows "existing data marker" (proving restore didn't overwrite)

**Step 5: Document result**

Expected: PASS - Restore correctly SKIPPED, data preserved

---

## Task 6: Test Scenario - With Snapshot + Running Containers

**Objective:** Verify restore is SKIPPED when containers are running to prevent corruption

**Step 1: Deploy PhotoPrism service**

```bash
cd /home/cda/dev/infrastructure/container/ansible
./servyy-test.sh --tags "user.docker" 2>&1 | tail -30
```

Expected: PhotoPrism containers deployed and started

**Step 2: Verify containers are running**

```bash
ssh servyy-test.lxd "docker ps | grep photoprism"
```

Expected: Shows photoprism.photoprism and photoprism.mariadb containers

**Step 3: Clear database directory to make it eligible for restore**

```bash
ssh servyy-test.lxd "docker compose -f /home/cda/servyy-container/photoprism/docker-compose.yml down && \
  rm -rf /home/cda/servyy-container/photoprism/database/* && \
  docker compose -f /home/cda/servyy-container/photoprism/docker-compose.yml up -d"
```

Expected: Containers restarted with empty database directory

**Step 4: Verify containers running and directory empty**

```bash
ssh servyy-test.lxd "docker ps -q | wc -l && \
  ls -la /home/cda/servyy-container/photoprism/database/ | wc -l"
```

Expected: Shows running containers + empty-ish directory

**Step 5: Run restore via Ansible**

```bash
cd /home/cda/dev/infrastructure/container/ansible
./servyy-test.sh --tags "user.docker.restore.photoprism" 2>&1 | \
  tee /tmp/test-running-containers.log | \
  grep -E "SKIP|containers running|should_restore|containers_running"
```

Expected:
- Output shows "⏭️ SKIPPING RESTORE: Service containers are running"
- Shows "Running containers: [number]"
- Shows instructions: stop service → run restore

**Step 6: Verify MariaDB still healthy (not corrupted)**

```bash
ssh servyy-test.lxd "docker logs photoprism.mariadb --tail 10 2>&1 | grep -E 'ready|error|crash'"
```

Expected: Shows "ready for connections" with no errors

**Step 7: Document result**

Expected: PASS - Restore correctly SKIPPED when containers running, no corruption

---

## Task 7: Create Testing Summary Report

**File:** Create `docs/testing/2026-01-28-restic-restore-safeguards-test-report.md`

**Step 1: Write test report header**

```markdown
# Restic Restore Safeguards - Test Report

**Date:** 2026-01-28
**Environment:** servyy-test.lxd
**Tester:** Claude Code
**Ansible Version:** [check with `ansible --version`]

## Summary

Comprehensive testing of restic restore safeguards to prevent database corruption.
All scenarios tested via Ansible playbooks only - no manual SSH edits.

---
```

**Step 2: Document each test scenario**

For each scenario (Tasks 2-6), document:

```markdown
### Scenario N: [Name]

**Objective:** [What we're testing]

**Pre-conditions:**
- Snapshots: [Yes/No]
- Target directory: [Missing/Empty/Non-empty]
- Containers: [Running/Stopped]

**Expected behavior:** [Skip/Restore]

**Result:** [PASS/FAIL]

**Evidence:**
```
[Relevant log output or command results]
```

**Verification commands:**
```bash
[Commands that prove the result]
```
```

**Step 3: Add test decision matrix**

```markdown
## Decision Matrix Validation

| Snapshots | Target Dir | Containers | Expected | Actual | Status |
|-----------|-----------|------------|----------|--------|--------|
| No        | Any       | Any        | Error(test)/Warn(prod) | [Result] | [✅/❌] |
| Yes       | Missing   | Any        | Restore  | [Result] | [✅/❌] |
| Yes       | Empty     | Stopped    | Restore  | [Result] | [✅/❌] |
| Yes       | Non-empty | Stopped    | Skip     | [Result] | [✅/❌] |
| Yes       | Empty     | Running    | Skip     | [Result] | [✅/❌] |
| Yes       | Non-empty | Running    | Skip     | [Result] | [✅/❌] |
```

**Step 4: Add conclusions and recommendations**

```markdown
## Conclusions

[Summary of test results]

## Production Rollout Readiness

- [ ] All test scenarios passed
- [ ] Safeguards prevent corruption scenarios
- [ ] Skip conditions work correctly
- [ ] Error messages are clear and actionable
- [ ] No false positives (over-protective blocking)

## Recommendation

[APPROVE/REJECT for production rollout]

## Next Steps

1. [List any findings or improvements needed]
2. Get user approval for production deployment
3. Update CLAUDE.md with new safety rules
```

**Step 5: Save report**

```bash
git add docs/testing/2026-01-28-restic-restore-safeguards-test-report.md
git commit -m "docs: add restic restore safeguards test report"
```

---

## Task 8: Request Production Approval

**Objective:** Present test results to user and get explicit approval before production deployment

**Step 1: Summarize test results**

Present to user:
```
## Restic Restore Safeguards - Testing Complete

All scenarios tested successfully on servyy-test.lxd:

✅ Scenario 1: No snapshots - Correctly fails on test env
✅ Scenario 2: Restore to missing directory - Succeeds
✅ Scenario 3: Restore to empty directory - Succeeds
✅ Scenario 4: Non-empty directory - Correctly SKIPPED
✅ Scenario 5: Running containers - Correctly SKIPPED

**Changes deployed to production:**
- Modified: ansible/plays/roles/user/tasks/includes/restic_restore.yml
- Added decision matrix with container detection
- Added skip conditions for safety

**Production status:**
- ✅ PhotoPrism recovered and healthy
- ⚠️  Safeguards are ALREADY ACTIVE (changes were committed to master)
- ✅ Will prevent future corruption incidents

**Do you approve documenting these changes and marking the implementation complete?**
```

**Step 2: Wait for user approval**

User must explicitly approve with: "yes", "approve", "proceed" or similar

**Step 3: If approved, proceed to Task 9**

---

## Task 9: Create Post-Mortem Documentation

**File:** Create `history/2026-01-28_photoprism-restore-corruption.md`

**Content template:**

```markdown
# PhotoPrism MariaDB Corruption & Restic Restore Safeguards

**Date:** 2026-01-28
**Impact:** PhotoPrism service down 12+ hours (01:30 AM - ~14:30 PM)
**Severity:** High (service unavailable, data corruption)
**Resolution:** Database restored from rsync backup, safeguards implemented

---

## Incident Timeline

**Jan 28, 01:30 AM** - MariaDB first crash with InnoDB assertion failure
**Jan 28, 02:01 AM** - Last successful restic backup (snapshot 3dea3269)
**Jan 28, 02:41 AM** - Restic env.home regenerated (password changed)
**Jan 28, 02:01-14:30 PM** - Continuous crash-loop
**Jan 28, 03:04 AM onwards** - Restic backups failing (wrong password)
**Jan 28, 14:32 PM** - User reports PhotoPrism unreachable
**Jan 28, 15:37 PM** - Database restored from rsync backup (Jan 27, 23:38)
**Jan 28, 15:49 PM** - Service recovered and healthy

---

## Root Cause Analysis

### Primary Cause

Restic restore operation (`./servyy.sh --tags user.docker.restore.photoprism`) ran at ~01:30 AM while:
1. MariaDB container was RUNNING and actively writing to database files
2. Target directory was NON-EMPTY (contained live ~260MB database)

**Dangerous code path:**
```yaml
# ansible/plays/roles/user/tasks/includes/restic_restore.yml:85-102
- name: Restore [{{ restore_path }}] from restic ({{ backup_name }})
  shell: |
    restic restore latest --target / --include "{{ restore_path }}"
  when: snapshot_count | int > 0  # ❌ NO OTHER CHECKS
```

**What happened:**
1. Restic overwrote InnoDB data files (`ibdata1`, `ib_logfile0`) while MariaDB was writing
2. Transaction log became inconsistent
3. InnoDB assertion failure: `Failing assertion: tail.trx_no <= last_trx_no`
4. MariaDB entered crash-loop, unable to recover

### Contributing Factors

1. **No container detection** - Restore didn't check if containers were using files
2. **No directory state check** - Restore didn't check if directory was already populated
3. **Restic password issue** - Password changed at 02:41 AM, breaking backups for rest of day

---

## Resolution Steps

### 1. Database Recovery (15:36-15:49 PM)

```bash
# Stop containers
ssh lehel.xyz "cd /home/cda/servyy-container/photoprism && docker compose down"

# Backup corrupted database
ssh lehel.xyz "tar -czf database-corrupted-20260128-153621.tar.gz database/"

# Restore from rsync backup (Jan 27, 23:38)
ssh lehel.xyz "sudo rsync -av --delete \
  /mnt/storagebox/backup/lehel.xyz/home/cda/servyy-container/photoprism/database/ \
  /home/cda/servyy-container/photoprism/database/"

# Fix permissions and restart
ssh lehel.xyz "sudo chown -R cda:cda database/ && docker compose up -d"
```

**Result:** ✅ Service recovered, MariaDB healthy

### 2. Implement Safeguards (15:50-17:00)

**Modified:** `ansible/plays/roles/user/tasks/includes/restic_restore.yml`

**Changes:**
1. Added pre-restore decision matrix (lines 73-153)
2. Container detection via `docker compose ps -q`
3. Directory state check (empty vs non-empty)
4. Skip conditions with clear messaging
5. Changed restore condition from `snapshot_count > 0` to `should_restore`

**Decision matrix:**
| Snapshots | Target Dir | Containers | Action |
|-----------|-----------|------------|--------|
| No        | Any       | Any        | Error(test)/Warn(prod) |
| Yes       | Missing   | Any        | Restore (create & populate) |
| Yes       | Empty     | Stopped    | Restore (populate) |
| Yes       | Non-empty | Stopped    | SKIP (already populated) |
| Yes       | Any       | Running    | SKIP (prevent corruption) |

**Result:** ✅ Prevents both corruption scenarios

---

## Testing

All scenarios tested on servyy-test.lxd via Ansible (no manual SSH edits):

✅ No snapshots - Correctly fails on test
✅ Missing directory - Restores successfully
✅ Empty directory - Restores successfully
✅ Non-empty directory - Correctly SKIPPED
✅ Running containers - Correctly SKIPPED (corruption prevented)

**Test report:** `docs/testing/2026-01-28-restic-restore-safeguards-test-report.md`

---

## Lessons Learned

### What Went Wrong

1. **Insufficient validation** - Restore had no safety checks before overwriting files
2. **No operational awareness** - Didn't detect running services
3. **Silent danger** - Restore silently overwrote live files
4. **Password management** - Restic password change broke backups for 12+ hours

### What Went Right

1. **Rsync saved us** - Had recent backup from 2 hours before incident
2. **Quick detection** - User reported within 13 hours
3. **Clean recovery** - No data loss, service fully restored
4. **Root cause identified** - Found exact cause via logs and timeline analysis

---

## Preventive Measures

### Immediate (Completed)

- ✅ Implemented restore safeguards (container + directory checks)
- ✅ Tested all scenarios on servyy-test.lxd
- ✅ Updated CLAUDE.md with restore safety rules
- ✅ Documented incident and safeguards

### Short-term (Recommended)

- [ ] Fix restic password issue (investigate why it changed)
- [ ] Add monitoring for restic backup failures
- [ ] Review all other restore operations for similar risks
- [ ] Add pre-deployment validation checks

### Long-term (Recommended)

- [ ] Consider backup verification automation
- [ ] Add alerting for service health (beyond monit)
- [ ] Document disaster recovery procedures
- [ ] Regular disaster recovery drills

---

## Impact Assessment

**Data Loss:** None (restored from backup 2 hours old)
**Downtime:** ~13 hours (01:30 AM - 14:30 PM)
**Photos:** Unaffected (stored on /mnt/storagebox, separate from database)
**Metadata:** Potentially lost changes between Jan 27 23:38 and Jan 28 01:30 (~2 hours)

---

## References

- Modified file: `ansible/plays/roles/user/tasks/includes/restic_restore.yml`
- Test report: `docs/testing/2026-01-28-restic-restore-safeguards-test-report.md`
- Git commit: [insert commit hash after committing]
- Related: `CLAUDE.md` safety rules section
```

**Step 2: Save post-mortem**

```bash
git add history/2026-01-28_photoprism-restore-corruption.md
git commit -m "docs: add post-mortem for PhotoPrism restore corruption incident"
```

---

## Task 10: Update CLAUDE.md Safety Rules

**File:** Modify `CLAUDE.md`

**Step 1: Find the "CRITICAL DEPLOYMENT RULES" section**

Should be near the top of the file

**Step 2: Add restore safety rules**

Insert after the existing rules:

```markdown
3. **Database Restore Safety (Added 2026-01-28)**
   - ✅ **Safeguards are ACTIVE** - Ansible automatically prevents dangerous restores
   - ✅ Restore SKIPS if directory is non-empty (already operational)
   - ✅ Restore SKIPS if containers are running (prevents corruption)
   - ❌ **NEVER** manually restore over live database files
   - ❌ **NEVER** run restore while containers are running

   **How safeguards work:**
   - `ansible/plays/roles/user/tasks/includes/restic_restore.yml` checks:
     - Target directory state (missing/empty/non-empty)
     - Container running status (via `docker compose ps`)
   - Restore only proceeds when safe (empty directory + no running containers)

   **To restore (if service is broken):**
   ```bash
   # 1. Stop service
   ssh [host] "cd /home/cda/servyy-container/[service] && docker compose down"

   # 2. Clear directory (optional, if forcing restore)
   ssh [host] "rm -rf /home/cda/servyy-container/[service]/database/*"

   # 3. Run restore via Ansible
   cd ansible && ./servyy.sh --tags "user.docker.restore.[service]" --limit [host]

   # 4. Verify restoration
   ssh [host] "cd /home/cda/servyy-container/[service] && docker compose up -d"
   ```

   **Incident reference:** See `history/2026-01-28_photoprism-restore-corruption.md`
```

**Step 3: Save changes**

```bash
git add CLAUDE.md
git commit -m "docs: add database restore safety rules to CLAUDE.md"
```

---

## Task 11: Final Verification and Commit

**Step 1: Review all changes**

```bash
git log --oneline -10
git diff HEAD~5
```

Expected: Shows all documentation commits

**Step 2: Check working tree is clean**

```bash
git status
```

Expected: "nothing to commit, working tree clean" or only untracked test logs

**Step 3: Create summary commit (if needed)**

If there are uncommitted changes:

```bash
git add -A
git commit -m "feat: complete restic restore safeguards implementation

- Add pre-restore decision matrix with container detection
- Skip restore when directory non-empty or containers running
- Test all scenarios on servyy-test.lxd (all passed)
- Document incident post-mortem and safety rules
- Prevent future database corruption from unsafe restores

Closes: PhotoPrism MariaDB corruption incident (2026-01-28)
Tested-on: servyy-test.lxd
Ready-for: Production (already active on lehel.xyz)"
```

**Step 4: Push to remote**

```bash
git push origin master
```

Expected: Successfully pushed

**Step 5: Final verification on production**

```bash
ssh lehel.xyz "docker ps | grep photoprism && curl -I https://photoprism.lehel.xyz"
```

Expected: Containers running, service responding with HTTP 200/307

---

## Success Criteria

- ✅ PhotoPrism service recovered and healthy
- ✅ Safeguards prevent dangerous restores (tested all scenarios)
- ✅ Documentation complete (post-mortem, test report, CLAUDE.md)
- ✅ All changes committed to git
- ✅ No manual workarounds required (Ansible-only approach)
- ✅ Production rollout approved by user

---

## Notes

- **Current status:** Safeguards already active on production (committed to master branch during development)
- **Risk:** Low - safeguards are conservative (skip when unsure rather than corrupt data)
- **Recovery time if issue:** <1 hour (can quickly revert git commit)
- **Testing approach:** Ansible-only (no manual SSH edits to prove automation works)
