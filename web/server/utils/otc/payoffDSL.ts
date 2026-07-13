export type RiskVectorType = 'equity' | 'rate' | 'fx' | 'commodity' | 'volatility';
export type HorizonType = 'perpetual' | 'discrete';
export type InstrumentType = 'call' | 'put' | 'spread' | 'collar' | 'ramp' | 'reinstatement';

export interface RiskVector {
  underlying: string;
  type: RiskVectorType;
  strike?: number;
  spot: number;
  maturity?: number;
  notional: number;
}

export interface RiskSpec {
  description: string;
  vectors: RiskVector[];
  horizon: HorizonType;
  fundingCost?: number;
  oneOffCost?: number;
  carry?: number;
}

export interface Payoff {
  strikes: number[];
  weights: number[];
  type: InstrumentType;
}

export interface Instrument {
  id: string;
  type: InstrumentType;
  underlying: string;
  payoff: Payoff;
  horizon: HorizonType;
  costDelta?: number;
  rationale: string;
  backtestResults?: BacktestResult;
  isAllowlisted: boolean;
}

export interface BacktestResult {
  scenarioCount: number;
  passed: number;
  failed: number;
  avgPnL: number;
  maxLoss: number;
  maxGain: number;
  confidence: number;
}

export interface CompilationResult {
  instrument: Instrument;
  isValid: boolean;
  errors: string[];
  warnings: string[];
}

export const INSTRUMENT_ALLOWLIST: InstrumentType[] = [
  'call',
  'put',
  'spread',
  'collar',
  'ramp',
  'reinstatement',
];

function getEnvNumber(key: string, defaultValue: number): number {
  const value = process.env[key];
  if (!value) return defaultValue;
  const parsed = parseFloat(value);
  return isNaN(parsed) ? defaultValue : parsed;
}

function getEnvInt(key: string, defaultValue: number): number {
  const value = process.env[key];
  if (!value) return defaultValue;
  const parsed = parseInt(value, 10);
  return isNaN(parsed) ? defaultValue : parsed;
}

export const MIN_CONFIDENCE_THRESHOLD = getEnvNumber('OTC_MIN_CONFIDENCE_THRESHOLD', 0.85);
export const MIN_SCENARIO_COUNT = getEnvInt('OTC_MIN_SCENARIO_COUNT', 100);
