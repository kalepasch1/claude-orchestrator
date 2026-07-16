import { describe, expect, it } from 'vitest'
import {
  aggregateRegulatoryFeedback,
  calculateEvidencePortability,
  compileSafeHarbor,
  createCausalityReceipt,
  matchSupervisoryCapacity,
  rankRegulatoryCounterfactuals,
  simulateRegulatoryIncident,
} from './regulatoryOpportunity'

describe('regulatory opportunity network', () => {
  it('proposes the smallest high-value lawful-market unlock', () => {
    const result = rankRegulatoryCounterfactuals({ activity: 'money_transmission', jurisdictions: ['NY','CA','TX'], market_value_cents: 9_000_000, confidence: .8 })
    expect(result.recommended.proposed_change.kind).toBe('provider_controlled_flow')
    expect(result.recommended.retained_capabilities).toContain('checkout_experience')
    expect(result.recommended.expected_value_cents).toBeGreaterThan(result.recommended.direct_cost_cents)
    expect(result.recommended.qa_plan).toContain('authority_receipt')
  })

  it('reuses verified evidence while preserving consent boundaries', () => {
    const result = calculateEvidencePortability({ organization_id: 'target', evidence: [{ kind: 'operating_history', digest: 'a', verified: true, preparation_days: 30 }, { kind: 'local_bond', digest: 'b', verified: true }, { kind: 'policy', digest: 'c', verified: true, owner_org_id: 'source' }] })
    expect(result.portable_evidence).toHaveLength(2)
    expect(result.nonportable_requirements[0].reason).toContain('jurisdiction')
    expect(result.consent_requirements).toHaveLength(1)
  })

  it('keeps shared feedback shadowed below its privacy cohort', () => {
    const small = aggregateRegulatoryFeedback({ outcomes: Array.from({ length: 7 }, (_, i) => ({ domain: 'payments', jurisdiction: 'NY', finding_code: 'aml', result: 'finding', organization_digest: `o${i}` })) })
    const enough = aggregateRegulatoryFeedback({ outcomes: Array.from({ length: 8 }, (_, i) => ({ domain: 'payments', jurisdiction: 'NY', finding_code: 'aml', result: 'finding', organization_digest: `o${i}` })) })
    expect(small[0].privacy_threshold_met).toBe(false)
    expect(enough[0].privacy_threshold_met).toBe(true)
    expect(enough[0].bounded_pattern.raw_examples_exposed).toBe(false)
  })

  it('matches supervisory capacity without silently activating it', () => {
    const matches = matchSupervisoryCapacity({ offers: [{ id: 'a', status: 'available', capacity_units: 5, used_units: 1, jurisdictions: ['NY'], capability: 'payments', correlation_score: 20, pricing_model: { base_cents: 100_000 } }], demand: { units: 2, jurisdiction: 'NY', capability: 'payments', readiness_score: 80 } })
    expect(matches[0].requires_affirmative_approval_from).toEqual(['requester','supervising_organization'])
  })

  it('compiles safe-harbor conditions to fail-closed controls', () => {
    const result = compileSafeHarbor({ conditions: [{ key: 'volume_cap', test: 'monthly volume below cap', verified: true }] })
    expect(result.ready).toBe(true)
    expect(result.executable_controls[0].fail_state).toBe('hold_affected_action')
    expect(result.activation_requires_approval).toBe(true)
  })

  it('simulates incidents with lawful fallback before notification', () => {
    const result = simulateRegulatoryIncident({ incident_type: 'sponsor_termination', affected_capabilities: ['payments'], relationships: [{ id: 'r1' }] })
    expect(result.containment_plan[0].action).toContain('fallback')
    expect(result.containment_plan[2].automatic).toBe(false)
  })

  it('creates stable explainable causality receipts', () => {
    const input = { subject_type: 'gate', subject_id: '1', decision: 'hold', causes: [{ reason: 'missing_authority' }] }
    expect(createCausalityReceipt(input).receipt_digest).toBe(createCausalityReceipt(input).receipt_digest)
  })
})
