# Refined Spec: cade-finance-determine-slice-2

## Executive Summary

Write and merge **5 test cases** validating the finance calculation component `cade-finance-determine-slice-2` within Tomorrow's risk advisory system. This component classifies financial instruments into risk-based fee tiers using a **Pareto 80/20 principle**: top 20% of instruments drive 80% of portfolio volatility risk.

**Output:** Test file + handler + passing test suite in isolated worktree, auto-merged to `orchestrator/dev`.

---

## Problem Statement

### Original Ambiguities (Resolved)

| Ambiguity | Resolution |
|-----------|-----------|
| "What specific behavior?" | Tier classification: rank instruments by volatility contribution; bucket A (>20%), B (5–20%), C (<5%); rank risk factors within tiers |
| "'cade-finance-determine-slice-2' meaning?" | Finance instrument classifier applying Pareto 80/20 principle to portfolio risk scoring; determines advisory fee tiers |
| "Implementation slots: 1?" | **5 test cases** (slots 1–5): tier classification, factor ranking, empty portfolio, high-correlation, schema+latency |
| "[patch-template:3cdb50245823]?" | Reference to pareto-2080-07062319 test patterns; cherry-pick fixture constants and Vitest structure, not full copy |
| "MERGED-DIFF truncation?" | Two diffs reference S2S verification; use first (sim 0.515) as primary; second as fallback for schema edge cases |
| "Bottleneck context?" | (1) Isolated component = no simultaneous conflicts. (2) Explicit 5-test scope = bounded definition. (3) 300ms SLA = no orchestration cascade delays |
| "PREFLIGHT DIRECTIVE incomplete?" | PR contains test file, handler, passing suite; commit message cites spec; auto-merge on test pass; no breaking changes |

---

## Refined Specification

### Feature Identity
**cade-finance-determine-slice-2** is a risk-based fee-tier classifier within Tomorrow's PLOEH S2S integration. It applies the **Pareto 80/20 principle** to portfolio instruments:
- Identify top 20% of instruments by volatility contribution
- Classify them as Tier A (high-impact)
- Remaining 80% split into Tier B (medium, 5–20%) and Tier C (low, <5%)
- Rank risk factors within each tier by impact score

**Why:** Tomorrow's advisory fees are risk-tiered; high-impact instruments warrant closer risk management.

---

## Behavior Specification

### Core Logic
```
1. Input: PloehRiskVectorSchema payload (array of instruments with volatility_contribution)
2. Calculate total volatility across portfolio
3. Rank instruments by contribution descending
4. Classify by percentile:
   - Tier A: instruments whose cumulative contribution ≥ 80% (typically top 20%)
   - Tier B: instruments with 5–20% contribution individually
   - Tier C: instruments with < 5% contribution
5. Within each tier, rank risk_factors by impact_score descending
6. Return Zod-validated tier assignment array
```

### Test Cases (5 Slots)

| Slot | Test | Behavior | Assertion |
|------|------|----------|-----------|
| 1 | Tier classification | 10-instrument portfolio: classify by volatility contribution | Tier A has ~20% of instruments; B and C split remainder; cumsum A ≥ 80% |
| 2 | Factor ranking | 3 tiers populated with 2–4 factors each | Each tier's factors ordered by impact_score DESC |
| 3 | Empty portfolio | 0 instruments | Returns empty array (no throw) |
| 4 | High correlation | 5 instruments, 90% pairwise correlation | Classification converges; tier assignments are sensible (no NaN, all in A\|B\|C) |
| 5 | Schema + latency | Valid PloehRiskVectorSchema input; bench with 1000 calls | (a) Schema parse succeeds, (b) median latency ≤300ms, (c) p95 latency ≤500ms |

---

## Acceptance Criteria

### ✅ Definition of Done
- [ ] 5 test cases written and passing
- [ ] Handler function (60–100 lines) implemented and invocable
- [ ] 100% code coverage of handler logic
- [ ] Latency bench: ≤300ms median per request
- [ ] Zero Zod schema violations
- [ ] PR merged to `orchestrator/dev`
- [ ] Worktree cleaned up
- [ ] Commit authored as `kalepasch1 <kalepasch@gmail.com>`

### Test Requirements
- **Framework:** Vitest
- **File:** `tests/server/api/apparently/ploeh/finance-determine-slice-2.spec.ts`
- **Count:** 5 test cases
- **Coverage:** 100% of handler logic

### Code Requirements
- **Handler:** `server/api/apparently/ploeh/finance-classify.ts`
- **Nitro route:** GET `/api/apparently/ploeh/finance-classify`
- **Input:** JSON body with PloehRiskVectorSchema
- **Output:** `[{instrument_id, tier: 'A'|'B'|'C', risk_factors_ranked: [{factor, impact_score}]}]`
- **Error handling:** Fail-soft; return empty array or default-C on parse error; log, never throw

### Performance
- **SLA:** ≤300ms per classify request (matches S2S HMAC window constraint)
- **Bench:** Vitest bench with 100–1000 sample portfolios; report median + p95

### Schema
- **Validation:** All tier assignments must satisfy PloehRiskVectorSchema or new TierAssignmentSchema
- **Tests:** Include schema violation check—`expect(() => parse(malformed)).toThrow()`

### Git
- **Branch:** `agent/finance-determine-slice-2`
- **Worktree:** `claude-orchestrator-wt/finance-determine-slice-2` (isolated, auto-cleanup)
- **Author:** `kalepasch1 <kalepasch@gmail.com>`
- **Message:** `feat(ploeh): add finance tier classifier with Pareto 80/20 volatility ranking`

### PR
- **Target:** `orchestrator/dev`
- **Auto-merge:** Yes (after tests pass)
- **Manual gates:** Legal review if S2S auth logic changes; otherwise auto-pass

---

## File Manifest

### New Files
| Path | Purpose | Lines | Dependencies |
|------|---------|-------|--------------|
| `tests/server/api/apparently/ploeh/finance-determine-slice-2.spec.ts` | 5 Vitest test cases | ~200 | Vitest, PloehRiskVectorSchema, finance-classify |
| `server/api/apparently/ploeh/finance-classify.ts` | Nitro route handler | ~80 | PloehRiskVectorSchema, Zod, s2sBridge (optional) |

### Modified Files (Optional)
| Path | Reason | Delta |
|------|--------|-------|
| `server/api/apparently/ploeh/index.ts` | Barrel export (if needed) | +1 line |

### Untouched
- `server/utils/otc/ploeh/schema.ts` — Reuse existing PloehRiskVectorSchema
- `server/api/risk/enrich.ts` — Tested separately; handler-only scope

---

## Context & Rationale

### Project Domain
**Tomorrow** is a financial advisory platform. The **PLOEH S2S bridge** (Apparently → Tomorrow) ingests risk vectors. The **finance-classify handler** applies Pareto 80/20 to advisory fee tiers.

### Pareto 80/20 Application
In risk scoring: top 20% of instruments (by volatility contribution) drive 80% of portfolio risk. Classify into 3 tiers (A/B/C) to segment advisory fees and risk controls by impact.

### Integration Point
Handler responds to PLOEH trigger-spec requests → returns tier assignments → feeds downstream risk narrative enrichment (`server/api/risk/enrich.ts`).

### Mechanical Task Scope
**Test-first:** Write 5 narrowly-scoped test cases that prove tier classification logic, then implement minimal handler to pass tests. No refactor, no feature flag, no broader remediation—just the 5 tests + handler.

### Bottleneck Mitigation
1. **Simultaneous remediation:** Isolated component; no cross-conflicts.
2. **Scope definition:** 5 test slots explicitly bound scope.
3. **Orchestration latency:** 300ms SLA prevents cascade delays.

---

## Testing Strategy

### Framework
**Vitest** (already in project)

### Structure
```
describe('finance-classify', () => {
  it('classifies instruments by Pareto 80/20 contribution', () => { ... })
  it('ranks factors within tiers by impact_score', () => { ... })
  it('handles empty portfolio (no throw)', () => { ... })
  it('converges with high-correlation instruments', () => { ... })
  it('validates schema and latency ≤300ms', () => { ... })
})
```

### Fixtures
- `MOCK_PORTFOLIO_A` — 10 instruments, diverse volatility
- `MOCK_PORTFOLIO_B` — 5 instruments, medium variance
- `MOCK_EDGE_EMPTY` — Empty array
- `MOCK_EDGE_SINGLE` — 1 instrument
- `MOCK_EDGE_CORRELATED` — 5 instruments, 90% correlation

### Assertions
- Tier classification: `tier in ['A', 'B', 'C']`
- Factor order: `factors[i].impact_score ≥ factors[i+1].impact_score`
- Edge cases: No throw, valid output
- Schema: `parse(result) succeeds`
- Latency: `performance.now() - start < 300`

---

## Rollback & Safety

### Rollback Plan
If tests fail post-merge:
```bash
git revert <commit>
git push origin orchestrator/dev
# Auto-deploy via batch train
```
No data loss or runtime impact (handler is new, not replacing existing routes).

### Pre-Merge Validation
- [ ] All 5 tests pass locally and in CI
- [ ] Manual QA: invoke handler with PLOEH test payload
- [ ] Verify tier assignments are sensible

### Secret Safety
No secrets in tests or handler. S2S keys (if used) are env vars, not hardcoded.

### Breaking Changes
**None.** New handler only; existing PLOEH routes untouched.

---

## Confidence Assessment

**Confidence: 0.85**

### Why High
1. Ambiguities resolved concretely—feature identity grounded in Pareto principle, 5 test slots explicit, file paths derived from Tomorrow structure.
2. Acceptance criteria are testable and measurable (5 tests, <300ms, Zod validation).
3. Context from PLOEH S2S bridge and project conventions applied consistently.
4. Mechanical task scope is narrow and well-bounded.

### Caveats (0.15 discount)
- No direct code inspection of `s2sBridge.ts` and `schema.ts` to confirm exact import paths and error patterns.
- `PloehRiskVectorSchema` structure inferred from context docs; may need schema review before implementation.
- File paths inferred from project structure; may differ if directories reorganized.

---

## Next Steps

1. **Verify file paths** — Confirm `s2sBridge.ts`, `schema.ts`, and `server/api/apparently/ploeh/` exist.
2. **Review schema** — Inspect `PloehRiskVectorSchema` shape; ensure mock fixtures align.
3. **Implement test file** — Write 5 test cases per spec.
4. **Implement handler** — Tier classification logic, ~80 lines.
5. **Run coverage** — `vitest run --coverage`; confirm 100%.
6. **Push & merge** — Branch `agent/finance-determine-slice-2` → auto-merge on tests pass.
7. **Verify merge** — Check `orchestrator/dev` log; cleanup worktree.

---

## Appendix: Pareto 80/20 Pseudocode

```python
def classify_instruments(instruments: List[Instrument]) -> List[TierAssignment]:
    if not instruments:
        return []
    
    # Sort by volatility contribution descending
    sorted_instruments = sorted(instruments, key=lambda x: x.volatility_contribution, reverse=True)
    total_volatility = sum(x.volatility_contribution for x in instruments)
    
    cumulative = 0.0
    tier_a = []
    tier_b = []
    tier_c = []
    
    for inst in sorted_instruments:
        contribution_pct = inst.volatility_contribution / total_volatility * 100
        cumulative += contribution_pct
        
        if cumulative <= 80:  # Top 20% threshold
            tier_a.append(inst)
        elif contribution_pct >= 5:
            tier_b.append(inst)
        else:
            tier_c.append(inst)
    
    # Rank factors within each tier
    result = []
    for tier_name, tier_instruments in [('A', tier_a), ('B', tier_b), ('C', tier_c)]:
        for inst in tier_instruments:
            ranked_factors = sorted(inst.risk_factors, key=lambda f: f.impact_score, reverse=True)
            result.append({
                'instrument_id': inst.id,
                'tier': tier_name,
                'risk_factors_ranked': ranked_factors
            })
    
    return result
```

---

**Spec Version:** 1.0  
**Generated:** 2026-07-30  
**Task ID:** `cade-finance-determine-slice-2-refined`  
**Model:** Claude Haiku 4.5
