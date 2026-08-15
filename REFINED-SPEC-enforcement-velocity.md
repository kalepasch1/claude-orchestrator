# Refined Task Spec: Enforcement Velocity Enforcement

## 1. Objective
Build `server/engines/hive/enforcement-velocity.ts`: a pure function that computes regulatory enforcement acceleration from `RegFact` arrival timestamps, then writes optimized refresh cadences to `HiveScoutSource` rows to reallocate Hive monitoring effort toward spiking regulatory activity.

## 2. Data Schemas (Existing)

### Input: RegFact Arrivals
**Source table:** `reg_facts` (defined in `shared/types/hive.ts`)
```typescript
// Relevant fields:
- id: string
- domain: HiveDomain
- jurisdiction: string
- fact_type: RegFactType
- created_at: string (ISO 8601 UTC timestamp)
- enforcement_observed: boolean
- lifecycle_stage: RegFactLifecycleStage
```

**Grouping key:** `(domain, jurisdiction)` tuple  
**Filter:** Only consider facts with `enforcement_observed = true` OR `lifecycle_stage = 'enforced'`  
**Input to computeVelocity:** Array of `created_at` timestamps (ISO strings) for facts in a domain-jurisdiction pair

### Output: Updated HiveScoutSource Rows
**Target table:** `hive_scout_sources` (defined in `shared/types/hive.ts`)
```typescript
// Fields to update:
- id: string (primary key, no change)
- cadence_hours: number (lowered if acceleration detected)
- metadata.regulatory_temperature?: number (optional: velocity score for audit)
- metadata.last_velocity_computation_at?: string (optional: timestamp)
```

**Update semantics:** Upsert existing rows only (never insert new HiveScoutSource rows). Update is keyed on `(domain, jurisdiction)`.

## 3. Velocity & Acceleration Computation

### Time Windows
- **Observation window:** Last 30 days (T-30d to T-now)
- **Current window:** Last 7 days (T-7d to T-now)
- **Previous window:** 7 days prior (T-14d to T-7d)

### Algorithm: `computeVelocity(arrivals: string[]): VelocityResult`

**Input:** Array of `RegFact.created_at` timestamps for a single (domain, jurisdiction) pair

**Output:**
```typescript
export interface VelocityResult {
  velocity_score: number          // Facts per day in 30-day window
  acceleration_ratio: number      // (current_7d - previous_7d) / max(1, previous_7d)
  is_accelerating: boolean        // acceleration_ratio > 0.1 (>10% growth)
  current_7d_count: number        // Fact count in last 7 days
  previous_7d_count: number       // Fact count in 7-14 days ago
  velocity_30d_count: number      // Total facts in last 30 days
}
```

**Calculation:**
1. Filter arrivals to those within last 30 days (now - 30d ≤ timestamp ≤ now)
2. Count facts in current 7-day window: `current_7d_count = count(T-7d to T-now)`
3. Count facts in previous 7-day window: `previous_7d_count = count(T-14d to T-7d)`
4. Calculate acceleration: `acceleration_ratio = (current_7d_count - previous_7d_count) / max(1, previous_7d_count)`
5. Calculate velocity: `velocity_score = velocity_30d_count / 30`
6. Set `is_accelerating = (acceleration_ratio > 0.1)`  ← Threshold: 10% velocity growth signals escalation

### Edge Cases
- **No arrivals in period:** `velocity_score = 0`, `acceleration_ratio = 0`, `is_accelerating = false`
- **Previous window has 0 facts but current has arrivals:** `acceleration_ratio = ∞` (capped to `1.0`), treat as `is_accelerating = true`
- **Future timestamps:** Ignore (filter out)

## 4. Cadence Reduction Logic

### Formula: `newCadenceHours = clamp(baseCadenceHours - reductionHours, 1, 24)`

where:
- `baseCadenceHours` = current `hive_scout_sources.cadence_hours` value
- `reductionHours = acceleration_ratio * 12` (maps 10% acceleration → 1.2h reduction, 100% acceleration → 12h reduction)
- `clamp(value, min, max)` = `max(min, min(max, value))`
- **Floor:** 1 hour (minimum check frequency when accelerating)
- **Ceiling:** 24 hours (no row gets raised to >24h; no reduction if already at 24h)

### Conditional Update
Update `hive_scout_sources.cadence_hours` **only if:**
1. `is_accelerating = true` AND
2. `newCadenceHours < baseCadenceHours` AND
3. `newCadenceHours ≥ 1`

If conditions are not met, do NOT update the row (preserve existing cadence).

**Optional metadata write:**
```typescript
metadata.regulatory_temperature = velocity_score
metadata.last_velocity_computation_at = new Date().toISOString()
```

## 5. Function Signatures & Exports

### Pure Domain Logic
```typescript
// server/engines/hive/enforcement-velocity.ts

export interface VelocityResult {
  velocity_score: number
  acceleration_ratio: number
  is_accelerating: boolean
  current_7d_count: number
  previous_7d_count: number
  velocity_30d_count: number
}

/**
 * Pure: compute velocity and acceleration from arrival timestamps.
 * No side effects; no DB access.
 */
export function computeVelocity(arrivals: string[], nowUtc: Date = new Date()): VelocityResult {
  // ... implementation ...
}

/**
 * Apply velocity computation to a single (domain, jurisdiction) pair
 * and return the recommended new cadence_hours (or null if no update needed).
 */
export function computeCadenceReduction(
  result: VelocityResult,
  baseCadenceHours: number
): number | null {
  // ... implementation ...
  // Returns new cadence_hours if should update, null otherwise
}
```

### Thin DB Write Wrapper
```typescript
/**
 * Transaction: fetch all (domain, jurisdiction) pairs from reg_facts,
 * compute velocity for each, update hive_scout_sources cadence where accelerating.
 * 
 * Called by:
 *   - Scheduled job (e.g., cron hourly)
 *   - Manual API endpoint: POST /api/hive/enforcement-velocity/compute
 * 
 * Returns: {updated_count: number, skipped_count: number}
 */
export async function updateSourceCadencesFromEnforcementVelocity(
  db: SupabaseClient
): Promise<{ updated_count: number; skipped_count: number }> {
  // ... implementation ...
}
```

## 6. Test File & Acceptance Criteria

**Test file:** `tests/engines/hive/enforcement-velocity.test.ts`

### Test Case 1: Basic Acceleration Detection (Domain × Jurisdiction)
**Setup:**
- Domain: `gaming`, Jurisdiction: `NV` (Nevada)
- Create 10 `RegFact` records with `enforcement_observed=true`:
  - 2 facts created 25 days ago
  - 3 facts created 10 days ago (previous 7d window)
  - 5 facts created 2 days ago (current 7d window)

**Execution:**
```
arrivals = [<25d ago>, <25d ago>, <10d ago>, <10d ago>, <10d ago>, <2d ago>, ...]
result = computeVelocity(arrivals)
```

**Expected Output:**
```
{
  velocity_score: 10 / 30 ≈ 0.33,
  acceleration_ratio: (5 - 3) / max(1, 3) ≈ 0.67,
  is_accelerating: true,          // 67% > 10% threshold
  current_7d_count: 5,
  previous_7d_count: 3,
  velocity_30d_count: 10
}
```

**Cadence Reduction (given base 8h):**
```
reductionHours = 0.67 * 12 ≈ 8h
newCadence = clamp(8 - 8, 1, 24) = 1h
→ Update hive_scout_sources row (gaming, NV) cadence_hours to 1
```

### Test Case 2: No Acceleration (Plateau)
**Setup:**
- Same domain-jurisdiction
- 3 facts 10-14 days ago, 3 facts 2-7 days ago (no change)

**Expected:** `acceleration_ratio ≈ 0`, `is_accelerating = false`, no update

### Test Case 3: Zero Arrivals
**Setup:**
- Domain-jurisdiction pair with no `RegFact` entries

**Expected:** `velocity_score = 0`, `is_accelerating = false`, no update

### Test Case 4: Floor Respect (Never Below 1h)
**Setup:**
- Base cadence: 2h
- Acceleration ratio: 2.0 (doubling)
- Reduction: 2.0 * 12 = 24h

**Expected:** `clamp(2 - 24, 1, 24) = 1h` (floor applied)

### Test Case 5: Ceiling Respect (Never Above 24h)
**Setup:**
- Base cadence: 24h
- Any acceleration

**Expected:** No update (already at ceiling)

### Test Case 6: Async DB Upsert
**Setup:**
- Multiple (domain, jurisdiction) pairs with varying acceleration
- Mock Supabase: insert base `HiveScoutSource` rows, then call `updateSourceCadencesFromEnforcementVelocity()`

**Expected:**
- Rows with acceleration: cadence lowered
- Rows without acceleration: cadence unchanged
- Return object: `{updated_count: 2, skipped_count: 3}`

## 7. Acceptance Criteria

✅ **Code Quality**
- [ ] Pure function `computeVelocity()` has no database access, no side effects
- [ ] DB wrapper function is thin (fetches facts → loops → updates in transaction)
- [ ] All parameters are explicit (no magic numbers outside constants)
- [ ] TypeScript strict mode; all types inferred or explicit

✅ **Correctness**
- [ ] Acceleration ratio correctly compares 7-day rolling windows
- [ ] Velocity score is facts/day over 30 days
- [ ] Cadence reduction formula respects floor (1h) and ceiling (24h)
- [ ] Edge cases: zero arrivals, future timestamps, previous window empty

✅ **Testing**
- [ ] All 6 test cases pass: `npx vitest run tests/engines/hive/enforcement-velocity.test.ts`
- [ ] >90% code coverage (computeVelocity + computeCadenceReduction)
- [ ] Mock Supabase client in DB wrapper test

✅ **Database Semantics**
- [ ] Only UPDATE existing `hive_scout_sources` rows; never INSERT
- [ ] Transaction atomicity: all-or-nothing per (domain, jurisdiction) pair
- [ ] Optional metadata fields do not block update if `regulatory_temperature` is missing

✅ **Integration**
- [ ] Exported types match `shared/types/hive.ts` (RegFact, HiveScoutSource)
- [ ] Function can be imported and called from scheduled job handler or API endpoint
- [ ] No hardcoded Supabase keys or secrets

## 8. File Paths

| File | Purpose |
|------|---------|
| `server/engines/hive/enforcement-velocity.ts` | Core logic: `computeVelocity`, `computeCadenceReduction`, `updateSourceCadencesFromEnforcementVelocity` |
| `tests/engines/hive/enforcement-velocity.test.ts` | 6 test cases covering pure function + DB wrapper |
| `shared/types/hive.ts` | *Already exists*; import `RegFact`, `HiveScoutSource` |

## 9. Definition of "Regulatory Temperature Spiking"

**"Regulatory temperature is spiking"** ≡ `is_accelerating = true` (10%+ velocity growth in current 7d vs. previous 7d)

When this condition is met, the Hive proactively reduces `cadence_hours` to increase monitoring frequency, signaling the coordination layer (e.g., `hivemind-council.ts`) to reallocate attention.
