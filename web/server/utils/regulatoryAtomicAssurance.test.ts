import { describe, expect, it } from 'vitest'
import { attributeRegulatoryLiability, compileRegulatoryUnitEconomics, derivePurposeConsent, evaluateProofChallenge, prepareAtomicRegulatoryTransaction, prepareCustomerRemedy, scoreCapacityReliability, verifyZkEnvelope } from './regulatoryAtomicAssurance'
import { createHash } from 'node:crypto'

const digest = (value: any) => createHash('sha256').update(JSON.stringify(value)).digest('hex')

describe('regulatory atomic assurance', () => {
  it('fails ZK verification closed without an active audited verifier', () => {
    const publicInputs = { threshold: 100 }
    const invalid = verifyZkEnvelope({ predicate: 'balance_gte', proof_digest: 'p', public_inputs: publicInputs, verifier: { status: 'shadow', verifier_digest: 'v', audit_manifest: { approved: true } }, verification_result: { valid: true, verifier_digest: 'v', proof_digest: 'p', predicate: 'balance_gte', public_inputs_digest: digest(publicInputs) } })
    expect(invalid.status).toBe('invalid')
    const valid = verifyZkEnvelope({ predicate: 'balance_gte', proof_digest: 'p', public_inputs: publicInputs, verifier: { status: 'active', verifier_digest: 'v', audit_manifest: { approved: true } }, verification_result: { valid: true, verifier_digest: 'v', proof_digest: 'p', predicate: 'balance_gte', public_inputs_digest: digest(publicInputs) } })
    expect(valid.status).toBe('valid')
  })

  it('holds the entire transaction if any atomic precondition fails', () => {
    const result = prepareAtomicRegulatoryTransaction({ steps: [{ key: 'authorize' }, { key: 'settle' }], preconditions: [{ key: 'license', satisfied: true }, { key: 'consent', satisfied: false }] })
    expect(result.status).toBe('held')
    expect(result.authorization_result.missing).toEqual(['consent'])
    expect(result.compensation_plan.map(x => x.step)).toEqual(['settle','authorize'])
  })

  it('allows inherited consent only to narrow purpose, action, and expiry', () => {
    const result = derivePurposeConsent({ parent: { id: 'p', purposes: ['exam'], allowed_actions: ['read'], expires_at: '2030-01-01T00:00:00.000Z' }, purposes: ['exam','marketing'], allowed_actions: ['read','write'], expires_at: '2031-01-01T00:00:00.000Z' })
    expect(result.purposes).toEqual(['exam'])
    expect(result.allowed_actions).toEqual(['read'])
    expect(result.expires_at).toBe('2030-01-01T00:00:00.000Z')
  })

  it('rewards validated proof defects but not unsuccessful challenges', () => {
    const found = evaluateProofChallenge({ nonce_reused: true, signature_valid: false, reward_per_finding_cents: 5000 })
    expect(found.status).toBe('validated')
    expect(found.reward_cents).toBe(10000)
    expect(found.resolution.human_review_required).toBe(true)
    expect(evaluateProofChallenge({ signature_valid: true }).reward_cents).toBe(0)
  })

  it('allocates remediation cost using evidence-weighted causal contribution', () => {
    const result = attributeRegulatoryLiability({ remediation_cost_cents: 100000, contributors: [{ ref: 'model', type: 'model', causal_weight: .6, evidence_confidence: 1 }, { ref: 'approval', type: 'human', causal_weight: .4, evidence_confidence: 1, contractually_recoverable: true }] })
    expect(result.allocation.map(x => x.allocated_cost_cents)).toEqual([60000,40000])
    expect(result.recoverable_cost_cents).toBe(40000)
  })

  it('compiles regulation into contribution margin and break-even volume', () => {
    const result = compileRegulatoryUnitEconomics({ monthly_volume: 1000, revenue_per_unit_cents: 1000, variable_cost_per_unit_cents: 300, supervision_cost_per_unit_cents: 100, reporting_cost_per_unit_cents: 100, fixed_regulatory_cost_cents: 100000 })
    expect(result.contribution_model.monthly_contribution_cents).toBe(400000)
    expect(result.break_even.monthly_units).toBe(200)
  })

  it('prepares tokenized remedies while gating money, notices, and admissions', () => {
    const result = prepareCustomerRemedy({ customers: [{ subject_token: 'a', loss_cents: 1000 }, { subject_token: 'b', loss_cents: 100 }], eligibility_rules: [{ type: 'minimum_loss', value: 500 }], interest_rate: .1 })
    expect(result.total_proposed_cents).toBe(1100)
    expect(result.affected_cohort.eligible).toBe(1)
    expect(result.execution_controls.payments_require_approval).toBe(true)
  })

  it('prices capacity from measured delivery reliability', () => {
    const good = scoreCapacityReliability({ reserved_minutes: 100, delivered_minutes: 100, response_minutes: 10, response_slo_minutes: 60, quality_score: 98, examination_score: 95 })
    const poor = scoreCapacityReliability({ reserved_minutes: 100, delivered_minutes: 40, response_minutes: 120, response_slo_minutes: 60, quality_score: 50, examination_score: 40 })
    expect(good.reliability_score).toBeGreaterThan(90)
    expect(poor.status).toBe('watch')
    expect(poor.pricing_adjustment.multiplier).toBeGreaterThan(1)
  })
})
