import { describe, expect, it } from 'vitest'
import { activationPrompt, recommendationFor } from './scopedImprovement'

describe('scoped improvement governance', () => {
  it('raises recommendation strength with recoverable friction', () => {
    const calm = recommendationFor({ scopeType: 'code', scopeRef: 'api', label: 'API', outcomes: [{ tests_passed: true, integrated: true }], tasks: [] })
    const friction = recommendationFor({ scopeType: 'code', scopeRef: 'api', label: 'API', outcomes: [{ tests_passed: false, integrated: false }], tasks: [{ state: 'TESTFAIL' }, { state: 'RETRY' }] })
    expect(friction.score).toBeGreaterThan(calm.score)
    expect(friction.expectedLift).toBeGreaterThan(calm.expectedLift)
  })
  it('binds rollback and locked invariants into every activation', () => {
    const prompt = activationPrompt({ label: 'Routing', scope_type: 'workflow', scope_ref: 'triage', mode: 'shadow', target_kpi: 'avg_wall_min', rollback_threshold: 8 })
    expect(prompt).toContain('Automatically roll back')
    expect(prompt).toContain('authority')
    expect(prompt).toContain('independent QA')
  })
})
