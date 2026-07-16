import { describe, expect, it } from 'vitest'
import { buildPrivacyPassport, coordinateTransactionAuthority, createRuntimeComplianceReceipt, estimateCausalRegulatoryEffect, forecastSupervisoryCapacity, matchRegulatoryCounterparty, reconcileProviderSwarm, simulateCustomerOutcomes } from './regulatoryProofMarket'

describe('regulatory proof market', () => {
  it('creates commitments while disclosing only selected claims', () => {
    const result = buildPrivacyPassport({ purpose: 'sponsor diligence', expires_at: new Date(Date.now() + 864e5).toISOString(), claims: [{ key: 'training_complete', value: true, disclose: true }, { key: 'capital_amount', value: 1000000, disclose: false }] })
    expect(result.claim_commitments).toHaveLength(2)
    expect(result.disclosed_proofs).toHaveLength(1)
    expect(JSON.stringify(result.claim_commitments)).not.toContain('1000000')
    expect(result.evidence_retention.raw_evidence_copied).toBe(false)
  })

  it('holds or reroutes a transaction when required proof is missing', () => {
    const held = coordinateTransactionAuthority({ requirements: [{ key: 'license', type: 'authority' }], proofs: {} })
    expect(held.decision).toBe('hold')
    const rerouted = coordinateTransactionAuthority({ requirements: [{ key: 'license', type: 'authority' }], proofs: {}, fallback_route: 'unregulated_information_only' })
    expect(rerouted.decision).toBe('reroute')
  })

  it('selects an eligible counterparty without performing an introduction', () => {
    const result = matchRegulatoryCounterparty({ candidates: [{ key: 'a', authority_score: 95, capacity_fit: 90, risk_score: 10, price_score: 30 }, { key: 'b', authority_score: 100, capacity_fit: 100, authority_valid: false }] })
    expect(result.recommended_match.candidate_ref).toBe('a')
    expect(result.recommended_match.requires_affirmative_introduction).toBe(true)
  })

  it('escalates multi-provider disagreement or material gaps', () => {
    const result = reconcileProviderSwarm({ provider_assessments: [{ provider: 'a', recommendation: 'allow', confidence: .9 }, { provider: 'b', recommendation: 'hold', confidence: .85, material_gaps: ['missing_order'] }] })
    expect(result.human_review_required).toBe(true)
    expect(result.material_gaps).toContain('missing_order')
  })

  it('does not make a causal claim from weak observational evidence', () => {
    const weak = estimateCausalRegulatoryEffect({ treated_outcomes: [1, 1], comparison_outcomes: [0, 0], confounders: ['selection'] })
    expect(weak.estimated_effect.causal_claim_allowed).toBe(false)
    const strong = estimateCausalRegulatoryEffect({ treated_outcomes: Array(12).fill(1), comparison_outcomes: Array(12).fill(0), confounders: [] })
    expect(strong.estimated_effect.causal_claim_allowed).toBe(true)
  })

  it('holds a customer outcome twin when disparity exceeds its threshold', () => {
    const result = simulateCustomerOutcomes({ segments: [{ key: 'a', adjustment: 20 }, { key: 'b', adjustment: -20 }], scenarios: [{ key: 'base', approval_rate: 60, access_score: 70, error_rate: 1 }], max_approval_disparity: 15 })
    expect(result.launch_recommendation).toBe('hold_for_mitigation')
    expect(result.disparity_findings[0]).toEqual(expect.objectContaining({ metric: 'approval_rate' }))
  })

  it('creates a chain-bound deterministic compliance receipt', () => {
    const input = { transaction_ref: 'tx-1', authority_ref: 'auth-1', agreement_ref: 'agr-1', policy_inputs: { amount: 10 }, decision: { allow: true }, receipt_chain_prev: 'prior' }
    const one = createRuntimeComplianceReceipt(input); const two = createRuntimeComplianceReceipt(input)
    expect(one.receipt_digest).toBe(two.receipt_digest)
    expect(one.verification_manifest.chain_bound).toBe(true)
  })

  it('forecasts supervisory shortages as permissioned capacity reservations', () => {
    const result = forecastSupervisoryCapacity({ periods: [{ period: 'Q1', expected_cases: 10, minutes_per_case: 60, available_minutes: 300 }], reservation_options: [{ provider: 'counsel', minutes: 300, cost_cents: 500000 }] })
    expect(result.forecast.total_shortage_minutes).toBe(300)
    expect(result.status).toBe('permission_required')
    expect(result.risk_transfer_terms.financial_derivative).toBe(false)
  })
})
