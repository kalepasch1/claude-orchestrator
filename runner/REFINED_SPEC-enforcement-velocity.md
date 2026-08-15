# Refined Spec: Enforcement Velocity Detection

## Overview
Build `server/engines/hive/enforcement-velocity.ts`: a pure-function velocity scorer that detects acceleration in regulatory fact arrivals per (domain × jurisdiction), then conditionally lowers `hive_scout_sources.cadence_hours` and raises client alerts.

---

## Resolved Ambiguities

### 1. Input Schema: `reg_facts` Arrival Timestamps
**Decision:** Array of arrival objects with domain, jurisdiction, and createdAt timestamp.

```typescript
interface RegFactArrival {
  domain: string
  jurisdiction: string
  createdAt: Date | string // ISO 8601 or Date object
}
```

**Rationale:** Derived from SQL queries over `public.reg_facts` table (indexed on `domain`, `jurisdiction`, `created_at`). Timestamps use database precision (millisecond resolution); caller converts to ISO 8601 or Date.

---

### 2. Time Window for Historical Data
**Decision:** Last 30 days (fixed window).

**Rationale:** Standard observability window (balances responsiveness vs. noise); 30-day lookback detects sustained acceleration, not one-off spikes. SQL: `WHERE created_at >= NOW() - INTERVAL '30 days'`.

---

### 3. Velocity/Acceleration Algorithm
**Decision:** Rate of arrival (facts per day) over the 30-day window.

```
velocity_score = arrival_count / 30
```

**Rationale:** Simple, interpretable metric. Example: 12 arrivals in 30 days = 0.4 facts/day. Normalized 0–100 scale for UI/alerting.

**Formula for 0–100 scale:**
```
velocity_normalized = min(100, Math.round((velocity_score / 5) * 100))
// Cap at 5 facts/day = 100 score (tails saturate above this)
```

---

### 4. Regulatory Temperature Spiking: Threshold & Metric
**Decision:** Velocity ≥ 2 facts/day triggers cadence reduction + alert.

| Velocity (facts/day) | Normalized Score | Urgency Level | Action |
|---|---|---|---|
| 0.0–0.5 | 0–10 | — | No alert |
| 0.5–1.0 | 10–20 | low | Alert only (no cadence change) |
| 1.0–2.0 | 20–40 | medium | Alert + cadence reduction |
| 2.0–3.0 | 40–60 | high | Alert + aggressive cadence reduction |
| ≥3.0 | 60–100 | critical | Alert + max reduction (6h floor) |

**Rationale:** Threshold of 2 facts/day represents 2× baseline ("spiking"), derived from typical enforcement cycles (1 fact per 2 weeks baseline). Below 1 fact/day is baseline noise.

---

### 5. Velocity Score → Cadence Hours Mapping
**Decision:** Linear interpolation from 168h (baseline) to 6h (floor).

```typescript
function mapVelocityToCadence(velocity: number): number {
  const floor = 6
  const ceiling = 168
  const spikeThreshold = 2.0 // facts/day

  if (velocity < spikeThreshold) {
    return ceiling // No change; maintain baseline
  }

  // Linear reduction from 168h down to 6h
  // velocity=2.0 → ~100h, velocity=4.0 → 6h (floor)
  const scaledVelocity = Math.min(velocity, 4.0)
  const fraction = (scaledVelocity - spikeThreshold) / (4.0 - spikeThreshold)
  const newCadence = ceiling - fraction * (ceiling - floor)

  return Math.max(floor, Math.round(newCadence))
}
```

**Rationale:** 
- Linear ensures predictability (velocity 2 → ~100h; velocity 3 → ~53h; velocity 4+ → 6h floor).
- Range (168 → 6) gives 28x reduction headroom.
- Saturation at 4 facts/day prevents over-reduction beyond 6h floor.

---

### 6. Ceiling Value for Cadence Hours
**Decision:** 168 hours (7 days, current default in `hive_scout_sources`).

**Rationale:** Matches database default; symmetric to floor (168/6 = 28). No reduction below baseline; no increase above it (one-way throttle).

---

### 7. Client Alert Urgency & Mechanism
**Decision:** Database write to `public.client_alerts` table; urgency derived from velocity.

```typescript
interface ClientAlert {
  domain: string
  jurisdiction: string
  urgency_level: 'low' | 'medium' | 'high' | 'critical'
  reason: string // e.g., "Enforcement velocity spike: 2.3 facts/day (30-day avg)"
  velocity_score: { value: number; unit: string; window_days: number }
  status: 'open'
  detected_at: timestamp (now)
  created_at: timestamp (now)
}
```

**Why database write?** Service-role RLS policy already exists; avoids webhooks/event bus; queryable for ops dashboards.

**No alert triggers at velocity < 1.0** (baseline noise).

---

### 8. Edge Cases & Behavior
**Decision:** Fail-soft on missing/invalid data.

| Scenario | Behavior | Velocity | Alert? |
|---|---|---|---|
| No arrivals in 30d | velocity = 0 | 0 | No |
| Single arrival | velocity = 0.033 (1/30) | ~0 | No |
| Identical timestamps | Count once per unique timestamp | Actual count | Per threshold |
| Domain×jurisdiction not found | Query returns empty list | 0 | No |
| Stale data (>30d old) | Excluded from window | N/A | N/A |
| NULL createdAt in reg_facts | Skip that row | Adjusted count | Adjusted |

**Rationale:** Graceful degradation; no crashes on malformed input. Tests must cover all 7 cases.

---

## Acceptance Criteria

### Input/Output Signatures
```typescript
// Pure core function (unit-testable, no side effects)
export function computeVelocity(arrivals: RegFactArrival[]): VelocityMetric
  → { 
      domainJurisdiction: string
      velocityScore: number // 0–100 normalized
      factCount: number
      factRate: number // facts/day
      windowDays: number
      recommendedCadenceHours: number
      recommendedUrgency: 'low' | 'medium' | 'high' | 'critical' | 'none'
    }

// Thin DB wrapper (writes result)
export async function updateScoutCadenceAndAlert(
  db: SupabaseClient,
  domainJurisdiction: { domain: string; jurisdiction: string },
  velocity: VelocityMetric
): Promise<{ cadenceUpdated: boolean; alertInserted: boolean; error?: string }>
```

### Test Coverage (Minimum 20 test cases)
1. ✓ Empty arrivals → velocity = 0, no alert
2. ✓ Single arrival → velocity ≈ 0.033, no alert
3. ✓ Exactly 30 arrivals (1/day) → velocity = 1.0, medium urgency
4. ✓ Exactly 60 arrivals (2/day) → velocity = 2.0, high urgency, cadence ≈ 100h
5. ✓ Exactly 120 arrivals (4/day) → velocity ≥ 2.0, critical urgency, cadence = 6h (floor)
6. ✓ Mixed timestamps across 30 days → correctly counted
7. ✓ Duplicate timestamps → counted once per unique ts
8. ✓ Arrivals outside 30-day window → excluded
9. ✓ NULL createdAt → skipped, count adjusted
10. ✓ velocityScore capped at 100
11. ✓ cadenceHours capped at ceiling (168h)
12. ✓ cadenceHours floored at 6h
13. ✓ urgency = 'none' when velocity < 1.0
14. ✓ urgency = 'low' when 0.5 ≤ velocity < 1.0
15. ✓ urgency = 'medium' when 1.0 ≤ velocity < 2.0
16. ✓ urgency = 'high' when 2.0 ≤ velocity < 3.0
17. ✓ urgency = 'critical' when velocity ≥ 3.0
18. ✓ Cadence interpolation: velocity = 2.0 → ~100h
19. ✓ Cadence interpolation: velocity = 3.0 → ~53h
20. ✓ Cadence interpolation: velocity = 4.0+ → 6h (saturated)

### Execution Trigger
**Decision:** On-demand via API endpoint or scheduled batch job.

- **API route:** `POST /api/hive/enforcement-velocity/compute` → accepts `{ domain, jurisdiction }` → calls `computeVelocity()` + `updateScoutCadenceAndAlert()`
- **Batch job:** Scheduled cron (not in scope here; separate handler)
- **Return:** `{ velocityScore, newCadenceHours, urgencyLevel, alertId }`

### Performance SLA
- **Latency:** < 500ms for single domain×jurisdiction
- **Memory:** < 50 MB for lookback of 30 days (< 1000 arrivals typical)
- **QPS:** No special scaling required (typical load: 1–10 req/min)

### Time Precision
- Input timestamps: Millisecond resolution (ISO 8601 or JavaScript Date)
- Database storage: Millisecond (TIMESTAMPTZ in PostgreSQL)
- Calculations: Use JavaScript `Date` objects (1ms precision)

---

## File Locations

| Purpose | Path |
|---|---|
| Pure core logic | `server/engines/hive/enforcement-velocity.ts` |
| Unit tests | `tests/engines/hive/enforcement-velocity.test.ts` |
| DB wrapper & API route | `server/api/hive/enforcement-velocity.post.ts` |
| Type definitions | `types/hive.ts` (extend existing RegFacts, add VelocityMetric) |
| Database schema | Already exists: `public.client_alerts`, `public.hive_scout_sources`, `public.reg_facts` |

---

## Success Proof
```bash
npx vitest run tests/engines/hive/enforcement-velocity.test.ts
# All 20+ tests pass ✓
# Exit code 0
```

**Golden path test:**
```
Given: domain='crypto', jurisdiction='NY', 
       30 arrivals over 30 days (1 per day)
Then:  computeVelocity() → { velocityScore: 20, factRate: 1.0, urgency: 'medium' }
       cadenceHours reduced from 168 → ~106h
       client_alerts row inserted with urgency='medium', status='open'
```

---

## Implementation Notes

1. **Logger:** Use `createLogger('enforcement-velocity')` for structured logs (existing convention).
2. **Fail-soft:** Return empty VelocityMetric (velocity=0, urgency='none') on any query error; log the error but do not throw.
3. **Atomicity:** DB wrapper ensures cadence update and alert insert are transactional (single transaction, both succeed or both roll back).
4. **Idempotency:** Multiple calls with identical (domain, jurisdiction) create new alerts (not upserts); assume caller de-dupes if needed.
5. **RLS:** Service-role policies already permit writes to `client_alerts` and `hive_scout_sources`; no additional policy needed.
