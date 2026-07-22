import { describe, expect, it } from 'vitest'
import {
  buildRegulatoryMarketTopology,
  constructReversibleJurisdictionLaunch,
  createConfidenceBond,
  evaluateLaunchTelemetry,
  learnCounterfactualOutcome,
  negotiateOperatingPerimeter,
  optimizeAuthorityYield,
  scheduleSupervisoryAttention,
  settleConfidenceBond,
} from './regulatoryExecution'

describe('regulatory execution network', () => {
  it('negotiates the highest-value compatible operating perimeter', () => {
    const result = negotiateOperatingPerimeter({ variants: [{ key: 'a', expected_value_cents: 900_000, coverage_score: 90, residual_risk_score: 10, effort_score: 10, retained_capabilities: ['checkout'] }, { key: 'b', expected_value_cents: 100_000, prohibited: true, excluded_actions: ['custody'] }] })
    expect(result.selected_variants[0].key).toBe('a')
    expect(result.excluded_actions).toContain('custody')
    expect(result.activation_requires_approval).toBe(true)
  })

  it('maps reachable and blocked regulatory markets', () => {
    const result = buildRegulatoryMarketTopology({ nodes: [{ id: 'org', available: true }, { id: 'license', available: false }, { id: 'ny', type: 'market' }, { id: 'ca', type: 'market' }], edges: [{ from: 'org', to: 'ny' }, { from: 'license', to: 'ca', blocked: true, requirement: 'CA license' }] })
    expect(result.reachable_markets.map(x => x.id)).toContain('ny')
    expect(result.blocked_markets[0].missing).toContain('CA license')
  })

  it('allocates scarce authority by risk-adjusted marginal value', () => {
    const result = optimizeAuthorityYield({ assets: [{ ref: 'sponsor', capacity_units: 2 }], opportunities: [{ ref: 'high', asset_ref: 'sponsor', required_units: 1, expected_value_cents: 1_000_000, risk_charge_cents: 50_000 }, { ref: 'low', asset_ref: 'sponsor', required_units: 2, expected_value_cents: 100_000, risk_charge_cents: 0 }] })
    expect(result.allocations[0].opportunity_ref).toBe('high')
    expect(result.requires_owner_and_asset_controller_approval).toBe(true)
  })

  it('creates and calibrates confidence accountability', () => {
    const bond = createConfidenceBond({ prediction_ref: 'p', prediction_type: 'approval', predicted_probability: .9, reliance_limit_cents: 1_000_000 })
    expect(bond.accountability_reserve_cents).toBeGreaterThan(0)
    expect(settleConfidenceBond({ predicted_probability: .9, outcome_occurred: true }).calibration_score).toBeGreaterThan(.9)
  })

  it('constructs a reversible launch with scoped fallback and proof-based re-entry', () => {
    const launch = constructReversibleJurisdictionLaunch({ canary_traffic_bps: 100 })
    expect(launch.stages.map(x => x.key)).toEqual(['shadow','internal','canary','limited','general'])
    expect(launch.rollback_policy.scope).toContain('affected_feature_and_jurisdiction_only')
    expect(launch.reentry_policy.explicit_reentry_approval).toBe(true)
  })

  it('rolls back immediately on critical telemetry and advances only after gates', () => {
    const launch = constructReversibleJurisdictionLaunch({ minimum_sample_size: 10 })
    expect(evaluateLaunchTelemetry(launch, { authority_expired: true }).decision).toBe('rollback')
    const gates = Object.fromEntries(launch.stages[0].exit_gates.map(key => [key, true]))
    expect(evaluateLaunchTelemetry(launch, { events: 10, gates }).decision).toBe('advance')
  })

  it('preserves review floors, conflicts, and escalations when scheduling experts', () => {
    const result = scheduleSupervisoryAttention({ specialists: [{ ref: 'alice', roles: ['legal'], available_minutes: 60 }], work: [{ ref: 'w1', type: 'contract', specialist_role: 'legal', requested_minutes: 45, minimum_review_floor_minutes: 30, marginal_risk_reduction: 90, unlocked_value_cents: 1_000_000 }, { ref: 'w2', type: 'contract', specialist_role: 'legal', minimum_review_floor_minutes: 30, marginal_risk_reduction: 10, conflicts: ['alice'] }] })
    expect(result.allocations[0].allocated_minutes).toBeGreaterThanOrEqual(30)
    expect(result.escalations).toHaveLength(1)
  })

  it('learns calibrated deltas from realized counterfactuals', () => {
    const result = learnCounterfactualOutcome({ predicted: { value_cents: 1_000_000, cost_cents: 100_000, time_days: 10 }, realized: { value_cents: 500_000, cost_cents: 150_000, time_days: 20 } })
    expect(result.lessons).toContain('recalibrate_market_value')
    expect(result.model_adjustments.apply_after_minimum_observations).toBe(8)
  })
})
