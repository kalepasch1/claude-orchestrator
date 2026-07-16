import { describe, expect, it } from 'vitest'
import {
  calculateContractNetworkRisk,
  compileDisputePrevention,
  detectAuthorityDrift,
  evaluateAuthorityGate,
  modelRegulatedEntityAcquisition,
  optimizeRegulatoryCapital,
  optimizeRegulatoryWorldlines,
  rehearseRegulatoryExamination,
} from './regulatoryFrontier'

describe('regulatory frontier intelligence', () => {
  it('ranks worldlines with explainable timing and cost', () => {
    const result = optimizeRegulatoryWorldlines({ jurisdictions: ['NY','CA'], readiness_score: 55, verified_inputs: 6 })
    expect(result.recommended.score).toBeGreaterThan(0)
    expect(result.alternatives.length).toBeGreaterThan(1)
    expect(result.uncertainty.confidence).toBeGreaterThan(.5)
  })

  it('finds concentrated contract-network exposure', () => {
    const result = calculateContractNetworkRisk({ nodes: [{ id: 'a' }, { id: 'b' }], edges: [{ to: 'a', exposure_cents: 900 }, { to: 'b', exposure_cents: 100 }] })
    expect(result.concentration_score).toBe(90)
    expect(result.mitigations).toContain('add_redundant_provider')
  })

  it('rehearses an adversarial examination', () => {
    const result = rehearseRegulatoryExamination({ completeness_score: 70, freshness_score: 65, contradiction_count: 1, overdue_obligations: 1 })
    expect(result.findings.length).toBe(4)
    expect(result.predicted_result).not.toBe('ready_for_review')
  })

  it('models acquisition and regulatory capital outcomes', () => {
    expect(modelRegulatedEntityAcquisition({ purchase_price_cents: 100, estimated_liabilities_cents: 50, integration_cost_cents: 25, transferability_score: 50 }).all_in_cost_cents).toBe(175)
    expect(optimizeRegulatoryCapital({ monthly_volume_cents: 1_000_000, minimum_capital_cents: 100_000 }).target_capital_cents).toBeGreaterThan(100_000)
  })

  it('turns contract ambiguity into preventative controls', () => {
    const result = compileDisputePrevention({ terms: ['Use reasonable efforts to deliver promptly.'] })
    expect(result.ambiguity_score).toBeGreaterThan(0)
    expect(result.missing_controls).toContain('acceptance_criteria')
    expect(result.evidence_schedule.madeus_retains).toContain('bounded')
  })

  it('holds deployment when authority proof is incomplete', () => {
    expect(evaluateAuthorityGate({ requested_capabilities: [{ key: 'payments' }], authority_evidence: {} }).decision).toBe('hold')
    expect(evaluateAuthorityGate({ requested_capabilities: [{ key: 'payments' }], authority_evidence: { payments: { verified: true } } }).decision).toBe('allow')
    expect(evaluateAuthorityGate({ requested_capabilities: [{ key: 'payments' }], authority_evidence: { payments: { prohibited: true } } }).decision).toBe('block')
  })

  it('contains material primary-authority drift', () => {
    const result = detectAuthorityDrift({ prior_digest: 'old', current_digest: 'new', dependencies: [{ rule_key: 'r1', project_ref: 'p1', enforced: true }] })
    expect(result.materiality).toBe('material')
    expect(result.containment_action).toContain('hold')
  })
})
