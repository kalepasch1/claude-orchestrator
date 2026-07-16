import { describe, expect, it } from 'vitest'
import {
  attestProductBehavior,
  compileEntityJurisdictionStructure,
  forecastExaminerQuestions,
  measureReviewEffectiveness,
  prepareSupervisoryPacket,
  runLaunchTournament,
  simulateRegulatoryCatastrophe,
  valueRegulatoryOption,
} from './regulatorySovereignty'

describe('regulatory sovereignty network', () => {
  it('fails a product feature closed when a required proof is absent', () => {
    const result = attestProductBehavior({
      required_proofs: ['authority', 'fallback'],
      authority_receipts: [{ valid: true }],
      fallback_receipt: { mode: 'read_only', valid: false },
    })
    expect(result.status).toBe('incomplete')
    expect(result.missing_proofs).toEqual(['fallback'])
    expect(result.effective_behavior).toEqual({ state: 'held', lawful_fallback: 'read_only' })
  })

  it('selects and sequences the quickest lawful structural routes', () => {
    const result = compileEntityJurisdictionStructure({ markets: [
      { jurisdiction: 'GB', license_months: 14, sponsor_available: true, sponsor_months: 2, expected_value_cents: 2_000_000 },
      { jurisdiction: 'DE', license_months: 12, acquisition_available: true, acquisition_months: 6, expected_value_cents: 3_000_000 },
    ] })
    expect(result.jurisdiction_plan.map(x => x.route)).toEqual(['sponsor_then_local_entity', 'acquire_regulated_entity'])
    expect(result.expected_value_cents).toBe(5_000_000)
    expect(result.execution_requires_separate_approvals).toBe(true)
  })

  it('propagates catastrophe dependencies while crediting tested fallbacks', () => {
    const result = simulateRegulatoryCatastrophe({
      shocks: [{ target: 'sponsor' }],
      dependencies: [{ from: 'sponsor', to: 'payments', transmission_probability: .9, exposure_cents: 1_000_000 }],
      fallback_coverage_score: 80,
      available_reserve_cents: 100_000,
    })
    expect(result.affected_capabilities).toContain('payments')
    expect(result.tail_loss_cents).toBe(200_000)
    expect(result.resilience_score).toBeGreaterThan(80)
  })

  it('disqualifies an unsafe launch even when its value is higher', () => {
    const result = runLaunchTournament({ candidates: [
      { key: 'fast', authority_confidence: 100, evidence_completeness: 100, value_score: 100, reversibility_score: 100, critical_events: 1 },
      { key: 'safe', authority_confidence: 90, evidence_completeness: 90, value_score: 65, reversibility_score: 95, critical_events: 0 },
    ] })
    expect(result.winner.key).toBe('safe')
    expect(result.promotion_receipt.promotion_requires_approval).toBe(true)
  })

  it('prepares bounded supervisory work without delegating final judgment', () => {
    const result = prepareSupervisoryPacket({ issues: [{ question: 'Is the authority current?' }], evidence: [] })
    expect(result.recommended_questions).toHaveLength(1)
    expect(result.draft_determination.not_final).toBe(true)
    expect(result.human_judgment_required).toContain('approval_or_signature')
  })

  it('prices the option value of preserved authority paths', () => {
    const result = valueRegulatoryOption({ replacement_cost_cents: 1_000_000, time_to_replace_days: 100, daily_delay_cost_cents: 10_000, annual_carry_cost_cents: 100_000, probability_of_use: .5, enabled_paths: [{ expected_value_cents: 2_000_000 }] })
    expect(result.strategic_option_value_cents).toBe(1_050_000)
    expect(result.preservation_actions).toContain('refresh_evidence')
  })

  it('forecasts examiner questions from current evidence and change gaps', () => {
    const result = forecastExaminerQuestions({ missing_evidence: [{ key: 'complaints', label: 'complaint log' }], material_changes: [{ feature: 'credit', authority_receipt: null }], verified_inputs: 8 })
    expect(result.predicted_questions.some(x => x.question.includes('complaint log'))).toBe(true)
    expect(result.likely_findings).toContainEqual(expect.objectContaining({ code: 'change_without_authority_receipt' }))
    expect(result.confidence).toBeGreaterThan(.5)
  })

  it('measures whether review effort changed risk, value, and approval odds', () => {
    const result = measureReviewEffectiveness({ minutes_spent: 30, risk_before: 80, risk_after: 40, value_before_cents: 0, value_after_cents: 500_000, approval_probability_before: .3, approval_probability_after: .8 })
    expect(result.effectiveness_score).toBeGreaterThan(40)
    expect(result.lessons).toContain('review_unlocked_value')
  })
})
