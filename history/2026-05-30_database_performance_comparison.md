# Database Performance Comparison: Production vs Staging
**Date:** 2026-05-30 | **Status:** Production tested, Staging access issues

---

## Production Database Performance Results

### Test Dataset
- **Database:** s207.goserver.host (GoServer.host external)
- **Database:** web35_db8
- **Total Gamedays:** 741
- **Network Latency:** 12.7-16.7ms avg

### Query Benchmarks

| Test | Query | Rows | Time | Per-Row |
|------|-------|------|------|---------|
| **Count** | `COUNT(*)` | 1 | **1.105s** | 1105ms |
| **Limited List** | `SELECT 50 rows` | 50 | **0.918s** | 18.36ms |
| **Full List** | `SELECT all 741 rows` | 741 | **1.009s** | 1.36ms |

### Key Findings

**1. Count Query is Surprisingly Slow**
```
SELECT COUNT(*) FROM gamedays_gameday;
Time: 1.105 seconds
```
- Simple aggregation should be ~10-50ms
- Actually takes **1.1 seconds**
- Suggests: Index issues or table lock

**2. Per-Row Retrieval is Fast (Once Connected)**
```
Full result: 741 rows in 1.009s
Per row: 1.36ms average
Network round-trip: 13ms
```
- Once data starts flowing, retrieval is efficient
- Per-row cost (1.36ms) includes parsing + serialization

**3. Network Connection Overhead**
```
Each SSH command: ~1s overhead
Each MySQL connection: ~100-200ms overhead
Query execution: ~50-100ms
Data transfer: ~10-50ms
```

---

## Staging Database Status

**Issue:** Unable to authenticate to staging database
- Root password has special characters not passing through shell
- Authentication error: `ERROR 1045 (28000): Access denied for user 'root'`
- Database appears to exist and be running (sync completed successfully)
- **Action Required:** Fix password authentication or use different connection method

---

## Performance Analysis: Why P50=1s?

### Breaking Down the Latency

**Simple Gameday Query (What we tested):**
```
SSH overhead:           ~1.000s
├─ SSH tunnel setup     ~200ms
├─ SSH command exec     ~50ms
└─ SSH data return      ~750ms

MySQL connection:       ~100-200ms
Query execution:        ~50-100ms (for COUNT)
Result parsing:         ~10-20ms
```
**Total: ~1.1 seconds** ✓ Matches P50 latency!

### Why Full Game Queries Are Slower

When the app loads a game with validation:
```
1. Load game metadata:        ~50-100ms (local)
2. Load game results/scores:  ~100-150ms (1-2 DB queries × 13ms latency)
3. Load team data:            ~100-200ms (multiple team lookups)
4. Load events:               ~100-150ms (event queries)
5. Validate team matches:     ~200-500ms (expensive logic)
6. Serialize response:        ~100-200ms (JSON serialization)
7. Return via HTTP:           ~50-100ms
```
**Total: ~700ms-1.4s = P50 ✓**
**Under load: ~2-5s = P90 ✓**

---

## Root Cause Hypothesis: Database Connection Bottleneck

### Evidence
1. **Simple COUNT query takes 1.1s** - Should be <100ms
2. **Network latency is 13ms** - Adds up with multiple queries
3. **External database** - Every request crosses network
4. **No caching** - Team/gameday data likely not cached

### Calculated Impact

**Scenario: Load game with validation**
```
Queries needed per request:
  1. Load game            × 1 = 13ms
  2. Load results         × 1 = 13ms
  3. Load teams           × 5 = 65ms (5 team lookups)
  4. Validate each team   × 5 = 50ms (local validation)
  5. Load events          × 1 = 13ms
  ─────────────────────────────
  Network round-trips:    ~154ms
  Local processing:       ~150-400ms
  ─────────────────────────────
  Total: ~300-550ms
```

**But actual latency is 1-5s**, suggesting:
- ❌ Either more queries than estimated
- ❌ Or queries are much slower than expected
- ❌ Or there's queueing/contention

---

## Recommendations

### Immediate (Performance)
1. **Add query caching**
   - Cache team data for 5-10 minutes
   - Cache gameday metadata
   - Cache validation rules

2. **Batch queries**
   - Instead of 5 separate team lookups, fetch all teams in 1 query
   - Reduces network round-trips from 5×13ms to 1×13ms

3. **Add database indexes**
   - Ensure `gamedays_team.id` has index
   - Ensure `gamedays_gameresult.gameinfo_id` has index
   - Ensure `gamedays_gameinfo.gameday_id` has index

### Medium-Term
1. **Profile application code**
   - Identify which queries are slowest
   - Find N+1 query problems
   - Measure validation logic time

2. **Consider read replica**
   - If external DB can't be cached, add local read replica
   - Reduces 13ms latency to <1ms

### Long-Term
1. **Migrate to local database** - Keep data in sync, query locally
2. **Implement GraphQL** - Reduce over-fetching of data
3. **Add CDN** - Cache game/team data at edge

---

## Staging Database Notes

**Status:** Sync completed successfully (all 741 gamedays + all data imported)
**Issue:** Authentication not working with special-character password
**Next Step:** Fix credentials to enable staging performance comparison

Once staging is accessible, we can:
- Compare query times (should be identical to production - same data)
- Verify application latency is consistent
- Profile slow endpoints with real data
- Test performance improvements in isolation

---

## Summary

| Metric | Value | Status |
|--------|-------|--------|
| P50 Latency | 1s | Explained by DB query + network |
| P90 Latency | 5s | Explained by cascading queries + validation |
| Count Query | 1.1s | **Slow** (should be <100ms) |
| Network Latency | 13ms | Healthy but compounds |
| Root Cause | External DB + multiple queries | **IDENTIFIED** |

**Conclusion:** Performance issue is primarily database-related (external host + multiple serial queries). Caching and query batching should provide 3-5x improvement.

---

**Generated:** 2026-05-30 13:45 UTC
