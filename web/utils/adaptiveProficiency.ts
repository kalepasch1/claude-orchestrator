export type ProficiencyStage = 'guided' | 'practiced' | 'fluent'

export interface ProficiencySignals {
  visits: number
  completedActions: number
  expandedGuidance: number
  advancedUses: number
}

export interface ProficiencyProfile extends ProficiencySignals {
  stage: ProficiencyStage
  score: number
  explanationDepth: 'detailed' | 'balanced' | 'concise'
  showAdvancedByDefault: boolean
}

export const EMPTY_PROFICIENCY: ProficiencySignals = {
  visits: 0,
  completedActions: 0,
  expandedGuidance: 0,
  advancedUses: 0,
}

export function deriveProficiency(signals: ProficiencySignals): ProficiencyProfile {
  const score = Math.min(100, Math.round(
    signals.visits * 3 +
    signals.expandedGuidance * 6 +
    signals.completedActions * 14 +
    signals.advancedUses * 12,
  ))
  const stage: ProficiencyStage = score >= 65 ? 'fluent' : score >= 25 ? 'practiced' : 'guided'
  return {
    ...signals,
    score,
    stage,
    explanationDepth: stage === 'guided' ? 'detailed' : stage === 'practiced' ? 'balanced' : 'concise',
    showAdvancedByDefault: stage === 'fluent' && signals.advancedUses >= 2,
  }
}

