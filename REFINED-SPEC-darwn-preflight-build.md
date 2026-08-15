# Refined Task Spec: DARWN Preflight Gate Build

## Task Identification

**Task Slug**: `darwn-preflight-build`  
**Source Route**: `native-claim` (improvement on original `preflight-gate`)  
**Project**: DARWN (healthcare worker trading platform)  
**Task Class**: `build` (implementation) — *Note: Original pipeline spec says `plan`; improvement request specifies `build`. **Assumption**: This is a **build task** that may generate a plan artifact.*  
**Complexity Estimate**: `need 6` (revised down from `need 8` in pipeline spec)  
**Risk Level**: `standard`  
**Date Refined**: 2026-08-01  
**Status**: PENDING CLARIFICATION

---

## Task Definition

### Objective
Build a **preflight validation gate** for DARWN claims processing that:
1. **Validates claim/ownership data** before downstream processing (matches healthcare worker trading rules)
2. **Generates execution plan** for remediation if validation fails
3. **Routes to appropriate QA/review** based on claim type and risk profile
4. **Integrates with existing owner module** (locate before adding new files)

### Context
DARWN allows users to own shares in healthcare workers; claims processing must validate ownership stakes, worker identities, and fair-market-value (FMV) calculations. Prior work exists in `pareto-2080/rework-buildfail-qafix` (see **Adaptation** section below).

---

## Scope & Deliverables

### What This Task Builds

**Primary Artifact**: `server/preflight/claims-gate.ts`  
**Type**: TypeScript utility module (fits DARWN's Nuxt 3 + TypeScript stack)

**Core Function Signature**:
```typescript
export interface PreflightGateInput {
  claimId: string
  workerId: string
  ownershipStakePercent: number
  bidType: 'buy' | 'sell'
  claimAmount: number
  workerSalaryBasis: number  // base salary for FMV calc
}

export interface PreflightGateResult {
  isValid: boolean
  validationErrors: ValidationError[]
  suggestedRemediations?: RemediationStep[]
  riskProfile: 'low' | 'medium' | 'high'
  requiresLegalGate: boolean  // legal gate trigger per CLAUDE.md
}

export interface ValidationError {
  field: string
  rule: string
  message: string
  severity: 'warn' | 'error'
}

export interface RemediationStep {
  action: string
  priority: number
  estimatedResolutionTime: string
}

export function validateClaim(input: PreflightGateInput): PreflightGateResult
```

### Secondary Artifacts (if applicable)

- **Test Suite**: `server/tests/test-claims-gate.spec.ts` (mocha/jest, ≥15 test cases)
- **Edge Cases Coverage**: 
  - Fractional ownership splits
  - FMV mismatch scenarios
  - Worker identity conflicts
  - Concurrent bid collisions
- **Integration Points**:
  - Queries existing `Ownership` model (Prisma/PostgreSQL)
  - Calls `fmv.ts` utility for valuation checks
  - Logs to `audit_trail` table (compliance)

---

## Validation Rules (Algorithm)

### Rule Set: `validateClaim()`

1. **Worker Identity Exists**
   - Query `MedicalStaff` table by `workerId`
   - Fail if not found; error: "Worker does not exist"

2. **Ownership Stake Range**
   - Check: `0 < ownershipStakePercent ≤ 100`
   - Fail if outside range; error: "Ownership stake must be between 0% and 100%"

3. **FMV Reasonableness**
   - Compute expected FMV: `expectedFMV = workerSalaryBasis * fmvMultiplier` (multiplier from `fmv.ts`)
   - Allow ±15% variance: `expectedFMV * 0.85 ≤ claimAmount ≤ expectedFMV * 1.15`
   - Warn (not fail) if outside; error: "Claim amount deviates >15% from FMV estimate"

4. **Bid Type Constraints**
   - **BUY**: Claimant must have sufficient liquidity (check `User.balance ≥ claimAmount`)
   - **SELL**: Must own stake (check `Ownership` table: `ownershipStakePercent > 0` for this user+worker)
   - Fail if constraints violated

5. **Concurrent Bid Conflict**
   - Query `Bids` table for same worker, same timeframe (last 5 minutes)
   - Warn if >2 concurrent bids on same worker (high contention signal)

6. **Legal Gate Trigger** ✓ (from CLAUDE.md)
   - Set `requiresLegalGate = true` if:
     - Claim would trigger licensing/registration implications (ask user context)
     - **OR** Claim involves custody/transmission (e.g., post-termination stake buyback)
     - **OR** Claim involves advice/opinion (platform should never give)

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| Worker salary basis = 0 | FMV calc undefined; error "Cannot validate FMV for worker with unknown salary" |
| Stake = 0% | Valid (allows user to clear position), but warn "Selling 0% stake has no effect" |
| Claim amount = 0 | Fail if BUY (no purchase); allow if SELL (clearing position) |
| Duplicate claim (same worker, same user, <5 min apart) | Warn "Duplicate claim attempt; prior bid at HH:MM:SS" |
| Fractional stakes (e.g., 33.333%) | Valid; no rounding, store as-is in decimal precision |

### Output: Risk Profile Assignment

```typescript
function computeRiskProfile(errors: ValidationError[]): 'low' | 'medium' | 'high' {
  const errorCount = errors.filter(e => e.severity === 'error').length
  const warnCount = errors.filter(e => e.severity === 'warn').length
  
  if (errorCount > 0) return 'high'
  if (warnCount >= 3) return 'high'
  if (warnCount > 0) return 'medium'
  return 'low'
}
```

---

## File Paths (Exact)

| Component | Path |
|-----------|------|
| **Implementation** | `/Users/kpasch/Documents/apparently/server/preflight/claims-gate.ts` |
| **Tests** | `/Users/kpasch/Documents/apparently/server/tests/test-claims-gate.spec.ts` |
| **Existing Owner Module** | `/Users/kpasch/Documents/apparently/server/models/Ownership.ts` (inspect before adding new files) |
| **FMV Utility** | `/Users/kpasch/Documents/apparently/utils/fmv.ts` (dependency, read-only) |
| **Branch** | `agent/darwn-preflight-build` (based on `master`) |
| **Deployment Target** | Vercel; merge to `orchestrator/dev` after tests pass, then batch release train to `master` (see CLAUDE.md deploy rules) |

---

## Acceptance Criteria (EXPLICIT)

### Code Correctness (REQUIRED)
- [ ] **All tests pass**: `npm run test server/tests/test-claims-gate.spec.ts` (≥15 cases, all green)
- [ ] **No TypeScript errors**: `npm run build` completes without type errors
- [ ] **No import errors**: All dependencies (Prisma, fmv.ts, Ownership model) resolve correctly
- [ ] **Function signature matches spec** above exactly

### Existing Behavior Preserved
- [ ] **Ownership model unchanged**: No modifications to `/server/models/Ownership.ts` (read-only reference)
- [ ] **FMV calculation untouched**: `/utils/fmv.ts` remains unchanged
- [ ] **Audit trail logging**: Claims passing validation are logged to `audit_trail` table with timestamp, claimId, userId, action='claim_validated'
- [ ] **No auto-execution**: Preflight gate **returns a plan**; it does NOT auto-merge/auto-execute claims (manual review required for high-risk)

### Test Quality
- [ ] **Edge cases covered**:
  - ✓ Worker not found
  - ✓ Ownership stake out of range (0%, >100%)
  - ✓ FMV mismatch (±>15% deviation)
  - ✓ BUY without sufficient balance
  - ✓ SELL without owning stake
  - ✓ Duplicate claims (race condition)
  - ✓ Fractional stakes (precision)
  - ✓ Concurrent bid contention (>2 bids in 5 min)
  - ✓ Worker with null salary basis
  - ✓ Zero claim amounts (BUY vs SELL differ)

- [ ] **No tautological assertions** (e.g., `true === true`)
- [ ] **Mocks use correct patterns**: `jest.mock()` at module scope, patches target Prisma/DB calls
- [ ] **Test isolation**: No shared state between tests; use `beforeEach()` to reset mocks

### Integration
- [ ] **Prisma integration**: Correctly queries `MedicalStaff`, `Ownership`, `Bids`, `User`, `audit_trail` tables
- [ ] **FMV dependency**: Calls `fmv.ts:getFmvMultiplier()` and uses result in calculation
- [ ] **Audit trail logging**: Inserts into `audit_trail` table for compliance
- [ ] **Legal gate decision**: `requiresLegalGate` flag correctly set per CLAUDE.md legal gate rules

### Deployment Readiness
- [ ] **No hardcoded secrets**: No API keys, database URLs, or credentials in code
- [ ] **No production deployments**: Commit does not run `vercel --prod` or `vercel deploy --prod` (see CLAUDE.md deploy rules)
- [ ] **Branch-only push**: Work pushed to `agent/darwn-preflight-build` branch; manual merge via batch release train after verification
- [ ] **Tests integrated into CI**: Jest tests run on GitHub Actions (existing setup in repo)

---

## Ambiguities in Original Spec (RESOLVED)

| Ambiguity | Original | Resolution | Confidence |
|-----------|----------|-----------|------------|
| **"need 8" vs "need 6"** | Pipeline spec `need 8`, improvement `need 6` | **Assumption**: "need 6" = task complexity points / estimated effort allocation. Treat as updated estimate. | MEDIUM |
| **"qpd leader q=6.2/6.6/7.7"** | Vague routing metrics, units unclear | **Assumption**: "qpd leader" = model selection gate; q-values = quality/confidence scores (0–10 scale). Not needed for task execution; routing metadata only. | LOW |
| **Task class "plan" vs "build"** | Pipeline says "plan", improvement says "build" | **Resolved to**: `build` (implementation task). "Plan" may refer to plan artifact output (RemediationStep[]), not task type. | MEDIUM |
| **"slice-3"** | Vague reference, no context | **Assumption**: Multi-slice task breakdown (slice-1, slice-2, slice-3). This is slice-3; prior slices in `pareto-2080` repo. Not core to this task. | LOW |
| **"PATCH TEMPLATE ce2e8dcd7954"** | Git commit hash, no explanation | **Resolved to**: Reference to prior work in `pareto-2080/rework-buildfail-qafix`. See **Adaptation** below. | LOW |
| **"pareto-2080/rework-buildfail-qafix"** | Should task adapt this patch or build independently? | **Resolved to**: **Inspect prior work, adapt patterns if applicable, but build independently.** Similarity=0.223 suggests code is mostly different; don't copy blindly. | MEDIUM |
| **"local:llama3.2:" incomplete** | QA panel entry cuts off mid-spec | **Resolved to**: Typo/truncation. Ignore; use standard Vercel CI/Jest for testing. | HIGH |
| **"preserve existing beh" incomplete** | Stub acceptance criterion | **Expanded**: See **Acceptance Criteria** section above (7 behavioral guarantees listed). | HIGH |
| **"Intent line metadata"** | Encoded hashes/timestamps/flags unclear | **Resolved to**: Auto-generated orchestrator routing metadata. Ignore; not actionable for task execution. | HIGH |

---

## Integration with Prior Work

### Source Reference: `pareto-2080/rework-buildfail-qafix`
**Similarity Score**: 0.223 (suggests ~22% code overlap)  
**Recommendation**:
1. Read `/Users/kpasch/Documents/pareto-2080/rework-buildfail-qafix/server/preflight/` (if exists)
2. If patterns exist (validation rule structure, test framework), adapt them
3. **Do NOT copy-paste wholesale**; similarity=0.223 means most logic is context-specific
4. Reuse only:
   - Test patterns (mocha setup, mock patterns)
   - Validation rule structure (field→rule→message)
   - Risk profile thresholds
5. Implement claim-specific logic independently (workers ≠ prior domain)

### Adaptation Checklist
- [ ] Inspect `pareto-2080/rework-buildfail-qafix` for prior patterns
- [ ] Extract reusable validation framework (if exists)
- [ ] Document what was adapted vs. built fresh in commit message
- [ ] Link to prior work in PR description for reviewability

---

## Orchestrator Routing & Deployment

### Model Routing (from original pipeline spec — kept for reference)
```
Preflight Triage:    google:gemini-2.5-flash (confidence q=6.2)
Strategy Planner:    google:gemini-2.5-flash (confidence q=6.6)
Agentic Coder:       claude-haiku-4-5-20251001 (author model)
QA Route:            local:llama3.1 (confidence q=7.7)
```
**Note**: These are routing hints for the orchestrator. Focus on **implementation**, not model selection.

### Merge & Release Rules (from CLAUDE.md)
1. **Development**: Auto-merge to `orchestrator/dev` after tests pass and code review approved
2. **Production**: Never push `master`/`main` directly. Use batch release train:
   - Push to feature branch `agent/darwn-preflight-build`
   - Open PR against `master`
   - Await batch release train automation (no manual `vercel --prod`)
3. **Coordination**: 
   - Reconcile with active loop-generated work (check git status before pushing)
   - Reuse prior solutions first (see pareto-2080 section above)
   - Do not delete/overwrite unrelated queued improvements
   - Leave recovered work in queue until shipped

### Legal Gate Trigger
**Condition**: Set `requiresLegalGate = true` if claim would:
- Force regulatory licensing/registration
- Involve custody/transmission of stakes (e.g., post-termination buyback)
- Constitute financial advice or medical opinion
**Owner-Only Review**: Only repo owner (kalepasch1) can approve such changes (see CLAUDE.md).

---

## Next Steps for Task Execution

### Phase 1: Investigation (Before Implementation)
1. [ ] Locate existing owner module (`/server/models/Ownership.ts`)
2. [ ] Read `utils/fmv.ts` to understand FMV calculation API
3. [ ] Inspect `pareto-2080/rework-buildfail-qafix` for reusable patterns
4. [ ] Verify Prisma schema includes `MedicalStaff`, `Ownership`, `Bids`, `User`, `audit_trail` tables
5. [ ] Clarify with user: What triggers legal gate? (licensing, custody, advice examples in your domain?)

### Phase 2: Implementation
1. Create branch: `git checkout -b agent/darwn-preflight-build master`
2. Write `server/preflight/claims-gate.ts` (function + types)
3. Write comprehensive test suite (`≥15 cases`)
4. Run tests: `npm run test`
5. Type-check: `npm run build`

### Phase 3: Review & Merge
1. Document what was adapted from `pareto-2080` vs. built fresh
2. Push to branch: `git push -u origin agent/darwn-preflight-build`
3. Open PR against `master`; request code review
4. Await batch release train approval (do NOT push master directly)

### Open Questions for User
- [ ] **Legal gate specifics**: What claim scenarios require owner-only review in your healthcare context?
- [ ] **FMV multiplier**: Does `fmv.ts` export `getFmvMultiplier()`, or different API?
- [ ] **Audit trail schema**: What fields does `audit_trail` table expect?
- [ ] **Concurrent bid window**: Is 5 minutes the right contention detection window, or different?
- [ ] **Prior work reusability**: Any specific files in `pareto-2080` branch to inspect first?

---

## Summary

This spec makes the task **executable and verifiable**. Key decisions:
1. **Task class**: `build` (implementation, not planning)
2. **Complexity**: `need 6` (revised estimate)
3. **Scope**: Preflight validation gate + remediation plan generation
4. **Acceptance**: 10+ explicit checkboxes covering correctness, behavior, testing, deployment
5. **Prior work**: Inspect `pareto-2080`, adapt patterns, build independently where different
6. **Routing**: Ignore orchestrator metadata (qpd_leader, q-values) — focus on implementation

**Status**: READY FOR IMPLEMENTATION pending clarifications above.
