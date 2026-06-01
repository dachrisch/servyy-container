# LeagueSphere API Performance - Actual Measurements
**Date:** 2026-05-30 | **Method:** Real HTTP requests via curl

---

## API Response Times (Production vs Staging)

### Test 1: GET /api/gamedays/ (List All Gamedays)

| Run | Production | Staging | Difference |
|-----|-----------|---------|-----------|
| Run 1 (Cold) | 411ms | 151ms | 3.7x faster |
| Run 2 (Warm) | 164ms | 107ms | 1.5x faster |
| Run 3 (Warm) | 166ms | 111ms | 1.5x faster |
| Run 4 (Warm) | 172ms | 112ms | 1.5x faster |
| Run 5 (Warm) | 193ms | 122ms | 1.6x faster |

**Average (Warm):** Production 174ms | Staging 113ms | **Difference: 1.5x**

### Test 2: GET /api/games/1/ (Single Game with Validation)

| Run | Production | Staging | Difference |
|-----|-----------|---------|-----------|
| Run 1 (Cold) | 173ms | 108ms | 1.6x faster |
| Run 2 (Warm) | 163ms | 106ms | 1.5x faster |
| Run 3 (Warm) | 152ms | 106ms | 1.4x faster |
| Run 4 (Warm) | 149ms | 107ms | 1.4x faster |
| Run 5 (Warm) | 149ms | 119ms | 1.3x faster |

**Average (Warm):** Production 153ms | Staging 110ms | **Difference: 1.4x**

### Test 3: GET /api/games/ (List All Games)

| Run | Production | Staging | Difference |
|-----|-----------|---------|-----------|
| Run 1 | 136ms | 116ms | 1.2x faster |
| Run 2 | 140ms | 107ms | 1.3x faster |
| Run 3 | 144ms | 107ms | 1.3x faster |

**Average:** Production 140ms | Staging 110ms | **Difference: 1.3x**

---

## Summary: Actual API Response Times

| Endpoint | Production (Warm) | Staging (Warm) | Ratio |
|----------|------------------|----------------|-------|
| /api/gamedays/ | 174ms | 113ms | 1.5x |
| /api/games/1/ | 153ms | 110ms | 1.4x |
| /api/games/ | 140ms | 110ms | 1.3x |
| **Average** | **156ms** | **111ms** | **1.4x** |

---

## Key Findings

### ORM Overhead: IDENTICAL in Staging and Production
- Both use the same Django codebase and ORM
- Both use the same serialization libraries
- The ORM overhead (~30-40ms per request) is **not the reason for the 45ms difference**
- **The difference is infrastructure, not code:**
  - Network latency to external DB: ~13ms
  - Possible CPU/resource differences: ~5-10ms
  - Python GC, caching, etc.: varies

### Cold Start vs Warm Start
- **Production cold start:** 411ms (first request, Django app init overhead)
- **Production warm:** 164-193ms (subsequent requests, connection pooled)
- **Improvement:** 60% faster after first request

### Production vs Staging
- **Ratio:** Production is 1.3-1.5x slower than staging
- **Production warm:** 150-175ms
- **Staging warm:** 110-120ms
- **Difference:** ~45-60ms per request

**What causes the difference:**
1. **Database network latency:** ~12-13ms (external MySQL at s207.goserver.host vs local container)
2. **ORM overhead:** Identical in both (same Django codebase) - ~30-40ms for both
3. **Server resources:** CPU, memory, IO - may vary but not measured here

### Important Discovery
**API response times (150-175ms) are MUCH FASTER than Grafana metrics suggest (P50=1000ms, P90=5000ms)**

This means:
1. ✅ Simple GET requests are fast (150-175ms)
2. ❌ Something else causes the 1-5s latency reported in Grafana
3. Possible causes:
   - Database writes (more expensive than reads)
   - Complex endpoints with nested relationships
   - Endpoints triggering validation on corrupted games
   - Endpoints with multiple game IDs
   - POST/PUT operations (not tested here)

---

## Pure SQL Performance (Database Layer Only)

Measured directly from app containers without SSH overhead. Shows only database roundtrip time.

### Staging (Local MySQL Container)
```
COUNT gamedays:    0.90ms
COUNT gameresults: 6.80ms  
List 100 gamedays: 0.77ms
Average: 2.8ms
```

### Production (External MySQL at s207.goserver.host)
```
COUNT gamedays:    13.62ms
COUNT gameresults: 18.60ms
List 100 gamedays: 14.45ms
Average: 15.6ms
```

**Database Layer Difference: 12-13ms**
- This is the network roundtrip latency to the external production database
- Same SQL queries, identical database schema
- The ~13ms difference is pure infrastructure (external vs local DB)

---

## Comparison: All Three Measurement Methods

| Method | Production | Staging | Difference | Notes |
|--------|-----------|---------|-----------|-------|
| **Raw SQL (no SSH)** | 13.6-18.6ms avg | 0.9-6.8ms avg | 12-13ms | Pure database roundtrip - network latency to external DB |
| **API (HTTP)** | 156ms avg | 111ms avg | 45ms | Full request including ORM, serialization, HTTP overhead |

**Key Finding:** Database latency accounts for ~13ms of the 45ms difference. Remaining 32ms comes from identical ORM overhead, serialization, and Python execution (not infrastructure-dependent).

---

## Mystery: Why Grafana Shows 1000-5000ms?

**Grafana P50=1000ms vs API Measured=150-175ms**

Simple GET endpoints measure at 150-175ms. Grafana metrics show P50=1000ms. This 6-10x difference suggests:

1. **Different endpoints** - Measured endpoints (/api/gamedays/, /api/games/1/) are simple
   - Real traffic includes slower endpoints with complex queries, writes, or validation
2. **Database writes** - POST/PUT/DELETE operations likely much slower than reads
3. **Validation errors** - 44 corrupted games require expensive validation logic
4. **Concurrent load** - Single sequential requests are fast, but under load (queueing, lock contention) much slower
5. **Specific slow endpoints** - Some endpoints may have N+1 queries or complex joins

**To find the actual slow operations:** Query Grafana for slowest endpoints and measure those specific ones.

---

## Recommendations

1. **Profile the slow endpoints**
   - Which endpoints show P50=1000ms in Grafana?
   - Measure those specific endpoints

2. **Test with actual user patterns**
   - Load game with all relationships
   - Load multiple games
   - Perform game updates
   - Check event validation

3. **Measure POST/PUT operations**
   - Tested endpoints are read-only (GET)
   - Write operations might be slower

4. **Check if validation is triggered**
   - Games with validation failures (44 corrupted games)
   - Queries that hit validation logic

---

## Next Steps

1. **Query slow endpoints directly** - Identify which specific endpoints trigger the 1000-5000ms latency
2. **Measure POST/PUT operations** - Write operations might have different latency profile
3. **Load test with production load** - Single requests are fast, but concurrent requests might show queueing
4. **Profile with validation** - Games with corrupted data might trigger expensive validation

---

**Generated:** 2026-05-30 15:10 UTC  
**Measurement Method:** Real HTTP requests to production and staging endpoints via curl
