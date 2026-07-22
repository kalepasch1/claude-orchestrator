import { describe, expect, it } from 'vitest'
import { compareLicenseStrategies, compileAgreementControls, evaluateAgreementAction, evidenceRoomStatus, planJurisdictionFeature, simulateAuthorityTimeline } from './regulatoryTemporal'

describe('regulatory temporal and execution system', () => {
  it('sequences jurisdictions and exposes temporal invalidation triggers', () => {
    const result = simulateAuthorityTimeline({ jurisdictions: ['NY','CA'], readiness_score: 70, monthly_growth_rate: .2, license_expires_in_days: 180, ownership_change_in_days: 45 })
    expect(result.jurisdiction_sequence).toHaveLength(2)
    expect(result.authority_timeline.map((event: any) => event.type)).toContain('ownership_change')
    expect(result.cade_prediction.confidence).toBeGreaterThan(0)
    expect(result.invalidation_triggers.every((trigger: any) => trigger.re_simulate)).toBe(true)
  })

  it('compiles operative terms into shadow-enforceable controls and obligations', () => {
    const result = compileAgreementControls({ terms: [
      { key: 'volume', text: 'Monthly volume may not exceed the approved cap.', value: 1000 },
      { key: 'consent', text: 'Prior written approval is required before a material product change.' },
      { key: 'sla', text: 'Monthly service level uptime must be 99.9%.', target: .999 },
      { key: 'termination', text: 'Sponsor may immediately suspend activity after a material breach.' },
    ] })
    expect(result.executable_controls.map((control: any) => control.type)).toEqual(expect.arrayContaining(['limit','approval_gate','termination']))
    expect(result.obligations.map((obligation: any) => obligation.type)).toContain('service_level')
    expect(result.interpreted_terms.raw_terms_stored).toBe(false)
  })

  it('blocks agreement actions that exceed limits or lack required approval', () => {
    const result = evaluateAgreementAction([
      { key:'volume', type:'limit', value:100 },
      { key:'change', type:'approval_gate' },
    ], { material:true, approved:false, metrics:{ volume:140 } })
    expect(result.decision).toBe('block')
    expect(result.reasons.map((reason:any)=>reason.reason)).toEqual(expect.arrayContaining(['explicit_approval_required','agreement_limit_exceeded']))
  })

  it('detects stale and contradictory evidence before application', () => {
    const status = evidenceRoomStatus([{ key:'owner', label:'Owner review', required:true }, { key:'policy', label:'Policy', required:true }], [
      { requirement_key:'owner', verification_status:'verified', expires_at:null },
      { requirement_key:'policy', verification_status:'contradicted', expires_at:null },
    ])
    expect(status.completeness_score).toBe(50)
    expect(status.contradiction_count).toBe(1)
    expect(status.status).toBe('building')
  })

  it('keeps jurisdiction feature controls in shadow until activated', () => {
    const uncovered = planJurisdictionFeature({ activity:'money_transmission', jurisdiction:'NY', covered:false })
    expect(uncovered.effective_state).toBe('shadow')
    expect(uncovered.one_click_action.requires_approval).toBe(true)
    expect(uncovered.compliant_variants.map((variant: any) => variant.state)).toContain('adjusted')
  })

  it('compares time, direct cost, indirect cost, control and risk', () => {
    const options = compareLicenseStrategies({ monthly_value_cents:200_000, horizon_months:24 })
    expect(options.length).toBeGreaterThanOrEqual(5)
    expect(options[0].cade_score.score).toBeGreaterThanOrEqual(options.at(-1)!.cade_score.score)
    expect(options.every(option => option.direct_costs.total_cents >= 0 && option.indirect_costs.opportunity_cost_cents >= 0)).toBe(true)
  })
})
