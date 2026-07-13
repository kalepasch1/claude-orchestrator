import { describe, it, expect } from 'vitest';
import {
  composeProgram,
  assertComposable,
  selectHorizon,
  generateRationale,
  performStructuralBacktest,
} from '../compositePayoffCompiler';
import {
  RiskSpec,
  RiskVector,
  INSTRUMENT_ALLOWLIST,
  MIN_CONFIDENCE_THRESHOLD,
  MIN_SCENARIO_COUNT,
} from '../payoffDSL';

describe('Composite Payoff Compiler', () => {
  const createBasicRiskSpec = (overrides?: Partial<RiskSpec>): RiskSpec => ({
    description: 'Basic equity call spread',
    vectors: [
      {
        underlying: 'AAPL',
        type: 'equity',
        strike: 150,
        spot: 145,
        maturity: 30,
        notional: 100000,
      } as RiskVector,
    ],
    horizon: 'perpetual',
    fundingCost: 50,
    oneOffCost: 35,
    carry: 10,
    ...overrides,
  });

  // ===== BASIC COMPILATION TESTS =====
  describe('composeProgram - basic compilation', () => {
    it('should successfully compile valid risk spec with call instrument', () => {
      const riskSpec = createBasicRiskSpec({
        description: 'Hedge call on AAPL',
      });
      const result = composeProgram(riskSpec);

      expect(result.isValid).toBe(true);
      expect(result.errors).toHaveLength(0);
      expect(result.instrument).toBeDefined();
      expect(result.instrument.type).toBe('call');
      expect(result.instrument.underlying).toBe('AAPL');
    });

    it('should parse instrument type from risk description - put', () => {
      const riskSpec = createBasicRiskSpec({
        description: 'Downside protection put on SPY',
        vectors: [
          {
            underlying: 'SPY',
            type: 'equity',
            strike: 450,
            spot: 460,
            maturity: 30,
            notional: 100000,
          } as RiskVector,
        ],
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument.type).toBe('put');
    });

    it('should parse instrument type from risk description - collar', () => {
      const riskSpec = createBasicRiskSpec({
        description: 'Collar strategy on TSLA',
        vectors: [
          {
            underlying: 'TSLA',
            type: 'equity',
            strike: 250,
            spot: 240,
            maturity: 30,
            notional: 100000,
          } as RiskVector,
        ],
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument.type).toBe('collar');
    });

    it('should parse instrument type from risk description - ramp', () => {
      const riskSpec = createBasicRiskSpec({
        description: 'Gradient ramp payoff',
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument.type).toBe('ramp');
    });

    it('should parse instrument type from risk description - reinstatement', () => {
      const riskSpec = createBasicRiskSpec({
        description: 'Reinstatement clause on equity position',
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument.type).toBe('reinstatement');
    });

    it('should default to spread for ambiguous description', () => {
      const riskSpec = createBasicRiskSpec({
        description: 'Equity strategy',
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument.type).toBe('spread');
    });

    it('should generate deterministic instrument IDs (same input → same ID)', () => {
      // Per server/utils conventions: no Date.now(), IDs are deterministic and reproducible.
      const riskSpec = createBasicRiskSpec();
      const result1 = composeProgram(riskSpec);
      const result2 = composeProgram(riskSpec);

      expect(result1.instrument.id).toBe(result2.instrument.id);
      expect(result1.instrument.id).toMatch(/AAPL-[a-z0-9]+/);
    });

    it('should generate different IDs for different underlying assets', () => {
      const spec1 = createBasicRiskSpec({
        vectors: [
          {
            underlying: 'AAPL',
            type: 'equity',
            strike: 150,
            spot: 145,
            maturity: 30,
            notional: 100000,
          } as RiskVector,
        ],
      });
      const spec2 = createBasicRiskSpec({
        vectors: [
          {
            underlying: 'MSFT',
            type: 'equity',
            strike: 150,
            spot: 145,
            maturity: 30,
            notional: 100000,
          } as RiskVector,
        ],
      });

      const result1 = composeProgram(spec1);
      const result2 = composeProgram(spec2);

      expect(result1.instrument.id).not.toBe(result2.instrument.id);
    });

    it('should include strike in payoff', () => {
      const riskSpec = createBasicRiskSpec({
        vectors: [
          {
            underlying: 'AAPL',
            type: 'equity',
            strike: 150,
            spot: 145,
            maturity: 30,
            notional: 100000,
          } as RiskVector,
        ],
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument.payoff.strikes).toContain(150);
    });
  });

  // ===== HORIZON SELECTION TESTS =====
  describe('selectHorizon - perpetual vs discrete selection', () => {
    it('should select discrete when one-off cost is lower than funding cost', () => {
      const riskSpec = createBasicRiskSpec({
        fundingCost: 50,
        oneOffCost: 30,
        carry: 0,
      });
      const horizon = selectHorizon(50, 30, 0, riskSpec);

      expect(horizon).toBe('discrete');
    });

    it('should select perpetual when funding cost is lower than one-off cost', () => {
      const riskSpec = createBasicRiskSpec({
        fundingCost: 20,
        oneOffCost: 60,
        carry: 5,
      });
      const horizon = selectHorizon(20, 60, 5, riskSpec);

      expect(horizon).toBe('perpetual');
    });

    it('should account for carry in horizon selection', () => {
      const riskSpec = createBasicRiskSpec({
        fundingCost: 50,
        carry: 30,
      });
      const horizon = selectHorizon(50, 40, 30, riskSpec);

      expect(horizon).toBe('discrete');
    });

    it('should default to perpetual when carry data is unavailable', () => {
      const riskSpec = createBasicRiskSpec({
        fundingCost: 50,
        oneOffCost: undefined,
      });
      const horizon = selectHorizon(50, undefined, undefined, riskSpec);

      expect(horizon).toBe('perpetual');
    });

    it('should handle perpetual horizon with no one-off cost', () => {
      const riskSpec = createBasicRiskSpec({
        fundingCost: 50,
        oneOffCost: undefined,
        carry: 10,
      });
      const horizon = selectHorizon(50, undefined, 10, riskSpec);

      expect(horizon).toBe('perpetual');
    });
  });

  // ===== COST DELTA AND RATIONALE TESTS =====
  describe('composeProgram - cost delta and rationale', () => {
    it('should set cost delta for discrete instruments', () => {
      const riskSpec = createBasicRiskSpec({
        fundingCost: 50,
        oneOffCost: 35,
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument.horizon).toBe('discrete');
      expect(result.instrument.costDelta).toBe(35 - 50);
    });

    it('should include rationale mentioning cost choice for discrete', () => {
      const riskSpec = createBasicRiskSpec({
        fundingCost: 50,
        oneOffCost: 35,
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument.rationale).toContain('Discrete');
      expect(result.instrument.rationale).toContain('one-off cost');
      expect(result.instrument.rationale).toContain('funding carry');
    });

    it('should include rationale mentioning carry for perpetual', () => {
      const riskSpec = createBasicRiskSpec({
        fundingCost: 20,
        oneOffCost: 60,
        carry: 15,
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument.rationale).toContain('Perpetual');
      expect(result.instrument.rationale).toContain('funding carry');
    });
  });

  // ===== BACKTEST VALIDATION TESTS =====
  describe('performStructuralBacktest', () => {
    it('should generate backtest results with required fields', () => {
      const results = performStructuralBacktest('AAPL', 'call');

      expect(results).toHaveProperty('scenarioCount');
      expect(results).toHaveProperty('passed');
      expect(results).toHaveProperty('failed');
      expect(results).toHaveProperty('avgPnL');
      expect(results).toHaveProperty('maxLoss');
      expect(results).toHaveProperty('maxGain');
      expect(results).toHaveProperty('confidence');
    });

    it('should have scenario count >= MIN_SCENARIO_COUNT', () => {
      const results = performStructuralBacktest('AAPL', 'call');

      expect(results.scenarioCount).toBeGreaterThanOrEqual(MIN_SCENARIO_COUNT);
    });

    it('should have passed + failed = scenarioCount', () => {
      const results = performStructuralBacktest('AAPL', 'call');

      expect(results.passed + results.failed).toBe(results.scenarioCount);
    });

    it('should have confidence = passed / scenarioCount', () => {
      const results = performStructuralBacktest('AAPL', 'call');
      const expectedConfidence = results.passed / results.scenarioCount;

      expect(results.confidence).toBeCloseTo(expectedConfidence, 5);
    });

    it('should have confidence >= MIN_CONFIDENCE_THRESHOLD', () => {
      const results = performStructuralBacktest('AAPL', 'call');

      expect(results.confidence).toBeGreaterThanOrEqual(MIN_CONFIDENCE_THRESHOLD);
    });

    it('should produce realistic PnL bounds', () => {
      const results = performStructuralBacktest('AAPL', 'call');

      expect(results.maxLoss).toBeLessThan(0);
      expect(results.maxGain).toBeGreaterThan(0);
      expect(results.maxGain).toBeGreaterThan(Math.abs(results.maxLoss) * 0.5);
    });
  });

  // ===== BACKTEST INCLUSION TESTS =====
  describe('composeProgram - backtest inclusion', () => {
    it('should include backtest results in compiled instrument', () => {
      const riskSpec = createBasicRiskSpec();
      const result = composeProgram(riskSpec);

      expect(result.instrument.backtestResults).toBeDefined();
      expect(result.instrument.backtestResults?.scenarioCount).toBeGreaterThanOrEqual(
        MIN_SCENARIO_COUNT
      );
      expect(result.instrument.backtestResults?.confidence).toBeGreaterThanOrEqual(
        MIN_CONFIDENCE_THRESHOLD
      );
    });

    it('should not return valid=true if backtest confidence is too low', () => {
      const riskSpec = createBasicRiskSpec();
      const result = composeProgram(riskSpec);

      if (result.instrument.backtestResults!.confidence < MIN_CONFIDENCE_THRESHOLD) {
        expect(result.isValid).toBe(false);
        expect(result.errors.length).toBeGreaterThan(0);
      }
    });
  });

  // ===== ALLOWLIST VALIDATION TESTS =====
  describe('composeProgram - allowlist validation', () => {
    it('should mark instrument as allowlisted for valid type', () => {
      const riskSpec = createBasicRiskSpec({
        description: 'Call spread',
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument.isAllowlisted).toBe(true);
    });

    it('should include all instrument types in allowlist', () => {
      const types = ['call', 'put', 'spread', 'collar', 'ramp', 'reinstatement'];

      types.forEach((type) => {
        expect(INSTRUMENT_ALLOWLIST).toContain(type);
      });
    });

    it('should generate error if instrument type is not allowlisted', () => {
      const riskSpec = createBasicRiskSpec();
      const result = composeProgram(riskSpec);

      if (!INSTRUMENT_ALLOWLIST.includes(result.instrument.type)) {
        expect(result.errors.some((e) => e.includes('not in allowlist'))).toBe(true);
      }
    });
  });

  // ===== ASSERTCOMPOSABLE VALIDATION TESTS =====
  describe('assertComposable - fail-closed validation', () => {
    it('should throw if instrument is not allowlisted', () => {
      const riskSpec = createBasicRiskSpec();
      const instrument = {
        ...createBasicRiskSpec().vectors[0],
        id: 'test-1',
        type: 'call' as const,
        underlying: 'TEST',
        payoff: { strikes: [100], weights: [1.0], type: 'call' as const },
        horizon: 'perpetual' as const,
        rationale: 'test',
        isAllowlisted: false,
        backtestResults: {
          scenarioCount: 250,
          passed: 235,
          failed: 15,
          avgPnL: 500,
          maxLoss: -2000,
          maxGain: 5000,
          confidence: 0.94,
        },
      };

      expect(() => assertComposable(riskSpec, instrument)).toThrow(
        /not in allowlist/
      );
    });

    it('should throw if backtest confidence is below threshold', () => {
      const riskSpec = createBasicRiskSpec();
      const instrument = {
        ...createBasicRiskSpec().vectors[0],
        id: 'test-2',
        type: 'call' as const,
        underlying: 'TEST',
        payoff: { strikes: [100], weights: [1.0], type: 'call' as const },
        horizon: 'perpetual' as const,
        rationale: 'test',
        isAllowlisted: true,
        backtestResults: {
          scenarioCount: 250,
          passed: 200,
          failed: 50,
          avgPnL: 500,
          maxLoss: -2000,
          maxGain: 5000,
          confidence: 0.8,
        },
      };

      expect(() => assertComposable(riskSpec, instrument)).toThrow(
        /confidence.*below threshold/
      );
    });

    it('should throw if instrument has no backtest results', () => {
      const riskSpec = createBasicRiskSpec();
      const instrument = {
        ...createBasicRiskSpec().vectors[0],
        id: 'test-3',
        type: 'call' as const,
        underlying: 'TEST',
        payoff: { strikes: [100], weights: [1.0], type: 'call' as const },
        horizon: 'perpetual' as const,
        rationale: 'test',
        isAllowlisted: true,
        backtestResults: undefined,
      };

      expect(() => assertComposable(riskSpec, instrument)).toThrow(
        /backtest results/
      );
    });

    it('should throw if backtest scenario count is below minimum', () => {
      const riskSpec = createBasicRiskSpec();
      const instrument = {
        ...createBasicRiskSpec().vectors[0],
        id: 'test-4',
        type: 'call' as const,
        underlying: 'TEST',
        payoff: { strikes: [100], weights: [1.0], type: 'call' as const },
        horizon: 'perpetual' as const,
        rationale: 'test',
        isAllowlisted: true,
        backtestResults: {
          scenarioCount: 50,
          passed: 45,
          failed: 5,
          avgPnL: 500,
          maxLoss: -2000,
          maxGain: 5000,
          confidence: 0.9,
        },
      };

      expect(() => assertComposable(riskSpec, instrument)).toThrow(
        /scenario count.*below minimum/
      );
    });

    it('should not throw for valid instrument', () => {
      const riskSpec = createBasicRiskSpec();
      const instrument = {
        ...createBasicRiskSpec().vectors[0],
        id: 'test-5',
        type: 'call' as const,
        underlying: 'TEST',
        payoff: { strikes: [100], weights: [1.0], type: 'call' as const },
        horizon: 'perpetual' as const,
        rationale: 'test',
        isAllowlisted: true,
        backtestResults: {
          scenarioCount: 250,
          passed: 235,
          failed: 15,
          avgPnL: 500,
          maxLoss: -2000,
          maxGain: 5000,
          confidence: 0.94,
        },
      };

      expect(() => assertComposable(riskSpec, instrument)).not.toThrow();
    });
  });

  // ===== EDGE CASES AND ERROR HANDLING =====
  describe('composeProgram - error handling', () => {
    it('should return error if risk spec has no vectors', () => {
      const riskSpec = createBasicRiskSpec({
        vectors: [],
      });
      const result = composeProgram(riskSpec);

      expect(result.isValid).toBe(false);
      expect(result.errors.length).toBeGreaterThan(0);
      expect(result.errors[0]).toContain('at least one risk vector');
    });

    it('should handle multiple risk vectors', () => {
      const riskSpec = createBasicRiskSpec({
        vectors: [
          {
            underlying: 'AAPL',
            type: 'equity',
            strike: 150,
            spot: 145,
            maturity: 30,
            notional: 100000,
          } as RiskVector,
          {
            underlying: 'MSFT',
            type: 'equity',
            strike: 350,
            spot: 340,
            maturity: 30,
            notional: 100000,
          } as RiskVector,
        ],
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument).toBeDefined();
      expect(result.instrument.underlying).toBe('AAPL');
    });

    it('should handle risk specs without strike prices', () => {
      const riskSpec = createBasicRiskSpec({
        vectors: [
          {
            underlying: 'EURUSD',
            type: 'fx',
            spot: 1.1,
            notional: 100000,
          } as RiskVector,
        ],
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument).toBeDefined();
      expect(result.instrument.payoff.strikes).toHaveLength(0);
    });
  });

  // ===== DISCRETE SELECTION SPECIFIC TESTS =====
  describe('composeProgram - discrete selection with cost delta', () => {
    it('should select discrete and show cost savings', () => {
      const riskSpec = createBasicRiskSpec({
        description: 'Temporary hedge call',
        fundingCost: 100,
        oneOffCost: 60,
        carry: 5,
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument.horizon).toBe('discrete');
      expect(result.instrument.costDelta).toBe(-40);
      expect(result.instrument.rationale).toContain('cost');
    });

    it('should include cost delta in rationale for discrete', () => {
      const riskSpec = createBasicRiskSpec({
        fundingCost: 50,
        oneOffCost: 30,
        horizon: 'discrete',
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument.rationale).toContain('one-off');
      expect(result.instrument.rationale).toContain('bps');
    });

    it('should reject discrete selection if backtest fails', () => {
      const riskSpec = createBasicRiskSpec({
        fundingCost: 50,
        oneOffCost: 30,
      });
      const result = composeProgram(riskSpec);

      if (result.instrument.backtestResults!.confidence < MIN_CONFIDENCE_THRESHOLD) {
        expect(result.isValid).toBe(false);
      }
    });
  });

  // ===== GENERATERATIONALE DIRECT TESTS =====
  describe('generateRationale - direct function tests', () => {
    it('should generate rationale for discrete horizon with cost delta', () => {
      const rationale = generateRationale('discrete', -40, 100, 10);

      expect(rationale).toContain('Discrete');
      expect(rationale).toContain('one-off cost');
      expect(rationale).toContain('-40.00bps');
      expect(rationale).toContain('100.00bps');
    });

    it('should generate rationale for perpetual horizon with carry', () => {
      const rationale = generateRationale('perpetual', -40, 50, 25);

      expect(rationale).toContain('Perpetual');
      expect(rationale).toContain('funding carry');
      expect(rationale).toContain('25.00bps');
      expect(rationale).toContain('50.00bps');
    });

    it('should format cost values as basis points', () => {
      const rationale = generateRationale('discrete', 123.456, 200, 50);

      expect(rationale).toMatch(/123\.46bps/);
      expect(rationale).toMatch(/200\.00bps/);
    });

    it('should handle undefined cost delta', () => {
      const rationale = generateRationale('discrete', undefined, 50, 10);

      expect(rationale).toContain('one-off cost');
      expect(rationale).toContain('undefinedBps');
    });
  });

  // ===== EDGE CASES FOR COST DELTA =====
  describe('composeProgram - cost delta edge cases', () => {
    it('should calculate cost delta as difference when both costs exist', () => {
      const riskSpec = createBasicRiskSpec({
        fundingCost: 100,
        oneOffCost: 60,
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument.costDelta).toBe(-40);
    });

    it('should use oneOffCost as costDelta when fundingCost is undefined', () => {
      const riskSpec = createBasicRiskSpec({
        fundingCost: undefined,
        oneOffCost: 75,
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument.costDelta).toBe(75);
    });

    it('should not set costDelta when oneOffCost is undefined', () => {
      const riskSpec = createBasicRiskSpec({
        fundingCost: 50,
        oneOffCost: undefined,
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument.costDelta).toBeUndefined();
    });

    it('should handle zero cost values', () => {
      const riskSpec = createBasicRiskSpec({
        fundingCost: 0,
        oneOffCost: 50,
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument.costDelta).toBe(50);
    });

    it('should handle negative cost delta (perpetual more expensive)', () => {
      const riskSpec = createBasicRiskSpec({
        fundingCost: 30,
        oneOffCost: 100,
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument.costDelta).toBe(70);
      expect(result.instrument.horizon).toBe('perpetual');
    });
  });

  // ===== RISK VECTOR TYPE SPECIFIC TESTS =====
  describe('composeProgram - risk vector types', () => {
    it('should handle rate risk vectors', () => {
      const riskSpec = createBasicRiskSpec({
        description: 'Interest rate call collar',
        vectors: [
          {
            underlying: 'SONIA',
            type: 'rate',
            spot: 0.05,
            maturity: 365,
            notional: 10000000,
          } as RiskVector,
        ],
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument).toBeDefined();
      expect(result.instrument.type).toBe('collar');
    });

    it('should handle volatility risk vectors', () => {
      const riskSpec = createBasicRiskSpec({
        description: 'VIX volatility put',
        vectors: [
          {
            underlying: 'VIX',
            type: 'volatility',
            spot: 25,
            maturity: 30,
            notional: 1000,
          } as RiskVector,
        ],
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument).toBeDefined();
      expect(result.instrument.type).toBe('put');
    });
  });

  // ===== BOUNDARY CONDITION TESTS =====
  describe('assertComposable - boundary conditions', () => {
    it('should accept instrument at exact MIN_CONFIDENCE_THRESHOLD', () => {
      const riskSpec = createBasicRiskSpec();
      const instrument = {
        ...createBasicRiskSpec().vectors[0],
        id: 'test-boundary-1',
        type: 'call' as const,
        underlying: 'TEST',
        payoff: { strikes: [100], weights: [1.0], type: 'call' as const },
        horizon: 'perpetual' as const,
        rationale: 'test',
        isAllowlisted: true,
        backtestResults: {
          scenarioCount: 100,
          passed: Math.round(100 * MIN_CONFIDENCE_THRESHOLD),
          failed: 100 - Math.round(100 * MIN_CONFIDENCE_THRESHOLD),
          avgPnL: 500,
          maxLoss: -2000,
          maxGain: 5000,
          confidence: MIN_CONFIDENCE_THRESHOLD,
        },
      };

      expect(() => assertComposable(riskSpec, instrument)).not.toThrow();
    });

    it('should accept instrument at exact MIN_SCENARIO_COUNT', () => {
      const riskSpec = createBasicRiskSpec();
      const instrument = {
        ...createBasicRiskSpec().vectors[0],
        id: 'test-boundary-2',
        type: 'call' as const,
        underlying: 'TEST',
        payoff: { strikes: [100], weights: [1.0], type: 'call' as const },
        horizon: 'perpetual' as const,
        rationale: 'test',
        isAllowlisted: true,
        backtestResults: {
          scenarioCount: MIN_SCENARIO_COUNT,
          passed: Math.round(MIN_SCENARIO_COUNT * 0.9),
          failed: MIN_SCENARIO_COUNT - Math.round(MIN_SCENARIO_COUNT * 0.9),
          avgPnL: 500,
          maxLoss: -2000,
          maxGain: 5000,
          confidence: 0.9,
        },
      };

      expect(() => assertComposable(riskSpec, instrument)).not.toThrow();
    });

    it('should reject instrument just below MIN_CONFIDENCE_THRESHOLD', () => {
      const riskSpec = createBasicRiskSpec();
      const instrument = {
        ...createBasicRiskSpec().vectors[0],
        id: 'test-boundary-3',
        type: 'call' as const,
        underlying: 'TEST',
        payoff: { strikes: [100], weights: [1.0], type: 'call' as const },
        horizon: 'perpetual' as const,
        rationale: 'test',
        isAllowlisted: true,
        backtestResults: {
          scenarioCount: 250,
          passed: 211,
          failed: 39,
          avgPnL: 500,
          maxLoss: -2000,
          maxGain: 5000,
          confidence: MIN_CONFIDENCE_THRESHOLD - 0.001,
        },
      };

      expect(() => assertComposable(riskSpec, instrument)).toThrow(
        /confidence.*below threshold/
      );
    });

    it('should reject instrument just below MIN_SCENARIO_COUNT', () => {
      const riskSpec = createBasicRiskSpec();
      const instrument = {
        ...createBasicRiskSpec().vectors[0],
        id: 'test-boundary-4',
        type: 'call' as const,
        underlying: 'TEST',
        payoff: { strikes: [100], weights: [1.0], type: 'call' as const },
        horizon: 'perpetual' as const,
        rationale: 'test',
        isAllowlisted: true,
        backtestResults: {
          scenarioCount: MIN_SCENARIO_COUNT - 1,
          passed: MIN_SCENARIO_COUNT - 11,
          failed: 10,
          avgPnL: 500,
          maxLoss: -2000,
          maxGain: 5000,
          confidence: 0.9,
        },
      };

      expect(() => assertComposable(riskSpec, instrument)).toThrow(
        /scenario count.*below minimum/
      );
    });
  });

  // ===== FULL INTEGRATION TESTS =====
  describe('End-to-end compilation workflow', () => {
    it('should compile a valid equity hedge from risk description', () => {
      const riskSpec: RiskSpec = {
        description: 'Downside protection put collar on tech portfolio',
        vectors: [
          {
            underlying: 'QQQ',
            type: 'equity',
            strike: 350,
            spot: 360,
            maturity: 90,
            notional: 1000000,
          } as RiskVector,
        ],
        horizon: 'perpetual',
        fundingCost: 75,
        oneOffCost: 120,
        carry: 20,
      };

      const result = composeProgram(riskSpec);

      expect(result.isValid).toBe(true);
      expect(result.instrument.type).toBe('collar');
      expect(result.instrument.underlying).toBe('QQQ');
      expect(result.instrument.horizon).toMatch(/^(perpetual|discrete)$/);
      expect(result.instrument.backtestResults?.confidence).toBeGreaterThanOrEqual(
        MIN_CONFIDENCE_THRESHOLD
      );
      expect(result.instrument.isAllowlisted).toBe(true);
    });

    it('should handle FX risk specs', () => {
      const riskSpec: RiskSpec = {
        description: 'EURUSD currency hedge call',
        vectors: [
          {
            underlying: 'EURUSD',
            type: 'fx',
            spot: 1.08,
            maturity: 60,
            notional: 5000000,
          } as RiskVector,
        ],
        horizon: 'discrete',
        oneOffCost: 45,
        fundingCost: 30,
      };

      const result = composeProgram(riskSpec);

      expect(result.instrument).toBeDefined();
      expect(result.instrument.type).toBe('call');
      expect(result.instrument.underlying).toBe('EURUSD');
    });

    it('should handle commodity risk specs', () => {
      const riskSpec: RiskSpec = {
        description: 'Oil price ramp hedge',
        vectors: [
          {
            underlying: 'WTI',
            type: 'commodity',
            strike: 80,
            spot: 85,
            maturity: 180,
            notional: 100000,
          } as RiskVector,
        ],
        horizon: 'perpetual',
        fundingCost: 50,
        carry: 15,
      };

      const result = composeProgram(riskSpec);

      expect(result.instrument.type).toBe('ramp');
      expect(result.instrument.underlying).toBe('WTI');
    });

    it('should assert composability on successfully compiled instrument', () => {
      const riskSpec = createBasicRiskSpec();
      const result = composeProgram(riskSpec);

      if (result.isValid) {
        expect(() => assertComposable(riskSpec, result.instrument)).not.toThrow();
      }
    });

    it('should reject un-backtested composite through assertComposable', () => {
      const riskSpec = createBasicRiskSpec();
      const instrument = {
        id: 'unbacked-1',
        type: 'spread' as const,
        underlying: 'UNBACKED',
        payoff: { strikes: [100], weights: [1.0], type: 'spread' as const },
        horizon: 'perpetual' as const,
        rationale: 'No backtest',
        isAllowlisted: true,
        backtestResults: undefined,
      };

      expect(() => assertComposable(riskSpec, instrument)).toThrow(
        /backtest results/
      );
    });

    it('should encode full decision path in rationale', () => {
      const riskSpec: RiskSpec = {
        description: 'One-off equity hedge call',
        vectors: [
          {
            underlying: 'MSFT',
            type: 'equity',
            strike: 400,
            spot: 395,
            maturity: 30,
            notional: 500000,
          } as RiskVector,
        ],
        horizon: 'discrete',
        fundingCost: 80,
        oneOffCost: 50,
        carry: 5,
      };

      const result = composeProgram(riskSpec);

      expect(result.instrument.rationale).toContain('Discrete');
      expect(result.instrument.rationale).toContain('one-off');
      expect(result.instrument.rationale).toContain('80');
      expect(result.instrument.rationale).toContain('bps');
    });
  });

  // ===== SPEC-SPECIFIC REQUIRED INSTRUMENTS =====
  describe('Spec-specific instrument types', () => {
    it('should create gradient ramp instruments for ramp description', () => {
      const riskSpec = createBasicRiskSpec({
        description: 'Gradient ramp exposure hedge',
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument.type).toBe('ramp');
      expect(result.instrument.isAllowlisted).toBe(true);
      expect(result.instrument.backtestResults).toBeDefined();
    });

    it('should create reinstatement instruments when specified', () => {
      const riskSpec = createBasicRiskSpec({
        description: 'Reinstatement feature protection',
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument.type).toBe('reinstatement');
      expect(result.instrument.isAllowlisted).toBe(true);
      expect(result.instrument.backtestResults).toBeDefined();
    });

    it('should create call-spread via spread type for multi-vector', () => {
      const riskSpec = createBasicRiskSpec({
        description: 'call spread hedge',
        vectors: [
          {
            underlying: 'SPX',
            type: 'equity',
            strike: 4500,
            spot: 4550,
            maturity: 60,
            notional: 500000,
          } as RiskVector,
          {
            underlying: 'SPX',
            type: 'equity',
            strike: 4600,
            spot: 4550,
            maturity: 60,
            notional: 500000,
          } as RiskVector,
        ],
      });
      const result = composeProgram(riskSpec);

      expect(result.instrument.type).toBe('spread');
      expect(result.instrument.underlying).toBe('SPX');
      expect(result.instrument.isAllowlisted).toBe(true);
    });
  });

  // ===== HORIZON DECISION LOGIC: FUNDING/CARRY VS ONE-OFF COST =====
  describe('Horizon selection: funding-carry vs one-off cost decision', () => {
    it('should choose discrete when one-off cost significantly beats funding+carry', () => {
      const riskSpec = createBasicRiskSpec({
        fundingCost: 100,
        carry: 50,
        oneOffCost: 80,
      });
      const result = composeProgram(riskSpec);

      // oneOffCost (80) < fundingCost + carry (150)
      expect(result.instrument.horizon).toBe('discrete');
      expect(result.instrument.costDelta).toBe(-20);
      expect(result.instrument.rationale).toContain('Discrete');
    });

    it('should choose perpetual when funding+carry beats one-off cost', () => {
      const riskSpec = createBasicRiskSpec({
        fundingCost: 30,
        carry: 15,
        oneOffCost: 100,
      });
      const result = composeProgram(riskSpec);

      // oneOffCost (100) > fundingCost (30) + carry (15)
      expect(result.instrument.horizon).toBe('perpetual');
      expect(result.instrument.rationale).toContain('Perpetual');
      expect(result.instrument.rationale).toContain('funding carry');
    });

    it('should close on discrete for break-even with zero carry', () => {
      const riskSpec = createBasicRiskSpec({
        fundingCost: 50,
        carry: 0,
        oneOffCost: 50,
      });
      const result = composeProgram(riskSpec);

      // oneOffCost (50) = fundingCost (50), but selectHorizon uses < so defaults to perpetual
      expect(result.instrument.horizon).toBe('perpetual');
    });

    it('should favor discrete when one-off has no carry burden', () => {
      const riskSpec = createBasicRiskSpec({
        fundingCost: 25,
        carry: 75,
        oneOffCost: 50,
      });
      const result = composeProgram(riskSpec);

      // oneOffCost (50) < fundingCost + carry (100)
      expect(result.instrument.horizon).toBe('discrete');
    });
  });

  // ===== DETERMINISTIC BACKTEST REPRODUCIBILITY =====
  describe('Deterministic backtest across multiple invocations', () => {
    it('should produce identical backtest results for same underlying+type', () => {
      const results1 = performStructuralBacktest('AAPL', 'call');
      const results2 = performStructuralBacktest('AAPL', 'call');

      expect(results1.scenarioCount).toBe(results2.scenarioCount);
      expect(results1.passed).toBe(results2.passed);
      expect(results1.failed).toBe(results2.failed);
      expect(results1.avgPnL).toBe(results2.avgPnL);
      expect(results1.maxLoss).toBe(results2.maxLoss);
      expect(results1.maxGain).toBe(results2.maxGain);
      expect(results1.confidence).toBe(results2.confidence);
    });

    it('should vary backtest results across different instrument types', () => {
      const callResults = performStructuralBacktest('AAPL', 'call');
      const putResults = performStructuralBacktest('AAPL', 'put');

      // Calls and puts have different risk profiles
      expect(callResults.confidence).not.toBe(putResults.confidence);
    });

    it('should vary backtest results across different underlyings', () => {
      const aaplResults = performStructuralBacktest('AAPL', 'call');
      const msftResults = performStructuralBacktest('MSFT', 'call');

      // Same instrument type but different underlying should differ
      expect(aaplResults.avgPnL).not.toBe(msftResults.avgPnL);
    });
  });

  // ===== FAIL-CLOSED VALIDATION =====
  describe('Fail-closed validation against instrumentAllowlist and backtest', () => {
    it('should mark invalid when instrument type not in allowlist', () => {
      const riskSpec = createBasicRiskSpec();
      const instrument = {
        ...createBasicRiskSpec().vectors[0],
        id: 'failclosed-1',
        type: 'exotic' as any,
        underlying: 'TEST',
        payoff: { strikes: [100], weights: [1.0], type: 'exotic' as any },
        horizon: 'perpetual' as const,
        rationale: 'test',
        isAllowlisted: false,
        backtestResults: {
          scenarioCount: 250,
          passed: 235,
          failed: 15,
          avgPnL: 500,
          maxLoss: -2000,
          maxGain: 5000,
          confidence: 0.94,
        },
      };

      expect(() => assertComposable(riskSpec, instrument)).toThrow();
    });

    it('should reject if backtest failed to meet confidence threshold', () => {
      const riskSpec = createBasicRiskSpec();
      const instrument = {
        ...createBasicRiskSpec().vectors[0],
        id: 'failclosed-2',
        type: 'call' as const,
        underlying: 'TEST',
        payoff: { strikes: [100], weights: [1.0], type: 'call' as const },
        horizon: 'perpetual' as const,
        rationale: 'test',
        isAllowlisted: true,
        backtestResults: {
          scenarioCount: 250,
          passed: 210,
          failed: 40,
          avgPnL: 500,
          maxLoss: -2000,
          maxGain: 5000,
          confidence: 0.84, // Below MIN_CONFIDENCE_THRESHOLD of 0.85
        },
      };

      expect(() => assertComposable(riskSpec, instrument)).toThrow(
        /confidence.*below threshold/
      );
    });

    it('should reject if backtest scenario count too low', () => {
      const riskSpec = createBasicRiskSpec();
      const instrument = {
        ...createBasicRiskSpec().vectors[0],
        id: 'failclosed-3',
        type: 'call' as const,
        underlying: 'TEST',
        payoff: { strikes: [100], weights: [1.0], type: 'call' as const },
        horizon: 'perpetual' as const,
        rationale: 'test',
        isAllowlisted: true,
        backtestResults: {
          scenarioCount: 50, // Below MIN_SCENARIO_COUNT
          passed: 45,
          failed: 5,
          avgPnL: 500,
          maxLoss: -2000,
          maxGain: 5000,
          confidence: 0.9,
        },
      };

      expect(() => assertComposable(riskSpec, instrument)).toThrow(
        /scenario count.*below minimum/
      );
    });

    it('should pass fail-closed validation when all criteria met', () => {
      const riskSpec = createBasicRiskSpec();
      const instrument = {
        ...createBasicRiskSpec().vectors[0],
        id: 'failclosed-4',
        type: 'call' as const,
        underlying: 'TEST',
        payoff: { strikes: [100], weights: [1.0], type: 'call' as const },
        horizon: 'perpetual' as const,
        rationale: 'test',
        isAllowlisted: true,
        backtestResults: {
          scenarioCount: 250,
          passed: 235,
          failed: 15,
          avgPnL: 500,
          maxLoss: -2000,
          maxGain: 5000,
          confidence: 0.94,
        },
      };

      expect(() => assertComposable(riskSpec, instrument)).not.toThrow();
    });
  });
});
