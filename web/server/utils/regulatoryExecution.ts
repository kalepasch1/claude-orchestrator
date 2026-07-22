import { createHash, randomBytes } from 'node:crypto'
import { serviceClient } from './fleetSupabase'
import { createCausalityReceipt } from './regulatoryOpportunity'

const now = () => new Date().toISOString()
const bounded = (value: any, limit = 400) => String(value || '').trim().slice(0, limit)
const clamp = (value: number, min = 0, max = 100) => Math.max(min, Math.min(max, value))
const stable = (value: any): string => Array.isArray(value) ? `[${value.map(stable).join(',')}]` : value && typeof value === 'object' ? `{${Object.keys(value).sort().map(key => `${key}:${stable(value[key])}`).join(',')}}` : JSON.stringify(value)
const digest = (value: any) => createHash('sha256').update(stable(value)).digest('hex')

export function negotiateOperatingPerimeter(input: any) {
  const variants = (input.variants || []).slice(0, 100).map((variant: any) => {
    const value = Math.max(0, Number(variant.expected_value_cents || 0))
    const risk = clamp(Number(variant.residual_risk_score || 50))
    const effort = clamp(Number(variant.effort_score || 30))
    const coverage = clamp(Number(variant.coverage_score || 0))
    const score = Math.round(clamp(value / Math.max(1, Number(input.value_scale_cents || 1_000_000)) * 35 + coverage * .35 + (100 - risk) * .2 + (100 - effort) * .1))
    return { ...variant, score, expected_value_cents: value, residual_risk_score: risk }
  }).filter((x: any) => x.prohibited !== true).sort((a: any, b: any) => b.score - a.score)
  const selected: any[] = []
  const used = new Set<string>()
  for (const variant of variants) {
    const conflicts = (variant.conflicts_with || []).some((key: string) => used.has(key))
    if (!conflicts && selected.length < Number(input.max_variants || 8)) { selected.push(variant); used.add(variant.key) }
  }
  return { selected_variants: selected, retained_capabilities: [...new Set(selected.flatMap(x => x.retained_capabilities || []))], excluded_actions: [...new Set((input.variants || []).filter((x: any) => x.prohibited || !selected.includes(x)).flatMap((x: any) => x.excluded_actions || []))], provider_handoffs: selected.flatMap(x => x.provider_handoffs || []), contract_changes: selected.flatMap(x => x.contract_changes || []), pricing_changes: selected.flatMap(x => x.pricing_changes || []), marketing_changes: selected.flatMap(x => x.marketing_changes || []), expected_value_cents: selected.reduce((sum, x) => sum + x.expected_value_cents, 0), residual_risk_score: selected.length ? Math.round(selected.reduce((sum, x) => sum + x.residual_risk_score, 0) / selected.length) : 100, activation_requires_approval: true }
}

export function buildRegulatoryMarketTopology(input: any) {
  const nodes = (input.nodes || []).slice(0, 2_000)
  const edges = (input.edges || []).slice(0, 10_000)
  const available = new Set(nodes.filter((n: any) => n.available === true).map((n: any) => String(n.id)))
  let changed = true
  while (changed) {
    changed = false
    for (const edge of edges) if (available.has(String(edge.from)) && edge.blocked !== true && !available.has(String(edge.to))) { available.add(String(edge.to)); changed = true }
  }
  const markets = nodes.filter((n: any) => n.type === 'market')
  const dependencyCounts = new Map<string, number>()
  for (const edge of edges.filter((e: any) => !e.blocked)) dependencyCounts.set(String(edge.from), (dependencyCounts.get(String(edge.from)) || 0) + 1)
  return { nodes, edges, reachable_markets: markets.filter((n: any) => available.has(String(n.id))).map((n: any) => ({ id: n.id, jurisdiction: n.jurisdiction, value_cents: n.value_cents || 0 })), blocked_markets: markets.filter((n: any) => !available.has(String(n.id))).map((n: any) => ({ id: n.id, jurisdiction: n.jurisdiction, missing: edges.filter((e: any) => String(e.to) === String(n.id) && (e.blocked || !available.has(String(e.from)))).map((e: any) => e.requirement || e.from) })), critical_dependencies: [...dependencyCounts.entries()].map(([id, dependents]) => ({ id, dependents })).sort((a, b) => b.dependents - a.dependents).slice(0, 12) }
}

export function optimizeAuthorityYield(input: any) {
  const remaining = new Map((input.assets || []).slice(0, 200).map((a: any) => [String(a.ref), Math.max(0, Number(a.capacity_units || 0) - Number(a.committed_units || 0))]))
  const opportunities = (input.opportunities || []).slice(0, 1_000).map((o: any) => ({ ...o, ratio: (Number(o.expected_value_cents || 0) - Number(o.risk_charge_cents || 0)) / Math.max(1, Number(o.required_units || 1)) })).sort((a: any, b: any) => b.ratio - a.ratio)
  const allocations = []
  for (const opportunity of opportunities) {
    const available = Number(remaining.get(String(opportunity.asset_ref)) || 0)
    const units = Math.min(available, Math.max(0, Number(opportunity.required_units || 1)))
    if (!units || opportunity.ratio <= 0) continue
    remaining.set(String(opportunity.asset_ref), available - units)
    allocations.push({ asset_ref: opportunity.asset_ref, opportunity_ref: opportunity.ref, allocated_units: units, expected_value_cents: Math.round(Number(opportunity.expected_value_cents || 0) * units / Math.max(1, Number(opportunity.required_units || 1))), marginal_value_cents: Math.round(opportunity.ratio), risk_charge_cents: Math.round(Number(opportunity.risk_charge_cents || 0) * units / Math.max(1, Number(opportunity.required_units || 1))), constraints: opportunity.constraints || [] })
  }
  return { allocations, unallocated_capacity: Object.fromEntries(remaining), portfolio_value_cents: allocations.reduce((s, x) => s + x.expected_value_cents - x.risk_charge_cents, 0), requires_owner_and_asset_controller_approval: true }
}

export function createConfidenceBond(input: any) {
  const probability = Math.max(0, Math.min(1, Number(input.predicted_probability || 0)))
  const reliance = Math.max(0, Number(input.reliance_limit_cents || 0))
  const uncertainty = 1 - Math.abs(probability - .5) * 2
  return { prediction_ref: bounded(input.prediction_ref, 240), prediction_type: bounded(input.prediction_type, 120), predicted_probability: probability, predicted_value: input.predicted_value || {}, invalidation_triggers: (input.invalidation_triggers || []).slice(0, 50), reliance_limit_cents: reliance, accountability_reserve_cents: Math.round(reliance * (.05 + uncertainty * .2)), status: 'open' }
}

export function settleConfidenceBond(input: any) {
  const probability = Math.max(0, Math.min(1, Number(input.predicted_probability || 0)))
  const observed = input.outcome_occurred === true ? 1 : 0
  const brier = Number(((probability - observed) ** 2).toFixed(4))
  return { calibration_score: Number((1 - brier).toFixed(4)), brier_score: brier, realized_value: input.realized_value || { outcome_occurred: Boolean(observed) }, reserve_release_bps: Math.round(clamp((1 - brier) * 10_000, 0, 10_000)), lesson: brier <= .1 ? 'well_calibrated' : brier <= .25 ? 'calibration_review' : 'material_over_or_underconfidence' }
}

export function constructReversibleJurisdictionLaunch(input: any) {
  const sample = Math.max(10, Number(input.minimum_sample_size || 100))
  const stages = [
    { key: 'shadow', traffic_bps: 0, minimum_events: sample, exit_gates: ['authority_receipt_current','contract_tests_pass','journey_replay_pass','fallback_verified'] },
    { key: 'internal', traffic_bps: 0, minimum_events: sample, exit_gates: ['internal_scenarios_pass','evidence_capture_verified','support_runbook_ready'] },
    { key: 'canary', traffic_bps: Math.min(500, Number(input.canary_traffic_bps || 100)), minimum_events: sample, exit_gates: ['no_critical_complaints','violation_rate_below_budget','rollback_drill_pass'] },
    { key: 'limited', traffic_bps: Math.min(5000, Number(input.limited_traffic_bps || 1000)), minimum_events: sample * 5, exit_gates: ['supervisory_review_complete','loss_and_complaint_budget_healthy','evidence_fresh'] },
    { key: 'general', traffic_bps: 10000, minimum_events: sample * 10, exit_gates: ['continuous_monitoring'] },
  ]
  return { stages, current_stage: 'shadow', lawful_fallback: { mode: input.fallback_mode || 'provider_handoff_or_unregulated_variant', preserves: (input.fallback_preserves || ['customer_access','data_export','support']).slice(0, 30), activation_slo_seconds: Math.max(1, Number(input.fallback_slo_seconds || 30)) }, evidence_contract: { capture: ['authority_snapshot','consent','transaction_boundary','provider_handoff','decision_receipt','complaint','exception','rollback'], raw_payload_stored: false, freshness_hours: Math.max(1, Number(input.evidence_freshness_hours || 24)) }, rollback_policy: { automatic_triggers: ['authority_expired','prohibited_action_detected','critical_complaint','evidence_capture_failed','contract_control_breached'], budget_triggers: { violation_rate_bps: Number(input.max_violation_rate_bps || 10), complaint_rate_bps: Number(input.max_complaint_rate_bps || 25), evidence_failure_rate_bps: Number(input.max_evidence_failure_rate_bps || 5) }, scope: 'affected_feature_and_jurisdiction_only', restore: 'lawful_fallback' }, reentry_policy: { minimum_cooldown_hours: Math.max(1, Number(input.reentry_cooldown_hours || 24)), required_proofs: ['root_cause_cured','fresh_authority_receipt','rollback_rehearsed','evidence_gap_closed','independent_review_for_material_event'], restart_at: 'shadow', explicit_reentry_approval: true }, status: 'shadow' }
}

export function evaluateLaunchTelemetry(launch: any, telemetry: any) {
  const policy = launch.rollback_policy || {}
  const budgets = policy.budget_triggers || {}
  const critical = Boolean(telemetry.authority_expired || telemetry.prohibited_action_detected || telemetry.critical_complaints > 0 || telemetry.evidence_capture_failed || telemetry.contract_control_breached)
  const overBudget = Number(telemetry.violation_rate_bps || 0) > Number(budgets.violation_rate_bps || 10) || Number(telemetry.complaint_rate_bps || 0) > Number(budgets.complaint_rate_bps || 25) || Number(telemetry.evidence_failure_rate_bps || 0) > Number(budgets.evidence_failure_rate_bps || 5)
  if (critical || overBudget) return { decision: 'rollback', target_stage: 'shadow', activate_fallback: true, reasons: [critical && 'critical_trigger', overBudget && 'risk_budget_exceeded'].filter(Boolean), reentry_proofs_required: launch.reentry_policy?.required_proofs || [] }
  const currentIndex = (launch.stages || []).findIndex((x: any) => x.key === launch.current_stage)
  const stage = launch.stages?.[Math.max(0, currentIndex)]
  const enough = Number(telemetry.events || 0) >= Number(stage?.minimum_events || 0)
  const gates = (stage?.exit_gates || []).every((gate: string) => telemetry.gates?.[gate] === true || gate === 'continuous_monitoring')
  return enough && gates && currentIndex < launch.stages.length - 1 ? { decision: 'advance', target_stage: launch.stages[currentIndex + 1].key, activate_fallback: false, reasons: ['sample_and_exit_gates_satisfied'] } : { decision: 'hold', target_stage: launch.current_stage, activate_fallback: false, reasons: [!enough && 'minimum_sample_not_met', !gates && 'exit_gates_incomplete'].filter(Boolean) }
}

export function scheduleSupervisoryAttention(input: any) {
  const capacity = new Map((input.specialists || []).slice(0, 200).map((s: any) => [String(s.ref), { ...s, remaining: Math.max(0, Number(s.available_minutes || 0)) }]))
  const work = (input.work || []).slice(0, 2_000).map((item: any) => {
    const deadlineHours = Math.max(1, (new Date(item.due_at || Date.now() + 30 * 86400_000).getTime() - Date.now()) / 3600_000)
    const urgency = clamp(100 - deadlineHours / 7)
    const riskReduction = clamp(Number(item.marginal_risk_reduction || 0))
    const value = Math.max(0, Number(item.unlocked_value_cents || 0))
    const floor = Math.max(0, Number(item.minimum_review_floor_minutes || (item.material ? 30 : 10)))
    const score = Math.round(clamp(riskReduction * .45 + urgency * .3 + Math.min(100, value / Math.max(1, Number(input.value_scale_cents || 100_000))) * .25))
    return { ...item, urgency_score: score, minimum_review_floor_minutes: floor }
  }).sort((a: any, b: any) => b.urgency_score - a.urgency_score)
  const allocations = []
  for (const item of work) {
    const eligible = [...capacity.values()].filter((s: any) => (s.roles || [s.role]).includes(item.specialist_role) && !(item.conflicts || []).includes(s.ref) && s.remaining >= item.minimum_review_floor_minutes).sort((a: any, b: any) => b.remaining - a.remaining)
    const specialist: any = eligible[0]
    if (!specialist) { allocations.push({ work_ref: item.ref, work_type: item.type, specialist_role: item.specialist_role, allocated_minutes: 0, marginal_risk_reduction: item.marginal_risk_reduction, unlocked_value_cents: item.unlocked_value_cents, urgency_score: item.urgency_score, conflict_flags: item.conflicts || [], minimum_review_floor_minutes: item.minimum_review_floor_minutes, status: 'unallocated', explanation: { reason: 'no_conflict_free_specialist_meets_minimum_floor', escalation: true } }); continue }
    const requested = Math.max(item.minimum_review_floor_minutes, Number(item.requested_minutes || item.minimum_review_floor_minutes))
    const minutes = Math.min(specialist.remaining, requested)
    specialist.remaining -= minutes
    allocations.push({ work_ref: item.ref, work_type: item.type, specialist_role: item.specialist_role, assigned_member_ref: specialist.ref, allocated_minutes: minutes, marginal_risk_reduction: item.marginal_risk_reduction, unlocked_value_cents: item.unlocked_value_cents, urgency_score: item.urgency_score, conflict_flags: [], minimum_review_floor_minutes: item.minimum_review_floor_minutes, status: 'recommended', explanation: { marginal_risk_reduction: item.marginal_risk_reduction, unlocked_value_cents: item.unlocked_value_cents, deadline: item.due_at, minimum_floor_preserved: true } })
  }
  return { allocations, remaining_capacity: Object.fromEntries([...capacity].map(([key, value]: any) => [key, value.remaining])), escalations: allocations.filter(x => x.status === 'unallocated') }
}

export function learnCounterfactualOutcome(input: any) {
  const predicted = input.predicted || {}; const realized = input.realized || {}
  const deltas = { value_cents: Number(realized.value_cents || 0) - Number(predicted.value_cents || 0), cost_cents: Number(realized.cost_cents || 0) - Number(predicted.cost_cents || 0), time_days: Number(realized.time_days || 0) - Number(predicted.time_days || 0), complaint_rate_bps: Number(realized.complaint_rate_bps || 0) - Number(predicted.complaint_rate_bps || 0) }
  return { predicted, realized, deltas, lessons: [Math.abs(deltas.value_cents) > Math.max(100_000, Number(predicted.value_cents || 0) * .2) && 'recalibrate_market_value', deltas.cost_cents > 0 && 'increase_implementation_cost_prior', deltas.time_days > 0 && 'increase_timeline_prior', deltas.complaint_rate_bps > 0 && 'increase_conduct_risk_prior'].filter(Boolean), model_adjustments: { value_multiplier: Number(predicted.value_cents) ? Number((Number(realized.value_cents || 0) / Number(predicted.value_cents)).toFixed(3)) : 1, cost_multiplier: Number(predicted.cost_cents) ? Number((Number(realized.cost_cents || 0) / Number(predicted.cost_cents)).toFixed(3)) : 1, apply_after_minimum_observations: 8 } }
}

export async function saveExecutionAction(organizationId: string, userId: string, action: string, values: any) {
  const sb = serviceClient()
  if (action === 'operating_perimeter') {
    const result = negotiateOperatingPerimeter(values)
    const perimeterDigest = digest({ organizationId, project: values.project_ref, objective: values.objective, variants: result.selected_variants.map((x: any) => x.key) })
    const row = { organization_id: organizationId, project_ref: bounded(values.project_ref, 160), objective: bounded(values.objective, 500), jurisdictions: (values.jurisdictions || []).slice(0, 30), ...result, perimeter_digest: perimeterDigest, status: 'shadow', updated_at: now() }
    if (!row.project_ref || !row.objective) throw createError({ statusCode: 400, message: 'project_and_objective_required' })
    return (await sb.from('regulatory_operating_perimeters').upsert(row, { onConflict: 'perimeter_digest' }).select().single()).data
  }
  if (action === 'authority_yield') {
    const result = optimizeAuthorityYield(values)
    for (const allocation of result.allocations) { const allocationDigest = digest({ organizationId, asset: allocation.asset_ref, opportunity: allocation.opportunity_ref, day: now().slice(0, 10) }); await sb.from('regulatory_authority_allocations').upsert({ organization_id: organizationId, ...allocation, allocation_digest: allocationDigest }, { onConflict: 'allocation_digest' }) }
    return result
  }
  if (action === 'prepare_launch') {
    const plan = constructReversibleJurisdictionLaunch(values)
    const launchDigest = digest({ organizationId, project: values.project_ref, feature: values.feature_key, jurisdiction: values.jurisdiction })
    const row = { organization_id: organizationId, project_ref: bounded(values.project_ref, 160), feature_key: bounded(values.feature_key, 160), jurisdiction: bounded(values.jurisdiction, 80), target_market: values.target_market || {}, ...plan, launch_digest: launchDigest, updated_at: now() }
    if (!row.project_ref || !row.feature_key || !row.jurisdiction) throw createError({ statusCode: 400, message: 'project_feature_jurisdiction_required' })
    return (await sb.from('regulatory_jurisdiction_launches').upsert(row, { onConflict: 'organization_id,project_ref,feature_key,jurisdiction' }).select().single()).data
  }
  if (action === 'launch_telemetry') {
    const { data: launch } = await sb.from('regulatory_jurisdiction_launches').select('*').eq('id', values.launch_id).eq('organization_id', organizationId).maybeSingle()
    if (!launch) throw createError({ statusCode: 404, message: 'launch_not_found' })
    const decision = evaluateLaunchTelemetry(launch, values.telemetry || {})
    const activate = values.explicit_approval === true && decision.decision === 'advance'
    const status = decision.decision === 'rollback' ? 'rolled_back' : activate ? 'active' : launch.status
    const stage = decision.decision === 'rollback' ? 'shadow' : activate ? decision.target_stage : launch.current_stage
    await sb.from('regulatory_jurisdiction_launches').update({ current_stage: stage, latest_decision: decision, status, activation_approved_at: activate ? now() : launch.activation_approved_at, activated_by: activate ? userId : launch.activated_by, updated_at: now() }).eq('id', launch.id)
    const receipt = createCausalityReceipt({ subject_type: 'jurisdiction_launch', subject_id: launch.id, decision: decision.decision, causes: decision.reasons, evidence_refs: (values.evidence_refs || []).slice(0, 50), approval_refs: activate ? [{ user_id: userId, at: now() }] : [] })
    await sb.from('regulatory_launch_events').insert({ launch_id: launch.id, organization_id: organizationId, event_type: decision.decision, from_stage: launch.current_stage, to_stage: stage, bounded_metrics: values.telemetry || {}, evidence_refs: (values.evidence_refs || []).slice(0, 50), decision, receipt_digest: receipt.receipt_digest })
    await sb.from('regulatory_causality_receipts').upsert({ organization_id: organizationId, ...receipt }, { onConflict: 'receipt_digest' })
    return { decision, effective_stage: stage, status, advancement_requires_explicit_approval: decision.decision === 'advance' && !activate }
  }
  if (action === 'confidence_bond') {
    const bond = createConfidenceBond(values); const bondDigest = digest({ organizationId, ...bond, nonce: randomBytes(4).toString('hex') })
    return (await sb.from('regulatory_confidence_bonds').insert({ organization_id: organizationId, ...bond, bond_digest: bondDigest }).select().single()).data
  }
  if (action === 'settle_confidence_bond') {
    const { data: bond } = await sb.from('regulatory_confidence_bonds').select('*').eq('id', values.bond_id).eq('organization_id', organizationId).eq('status', 'open').maybeSingle()
    if (!bond) throw createError({ statusCode: 404, message: 'open_confidence_bond_not_found' })
    const settlement = settleConfidenceBond({ ...values, predicted_probability: bond.predicted_probability })
    return (await sb.from('regulatory_confidence_bonds').update({ realized_value: settlement.realized_value, calibration_score: settlement.calibration_score, settled_at: now(), status: 'settled' }).eq('id', bond.id).select().single()).data
  }
  if (action === 'accept_attention') {
    if (values.explicit_approval !== true) throw createError({ statusCode: 400, message: 'explicit_attention_acceptance_required' })
    return (await sb.from('regulatory_attention_allocations').update({ status: 'accepted' }).eq('id', values.allocation_id).eq('organization_id', organizationId).select().single()).data
  }
  if (action === 'counterfactual_outcome') {
    const learned = learnCounterfactualOutcome(values); const outcomeDigest = digest({ organizationId, opportunity: values.opportunity_id, realized: learned.realized })
    return (await sb.from('regulatory_counterfactual_outcomes').upsert({ organization_id: organizationId, opportunity_id: values.opportunity_id, ...learned, outcome_digest: outcomeDigest }, { onConflict: 'outcome_digest' }).select().single()).data
  }
  throw createError({ statusCode: 400, message: 'unknown_execution_action' })
}

export async function runRegulatoryExecutionAutopilot(organizationId: string) {
  const sb = serviceClient()
  const [{ data: opportunities }, { data: relationships }, { data: paths }] = await Promise.all([
    sb.from('regulatory_counterfactual_opportunities').select('*').eq('organization_id', organizationId).in('status', ['selected','preparing']).limit(30),
    sb.from('regulatory_relationships').select('*').eq('organization_id', organizationId).limit(100),
    sb.from('regulatory_readiness_paths').select('*').eq('organization_id', organizationId).limit(100),
  ])
  const nodes = [{ id: 'organization', type: 'organization', available: true }, ...(relationships || []).map((x: any) => ({ id: `relationship:${x.id}`, type: 'authority', available: x.status === 'active' })), ...(paths || []).map((x: any) => ({ id: `market:${x.jurisdiction}:${x.target_capability}`, type: 'market', jurisdiction: x.jurisdiction, value_cents: 0 }))]
  const edges = (paths || []).map((path: any) => ({ from: (relationships || []).find((r: any) => (r.covered_activities || []).includes(path.target_capability)) ? `relationship:${(relationships || []).find((r: any) => (r.covered_activities || []).includes(path.target_capability)).id}` : 'organization', to: `market:${path.jurisdiction}:${path.target_capability}`, blocked: path.readiness_score < 100 && !(relationships || []).some((r: any) => r.status === 'active' && (r.covered_activities || []).includes(path.target_capability)), requirement: path.target_capability }))
  const topology = buildRegulatoryMarketTopology({ nodes, edges }); const topologyDigest = digest({ organizationId, topology })
  await sb.from('regulatory_market_topology_snapshots').upsert({ organization_id: organizationId, ...topology, topology_digest: topologyDigest }, { onConflict: 'topology_digest' })
  const work = (opportunities || []).map((x: any) => ({ ref: x.id, type: 'counterfactual_review', specialist_role: 'regulatory', requested_minutes: 45, minimum_review_floor_minutes: 30, marginal_risk_reduction: 70, unlocked_value_cents: x.expected_value_cents, due_at: new Date(Date.now() + 7 * 86400_000).toISOString(), material: x.proposed_change?.materiality === 'material' }))
  const schedule = scheduleSupervisoryAttention({ work, specialists: [{ ref: 'role:regulatory', roles: ['regulatory'], available_minutes: 240 }], value_scale_cents: 500_000 })
  for (const allocation of schedule.allocations.filter((x: any) => x.status === 'recommended')) { const allocationDigest = digest({ organizationId, work: allocation.work_ref, day: now().slice(0, 10) }); await sb.from('regulatory_attention_allocations').upsert({ organization_id: organizationId, ...allocation, allocation_digest: allocationDigest }, { onConflict: 'allocation_digest' }) }
  return { topology_markets_reachable: topology.reachable_markets.length, attention_allocations_updated: schedule.allocations.length, attention_escalations: schedule.escalations.length }
}

export async function executionCockpit(organizationId: string) {
  const sb = serviceClient()
  const [launches, attention, topology, allocations, bonds, perimeters, outcomes] = await Promise.all([
    sb.from('regulatory_jurisdiction_launches').select('*').eq('organization_id', organizationId).order('updated_at', { ascending: false }).limit(30),
    sb.from('regulatory_attention_allocations').select('*').eq('organization_id', organizationId).in('status', ['recommended','accepted','in_progress']).order('urgency_score', { ascending: false }).limit(50),
    sb.from('regulatory_market_topology_snapshots').select('*').eq('organization_id', organizationId).eq('status', 'current').order('created_at', { ascending: false }).limit(1).maybeSingle(),
    sb.from('regulatory_authority_allocations').select('*').eq('organization_id', organizationId).in('status', ['recommended','approved','active']).limit(50),
    sb.from('regulatory_confidence_bonds').select('*').eq('organization_id', organizationId).eq('status', 'open').limit(50),
    sb.from('regulatory_operating_perimeters').select('*').eq('organization_id', organizationId).in('status', ['shadow','review','approved','active']).limit(30),
    sb.from('regulatory_counterfactual_outcomes').select('*').eq('organization_id', organizationId).order('observed_at', { ascending: false }).limit(30),
  ])
  return {
    launches: launches.data || [], attention: attention.data || [], topology: topology.data || null,
    authority_allocations: allocations.data || [], confidence_bonds: bonds.data || [],
    perimeters: perimeters.data || [], learned_outcomes: outcomes.data || [],
    summary: {
      active_launches: (launches.data || []).filter((x: any) => x.status === 'active').length,
      launches_requiring_attention: (launches.data || []).filter((x: any) => ['paused','rolled_back'].includes(x.status)).length,
      scheduled_review_minutes: (attention.data || []).reduce((s: number, x: any) => s + Number(x.allocated_minutes || 0), 0),
      unlocked_value_under_review_cents: (attention.data || []).reduce((s: number, x: any) => s + Number(x.unlocked_value_cents || 0), 0),
    },
  }
}
