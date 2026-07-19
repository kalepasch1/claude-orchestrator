/**
 * quarantineBinning.ts — Root-cause binning for quarantined tests.
 * Stub: categorizes test failures into bins for auto-recovery.
 */
export type FailureBin = 'flaky' | 'infra' | 'regression' | 'unknown'

export interface BinResult {
  testId: string
  bin: FailureBin
  confidence: number
}

export function binFailure(testId: string, consecutiveFails: number, infraError: boolean): BinResult {
  if (infraError) return { testId, bin: 'infra', confidence: 0.9 }
  if (consecutiveFails === 1) return { testId, bin: 'flaky', confidence: 0.7 }
  if (consecutiveFails >= 3) return { testId, bin: 'regression', confidence: 0.8 }
  return { testId, bin: 'unknown', confidence: 0.3 }
}
