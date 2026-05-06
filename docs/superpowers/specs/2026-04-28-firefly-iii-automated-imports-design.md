# Firefly III Automated Daily Imports — Design Spec

**Date:** 2026-04-28  
**Status:** Approved  
**Scope:** Automate daily imports from Enable Banking into Firefly III via Data Importer

---

## Overview

Enable an unattended daily import of bank transactions from GLS Gemeinschaftsbank (via Enable Banking) into Firefly III. The import configuration is already in place (`finance/import_config_2026-04-28.json`). This spec covers:

1. **Manual validation** on production to ensure unattended import works
2. **Automation setup** using Ofelia scheduler
3. **Testing** on servyy-test to verify scheduling logic
4. **Production deployment** with explicit approval

---

## Architecture

### Components

- **Firefly III Core** — Personal finance database (lehel.xyz)
- **Firefly III Data Importer** — Fetches from Enable Banking, imports via API
- **Ofelia** — Docker-based job scheduler (added to finance stack)
- **Enable Banking** — Third-party bank data provider (GLS Gemeinschaftsbank)

### Data Flow

```
Ofelia (6 AM daily)
  ↓
POST /autoupload?secret=X (to importer)
  ↓
Importer fetches from Enable Banking
  ↓
Importer calls Firefly III API (using PAM token)
  ↓
Transactions imported into Firefly III
  ↓
Logs captured (errors only logged, no notifications)
```

---

## Configuration Requirements

### New Environment Variables

Add to `finance.env.j2`:

```bash
# Importer automation settings
AUTO_IMPORT_SECRET={{ finance.auto_import_secret }}
CAN_POST_FILES=true
CAN_POST_AUTOIMPORT=true
IMPORT_DIR_ALLOWLIST=/import

# Firefly III authentication (Personal Access Token)
FIREFLY_III_ACCESS_TOKEN={{ finance.firefly_pam_token }}
```

### Secrets to Add

Store in `ansible/plays/vars/secrets.yml` (git-crypt encrypted):

```yaml
finance:
  auto_import_secret: "YOUR_16_CHAR_SECRET"  # Generate random 16+ char string
  firefly_pam_token: "eyJ0eXAi..."  # Personal Access Token from Firefly III
```

### Import Configuration File

- Path: `finance/import_config_2026-04-28.json` (already exists)
- Must be mounted to importer service at `/import/`
- Contains Enable Banking credentials and transaction mapping rules

---

## Implementation Phases

### Phase 1: Manual Validation (Production)

**Goal:** Verify unattended import works before automating

**Steps:**

1. Update `finance.env` with new variables
2. Restart importer service
3. Manually trigger import via curl:
   ```bash
   curl -X POST 'https://importer.finance.lehel.xyz/autoupload?secret=YOUR_SECRET' \
     -H 'Accept: application/json' \
     -H 'Authorization: Bearer YOUR_PAM_TOKEN' \
     -F 'json=@/home/cda/servyy-container/finance/import_config_2026-04-28.json'
   ```
4. Verify in logs:
   - Importer logs: successful config parse, Enable Banking fetch
   - Firefly III logs: successful transaction import
5. Check Firefly III UI for imported transactions

**Success Criteria:**
- API returns 200 status
- No errors in logs
- New transactions appear in Firefly III

---

### Phase 2: Automate with Ofelia (Ansible Update)

**Goal:** Add scheduler to run daily at 6 AM

**Changes:**

1. Add Ofelia service to `finance/docker-compose.yml`
2. Label importer service with daily job
3. Update Ansible to deploy docker-compose changes

**Implementation:**
- Ofelia runs on host, calls importer API daily at 6 AM CET
- Logs captured to Docker stdout (visible via `docker logs`)
- Errors logged only (no notifications)

---

### Phase 3: Test Automation Logic (servyy-test)

**Goal:** Verify Ofelia scheduling works before production

**Steps:**

1. Deploy updated Ansible to servyy-test
2. Verify Ofelia service starts
3. Check job is registered: `docker exec finance.ofelia ofelia list`
4. Monitor for scheduled execution or trigger manually

**Success Criteria:**
- Ofelia service runs without errors
- Job scheduled correctly
- No docker-compose or networking issues

---

### Phase 4: Deploy to Production (lehel.xyz)

**Goal:** Enable automated daily imports

**Steps:**

1. Update Ansible playbooks with Ofelia config
2. Deploy to lehel.xyz with explicit user approval
3. Verify daily 6 AM import runs
4. Check logs for successful imports

**Success Criteria:**
- Ofelia runs scheduled jobs
- Daily 6 AM import executes
- Transactions imported successfully

---

## Error Handling

- **Importer failures:** Logged to Docker logs, visible via `docker logs finance.importer`
- **Enable Banking connectivity:** Logged (bank outages are transient)
- **Firefly III API failures:** Logged (will retry next day)
- **No notifications:** User can monitor via Grafana/Loki logs if needed

---

## Rollback

If automated imports cause issues:

1. Disable Ofelia job by removing labels from importer service
2. Redeploy to production
3. Revert to manual validation (manual curl calls)

---

## Testing on Production vs. Test

**Why production only for validation:**
- Enable Banking credentials + Firefly III config only fully set up on lehel.xyz
- All authentication tokens valid on production
- Test environment lacks complete bank data integration

**Why test for automation logic:**
- Verifies Ofelia scheduling works without risking production
- Tests docker-compose and networking changes
- Safer iteration before prod deployment

---

## Success Metrics

- ✅ Manual import via API works on lehel.xyz
- ✅ Ofelia service deploys without errors
- ✅ Daily 6 AM job executes automatically
- ✅ Transactions imported successfully
- ✅ Errors logged appropriately
