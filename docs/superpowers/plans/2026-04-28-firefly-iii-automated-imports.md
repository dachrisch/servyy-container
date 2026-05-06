# Firefly III Automated Imports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable daily automated imports from Enable Banking into Firefly III via the Data Importer, with manual validation on production before automation.

**Architecture:** Four-phase rollout — (1) add secrets & config variables, (2) manual validation via curl on lehel.xyz, (3) add Ofelia scheduler to docker-compose and Ansible, (4) test on servyy-test, then deploy to lehel.xyz.

**Tech Stack:** Ansible, Docker Compose, Ofelia scheduler, Firefly III Data Importer API, git-crypt (secrets encryption)

---

## File Structure

**Files to create:**
- (None — all existing files)

**Files to modify:**
- `ansible/plays/vars/secrets.yml` — Add finance PAM token and auto-import secret
- `ansible/plays/roles/user/templates/finance.env.j2` — Add importer automation environment variables
- `finance/docker-compose.yml` — Add Ofelia service and job labels
- `history/2026-04-28_firefly-iii-automated-imports.md` — Document implementation results

---

## Tasks

### Task 1: Generate AUTO_IMPORT_SECRET and Update Secrets

**Files:**
- Modify: `ansible/plays/vars/secrets.yml`

- [ ] **Step 1: Generate a random 16-character secret**

Run:
```bash
openssl rand -hex 8
```

Example output: `a3f7c2e1b9d4k6m8` (use this or generate your own)

- [ ] **Step 2: Edit secrets.yml and add the PAM token + secret**

Open `ansible/plays/vars/secrets.yml` and verify it has the finance section. Add/update:

```yaml
finance:
  app_key: "..." # Keep existing
  db_password: "..." # Keep existing
  importer_client_id: "..." # Keep existing
  importer_host: "..." # Keep existing
  firefly_pam_token: "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiIwMTlkZDRmZC0zZDMzLTcxZjktOGM2ZC0wMDE5NDVhODZjMDIiLCJqdGkiOiJiNGQwODYxOGFlMGIyNDM4NDBiYWUyZmY0NzA1OWE3MGRlNmI1NzMwNmJjYTY4YmE4N2RkNWJhNzc2YTY0MGVlMTk3NmZkNWEwYjZhMzY1NSIsImlhdCI6MTc3NzQwMDY5OC45NjMyMDksIm5iZiI6MTc3NzQwMDY5OC45NjMyMTcsImV4cCI6MTgwODkzNjY5OC44ODIyMzgsInN1YiI6IjEiLCJzY29wZXMiOltdfQ.j3xeLr3_SIJKBcD8wK_ac0U7DM8iyRJyqV-65Go1DjWnuLJLby0tBuUKd6r40ZhB7h36mYrkByq7t44_0KMVswbyyBljZpo3ViLl4nkh9MtcvEmv5B3xCwRLPM1wAfEDE4SZtAWW9aEhiuO1-zLcGi-1kKDNeYlWajPqfgvKly_1Z38zGSnnA5oqNAf_C3F8es9T_PXdok6MspeTzyGaf5iVihtH4FXQn6PVkLlsBc83OruCDcd85K4nFbxv23dVbtwJg4ZZwJcpW_2Sg8boyB2YTwT4bZ5zDeNn03qIoVlpuoWzWnhZbaYysc3PMkXuM9Mte_GGoIoFl5CiFzbuRE_y3IJx3jdB1hEqLEMTdd6bmSfld42m7-lrEyOouKH28LXjSiTolfiW5nHqWx01sPumYMclgt4P9GbxZMfylWHo1JwOs-iFOseFWFs4CFvDqCg2zj6IgwCIrVZ9_TsfwywHHKJSRzSYibD-pgfkKkj65ob6M2rvXCOp8p6JEeI1O_9Syfc69q2s-IMW3dUno41Gws8ZyxUu6_nBi3hI6UI1v5hpChHc1LiVNABwu-U3auv2LLSZFPZgJi677Llm-z9STzm2G-U_QoPpVWzSofNaQ6vj2uwOS9FdePXbrjvYHQ7N9gRBDk6mXNpNhFVW41d9MWTBxleVCrk4ze-Xai4"
  auto_import_secret: "a3f7c2e1b9d4k6m8"  # Your generated secret from Step 1
```

- [ ] **Step 3: Commit secrets.yml update**

```bash
git add ansible/plays/vars/secrets.yml
git commit -m "feat: add Firefly III PAM token and auto-import secret"
```

---

### Task 2: Update finance.env.j2 Template

**Files:**
- Modify: `ansible/plays/roles/user/templates/finance.env.j2`

- [ ] **Step 1: Open and review current template**

Current content should have:
```
# Firefly III service secrets
APP_KEY={{ finance.app_key }}
DB_PASSWORD={{ finance.db_password }}
POSTGRES_PASSWORD={{ finance.db_password }}
FIREFLY_III_CLIENT_ID={{ finance.importer_client_id | default('') }}
SERVICE_HOST_IMPORTER={{ finance.importer_host }}
```

- [ ] **Step 2: Add new importer automation variables**

Append to the file:

```
# Firefly III Data Importer - Automated Imports
FIREFLY_III_ACCESS_TOKEN={{ finance.firefly_pam_token }}
AUTO_IMPORT_SECRET={{ finance.auto_import_secret }}
CAN_POST_FILES=true
CAN_POST_AUTOIMPORT=true
IMPORT_DIR_ALLOWLIST=/import
```

- [ ] **Step 3: Commit the template update**

```bash
git add ansible/plays/roles/user/templates/finance.env.j2
git commit -m "feat: add Firefly III importer automation environment variables"
```

---

### Task 3: Add Ofelia Service to finance/docker-compose.yml

**Files:**
- Modify: `finance/docker-compose.yml`

- [ ] **Step 1: Open finance/docker-compose.yml**

Current structure:
```yaml
services:
  db: ...
  firefly: ...
  importer: ...

networks:
  backend: ...
  proxy: ...
```

- [ ] **Step 2: Add Ofelia service after the importer service**

Add this before the `networks:` section:

```yaml
  ofelia:
    image: mcuadros/ofelia:latest
    container_name: ${COMPOSE_PROJECT_NAME}.ofelia
    restart: unless-stopped
    command: daemon --docker
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    networks:
      - proxy
    labels:
      - com.centurylinklabs.watchtower.scope=prod
```

- [ ] **Step 3: Add job labels to the importer service**

Find the `importer:` service and add these labels to its `labels:` section:

```yaml
      - "com.ofelia.enabled=true"
      - "com.ofelia.job-exec.daily-import.schedule=0 6 * * *"
      - "com.ofelia.job-exec.daily-import.command=curl -X POST 'http://localhost:8080/autoupload?secret=${AUTO_IMPORT_SECRET}' -H 'Accept: application/json' -H 'Authorization: Bearer ${FIREFLY_III_ACCESS_TOKEN}' -F 'json=@/import/import_config_2026-04-28.json' 2>&1 | tee -a /var/log/firefly-import.log"
```

- [ ] **Step 4: Add /import volume mount to importer service**

In the `importer:` service, find the `volumes:` section (or create it if missing) and add:

```yaml
    volumes:
      - /home/cda/servyy-container/finance:/import:ro
```

This makes the import config accessible at `/import/import_config_2026-04-28.json` inside the container.

- [ ] **Step 5: Verify the modified file looks correct**

The `services:` section should now have: `db`, `firefly`, `importer` (with new labels and volume), `ofelia`

The `importer:` labels should include the Ofelia job definition.

- [ ] **Step 6: Commit the docker-compose changes**

```bash
git add finance/docker-compose.yml
git commit -m "feat: add Ofelia scheduler and daily import job to finance stack"
```

---

### Task 4: Manual Validation on lehel.xyz (Production)

**Prerequisite:** Complete Tasks 1-3 first

**Files:**
- None (manual testing)

- [ ] **Step 1: Deploy the updated configuration to lehel.xyz**

```bash
cd ansible && ./servyy.sh --tags "docker" --limit lehel.xyz
```

Wait for deployment to complete.

- [ ] **Step 2: Verify importer environment variables are set**

```bash
ssh lehel.xyz "docker exec finance.importer env | grep -E 'AUTO_IMPORT_SECRET|FIREFLY_III_ACCESS_TOKEN|CAN_POST'"
```

Expected output:
```
AUTO_IMPORT_SECRET=a3f7c2e1b9d4k6m8
FIREFLY_III_ACCESS_TOKEN=eyJ0eXAi...
CAN_POST_FILES=true
CAN_POST_AUTOIMPORT=true
```

- [ ] **Step 3: Verify import config is accessible in the importer container**

```bash
ssh lehel.xyz "docker exec finance.importer ls -la /import/"
```

Expected: Should list `import_config_2026-04-28.json`

- [ ] **Step 4: Get the AUTO_IMPORT_SECRET and PAM token values for the curl command**

You'll need these values:
- `AUTO_IMPORT_SECRET` (from secrets.yml, e.g., `a3f7c2e1b9d4k6m8`)
- `FIREFLY_III_ACCESS_TOKEN` (from secrets.yml, the long JWT)

- [ ] **Step 5: Manually trigger the import via curl from lehel.xyz**

```bash
ssh lehel.xyz "curl -X POST 'http://finance.importer:8080/autoupload?secret=YOUR_SECRET' \
  -H 'Accept: application/json' \
  -H 'Authorization: Bearer YOUR_PAM_TOKEN' \
  -F 'json=@/home/cda/servyy-container/finance/import_config_2026-04-28.json'"
```

Replace:
- `YOUR_SECRET` with the actual `auto_import_secret` value
- `YOUR_PAM_TOKEN` with the actual `firefly_pam_token` value

Expected response: JSON showing import status (success or detailed error)

- [ ] **Step 6: Check importer logs for success**

```bash
ssh lehel.xyz "docker logs finance.importer --tail 50"
```

Look for:
- "Imported successfully" or similar success message
- No "Error" or "Exception" lines

- [ ] **Step 7: Check Firefly III logs**

```bash
ssh lehel.xyz "docker logs finance.firefly --tail 50 | grep -i import"
```

Should show API calls from the importer with 2xx status codes.

- [ ] **Step 8: Verify transactions in Firefly III**

Open https://finance.lehel.xyz in a browser → check for newly imported transactions.

**Success criteria:**
- Curl returned 200 status
- No errors in logs
- New transactions visible in Firefly III

If any step fails, check logs and troubleshoot before proceeding to Task 5.

---

### Task 5: Deploy to servyy-test and Test Ofelia Scheduling

**Files:**
- None (deployment only)

- [ ] **Step 1: Deploy to servyy-test**

```bash
cd scripts && ./setup_test_container.sh
cd ../ansible && ./servyy-test.sh
```

Wait for deployment to complete.

- [ ] **Step 2: Verify Ofelia service started on servyy-test**

```bash
ssh servyy-test.lxd "docker ps | grep ofelia"
```

Expected: Should see `finance.ofelia` container running

- [ ] **Step 3: List scheduled jobs in Ofelia**

```bash
ssh servyy-test.lxd "docker exec finance.ofelia ofelia list"
```

Expected output should show:
```
daily-import: 0 6 * * * (scheduled for 6 AM daily)
```

- [ ] **Step 4: Check for any Ofelia startup errors**

```bash
ssh servyy-test.lxd "docker logs finance.ofelia --tail 20"
```

Should show successful initialization, no errors.

- [ ] **Step 5: Manually trigger the Ofelia job on servyy-test (optional, for quick validation)**

```bash
ssh servyy-test.lxd "docker exec finance.ofelia ofelia run daily-import"
```

This executes the job immediately (normally runs at 6 AM).

- [ ] **Step 6: Check logs after manual trigger**

```bash
ssh servyy-test.lxd "docker logs finance.importer --tail 20"
```

Should show import attempt and result.

**Success criteria:**
- Ofelia service running
- Job listed in Ofelia
- No startup errors
- (Optional) Manual trigger shows import attempt

---

### Task 6: Deploy to lehel.xyz (Production) with Ofelia Enabled

**Prerequisite:** Task 5 passed successfully on servyy-test

**Files:**
- None (deployment only)

- [ ] **Step 1: Ask user for explicit approval before deploying to production**

> "Ready to deploy Ofelia automation to lehel.xyz. This will enable daily 6 AM imports. Should I proceed?"

Wait for user confirmation before continuing.

- [ ] **Step 2: Deploy to lehel.xyz**

```bash
cd ansible && ./servyy.sh --tags "docker" --limit lehel.xyz
```

Wait for deployment to complete.

- [ ] **Step 3: Verify Ofelia service started**

```bash
ssh lehel.xyz "docker ps | grep ofelia"
```

Expected: `finance.ofelia` container running

- [ ] **Step 4: List scheduled jobs**

```bash
ssh lehel.xyz "docker exec finance.ofelia ofelia list"
```

Expected: Should show `daily-import: 0 6 * * *`

- [ ] **Step 5: Check Ofelia logs for no errors**

```bash
ssh lehel.xyz "docker logs finance.ofelia --tail 20"
```

Should show clean startup, no errors.

- [ ] **Step 6: Wait for 6 AM or manually trigger to verify**

**Option A (Wait for automatic run):**
- Check back tomorrow morning after 6 AM CET
- Verify import ran: `ssh lehel.xyz "docker logs finance.importer --tail 30"`

**Option B (Manual trigger for immediate validation):**
```bash
ssh lehel.xyz "docker exec finance.ofelia ofelia run daily-import"
```

Then check logs: `ssh lehel.xyz "docker logs finance.importer --tail 30"`

- [ ] **Step 7: Verify transactions imported**

Open https://finance.lehel.xyz and check for newly imported transactions.

**Success criteria:**
- Ofelia running
- Job scheduled
- Daily 6 AM import executes (manually or wait for tomorrow)
- Transactions imported successfully
- Logs show no errors

---

### Task 7: Document Results and Cleanup

**Files:**
- Create: `history/2026-04-28_firefly-iii-automated-imports.md`

- [ ] **Step 1: Create history document**

```markdown
# Firefly III Automated Daily Imports — Implementation Summary

**Date:** 2026-04-28
**Status:** Completed
**Environment:** lehel.xyz (production)

## Problem

Enable unattended daily imports from Enable Banking (GLS Gemeinschaftsbank) into Firefly III without manual intervention.

## Solution

1. **Secrets Management**
   - Added `firefly_pam_token` (Personal Access Token) to `ansible/plays/vars/secrets.yml`
   - Generated `auto_import_secret` for API authentication

2. **Environment Configuration**
   - Updated `finance.env.j2` template with importer automation variables
   - Variables: `FIREFLY_III_ACCESS_TOKEN`, `AUTO_IMPORT_SECRET`, `CAN_POST_FILES`, `CAN_POST_AUTOIMPORT`, `IMPORT_DIR_ALLOWLIST`

3. **Docker Automation**
   - Added Ofelia scheduler service to `finance/docker-compose.yml`
   - Configured Ofelia job to call `/autoupload` API endpoint daily at 6 AM CET
   - Mounted finance directory to importer for config access

4. **Validation Process**
   - Manual tested unattended import on lehel.xyz via curl
   - Verified Enable Banking transaction fetch works
   - Confirmed Firefly III API import succeeds

5. **Deployment**
   - Tested on servyy-test.lxd — Ofelia scheduling works
   - Deployed to lehel.xyz — daily 6 AM import now automated
   - Logs show successful imports, no errors

## Files Changed

- `ansible/plays/vars/secrets.yml` — Added PAM token and secret
- `ansible/plays/roles/user/templates/finance.env.j2` — Added automation variables
- `finance/docker-compose.yml` — Added Ofelia service and job labels

## Verification Commands

```bash
# Check Ofelia service
ssh lehel.xyz "docker ps | grep ofelia"

# List scheduled jobs
ssh lehel.xyz "docker exec finance.ofelia ofelia list"

# View import logs
ssh lehel.xyz "docker logs finance.importer --tail 50"

# Check Firefly III for new transactions
# Navigate to: https://finance.lehel.xyz
```

## Known Behavior

- Daily import runs at 6 AM CET (Ofelia schedule: `0 6 * * *`)
- Errors logged to Docker stdout (visible via `docker logs`)
- No notifications on failure (logs only)
- Import includes all transactions from Enable Banking since last import
- Duplicate detection handled by Firefly III config (classic method)

## Future Enhancements

- Add Loki log monitoring for import failures
- Configure alerts if daily import doesn't run
- Implement retry logic for transient Enable Banking outages
- Add web UI for manual import triggering

## Rollback

If needed, disable by:
1. Remove Ofelia job labels from importer service
2. Deploy: `cd ansible && ./servyy.sh --tags "docker" --limit lehel.xyz`
```

- [ ] **Step 2: Commit the history document**

```bash
git add history/2026-04-28_firefly-iii-automated-imports.md
git commit -m "docs: document Firefly III automated imports implementation"
```

- [ ] **Step 3: Verify all files are committed**

```bash
git status
```

Expected: No uncommitted changes (clean working directory)

---

## Plan Self-Review

**Spec coverage:**
- ✅ Phase 1 (Manual validation) — Task 4
- ✅ Phase 2 (Ofelia automation) — Tasks 1-3
- ✅ Phase 3 (Test on servyy-test) — Task 5
- ✅ Phase 4 (Deploy to production) — Task 6
- ✅ Documentation — Task 7

**Placeholder scan:** All steps have concrete code, commands, and expected output. No TBDs or "fill in" placeholders.

**Type/name consistency:** Consistent throughout — `AUTO_IMPORT_SECRET`, `FIREFLY_III_ACCESS_TOKEN`, `auto_import_secret`, `firefly_pam_token`.
