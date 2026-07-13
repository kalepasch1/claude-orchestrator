# Composite Payoff Compiler Test Coverage

## Overview
The `compositePayoffCompiler.test.ts` provides comprehensive test coverage for the OTC composite payoff compilation system. This document outlines the test categories and their coverage areas.

**Test Count: 74 tests**
**Status: All passing**

## Test Categories

### 1. Basic Compilation (9 tests)
- Valid risk spec compilation with different instrument types (call, put, collar, ramp, reinstatement)
- Instrument type parsing from natural language descriptions
- Default to spread for ambiguous descriptions
- Deterministic ID generation (same input → same ID)
- Different IDs for different underlying assets
- Strike inclusion in payoff

### 2. Horizon Selection: Perpetual vs Discrete (5 tests)
- Discrete selection when one-off cost is lower than funding cost
- Perpetual selection when funding cost is lower than one-off cost
- Carry consideration in horizon selection
- Perpetual default when carry data unavailable
- Perpetual handling with no one-off cost

### 3. Cost Delta and Rationale (4 tests)
- Cost delta calculation for discrete instruments
- Rationale messaging for discrete instruments
- Rationale messaging for perpetual instruments
- Cost comparison explanation in narrative

### 4. Structural Backtest Validation (7 tests)
- Required backtest result fields present
- Scenario count >= MIN_SCENARIO_COUNT (100)
- Passed + failed = scenarioCount invariant
- Confidence = passed / scenarioCount calculation
- Confidence >= MIN_CONFIDENCE_THRESHOLD (0.85)
- Realistic PnL bounds (maxLoss < 0 < maxGain)
- Deterministic results for same underlying+type

### 5. Backtest Inclusion in Compilation (2 tests)
- Backtest results included in compiled instrument
- Invalid compilation if backtest confidence too low

### 6. Allowlist Validation (3 tests)
- Instruments marked as allowlisted for valid types
- All instrument types (call, put, spread, collar, ramp, reinstatement) in allowlist
- Error generation for non-allowlisted types

### 7. Fail-Closed Validation via assertComposable (5 tests)
- Throws if instrument not allowlisted
- Throws if backtest confidence below threshold
- Throws if backtest results missing
- Throws if backtest scenario count below minimum
- No throw for valid instrument (all criteria met)

### 8. Error Handling (3 tests)
- Error returned for risk spec with no vectors
- Multi-vector risk spec handling
- Risk specs without strike prices

### 9. Discrete Selection with Cost Delta (3 tests)
- Discrete selection with cost savings display
- Cost delta inclusion in rationale
- Rejection if backtest fails for discrete selection

### 10. Rationale Generation Direct Tests (4 tests)
- Discrete horizon rationale with cost delta
- Perpetual horizon rationale with carry
- Cost values formatted as basis points
- Undefined cost delta handling

### 11. Cost Delta Edge Cases (5 tests)
- Cost delta as difference when both costs exist
- OneOffCost as costDelta when fundingCost undefined
- CostDelta undefined when oneOffCost undefined
- Zero cost value handling
- Negative cost delta (perpetual more expensive)

### 12. Risk Vector Type Handling (2 tests)
- Rate risk vectors (e.g., SONIA)
- Volatility risk vectors (e.g., VIX)

### 13. Boundary Condition Testing (4 tests)
- Acceptance at exact MIN_CONFIDENCE_THRESHOLD
- Acceptance at exact MIN_SCENARIO_COUNT
- Rejection just below MIN_CONFIDENCE_THRESHOLD
- Rejection just below MIN_SCENARIO_COUNT

### 14. End-to-End Integration (5 tests)
- Complete equity hedge compilation from risk description
- FX risk spec handling (EURUSD)
- Commodity risk spec handling (WTI)
- Composability assertion on compiled instrument
- Rejection of un-backtested composites

### 15. Spec-Specific Instrument Types (3 tests)
- Gradient ramp instrument creation
- Reinstatement feature protection instrument
- Call-spread via spread type for multi-vector

### 16. Horizon Decision Logic: Funding/Carry vs One-Off (4 tests)
- Discrete when one-off cost significantly beats funding+carry
- Perpetual when funding+carry beats one-off cost
- Break-even at equal costs (closes to perpetual)
- Discrete favored when one-off has no carry burden

### 17. Deterministic Backtest Reproducibility (3 tests)
- Identical results for same underlying+type across invocations
- Different results across instrument types
- Different results across different underlyings

### 18. Fail-Closed Validation (3 tests)
- Marks invalid when instrument type not in allowlist
- Rejects if backtest confidence below threshold
- Rejects if backtest scenario count too low
- Passes when all criteria met

## Key Features Tested

### Instrument Types
- ✅ Call (directional upside)
- ✅ Put (directional downside)
- ✅ Spread (multi-leg)
- ✅ Collar (bounded payoff)
- ✅ Ramp (gradient exposure)
- ✅ Reinstatement (protection clause)

### Risk Vectors
- ✅ Equity (stocks, indices)
- ✅ FX (currency pairs)
- ✅ Rate (interest rates)
- ✅ Commodity (oil, metals)
- ✅ Volatility (VIX, variance)

### Horizon Selection
- ✅ Perpetual (continuous funding)
- ✅ Discrete (one-off cost)
- ✅ Cost comparison logic
- ✅ Carry burden factoring

### Fail-Closed Guarantees
- ✅ Allowlist validation
- ✅ Minimum confidence threshold
- ✅ Minimum scenario count
- ✅ Backtest results requirement

### Determinism
- ✅ No Date.now() usage
- ✅ No Math.random() usage
- ✅ Seeded hash-based randomization
- ✅ Reproducible IDs and backtest results

## Test Assertions Summary

Each test verifies one or more of:
1. **Validity**: isValid flag and error/warning arrays
2. **Instrument Properties**: type, underlying, horizon, payoff structure
3. **Backtest Results**: confidence, scenario count, PnL bounds
4. **Rationale**: Cost deltas and decision explanations
5. **Allowlist Compliance**: Type restrictions enforcement
6. **Fail-Closed Behavior**: Predictable rejection of invalid composites
7. **Determinism**: Same input → same output (no randomness)
8. **Edge Cases**: Boundary conditions, missing data, zero values

## Running Tests

```bash
cd web
npx vitest run server/utils/otc/__tests__/compositePayoffCompiler.test.ts
```

Expected output:
```
Test Files  1 passed (1)
     Tests  74 passed (74)
```
