# Refined Task Spec: hive-enforcement-velocity

**Task Slug**: `hive-enforcement-velocity`  
**Status**: READY FOR IMPLEMENTATION  
**Date Finalized**: 2026-07-30  
**Branch**: `agent/hive-enforcement-velocity` (based on `master`)

---

## Objective (Plain English)

Detect when regulatory fact arrivals are accelerating in a domain×jurisdiction and automatically reduce the Hive's polling interval (`cadence_hours`) to increase surveillance frequency. When enforcement activity spikes, the system should raise an alert to notify operators that regulatory temperature is rising.

**Core Problem Solved**: Without velocity scoring, the Hive polls all domain×jurisdictions on a fixed cadence, missing opportunities to react quickly when enforcement activity accelerates. This system enables reactive reallocation of surveillance resources based on real-time activity signals.

---

## What This System Does

The `enforcement-velocity` engine computes three core operations:

1. **Velocity Scoring**: Analyze `reg_facts` arrival timestamps for a domain×jurisdiction over a rolling 24-hour window:
   - Count facts arriving per hour (normalized rate)
   - Compute acceleration as slope of a 3-point time-series (using polynomial fit)
   - Yield a velocity score on `[0.0, 1.0]` where 0.0 = no activity, 1.0 = rapid acceleration

2. **Cadence Adjustment**: When velocity score exceeds 0.5 (moderate-to-high activity):
   - Lower `hive_scout_sources.cadence_hours` proportionally (see mapping table below)
   - Ensure floor of 6 hours and ceiling of 24 hours (never below 6h, never above 24h)
   - Update `last_velocity_score` and `velocity_evaluated_at` in metadata

3. **Alert Escalation**: When velocity score > 0.7 (high acceleration):
   - Create an alert row in `alerts` table with source='hive_enforcement', severity='warn'
   - Include velocity score and top 3 recent facts in alert payload
   - Dedupe via (source='hive_enforcement', source_key='domain::jurisdiction')

---

## Implementation Details

### Input: `reg_facts` Arrival Timestamps

**Table**: `public.reg_facts` (from migration 502_hive_innovation_layer.sql)

Query all facts for a domain×jurisdiction pair where `is_current = true` and `created_at >= now() - interval '24 hours'`:

```sql
SELECT id, domain, jurisdiction, fact_type, subject, lifecycle_stage, created_at
FROM public.reg_facts
WHERE domain = ? AND jurisdiction = ? AND is_current = true
  AND created_at >= now() - interval '24 hours'
ORDER BY created_at ASC
```

**Schema fields used**:
- `created_at` (timestamptz): Fact discovery timestamp (UTC)
- `domain` (text): e.g. 'gaming', 'lending', 'money_transmitter'
- `jurisdiction` (text): e.g. 'US-CA', 'US-NY', 'tribal-navajo'
- `fact_type` (text): e.g. 'enforcement_action', 'license_requirement', 'ban'
- `subject` (text): Fact description
- `lifecycle_stage` (text): e.g. 'proposed_bill', 'effective', 'enforced'

---

### Core Algorithm: `computeVelocity(arrivals: FactArrival[])`

**Input**: Array of `FactArrival` objects with `created_at` (ISO 8601 datetime string or Date)

**Output**: Velocity score on `[0.0, 1.0]`

**Algorithm**:

1. **Bin arrivals into hourly buckets** (24 buckets, rolling 24h):
   - For each hour in the last 24 hours, count facts arriving in that hour
   - Result: `hourly_counts = [count_hour_0, count_hour_1, ..., count_hour_23]`

2. **Normalize rate**:
   - Total facts = sum of hourly_counts
   - If total < 1, return `0.0` (no activity)
   - Normalize: `rates = hourly_counts.map(c => c / total)`

3. **Compute acceleration** via polynomial fit (quadratic):
   - Use least-squares fit of a degree-2 polynomial to `rates` over 24 hours
   - Extract the acceleration coefficient (second derivative = 2 * quadratic coefficient)
   - Normalize acceleration to `[-1, 1]` range

4. **Map acceleration to velocity score**:
   - Positive acceleration (ramping up) → score on `[0.5, 1.0]`
   - Negative acceleration (ramping down) → score on `[0.0, 0.5]`
   - No acceleration (flat) → score = `0.5`
   - Formula: `velocity = 0.5 + (acceleration / 2.0)`

5. **Clamp to `[0.0, 1.0]`**

**Example**:
```
Arrivals (last 24h): 1 fact at hour 0, 2 at hour 12, 5 at hour 23 (acceleration detected)
Hourly counts: [1, 0, 0, ..., 0, 2, 0, ..., 0, 5]
Total: 8 facts
Normalized rates: [0.125, 0, ..., 0, 0.25, 0, ..., 0, 0.625]
Polynomial fit: coefficient_2 ≈ 0.015 (positive, ramping up)
Acceleration: 0.015 * 2 = 0.03
Velocity score: 0.5 + (0.03 / 2.0) ≈ 0.515 → maps to 'moderate' activity
```

---

### Velocity Score → Cadence Mapping

**Velocity Score Range** → **Cadence Hours** → **Alert Severity**

| Score Range | Interpretation | Cadence Hours | Alert? |
|---|---|---|---|
| 0.0–0.3 | Silent (no activity) | 24 (no change) | No |
| 0.3–0.5 | Low activity | 18 | No |
| 0.5–0.7 | Moderate activity | 12 | No |
| 0.7–0.85 | High activity | 6 (floor) | Yes, 'warn' |
| 0.85–1.0 | Critical acceleration | 6 (floor) | Yes, 'critical' |

**Rule**: 
- Always enforce floor (≥ 6 hours) and ceiling (≤ 24 hours)
- Only update if score differs by > 0.05 from previous (avoid thrashing on marginal changes)
- Store previous score in `hive_scout_sources.metadata['last_velocity_score']` for comparison

---

### Domain × Jurisdiction Key

**Compound natural key**: `${domain}::${jurisdiction}`

- Separator: double colon (PostgreSQL convention)
- Example: `gaming::US-CA`, `lending::tribal-navajo`, `money_transmitter::US-NY`
- Usage: Alert deduping via `alerts.source_key = '${domain}::${jurisdiction}'`

---

### Database Write Interface

**Function signature** (Nitro API handler in `server/api/hive/enforcement-velocity.post.ts`):

```typescript
// POST /api/hive/enforcement-velocity
// Body: { domain: string, jurisdiction: string }
// Response: { velocity_score: number, cadence_hours: number, alert_created?: boolean, error?: string }
export default defineEventHandler(async (event) => {
  const { domain, jurisdiction } = await readBody(event);
  
  const result = await computeAndWriteVelocity(domain, jurisdiction);
  return result;
});
```

**Core engine** (pure function in `server/engines/hive/enforcement-velocity.ts`):

```typescript
export async function computeAndWriteVelocity(
  domain: string,
  jurisdiction: string
): Promise<VelocityWriteResult> {
  // 1. Query reg_facts via supabase
  // 2. Compute velocity score via computeVelocity()
  // 3. Determine new cadence_hours
  // 4. UPDATE hive_scout_sources where domain=? and jurisdiction=?
  // 5. Conditionally CREATE alert if score > 0.7
  // 6. Return result with score, cadence, alert_id
}
```

**Database writes**:

1. **Update `hive_scout_sources`** (via Supabase client):
   ```sql
   UPDATE public.hive_scout_sources
   SET cadence_hours = ?,
       metadata = jsonb_set(
         COALESCE(metadata, '{}'::jsonb),
         '{last_velocity_score}',
         to_jsonb(?::float)
       ),
       metadata = jsonb_set(
         metadata,
         '{velocity_evaluated_at}',
         to_jsonb(now()::text)
       ),
       updated_at = now()
   WHERE domain = ? AND jurisdiction = ?
   ```

2. **Conditionally create alert** (via Supabase insert, upsert on source_key):
   ```sql
   INSERT INTO public.alerts (
     source, source_key, severity, title, detail, payload, status
   ) VALUES (
     'hive_enforcement',
     ?, -- '${domain}::${jurisdiction}'
     ?, -- 'warn' or 'critical'
     'Enforcement velocity spike in ' || ? || ' / ' || ?,
     'Facts arriving at accelerating rate over last 24h',
     jsonb_build_object(
       'velocity_score', ?,
       'recent_facts', ?::jsonb,
       'domain', ?,
       'jurisdiction', ?
     ),
     'open'
   )
   ON CONFLICT (source, source_key) WHERE status = 'open'
   DO UPDATE SET updated_at = now()
   ```

---

## File Paths (Exact)

| Component | Path | Type |
|-----------|------|------|
| Pure engine (velocity scoring) | `/Users/kpasch/Documents/apparently/server/engines/hive/enforcement-velocity.ts` | TypeScript source |
| Thin DB wrapper | `/Users/kpasch/Documents/apparently/server/engines/hive/enforcement-velocity.write.ts` | TypeScript source |
| API handler | `/Users/kpasch/Documents/apparently/server/api/hive/enforcement-velocity.post.ts` | TypeScript Nitro handler |
| Zod schema | `/Users/kpasch/Documents/apparently/shared/schemas/hive.ts` | TypeScript types + validation |
| Unit tests | `/Users/kpasch/Documents/apparently/tests/engines/hive/enforcement-velocity.test.ts` | Vitest |

---

## Acceptance Criteria (ALL TESTABLE)

### Code Correctness ✓
- [ ] All tests in `enforcement-velocity.test.ts` pass: `npm test tests/engines/hive/enforcement-velocity.test.ts`
- [ ] No TypeScript errors (strict mode)
- [ ] Zod validation enforces domain/jurisdiction/arrivals schema
- [ ] computeVelocity is pure (no side effects, deterministic)
- [ ] All exception paths return sensible defaults (no unhandled throws)

### Velocity Computation ✓
- [ ] Zero arrivals (last 24h) → velocity = 0.0
- [ ] 1 arrival → velocity = 0.0 (insufficient data)
- [ ] Constant rate (N facts per hour, evenly spaced) → velocity ≈ 0.5 (no acceleration)
- [ ] Accelerating arrivals (0→1→2→3 facts per hour) → velocity > 0.5
- [ ] Decelerating arrivals (3→2→1→0 facts per hour) → velocity < 0.5
- [ ] Spike at end (0→0→...→10 in final hour) → velocity > 0.8
- [ ] Sample test: "gaming::US-CA with 8 facts (accelerating) yields score 0.65 → cadence=12"

### Cadence Adjustment ✓
- [ ] velocity ≤ 0.3: cadence unchanged (remains 24 or previous value)
- [ ] velocity 0.3–0.5: cadence → 18 hours
- [ ] velocity 0.5–0.7: cadence → 12 hours
- [ ] velocity 0.7–0.85: cadence → 6 hours (floor enforced)
- [ ] velocity ≥ 0.85: cadence → 6 hours (floor enforced)
- [ ] Score change < 0.05: cadence unchanged (dedup thrashing)
- [ ] Cadence never < 6 or > 24 hours

### Alert Escalation ✓
- [ ] velocity ≤ 0.7: no alert created
- [ ] velocity 0.7–0.85: alert created with severity='warn'
- [ ] velocity ≥ 0.85: alert created with severity='critical'
- [ ] Alert source='hive_enforcement', source_key='domain::jurisdiction'
- [ ] Alert payload includes velocity_score and top 3 recent facts
- [ ] Dedup: existing OPEN alert for same source_key → updated_at touched, no duplicate

### Metadata & Timestamps ✓
- [ ] velocity_evaluated_at stored as ISO 8601 UTC (YYYY-MM-DDTHH:MM:SSZ)
- [ ] last_velocity_score stored as float (0.0–1.0) in metadata
- [ ] updated_at timestamp on hive_scout_sources reflects write time

### Edge Cases ✓
- [ ] No reg_facts for domain×jurisdiction → velocity = 0.0, no alert
- [ ] Single domain but multiple jurisdictions → each scored independently
- [ ] Timezone handling: all timestamps treated as UTC (no conversion)
- [ ] Unicode in fact_subject → preserved in alert payload
- [ ] Domain/jurisdiction not found in hive_scout_sources → INSERT new row (or skip alert, log warning)

### Integration & API ✓
- [ ] POST /api/hive/enforcement-velocity accepts { domain, jurisdiction }
- [ ] Response includes { velocity_score, cadence_hours, alert_created, timestamp }
- [ ] Error response: { error: string, timestamp }
- [ ] Zod validation on request body enforces required fields and types
- [ ] Calls Supabase via server-side client (no auth leakage)

---

## Sample Test Data & Expected Results

### Test Case 1: Accelerating Activity (Should Alert)

**Input**: `gaming::US-CA` with facts arriving acceleratingly

```json
{
  "domain": "gaming",
  "jurisdiction": "US-CA",
  "arrivals": [
    { "created_at": "2026-07-30T00:00:00Z", "subject": "New slot machine rule proposed" },
    { "created_at": "2026-07-30T06:00:00Z", "subject": "Notice of intent to investigate" },
    { "created_at": "2026-07-30T12:00:00Z", "subject": "First enforcement letter issued" },
    { "created_at": "2026-07-30T18:00:00Z", "subject": "Second enforcement letter issued" },
    { "created_at": "2026-07-30T22:00:00Z", "subject": "Third enforcement letter issued" }
  ]
}
```

**Expected Output**:
```json
{
  "velocity_score": 0.75,
  "cadence_hours": 6,
  "alert_created": true,
  "alert_severity": "warn",
  "previous_cadence_hours": 24,
  "timestamp": "2026-07-30T23:45:00Z"
}
```

**Database changes**:
- `hive_scout_sources` row (domain='gaming', jurisdiction='US-CA'): cadence_hours 24→6, metadata.last_velocity_score=0.75, metadata.velocity_evaluated_at='2026-07-30T23:45:00Z'
- `alerts` row created: source='hive_enforcement', source_key='gaming::US-CA', severity='warn', payload includes top 3 facts

---

### Test Case 2: Constant Activity (No Alert)

**Input**: `lending::US-NY` with steady-state facts

```json
{
  "domain": "lending",
  "jurisdiction": "US-NY",
  "arrivals": [
    { "created_at": "2026-07-29T01:00:00Z", "subject": "Rate cap rule clarified" },
    { "created_at": "2026-07-29T07:00:00Z", "subject": "Compliance deadline extended" },
    { "created_at": "2026-07-29T13:00:00Z", "subject": "FAQ updated" },
    { "created_at": "2026-07-29T19:00:00Z", "subject": "Exam guidance released" }
  ]
}
```

**Expected Output**:
```json
{
  "velocity_score": 0.50,
  "cadence_hours": 12,
  "alert_created": false,
  "previous_cadence_hours": 12,
  "timestamp": "2026-07-30T23:45:00Z"
}
```

---

### Test Case 3: No Activity (Floor)

**Input**: `money_transmitter::tribal-navajo` with zero facts in last 24h

```json
{
  "domain": "money_transmitter",
  "jurisdiction": "tribal-navajo",
  "arrivals": []
}
```

**Expected Output**:
```json
{
  "velocity_score": 0.0,
  "cadence_hours": 24,
  "alert_created": false,
  "timestamp": "2026-07-30T23:45:00Z"
}
```

---

## Time-Series Window & Edge Cases

### Time-Series Window
- **Rolling window**: Last 24 hours from `now()`
- **Granularity**: Hourly buckets (24 buckets total)
- **Boundary**: Facts with `created_at >= now() - interval '24 hours'`
- **Timezone**: All timestamps in UTC; no client-side conversion

### Edge Case Handling

1. **No facts for domain×jurisdiction**:
   - velocity = 0.0, no cadence change, no alert

2. **Single fact in 24h**:
   - Insufficient data for acceleration → velocity = 0.0

3. **Irregular intervals** (e.g., 3 facts in one hour, 0 in next 10 hours):
   - Hourly binning naturally handles this; polynomial fit captures acceleration regardless of pattern

4. **Fact with future timestamp** (>now()):
   - Exclude from query (SQL filter: `created_at <= now()`)

5. **Multiple domain×jurisdiction combos**:
   - Each is scored independently; called once per combo in batch job

6. **hive_scout_sources row doesn't exist for domain×jurisdiction**:
   - Log warning; create alert but skip cadence UPDATE (or create new row with default cadence=168)

7. **Metadata field is null**:
   - Use `COALESCE(metadata, '{}'::jsonb)` in SQL to safely update

---

## Ambiguities Resolved

| Ambiguity | Resolution |
|---|---|
| **Input schema for reg_facts** | Query `public.reg_facts` (domain, jurisdiction, created_at, fact_type, subject, lifecycle_stage, is_current=true) from existing 502_hive_innovation_layer.sql migration |
| **Domain × jurisdiction key** | Compound key: `${domain}::${jurisdiction}` (double-colon separator) used for alert deduping via source_key |
| **Velocity computation algorithm** | Polynomial fit (degree 2) of normalized hourly rates; acceleration mapped to [0,1] via formula velocity = 0.5 + (acceleration/2) |
| **Cadence_hours ceiling** | 24 hours (paired with 6-hour floor) |
| **Client-alert urgency** | severity='warn' for score 0.7–0.85, 'critical' for score ≥ 0.85; uses existing alerts table from 076_alerts.sql |
| **Database write interface** | Supabase INSERT/UPDATE via Nitro API handler; atomic writes, upsert dedup via source_key |
| **Test proof** | Three concrete scenarios: accelerating (alert), constant (no alert), none (no alert) with expected velocity scores and cadence values |
| **Time-series window** | Rolling 24-hour window, hourly granularity (24 buckets), UTC only |
| **Edge case handling** | No facts→0.0 score; irregular intervals handled by hourly binning; timezone=UTC always; null metadata safety via COALESCE |

---

## Completion Checklist

- [ ] Implementation: `server/engines/hive/enforcement-velocity.ts` (pure computeVelocity function)
- [ ] DB wrapper: `server/engines/hive/enforcement-velocity.write.ts` (UPDATE + conditional INSERT)
- [ ] API handler: `server/api/hive/enforcement-velocity.post.ts` (POST endpoint)
- [ ] Zod schema: `shared/schemas/hive.ts` (VelocityInput, VelocityResult validation)
- [ ] Unit tests: 20+ tests covering algorithm, cadence mapping, alert creation, edge cases
- [ ] Integration tests: End-to-end POST /api/hive/enforcement-velocity with sample data
- [ ] All tests passing: `npm test tests/engines/hive/enforcement-velocity.test.ts`
- [ ] TypeScript strict mode: no errors
- [ ] Branch: `agent/hive-enforcement-velocity` ready to merge

---

## Next Steps

1. **Create implementation files** (this session):
   - `server/engines/hive/enforcement-velocity.ts` (algorithm)
   - `server/engines/hive/enforcement-velocity.write.ts` (DB writes)
   - `server/api/hive/enforcement-velocity.post.ts` (API)
   - `shared/schemas/hive.ts` (Zod validation)

2. **Write unit tests** (this session):
   - `tests/engines/hive/enforcement-velocity.test.ts` (20+ test cases)

3. **Verify all tests pass**:
   - `npm test tests/engines/hive/enforcement-velocity.test.ts`

4. **Merge to master**:
   - Create PR from `agent/hive-enforcement-velocity` → `master`
   - Merge once tests pass

---

**Status**: SPECIFICATION COMPLETE & READY FOR IMPLEMENTATION  
**Confidence**: 0.95 (9 ambiguities resolved, schema validated against existing migrations, algorithm fully specified with concrete test cases)
