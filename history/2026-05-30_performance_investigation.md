# LeagueSphere Performance Investigation
**Date:** 2026-05-30 | **Latency:** P50=1s, P90=5s | **Status:** INVESTIGATING

---

## Initial Findings

### Container Metrics (Healthy ✅)
- **CPU:** 0.71% (very low - not bottleneck)
- **Memory:** 140.2MB / 7.57GB (1.81% - plenty of headroom)
- **Network:** 608MB sent / 1.12GB received (normal)
- **Block I/O:** Minimal (13.3MB written / 221KB read)

### Error Rate (Low ✅)
- Last 30 mins: **59 errors** (mostly 404s - static assets)
  - Not Found: 47
  - Unauthorized: 6
  - Forbidden: 3
  - Bad Request: 3

### Validation Issues (Minimal ✅)
- Events data mismatch: **2 in last hour**
- Team 513 errors: **1 in last hour**
- Neither is significant contributor to latency

### Database Status (Healthy ✅)
- Active connections: 29 (healthy pool)
- Threads cached: 229
- No slow queries detected
- Response time: 71-106ms per query (fast)

---

## The Performance Paradox

```
OBSERVED:
  P50 latency = 1 second  ⚠️ HIGH
  P90 latency = 5 seconds ⚠️ HIGH
  CPU usage = 0.71%       ✅ LOW
  Memory = 1.81%          ✅ LOW
  Errors = 59/30mins      ✅ LOW
  
CONCLUSION: Not a resource constraint or error handling bottleneck
```

---

## Hypotheses for Slow Performance

### Hypothesis 1: Game Validation Logic
**Theory:** Even successful requests are expensive because they validate all game/event data.

**Evidence:**
- We know 44+ games have validation failures
- Validation runs on every game request
- Even when validation passes, it still processes

**Investigation Needed:**
- Profile `/api/games/` endpoints
- Check game list queries with validation
- Measure event validation processing time

### Hypothesis 2: Event Processing Cascade
**Theory:** Some requests trigger validation of all 44+ corrupted games.

**Evidence:**
- Games with mismatched team data require extra validation
- Validation logic runs on every request that touches games
- Each game iterates through team validation

**Investigation Needed:**
- Check which endpoints fetch multiple games
- Profile event validation in `passcheck_service.py`
- Measure time per game validation

### Hypothesis 3: Team Name Resolution
**Theory:** Abbreviated team names require expensive lookups or string matching.

**Evidence:**
- Database has abbreviated names ("Mon2", "Frogs")
- App expects full names ("Dresden Monarchs 2 Flag5", "Fighting Frogs")
- Each team reference might trigger mapping logic

**Investigation Needed:**
- Check team name resolution code
- Profile name matching/lookup performance
- Count team lookups per request

### Hypothesis 4: Bad Request Processing
**Theory:** Invalid login/request attempts use expensive validation.

**Evidence:**
- Many "Bad Request" errors on `/accounts/auth/login/`
- Form validation with CSRF checks is typically expensive
- Could be repeated from same source (brute force attempts?)

**Investigation Needed:**
- Check login form validation code
- Monitor source IPs for repeated failures
- Profile CSRF token validation

### Hypothesis 5: External Database Latency
**Theory:** 13ms network latency to external database compounds on every query.

**Evidence:**
- Database is on GoServer.host (12.7-16.7ms latency)
- Each request might trigger multiple queries
- 13ms per query × many queries = slow response

**Investigation Needed:**
- Count queries per request
- Profile database round-trips
- Check query batching efficiency

---

## Performance Profile (Estimated)

Based on P50=1s and P90=5s:

```
Request Flow (Typical):
  1. Auth/CSRF validation     ~50-100ms
  2. Load game data           ~200-300ms (external DB + network)
  3. Validate game events     ~400-700ms (validation logic)
  4. Serialize response       ~100-200ms
  5. Send to client           ~50-100ms
  ─────────────────────────────────────────
  Total                       ~800ms-1.4s (matches P50≈1s)

Under Load (P90):
  Same flow but with:
  - Queue delay               ~1-2s
  - Cascading validation      ~2-3s (multiple corrupted games)
  - DB connection contention  ~500ms-1s
  ─────────────────────────────────────────
  Total                       ~4-7s (matches P90≈5s)
```

---

## Recommended Deep Dives

### 1. Profile Slow Endpoints
```
Critical endpoints to profile:
- GET /api/games/          (game list - likely slow)
- GET /api/games/{id}/     (single game - validation)
- GET /passcheck/team/*/   (team roster - validation)
- POST /accounts/auth/login/ (form validation - expensive)
```

### 2. Add Timing Instrumentation
```
Add Django middleware to measure:
- Request auth time
- Database query time
- Validation logic time
- Serialization time
- Response write time
```

### 3. Check Application Caching
```
Are these cached?
- Team data (expensive lookups)
- Game validation rules
- Event data
```

### 4. Analyze Request Patterns
```
Questions:
- How many requests per second?
- What's the distribution of endpoints?
- Are there bulk requests?
- Any bot traffic?
```

---

## Next Steps

1. **Enable Django debug toolbar** or logging to see request timings
2. **Profile slow endpoints** with cProfile or similar
3. **Check application code** for:
   - N+1 query problems
   - Expensive validation loops
   - Missing database indexes
4. **Investigate team name resolution** - might be the key
5. **Monitor database query count** per request

---

## Preliminary Conclusion

The performance issue is **NOT** caused by:
- ❌ Resource constraints (CPU/memory are healthy)
- ❌ Database queries (no slow queries detected)
- ❌ High error rates (only 59 errors in 30 mins)
- ❌ Validation failures (only 2 game validation errors in 1 hour)

**Most Likely Cause:**
- ✅ Application-level logic (validation, team resolution, serialization)
- ✅ Multiple serial database queries (network round-trips)
- ✅ Cascading validation on corrupted game data
- ✅ Team name mapping overhead

**Action:** Need application profiling to identify specific bottleneck.

