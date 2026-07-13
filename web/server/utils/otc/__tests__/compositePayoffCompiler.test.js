"use strict";
var __assign = (this && this.__assign) || function () {
    __assign = Object.assign || function(t) {
        for (var s, i = 1, n = arguments.length; i < n; i++) {
            s = arguments[i];
            for (var p in s) if (Object.prototype.hasOwnProperty.call(s, p))
                t[p] = s[p];
        }
        return t;
    };
    return __assign.apply(this, arguments);
};
exports.__esModule = true;
var vitest_1 = require("vitest");
var compositePayoffCompiler_1 = require("../compositePayoffCompiler");
var payoffDSL_1 = require("../payoffDSL");
(0, vitest_1.describe)('Composite Payoff Compiler', function () {
    var createBasicRiskSpec = function (overrides) { return (__assign({ description: 'Basic equity call spread', vectors: [
            {
                underlying: 'AAPL',
                type: 'equity',
                strike: 150,
                spot: 145,
                maturity: 30,
                notional: 100000
            },
        ], horizon: 'perpetual', fundingCost: 50, oneOffCost: 35, carry: 10 }, overrides)); };
    // ===== BASIC COMPILATION TESTS =====
    (0, vitest_1.describe)('composeProgram - basic compilation', function () {
        (0, vitest_1.it)('should successfully compile valid risk spec with call instrument', function () {
            var riskSpec = createBasicRiskSpec({
                description: 'Hedge call on AAPL'
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.isValid).toBe(true);
            (0, vitest_1.expect)(result.errors).toHaveLength(0);
            (0, vitest_1.expect)(result.instrument).toBeDefined();
            (0, vitest_1.expect)(result.instrument.type).toBe('call');
            (0, vitest_1.expect)(result.instrument.underlying).toBe('AAPL');
        });
        (0, vitest_1.it)('should parse instrument type from risk description - put', function () {
            var riskSpec = createBasicRiskSpec({
                description: 'Downside protection put on SPY',
                vectors: [
                    {
                        underlying: 'SPY',
                        type: 'equity',
                        strike: 450,
                        spot: 460,
                        maturity: 30,
                        notional: 100000
                    },
                ]
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument.type).toBe('put');
        });
        (0, vitest_1.it)('should parse instrument type from risk description - collar', function () {
            var riskSpec = createBasicRiskSpec({
                description: 'Collar strategy on TSLA',
                vectors: [
                    {
                        underlying: 'TSLA',
                        type: 'equity',
                        strike: 250,
                        spot: 240,
                        maturity: 30,
                        notional: 100000
                    },
                ]
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument.type).toBe('collar');
        });
        (0, vitest_1.it)('should parse instrument type from risk description - ramp', function () {
            var riskSpec = createBasicRiskSpec({
                description: 'Gradient ramp payoff'
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument.type).toBe('ramp');
        });
        (0, vitest_1.it)('should parse instrument type from risk description - reinstatement', function () {
            var riskSpec = createBasicRiskSpec({
                description: 'Reinstatement clause on equity position'
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument.type).toBe('reinstatement');
        });
        (0, vitest_1.it)('should default to spread for ambiguous description', function () {
            var riskSpec = createBasicRiskSpec({
                description: 'Equity strategy'
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument.type).toBe('spread');
        });
        (0, vitest_1.it)('should generate unique instrument IDs', function () {
            var riskSpec = createBasicRiskSpec();
            var result1 = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            var result2 = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result1.instrument.id).not.toBe(result2.instrument.id);
        });
        (0, vitest_1.it)('should include strike in payoff', function () {
            var riskSpec = createBasicRiskSpec({
                vectors: [
                    {
                        underlying: 'AAPL',
                        type: 'equity',
                        strike: 150,
                        spot: 145,
                        maturity: 30,
                        notional: 100000
                    },
                ]
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument.payoff.strikes).toContain(150);
        });
    });
    // ===== HORIZON SELECTION TESTS =====
    (0, vitest_1.describe)('selectHorizon - perpetual vs discrete selection', function () {
        (0, vitest_1.it)('should select discrete when one-off cost is lower than funding cost', function () {
            var riskSpec = createBasicRiskSpec({
                fundingCost: 50,
                oneOffCost: 30,
                carry: 0
            });
            var horizon = (0, compositePayoffCompiler_1.selectHorizon)(50, 30, 0, riskSpec);
            (0, vitest_1.expect)(horizon).toBe('discrete');
        });
        (0, vitest_1.it)('should select perpetual when funding cost is lower than one-off cost', function () {
            var riskSpec = createBasicRiskSpec({
                fundingCost: 20,
                oneOffCost: 60,
                carry: 5
            });
            var horizon = (0, compositePayoffCompiler_1.selectHorizon)(20, 60, 5, riskSpec);
            (0, vitest_1.expect)(horizon).toBe('perpetual');
        });
        (0, vitest_1.it)('should account for carry in horizon selection', function () {
            var riskSpec = createBasicRiskSpec({
                fundingCost: 50,
                carry: 30
            });
            var horizon = (0, compositePayoffCompiler_1.selectHorizon)(50, 40, 30, riskSpec);
            (0, vitest_1.expect)(horizon).toBe('discrete');
        });
        (0, vitest_1.it)('should default to perpetual when carry data is unavailable', function () {
            var riskSpec = createBasicRiskSpec({
                fundingCost: 50,
                oneOffCost: undefined
            });
            var horizon = (0, compositePayoffCompiler_1.selectHorizon)(50, undefined, undefined, riskSpec);
            (0, vitest_1.expect)(horizon).toBe('perpetual');
        });
        (0, vitest_1.it)('should handle perpetual horizon with no one-off cost', function () {
            var riskSpec = createBasicRiskSpec({
                fundingCost: 50,
                oneOffCost: undefined,
                carry: 10
            });
            var horizon = (0, compositePayoffCompiler_1.selectHorizon)(50, undefined, 10, riskSpec);
            (0, vitest_1.expect)(horizon).toBe('perpetual');
        });
    });
    // ===== COST DELTA AND RATIONALE TESTS =====
    (0, vitest_1.describe)('composeProgram - cost delta and rationale', function () {
        (0, vitest_1.it)('should set cost delta for discrete instruments', function () {
            var riskSpec = createBasicRiskSpec({
                fundingCost: 50,
                oneOffCost: 35
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument.horizon).toBe('discrete');
            (0, vitest_1.expect)(result.instrument.costDelta).toBe(35 - 50);
        });
        (0, vitest_1.it)('should include rationale mentioning cost choice for discrete', function () {
            var riskSpec = createBasicRiskSpec({
                fundingCost: 50,
                oneOffCost: 35
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument.rationale).toContain('Discrete');
            (0, vitest_1.expect)(result.instrument.rationale).toContain('one-off cost');
            (0, vitest_1.expect)(result.instrument.rationale).toContain('funding carry');
        });
        (0, vitest_1.it)('should include rationale mentioning carry for perpetual', function () {
            var riskSpec = createBasicRiskSpec({
                fundingCost: 20,
                oneOffCost: 60,
                carry: 15
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument.rationale).toContain('Perpetual');
            (0, vitest_1.expect)(result.instrument.rationale).toContain('funding carry');
        });
    });
    // ===== BACKTEST VALIDATION TESTS =====
    (0, vitest_1.describe)('performStructuralBacktest', function () {
        (0, vitest_1.it)('should generate backtest results with required fields', function () {
            var results = (0, compositePayoffCompiler_1.performStructuralBacktest)('AAPL', 'call');
            (0, vitest_1.expect)(results).toHaveProperty('scenarioCount');
            (0, vitest_1.expect)(results).toHaveProperty('passed');
            (0, vitest_1.expect)(results).toHaveProperty('failed');
            (0, vitest_1.expect)(results).toHaveProperty('avgPnL');
            (0, vitest_1.expect)(results).toHaveProperty('maxLoss');
            (0, vitest_1.expect)(results).toHaveProperty('maxGain');
            (0, vitest_1.expect)(results).toHaveProperty('confidence');
        });
        (0, vitest_1.it)('should have scenario count >= MIN_SCENARIO_COUNT', function () {
            var results = (0, compositePayoffCompiler_1.performStructuralBacktest)('AAPL', 'call');
            (0, vitest_1.expect)(results.scenarioCount).toBeGreaterThanOrEqual(payoffDSL_1.MIN_SCENARIO_COUNT);
        });
        (0, vitest_1.it)('should have passed + failed = scenarioCount', function () {
            var results = (0, compositePayoffCompiler_1.performStructuralBacktest)('AAPL', 'call');
            (0, vitest_1.expect)(results.passed + results.failed).toBe(results.scenarioCount);
        });
        (0, vitest_1.it)('should have confidence = passed / scenarioCount', function () {
            var results = (0, compositePayoffCompiler_1.performStructuralBacktest)('AAPL', 'call');
            var expectedConfidence = results.passed / results.scenarioCount;
            (0, vitest_1.expect)(results.confidence).toBeCloseTo(expectedConfidence, 5);
        });
        (0, vitest_1.it)('should have confidence >= MIN_CONFIDENCE_THRESHOLD', function () {
            var results = (0, compositePayoffCompiler_1.performStructuralBacktest)('AAPL', 'call');
            (0, vitest_1.expect)(results.confidence).toBeGreaterThanOrEqual(payoffDSL_1.MIN_CONFIDENCE_THRESHOLD);
        });
        (0, vitest_1.it)('should produce realistic PnL bounds', function () {
            var results = (0, compositePayoffCompiler_1.performStructuralBacktest)('AAPL', 'call');
            (0, vitest_1.expect)(results.maxLoss).toBeLessThan(0);
            (0, vitest_1.expect)(results.maxGain).toBeGreaterThan(0);
            (0, vitest_1.expect)(results.maxGain).toBeGreaterThan(Math.abs(results.maxLoss) * 0.5);
        });
    });
    // ===== BACKTEST INCLUSION TESTS =====
    (0, vitest_1.describe)('composeProgram - backtest inclusion', function () {
        (0, vitest_1.it)('should include backtest results in compiled instrument', function () {
            var _a, _b;
            var riskSpec = createBasicRiskSpec();
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument.backtestResults).toBeDefined();
            (0, vitest_1.expect)((_a = result.instrument.backtestResults) === null || _a === void 0 ? void 0 : _a.scenarioCount).toBeGreaterThanOrEqual(payoffDSL_1.MIN_SCENARIO_COUNT);
            (0, vitest_1.expect)((_b = result.instrument.backtestResults) === null || _b === void 0 ? void 0 : _b.confidence).toBeGreaterThanOrEqual(payoffDSL_1.MIN_CONFIDENCE_THRESHOLD);
        });
        (0, vitest_1.it)('should not return valid=true if backtest confidence is too low', function () {
            var riskSpec = createBasicRiskSpec();
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            if (result.instrument.backtestResults.confidence < payoffDSL_1.MIN_CONFIDENCE_THRESHOLD) {
                (0, vitest_1.expect)(result.isValid).toBe(false);
                (0, vitest_1.expect)(result.errors.length).toBeGreaterThan(0);
            }
        });
    });
    // ===== ALLOWLIST VALIDATION TESTS =====
    (0, vitest_1.describe)('composeProgram - allowlist validation', function () {
        (0, vitest_1.it)('should mark instrument as allowlisted for valid type', function () {
            var riskSpec = createBasicRiskSpec({
                description: 'Call spread'
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument.isAllowlisted).toBe(true);
        });
        (0, vitest_1.it)('should include all instrument types in allowlist', function () {
            var types = ['call', 'put', 'spread', 'collar', 'ramp', 'reinstatement'];
            types.forEach(function (type) {
                (0, vitest_1.expect)(payoffDSL_1.INSTRUMENT_ALLOWLIST).toContain(type);
            });
        });
        (0, vitest_1.it)('should generate error if instrument type is not allowlisted', function () {
            var riskSpec = createBasicRiskSpec();
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            if (!payoffDSL_1.INSTRUMENT_ALLOWLIST.includes(result.instrument.type)) {
                (0, vitest_1.expect)(result.errors.some(function (e) { return e.includes('not in allowlist'); })).toBe(true);
            }
        });
    });
    // ===== ASSERTCOMPOSABLE VALIDATION TESTS =====
    (0, vitest_1.describe)('assertComposable - fail-closed validation', function () {
        (0, vitest_1.it)('should throw if instrument is not allowlisted', function () {
            var riskSpec = createBasicRiskSpec();
            var instrument = __assign(__assign({}, createBasicRiskSpec().vectors[0]), { id: 'test-1', type: 'call', underlying: 'TEST', payoff: { strikes: [100], weights: [1.0], type: 'call' }, horizon: 'perpetual', rationale: 'test', isAllowlisted: false, backtestResults: {
                    scenarioCount: 250,
                    passed: 235,
                    failed: 15,
                    avgPnL: 500,
                    maxLoss: -2000,
                    maxGain: 5000,
                    confidence: 0.94
                } });
            (0, vitest_1.expect)(function () { return (0, compositePayoffCompiler_1.assertComposable)(riskSpec, instrument); }).toThrow(/not in allowlist/);
        });
        (0, vitest_1.it)('should throw if backtest confidence is below threshold', function () {
            var riskSpec = createBasicRiskSpec();
            var instrument = __assign(__assign({}, createBasicRiskSpec().vectors[0]), { id: 'test-2', type: 'call', underlying: 'TEST', payoff: { strikes: [100], weights: [1.0], type: 'call' }, horizon: 'perpetual', rationale: 'test', isAllowlisted: true, backtestResults: {
                    scenarioCount: 250,
                    passed: 200,
                    failed: 50,
                    avgPnL: 500,
                    maxLoss: -2000,
                    maxGain: 5000,
                    confidence: 0.8
                } });
            (0, vitest_1.expect)(function () { return (0, compositePayoffCompiler_1.assertComposable)(riskSpec, instrument); }).toThrow(/confidence.*below threshold/);
        });
        (0, vitest_1.it)('should throw if instrument has no backtest results', function () {
            var riskSpec = createBasicRiskSpec();
            var instrument = __assign(__assign({}, createBasicRiskSpec().vectors[0]), { id: 'test-3', type: 'call', underlying: 'TEST', payoff: { strikes: [100], weights: [1.0], type: 'call' }, horizon: 'perpetual', rationale: 'test', isAllowlisted: true, backtestResults: undefined });
            (0, vitest_1.expect)(function () { return (0, compositePayoffCompiler_1.assertComposable)(riskSpec, instrument); }).toThrow(/backtest results/);
        });
        (0, vitest_1.it)('should throw if backtest scenario count is below minimum', function () {
            var riskSpec = createBasicRiskSpec();
            var instrument = __assign(__assign({}, createBasicRiskSpec().vectors[0]), { id: 'test-4', type: 'call', underlying: 'TEST', payoff: { strikes: [100], weights: [1.0], type: 'call' }, horizon: 'perpetual', rationale: 'test', isAllowlisted: true, backtestResults: {
                    scenarioCount: 50,
                    passed: 45,
                    failed: 5,
                    avgPnL: 500,
                    maxLoss: -2000,
                    maxGain: 5000,
                    confidence: 0.9
                } });
            (0, vitest_1.expect)(function () { return (0, compositePayoffCompiler_1.assertComposable)(riskSpec, instrument); }).toThrow(/scenario count.*below minimum/);
        });
        (0, vitest_1.it)('should not throw for valid instrument', function () {
            var riskSpec = createBasicRiskSpec();
            var instrument = __assign(__assign({}, createBasicRiskSpec().vectors[0]), { id: 'test-5', type: 'call', underlying: 'TEST', payoff: { strikes: [100], weights: [1.0], type: 'call' }, horizon: 'perpetual', rationale: 'test', isAllowlisted: true, backtestResults: {
                    scenarioCount: 250,
                    passed: 235,
                    failed: 15,
                    avgPnL: 500,
                    maxLoss: -2000,
                    maxGain: 5000,
                    confidence: 0.94
                } });
            (0, vitest_1.expect)(function () { return (0, compositePayoffCompiler_1.assertComposable)(riskSpec, instrument); }).not.toThrow();
        });
    });
    // ===== EDGE CASES AND ERROR HANDLING =====
    (0, vitest_1.describe)('composeProgram - error handling', function () {
        (0, vitest_1.it)('should return error if risk spec has no vectors', function () {
            var riskSpec = createBasicRiskSpec({
                vectors: []
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.isValid).toBe(false);
            (0, vitest_1.expect)(result.errors.length).toBeGreaterThan(0);
            (0, vitest_1.expect)(result.errors[0]).toContain('at least one risk vector');
        });
        (0, vitest_1.it)('should handle multiple risk vectors', function () {
            var riskSpec = createBasicRiskSpec({
                vectors: [
                    {
                        underlying: 'AAPL',
                        type: 'equity',
                        strike: 150,
                        spot: 145,
                        maturity: 30,
                        notional: 100000
                    },
                    {
                        underlying: 'MSFT',
                        type: 'equity',
                        strike: 350,
                        spot: 340,
                        maturity: 30,
                        notional: 100000
                    },
                ]
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument).toBeDefined();
            (0, vitest_1.expect)(result.instrument.underlying).toBe('AAPL');
        });
        (0, vitest_1.it)('should handle risk specs without strike prices', function () {
            var riskSpec = createBasicRiskSpec({
                vectors: [
                    {
                        underlying: 'EURUSD',
                        type: 'fx',
                        spot: 1.1,
                        notional: 100000
                    },
                ]
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument).toBeDefined();
            (0, vitest_1.expect)(result.instrument.payoff.strikes).toHaveLength(0);
        });
    });
    // ===== DISCRETE SELECTION SPECIFIC TESTS =====
    (0, vitest_1.describe)('composeProgram - discrete selection with cost delta', function () {
        (0, vitest_1.it)('should select discrete and show cost savings', function () {
            var riskSpec = createBasicRiskSpec({
                description: 'Temporary hedge call',
                fundingCost: 100,
                oneOffCost: 60,
                carry: 5
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument.horizon).toBe('discrete');
            (0, vitest_1.expect)(result.instrument.costDelta).toBe(-40);
            (0, vitest_1.expect)(result.instrument.rationale).toContain('cost');
        });
        (0, vitest_1.it)('should include cost delta in rationale for discrete', function () {
            var riskSpec = createBasicRiskSpec({
                fundingCost: 50,
                oneOffCost: 30,
                horizon: 'discrete'
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument.rationale).toContain('one-off');
            (0, vitest_1.expect)(result.instrument.rationale).toContain('bps');
        });
        (0, vitest_1.it)('should reject discrete selection if backtest fails', function () {
            var riskSpec = createBasicRiskSpec({
                fundingCost: 50,
                oneOffCost: 30
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            if (result.instrument.backtestResults.confidence < payoffDSL_1.MIN_CONFIDENCE_THRESHOLD) {
                (0, vitest_1.expect)(result.isValid).toBe(false);
            }
        });
    });
    // ===== GENERATERATIONALE DIRECT TESTS =====
    (0, vitest_1.describe)('generateRationale - direct function tests', function () {
        (0, vitest_1.it)('should generate rationale for discrete horizon with cost delta', function () {
            var rationale = (0, compositePayoffCompiler_1.generateRationale)('discrete', -40, 100, 10);
            (0, vitest_1.expect)(rationale).toContain('Discrete');
            (0, vitest_1.expect)(rationale).toContain('one-off cost');
            (0, vitest_1.expect)(rationale).toContain('-40.00bps');
            (0, vitest_1.expect)(rationale).toContain('100.00bps');
        });
        (0, vitest_1.it)('should generate rationale for perpetual horizon with carry', function () {
            var rationale = (0, compositePayoffCompiler_1.generateRationale)('perpetual', -40, 50, 25);
            (0, vitest_1.expect)(rationale).toContain('Perpetual');
            (0, vitest_1.expect)(rationale).toContain('funding carry');
            (0, vitest_1.expect)(rationale).toContain('25.00bps');
            (0, vitest_1.expect)(rationale).toContain('50.00bps');
        });
        (0, vitest_1.it)('should format cost values as basis points', function () {
            var rationale = (0, compositePayoffCompiler_1.generateRationale)('discrete', 123.456, 200, 50);
            (0, vitest_1.expect)(rationale).toMatch(/123\.46bps/);
            (0, vitest_1.expect)(rationale).toMatch(/200\.00bps/);
        });
        (0, vitest_1.it)('should handle undefined cost delta', function () {
            var rationale = (0, compositePayoffCompiler_1.generateRationale)('discrete', undefined, 50, 10);
            (0, vitest_1.expect)(rationale).toContain('one-off cost');
            (0, vitest_1.expect)(rationale).toContain('undefinedBps');
        });
    });
    // ===== EDGE CASES FOR COST DELTA =====
    (0, vitest_1.describe)('composeProgram - cost delta edge cases', function () {
        (0, vitest_1.it)('should calculate cost delta as difference when both costs exist', function () {
            var riskSpec = createBasicRiskSpec({
                fundingCost: 100,
                oneOffCost: 60
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument.costDelta).toBe(-40);
        });
        (0, vitest_1.it)('should use oneOffCost as costDelta when fundingCost is undefined', function () {
            var riskSpec = createBasicRiskSpec({
                fundingCost: undefined,
                oneOffCost: 75
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument.costDelta).toBe(75);
        });
        (0, vitest_1.it)('should not set costDelta when oneOffCost is undefined', function () {
            var riskSpec = createBasicRiskSpec({
                fundingCost: 50,
                oneOffCost: undefined
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument.costDelta).toBeUndefined();
        });
        (0, vitest_1.it)('should handle zero cost values', function () {
            var riskSpec = createBasicRiskSpec({
                fundingCost: 0,
                oneOffCost: 50
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument.costDelta).toBe(50);
        });
        (0, vitest_1.it)('should handle negative cost delta (perpetual more expensive)', function () {
            var riskSpec = createBasicRiskSpec({
                fundingCost: 30,
                oneOffCost: 100
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument.costDelta).toBe(70);
            (0, vitest_1.expect)(result.instrument.horizon).toBe('perpetual');
        });
    });
    // ===== RISK VECTOR TYPE SPECIFIC TESTS =====
    (0, vitest_1.describe)('composeProgram - risk vector types', function () {
        (0, vitest_1.it)('should handle rate risk vectors', function () {
            var riskSpec = createBasicRiskSpec({
                description: 'Interest rate call collar',
                vectors: [
                    {
                        underlying: 'SONIA',
                        type: 'rate',
                        spot: 0.05,
                        maturity: 365,
                        notional: 10000000
                    },
                ]
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument).toBeDefined();
            (0, vitest_1.expect)(result.instrument.type).toBe('collar');
        });
        (0, vitest_1.it)('should handle volatility risk vectors', function () {
            var riskSpec = createBasicRiskSpec({
                description: 'VIX volatility put',
                vectors: [
                    {
                        underlying: 'VIX',
                        type: 'volatility',
                        spot: 25,
                        maturity: 30,
                        notional: 1000
                    },
                ]
            });
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument).toBeDefined();
            (0, vitest_1.expect)(result.instrument.type).toBe('put');
        });
    });
    // ===== BOUNDARY CONDITION TESTS =====
    (0, vitest_1.describe)('assertComposable - boundary conditions', function () {
        (0, vitest_1.it)('should accept instrument at exact MIN_CONFIDENCE_THRESHOLD', function () {
            var riskSpec = createBasicRiskSpec();
            var instrument = __assign(__assign({}, createBasicRiskSpec().vectors[0]), { id: 'test-boundary-1', type: 'call', underlying: 'TEST', payoff: { strikes: [100], weights: [1.0], type: 'call' }, horizon: 'perpetual', rationale: 'test', isAllowlisted: true, backtestResults: {
                    scenarioCount: 100,
                    passed: Math.round(100 * payoffDSL_1.MIN_CONFIDENCE_THRESHOLD),
                    failed: 100 - Math.round(100 * payoffDSL_1.MIN_CONFIDENCE_THRESHOLD),
                    avgPnL: 500,
                    maxLoss: -2000,
                    maxGain: 5000,
                    confidence: payoffDSL_1.MIN_CONFIDENCE_THRESHOLD
                } });
            (0, vitest_1.expect)(function () { return (0, compositePayoffCompiler_1.assertComposable)(riskSpec, instrument); }).not.toThrow();
        });
        (0, vitest_1.it)('should accept instrument at exact MIN_SCENARIO_COUNT', function () {
            var riskSpec = createBasicRiskSpec();
            var instrument = __assign(__assign({}, createBasicRiskSpec().vectors[0]), { id: 'test-boundary-2', type: 'call', underlying: 'TEST', payoff: { strikes: [100], weights: [1.0], type: 'call' }, horizon: 'perpetual', rationale: 'test', isAllowlisted: true, backtestResults: {
                    scenarioCount: payoffDSL_1.MIN_SCENARIO_COUNT,
                    passed: Math.round(payoffDSL_1.MIN_SCENARIO_COUNT * 0.9),
                    failed: payoffDSL_1.MIN_SCENARIO_COUNT - Math.round(payoffDSL_1.MIN_SCENARIO_COUNT * 0.9),
                    avgPnL: 500,
                    maxLoss: -2000,
                    maxGain: 5000,
                    confidence: 0.9
                } });
            (0, vitest_1.expect)(function () { return (0, compositePayoffCompiler_1.assertComposable)(riskSpec, instrument); }).not.toThrow();
        });
        (0, vitest_1.it)('should reject instrument just below MIN_CONFIDENCE_THRESHOLD', function () {
            var riskSpec = createBasicRiskSpec();
            var instrument = __assign(__assign({}, createBasicRiskSpec().vectors[0]), { id: 'test-boundary-3', type: 'call', underlying: 'TEST', payoff: { strikes: [100], weights: [1.0], type: 'call' }, horizon: 'perpetual', rationale: 'test', isAllowlisted: true, backtestResults: {
                    scenarioCount: 250,
                    passed: 211,
                    failed: 39,
                    avgPnL: 500,
                    maxLoss: -2000,
                    maxGain: 5000,
                    confidence: payoffDSL_1.MIN_CONFIDENCE_THRESHOLD - 0.001
                } });
            (0, vitest_1.expect)(function () { return (0, compositePayoffCompiler_1.assertComposable)(riskSpec, instrument); }).toThrow(/confidence.*below threshold/);
        });
        (0, vitest_1.it)('should reject instrument just below MIN_SCENARIO_COUNT', function () {
            var riskSpec = createBasicRiskSpec();
            var instrument = __assign(__assign({}, createBasicRiskSpec().vectors[0]), { id: 'test-boundary-4', type: 'call', underlying: 'TEST', payoff: { strikes: [100], weights: [1.0], type: 'call' }, horizon: 'perpetual', rationale: 'test', isAllowlisted: true, backtestResults: {
                    scenarioCount: payoffDSL_1.MIN_SCENARIO_COUNT - 1,
                    passed: payoffDSL_1.MIN_SCENARIO_COUNT - 11,
                    failed: 10,
                    avgPnL: 500,
                    maxLoss: -2000,
                    maxGain: 5000,
                    confidence: 0.9
                } });
            (0, vitest_1.expect)(function () { return (0, compositePayoffCompiler_1.assertComposable)(riskSpec, instrument); }).toThrow(/scenario count.*below minimum/);
        });
    });
    // ===== FULL INTEGRATION TESTS =====
    (0, vitest_1.describe)('End-to-end compilation workflow', function () {
        (0, vitest_1.it)('should compile a valid equity hedge from risk description', function () {
            var _a;
            var riskSpec = {
                description: 'Downside protection put collar on tech portfolio',
                vectors: [
                    {
                        underlying: 'QQQ',
                        type: 'equity',
                        strike: 350,
                        spot: 360,
                        maturity: 90,
                        notional: 1000000
                    },
                ],
                horizon: 'perpetual',
                fundingCost: 75,
                oneOffCost: 120,
                carry: 20
            };
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.isValid).toBe(true);
            (0, vitest_1.expect)(result.instrument.type).toBe('collar');
            (0, vitest_1.expect)(result.instrument.underlying).toBe('QQQ');
            (0, vitest_1.expect)(result.instrument.horizon).toMatch(/^(perpetual|discrete)$/);
            (0, vitest_1.expect)((_a = result.instrument.backtestResults) === null || _a === void 0 ? void 0 : _a.confidence).toBeGreaterThanOrEqual(payoffDSL_1.MIN_CONFIDENCE_THRESHOLD);
            (0, vitest_1.expect)(result.instrument.isAllowlisted).toBe(true);
        });
        (0, vitest_1.it)('should handle FX risk specs', function () {
            var riskSpec = {
                description: 'EURUSD currency hedge call',
                vectors: [
                    {
                        underlying: 'EURUSD',
                        type: 'fx',
                        spot: 1.08,
                        maturity: 60,
                        notional: 5000000
                    },
                ],
                horizon: 'discrete',
                oneOffCost: 45,
                fundingCost: 30
            };
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument).toBeDefined();
            (0, vitest_1.expect)(result.instrument.type).toBe('call');
            (0, vitest_1.expect)(result.instrument.underlying).toBe('EURUSD');
        });
        (0, vitest_1.it)('should handle commodity risk specs', function () {
            var riskSpec = {
                description: 'Oil price ramp hedge',
                vectors: [
                    {
                        underlying: 'WTI',
                        type: 'commodity',
                        strike: 80,
                        spot: 85,
                        maturity: 180,
                        notional: 100000
                    },
                ],
                horizon: 'perpetual',
                fundingCost: 50,
                carry: 15
            };
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument.type).toBe('ramp');
            (0, vitest_1.expect)(result.instrument.underlying).toBe('WTI');
        });
        (0, vitest_1.it)('should assert composability on successfully compiled instrument', function () {
            var riskSpec = createBasicRiskSpec();
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            if (result.isValid) {
                (0, vitest_1.expect)(function () { return (0, compositePayoffCompiler_1.assertComposable)(riskSpec, result.instrument); }).not.toThrow();
            }
        });
        (0, vitest_1.it)('should reject un-backtested composite through assertComposable', function () {
            var riskSpec = createBasicRiskSpec();
            var instrument = {
                id: 'unbacked-1',
                type: 'spread',
                underlying: 'UNBACKED',
                payoff: { strikes: [100], weights: [1.0], type: 'spread' },
                horizon: 'perpetual',
                rationale: 'No backtest',
                isAllowlisted: true,
                backtestResults: undefined
            };
            (0, vitest_1.expect)(function () { return (0, compositePayoffCompiler_1.assertComposable)(riskSpec, instrument); }).toThrow(/backtest results/);
        });
        (0, vitest_1.it)('should encode full decision path in rationale', function () {
            var riskSpec = {
                description: 'One-off equity hedge call',
                vectors: [
                    {
                        underlying: 'MSFT',
                        type: 'equity',
                        strike: 400,
                        spot: 395,
                        maturity: 30,
                        notional: 500000
                    },
                ],
                horizon: 'discrete',
                fundingCost: 80,
                oneOffCost: 50,
                carry: 5
            };
            var result = (0, compositePayoffCompiler_1.composeProgram)(riskSpec);
            (0, vitest_1.expect)(result.instrument.rationale).toContain('Discrete');
            (0, vitest_1.expect)(result.instrument.rationale).toContain('one-off');
            (0, vitest_1.expect)(result.instrument.rationale).toContain('80');
            (0, vitest_1.expect)(result.instrument.rationale).toContain('bps');
        });
    });
});
