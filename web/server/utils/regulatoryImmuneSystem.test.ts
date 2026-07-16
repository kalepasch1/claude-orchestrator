import { describe, expect, it } from 'vitest'
import { buildRegulatoryImmuneResponse, calculateAuthorityDecay, clearCrossBorderAuthority, compileLawToRuntime, designRegulatorEvidenceStream, priceProofPortability, rehearseEnforcement, runSupervisoryCertificationSwarm } from './regulatoryImmuneSystem'

describe('regulatory immune system', () => {
  it('compiles cited provisions into traceable shadow controls and tests', () => {
    const result = compileLawToRuntime({ provisions: [{ key: 'volume_cap', authority_citation: 'Order §4', interpretation_confidence: .95, predicate: { volume_gt: 100 }, effect: 'hold', fallback: 'manual_review' }] })
    expect(result.status).toBe('shadow')
    expect(result.traceability[0].authority_citation).toBe('Order §4')
    expect(result.test_vectors).toHaveLength(2)
  })

  it('escalates a supervisory swarm only when material risk or gaps are found', () => {
    const clean = runSupervisoryCertificationSwarm({ shadow_history: { evidence_completeness: 98, authority_coverage: 97, qa_pass_rate: 99, open_complaints: 0, material_incidents: 0, contradictions: 0, operating_days: 120 } })
    expect(clean.human_escalation_required).toBe(false)
    expect(clean.recommendation).toBe('swarm_eligible_for_sponsor_review')
    const risky = runSupervisoryCertificationSwarm({ shadow_history: { evidence_completeness: 60, authority_coverage: 65, qa_pass_rate: 90, material_incidents: 1, operating_days: 10 } })
    expect(risky.human_escalation_required).toBe(true)
    expect(risky.material_risks).toContain('material_incident_history')
    expect(risky.evidence_gaps).toContain('evidence_incomplete')
  })

  it('isolates only the degraded boundary and preserves lawful behavior', () => {
    const result = buildRegulatoryImmuneResponse({ project_ref: 'p', feature_key: 'payments', jurisdiction: 'NY', invalid_authority: true, fallback_mode: 'provider_handoff' })
    expect(result.affected_boundary.feature_key).toBe('payments')
    expect(result.autonomous_actions).toContain('activate_preapproved_fallback')
    expect(result.approval_required_actions).toContain('production_reentry_if_material')
  })

  it('constructs the smallest consent-bound cross-border authority bundle', () => {
    const result = clearCrossBorderAuthority({ requirements: [{ key: 'payments', jurisdiction: 'GB' }, { key: 'custody', jurisdiction: 'GB' }], candidates: [{ key: 'principal-a', capabilities: ['payments'], jurisdictions: ['GB'], reliability: 95, evidence_score: 90, monthly_cents: 1000 }, { key: 'principal-b', capabilities: ['custody'], jurisdictions: ['GB'], reliability: 90, evidence_score: 90, monthly_cents: 2000 }] })
    expect(result.recommended_bundle.uncovered_requirements).toEqual([])
    expect(result.recommended_bundle.activation).toBe('permission_required')
    expect(result.consent_requirements).toHaveLength(2)
  })

  it('prices permissioned proof reuse and contributor rebates', () => {
    const result = priceProofPortability({ verified_uses: 10, hours_saved_per_use: 4, blended_hourly_cost_cents: 20_000, rebate_rate: .25, share_approved: true })
    expect(result.recipient_savings_cents).toBe(800_000)
    expect(result.contributor_rebate_cents).toBe(200_000)
    expect(result.status).toBe('permissioned')
  })

  it('denies evidence fields outside an explicit regulator grant', () => {
    const result = designRegulatorEvidenceStream({ grant_active: true, grant_fields: ['complaint_count'], requested_fields: ['complaint_count', 'customer_names'] })
    expect(result.delivery_manifest.map(x => x.field)).toEqual(['complaint_count'])
    expect(result.denied_fields).toEqual(['customer_names'])
    expect(result.status).toBe('shadow')
  })

  it('rehearses enforcement without creating an admission', () => {
    const result = rehearseEnforcement({ alleged_findings: [{ code: 'recordkeeping', severity: 2 }], affected_customers: 5, restitution_per_customer_cents: 1000 })
    expect(result.customer_restitution_cents).toBe(5000)
    expect(result.evidence_gaps).toEqual(['recordkeeping'])
    expect(result.defense_options).toContain('correct_factual_record')
  })

  it('prioritizes authority preservation by time and value', () => {
    const result = calculateAuthorityDecay({ current_value_cents: 10_000_000, material_loss_at: new Date(Date.now() + 5 * 864e5).toISOString(), preservation_options: [{ action: 'renew', cost_cents: 100_000, value_preserved_cents: 9_000_000 }] })
    expect(result.days_to_material_loss).toBeLessThanOrEqual(5)
    expect(result.priority_score).toBeGreaterThan(80)
    expect(result.recommended_action.action).toBe('renew')
  })
})
