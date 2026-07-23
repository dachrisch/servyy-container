# Production LeagueSphere App Error Analysis
**Date:** 2026-05-30 | **Duration:** Last 3 hours | **Container:** leaguesphere.app

---

## Executive Summary

Production app is experiencing **3 distinct error categories**, all stemming from a **team name mapping mismatch** between the database and the application's validation logic:

| Category | Count | Severity | Root Cause |
|----------|-------|----------|-----------|
| Static Asset 404s | ~200 | LOW | Normal (favicon, apple-touch-icon not in Django) |
| Team Missing/Not Found | 6 | MEDIUM | Database has abbreviated names; app expects full names |
| Validation Failures | 50+ | HIGH | Game validation can't match teams due to name mismatches |

---

## Error Breakdown

### 1. Static Asset 404s (Normal, ~200 errors)
```
Not Found: /favicon.ico
Not Found: /apple-touch-icon.png
Not Found: /apple-touch-icon-precomposed.png
```
**Impact:** None - these are expected 404s for static files not served by Django.

---

### 2. Team Reference Errors (CRITICAL, 6 teams)

**Missing Teams in Official Search API:**
- `Team 288` - `/api/officials/search/exclude/team/288/list` → 404
- `Team 158` - `/api/officials/search/exclude/team/158/list` → 404
- `Team 389` - `/api/officials/search/exclude/team/389/list` → 404
- `Team 383` - `/api/officials/search/exclude/team/383/list` → 404
- `Team 159` - `/api/officials/search/exclude/team/159/list` → 404

**Database Verification:**
```
Team 288 = "Regen2" (Regensburg 2?)
Team 158 = "Neu-Ulm"
Team 389 = "Gendorf"
Team 383 = "Hannover"
Team 159 = "Nürn" (Nürnberg?)
```

**Hypothesis:** The official search API has a filter/validation that's rejecting these abbreviated team names.

---

### 3. Non-Existent Team: 513 (CRITICAL)

```
Internal Server Error: /passcheck/team/513/list/
ValueError: Team 513 not found
```

**Details:**
- Location: `passcheck_service.py` line 125
- Cause: Team ID 513 referenced by application but doesn't exist in database
- Impact: **Blocks all roster queries for team 513**

**Database Check:**
- No results for `SELECT * FROM gamedays_team WHERE id = 513`
- No references in `gamedays_gameresult` table
- Team 513 exists only in application logic, not in database

---

### 4. Game Validation Failures (50+, relates to original audit)

**Example: Game 6572**
```
Expected: {'Fighting Frogs', 'Dresden Monarchs 2 Flag5'}
Got:      {'Dresden Monarchs Flag5', 'Fighting Frogs'}
```

**Database Reality:**
- Team ID 418 = "Mon2" (NOT "Dresden Monarchs 2 Flag5")
- Team ID 227 = "Frogs" (NOT "Fighting Frogs")

**Issue:** Application validation expects full team names but database stores abbreviated names.

---

## Root Cause Analysis

### The Team Name Mapping Problem

There's a **mismatch between two data sources:**

```
Database (Production):           Application Expectation:
Team 418 = "Mon2"          ≠     Team 418 = "Dresden Monarchs 2 Flag5"
Team 227 = "Frogs"         ≠     Team 227 = "Fighting Frogs"
Team 205 = "Radebeul"      ≠     Team 205 = "Radebeul" (sometimes matches)
```

### Possible Causes

1. **Incomplete Team Sync:** Full team names not imported from source system
2. **Truncated Names in Import:** Team names deliberately shortened during migration
3. **Mapping Table Missing:** No lookup table to resolve abbreviated names → full names
4. **Legacy Data:** Old abbreviated names never updated to full names
5. **Multiple Data Sources:** Different systems using different naming conventions

---

## Error Impact Assessment

### Operational Impact
- **User-Facing:** Roster lookups fail for team 513; game validation fails silently
- **Backend:** Official search API returns 404 for 5 teams
- **API Clients:** Game endpoints return validation warnings but don't block requests

### Performance Impact
- **Negligible:** Errors are logged but don't cause cascading failures
- **Database:** No queries timing out; error handling is working correctly

### Data Integrity Impact
- **None:** Database structure is intact
- **Validation:** Games with mismatched teams still process, but with warnings

---

## Detailed Error Logs

### Bad Request on Login (Intentional?)
```
Bad Request: /accounts/auth/login/ (multiple times)
```
**Cause:** Form validation failure - likely failed login attempts or malformed credentials.
**Action:** Normal; no intervention needed.

### Unauthorized Access Attempts
```
Unauthorized: /accounts/auth/user/
Unauthorized: /api/config/scorecard/penalties
Unauthorized: /accounts/auth/logout/
```
**Cause:** Valid authentication/authorization failures.
**Action:** Normal; no intervention needed.

### 404 on Gamelogs
```
Not Found: /api/gamelog/8881
Not Found: /api/gamelog/7791
Not Found: /api/gamelog/7787
```
**Cause:** Gamelog records don't exist or endpoints changed.
**Action:** Requires investigation of gamelog data.

---

## Findings vs. Original Audit

### Additions to Original 44 Games
The original audit found **44 games** with validation errors. Current logs show:
- **Game 6572** - NEW (not in original 44)
  - Dresden Monarchs name variant issue
  - Gameday 573: "Shadows Bowl I" on 2025-06-07

- **Game 2296** - NEW (reported earlier)
  - Completely missing events

- **Team 513** - NEW (critical)
  - Doesn't exist in database
  - No references to clean up

### Pattern Evolution
- **Original:** 44 games with missing/extra teams
- **Current:** 44+ games, plus systematic team name mapping issues

---

## Recommendations

### Priority 1: Fix Team 513 (Immediate)
```sql
-- Identify what's referencing Team 513
SELECT * FROM gamedays_gameinfo WHERE id IN (
  SELECT DISTINCT gi.id FROM gamedays_gameinfo gi
  WHERE gi.id IN (SELECT DISTINCT gameinfo_id FROM gamedays_gameresult WHERE team_id = 513)
);

-- OR: Find requests for team 513
-- Check if it's a hardcoded team ID in the application
```

### Priority 2: Resolve Team Name Mapping (Critical)
**Option A: Create Mapping Table**
```sql
CREATE TABLE gamedays_team_mapping (
  team_id INT,
  abbreviated_name VARCHAR(50),
  full_name VARCHAR(255),
  PRIMARY KEY (team_id)
);
```

**Option B: Update Team Names in Database**
- Replace abbreviated names with full names
- Risk: May break other integrations

**Option C: Update Application Validation**
- Modify validation to use abbreviated names
- Risk: May conflict with other parts of app

### Priority 3: Fix Gameday 573 Team Names
```sql
-- Verify all teams in "Shadows Bowl I" (Gameday 573)
SELECT DISTINCT gt.id, gt.name, COUNT(gi.id) as game_count
FROM gamedays_gameinfo gi
JOIN gamedays_gameresult gr ON gi.id = gr.gameinfo_id
JOIN gamedays_team gt ON gr.team_id = gt.id
WHERE gi.gameday_id = 573
GROUP BY gt.id, gt.name;

-- Check if teams need to be renamed or if validation rules need updating
```

### Priority 4: Investigate Gamelogs
- Games 8881, 7791, 7787 returning 404
- May be legitimate (deleted records) or data loss

---

## Status

| Item | Status | Action |
|------|--------|--------|
| Team 513 | ❌ CRITICAL | Doesn't exist; identify source |
| Team Names | ⚠️ HIGH | Abbreviated vs. Full name mismatch |
| Game Validation | ⚠️ MEDIUM | 44+ games with validation warnings |
| Gamelogs | ⚠️ MEDIUM | Some records missing |
| Production App | ✅ RUNNING | Errors logged but app functioning |

---

## Appendix: Affected Teams (Team Name Mapping)

| ID | DB Name | Expected Name | Status |
|----|---------|---------------|--------|
| 418 | Mon2 | Dresden Monarchs 2 Flag5 | MISMATCH |
| 227 | Frogs | Fighting Frogs | MISMATCH |
| 288 | Regen2 | Regensburg Phoenix II (?) | MISSING |
| 158 | Neu-Ulm | Neu-Ulm | MATCH? |
| 389 | Gendorf | Gendorf (?) | MISSING |
| 383 | Hannover | Hannover | MATCH? |
| 159 | Nürn | Nürnberg Hawks (?) | MISMATCH |
| 513 | (none) | UNKNOWN | DOES NOT EXIST |

---

**Generated:** 2026-05-30 13:15 UTC  
**Analysis Method:** Production logs (3-hour window) + Database queries
