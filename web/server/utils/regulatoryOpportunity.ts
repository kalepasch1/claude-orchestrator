import { createHash, randomBytes } from 'node:crypto'
import { serviceClient } from './fleetSupabase'

const now = () => new Date().toISOString()
const bounded = (value: any, limit = 400) => String(value || '').trim().slice(0, limit)
const clamp = (value: number, min = 0, max = 100) => Math.max(min, Math.min(max, value))
const stable = (value: any): string => Array.isArray(value) ? `[${value.map(stable).join(',')}]` : value && typeof value === 'object' ? `{${Object.keys(value).sort().map(key => `${key}:${stable(value[key])}`).join(',')}}` : JSON.stringify(value)
const digest = (value: any) => createHash('sha256').update(stable(value)).digest('hex')

const CHANGE_LIBRARY: Record<string, Array<{ change: string; kind: string; effort: number; retained: string[]; lost: string[]; unlocked: string[] }>> = {
  securities_intermediation: [
    { change: 'Replace transaction-linked compensation with a reviewed fixed-fee introduction workflow.', kind: 'compensation_boundary', effort: 18, retained: ['introductions','factual_company_information','relationship_tracking'], lost: ['transaction_participation','success_fee'], unlocked: ['introduction_only_markets'] },
    { change: 'Route solicitation and negotiation to a supervised associated person while retaining workflow technology.', kind: 'covered_handoff', effort: 35, retained: ['technology','workflow','customer_context'], lost: ['unsupervised_solicitation'], unlocked: ['sponsor_covered_markets'] },
  ],
  money_transmission: [
    { change: 'Move custody, KYC/AML, funds control, and settlement to a licensed provider; retain orchestration and reconciliation.', kind: 'provider_controlled_flow', effort: 28, retained: ['checkout_experience','ledger_view','reconciliation'], lost: ['custody','funds_control'], unlocked: ['provider_covered_payment_markets'] },
  ],
  insurance_distribution: [
    { change: 'Convert recommendations into factual routing and hand policy advice, binding, and commissions to an appointed producer.', kind: 'licensed_handoff', effort: 24, retained: ['education','needs_intake','routing'], lost: ['policy_advice','binding'], unlocked: ['producer_covered_markets'] },
  ],
  mortgage_origination: [
    { change: 'Stop before application and term discussion; route qualified leads to a licensed originator under reviewed compensation.', kind: 'lead_boundary', effort: 22, retained: ['lead_generation','education','scheduling'], lost: ['application_intake','rate_negotiation'], unlocked: ['referral_permitted_markets'] },
  ],
  regulated_data_processing: [
    { change: 'Disable independent profiling and reuse; enforce processor-only purpose limits, deletion, and data minimization.', kind: 'processor_mode', effort: 16, retained: ['customer_directed_processing','analytics_for_customer'], lost: ['independent_reuse','targeted_advertising'], unlocked: ['processor_permitted_markets'] },
  ],
}

export function rankRegulatoryCounterfactuals(input: any) {
  const activity = bounded(input.activity, 120)
  const jurisdictions = (input.jurisdictions || ['US-general']).slice(0, 30)
  const marketValue = Math.max(0, Number(input.market_value_cents || 5_000_000))
  const confidence = Math.max(.45, Math.min(.94, Number(input.confidence || .65)))
  const candidates = (CHANGE_LIBRARY[activity] || [{ change: 'Separate the irreducible regulated action into an approved provider or permissioned workflow.', kind: 'regulated_core_boundary', effort: 40, retained: ['lawful_product_core'], lost: ['uncovered_regulated_action'], unlocked: ['bounded_markets'] }]).map((candidate, index) => {
    const unlockedCount = Math.max(1, jurisdictions.length - index)
    const value = Math.round(marketValue * unlockedCount / Math.max(jurisdictions.length, 1) * confidence)
    const cost = Math.round((candidate.effort * 1_250 + index * 5_000) * 100)
    const score = Math.round(clamp((value / Math.max(marketValue, 1)) * 55 + (100 - candidate.effort) * .3 + confidence * 15))
    return { rank: index + 1, score, activity, proposed_change: { kind: candidate.kind, summary: candidate.change, materiality: candidate.effort >= 30 ? 'material' : 'unknown' }, unlocked_markets: jurisdictions.slice(0, unlockedCount).map((jurisdiction: string) => ({ jurisdiction, market: candidate.unlocked[0], requires_final_review: true })), retained_capabilities: candidate.retained, lost_capabilities: candidate.lost, expected_value_cents: value, direct_cost_cents: cost, time_to_value_days: Math.max(3, Math.round(candidate.effort * .7)), reversibility_score: Math.round(100 - candidate.effort * .45), confidence, implementation_plan: [{ order: 1, action: 'prepare_shadow_variant' }, { order: 2, action: 'run_contract_code_and_journey_qa' }, { order: 3, action: 'obtain_required_approvals' }, { order: 4, action: 'activate_jurisdictionally' }], qa_plan: ['unit_and_contract_tests','payment_or_dataflow_assertions','journey_replay','authority_receipt','canary_and_rollback'] }
  }).sort((a, b) => b.score - a.score)
  return { recommended: candidates[0], alternatives: candidates.slice(1, 4), explanation: 'Ranked by lawful market unlocked, expected value, implementation effort, reversibility, retained capability, and evidence confidence.' }
}

export function calculateEvidencePortability(input: any) {
  const evidence = (input.evidence || []).slice(0, 200)
  const portable = evidence.filter((item: any) => !['jurisdiction_specific_exam','local_bond','regulator_fingerprint','appointment'].includes(item.kind) && item.verified === true)
  const nonportable = evidence.filter((item: any) => !portable.includes(item))
  const days = portable.reduce((sum: number, item: any) => sum + Math.max(1, Number(item.preparation_days || 5)), 0)
  return { portable_evidence: portable.map((x: any) => ({ kind: x.kind, digest: x.digest, consent_required: x.owner_org_id !== input.organization_id })), nonportable_requirements: nonportable.map((x: any) => ({ kind: x.kind, reason: x.verified !== true ? 'not_verified' : 'jurisdiction_or_regulator_specific' })), predicted_time_saved_days: days, predicted_cost_saved_cents: days * Math.max(10_000, Number(input.daily_cost_cents || 50_000)), consent_requirements: portable.filter((x: any) => x.owner_org_id && x.owner_org_id !== input.organization_id).map((x: any) => ({ owner_org_id: x.owner_org_id, evidence_kind: x.kind, approval: 'affirmative' })), confidence: Number(Math.min(.92, .45 + portable.length * .05).toFixed(2)) }
}

export function aggregateRegulatoryFeedback(input: any) {
  const outcomes = (input.outcomes || []).slice(0, 5_000)
  const minimum = Math.max(5, Number(input.minimum_cohort || 8))
  const groups = new Map<string, any[]>()
  for (const outcome of outcomes) {
    const key = `${bounded(outcome.domain, 80)}:${bounded(outcome.jurisdiction, 80)}:${bounded(outcome.finding_code, 120)}`
    groups.set(key, [...(groups.get(key) || []), outcome])
  }
  return [...groups.entries()].map(([patternKey, group]) => ({ pattern_key: patternKey, domain: bounded(group[0]?.domain, 80), jurisdiction: bounded(group[0]?.jurisdiction, 80), cohort_size: new Set(group.map(x => x.organization_digest)).size, bounded_pattern: { finding_code: bounded(group[0]?.finding_code, 120), rate: Number((group.filter(x => x.result === 'finding').length / group.length).toFixed(3)), raw_examples_exposed: false }, recommended_control: { action: bounded(group[0]?.recommended_control || 'increase_evidence_and_preflight_review', 240), mode: 'shadow' }, support_score: Number(Math.min(.99, group.length / 25).toFixed(2)) })).map(pattern => ({ ...pattern, privacy_threshold_met: pattern.cohort_size >= minimum, status: pattern.cohort_size >= minimum ? 'eligible' : 'shadow' }))
}

export function matchSupervisoryCapacity(input: any) {
  const demand = input.demand || {}
  return (input.offers || []).slice(0, 200).filter((offer: any) => offer.status === 'available' && Number(offer.capacity_units || 0) - Number(offer.used_units || 0) >= Number(demand.units || 1) && (offer.jurisdictions || []).includes(demand.jurisdiction) && offer.capability === demand.capability).map((offer: any) => {
    const available = Number(offer.capacity_units) - Number(offer.used_units || 0)
    const correlation = clamp(Number(offer.correlation_score || 25))
    const evidence = clamp(Number(demand.readiness_score || 0))
    const score = Math.round(clamp(available * 3 + (100 - correlation) * .35 + evidence * .25))
    return { offer_id: offer.id, score, available_units: available, modeled_monthly_price_cents: Math.round(Number(offer.pricing_model?.base_cents || 25_000) * (1 + correlation / 100) * (1 - Math.min(.3, evidence / 400))), requires_affirmative_approval_from: ['requester','supervising_organization'], reasons: ['jurisdiction_covered','capability_match','capacity_available','correlation_within_modeled_limit'] }
  }).sort((a: any, b: any) => b.score - a.score)
}

export function compileSafeHarbor(input: any) {
  const conditions = (input.conditions || []).slice(0, 100)
  return { eligibility_conditions: conditions.map((item: any, index: number) => ({ key: bounded(item.key || `condition_${index + 1}`, 100), test: bounded(item.test || item.text || item, 400), verified: item.verified === true })), executable_controls: conditions.map((item: any, index: number) => ({ key: bounded(item.key || `condition_${index + 1}`, 100), enforcement: item.machine_testable === false ? 'approval_gate' : 'runtime_assertion', fail_state: 'hold_affected_action' })), evidence_schedule: { capture: ['before_action','at_action','exception','periodic_revalidation'], retain: 'bounded_facts_and_digest' }, disqualifying_events: (input.disqualifying_events || ['condition_no_longer_satisfied','authority_source_changed','material_product_change']).slice(0, 50), ready: conditions.length > 0 && conditions.every((x: any) => x.verified === true), activation_requires_approval: true }
}

export function simulateRegulatoryIncident(input: any) {
  const type = bounded(input.incident_type || 'authority_loss', 120)
  const affected = (input.affected_capabilities || []).slice(0, 100)
  const relationships = (input.relationships || []).slice(0, 100)
  const severity = clamp(Number(input.severity || 65))
  const hours = Math.round(Math.max(1, severity * .6 + affected.length * 4 + relationships.length * 2))
  return { incident_type: type, cascade: [{ order: 1, effect: 'hold_affected_capabilities' }, ...relationships.map((x: any, index: number) => ({ order: index + 2, effect: 'relationship_review', relationship_id: x.id }))], containment_plan: [{ order: 1, action: 'activate_lawful_fallback_variants', automatic: true }, { order: 2, action: 'preserve_evidence_and_issue_causality_receipt', automatic: true }, { order: 3, action: 'approve_external_notifications', automatic: false }], notification_plan: ['counsel_and_compliance_review','contractual_counterparty_notice','regulator_or_customer_notice_if_required'], authority_effects: affected.map((capability: any) => ({ capability, state: 'held_pending_reverification' })), recovery_plan: ['cure_root_condition','rehearse_examination','refresh_authority_receipt','canary_reactivation'], direct_cost_cents: Math.round(hours * Number(input.hourly_cost_cents || 25_000)), downtime_hours: hours }
}

export function createCausalityReceipt(input: any) {
  const receipt = { subject_type: bounded(input.subject_type, 80), subject_id: bounded(input.subject_id, 240), decision: bounded(input.decision, 120), causes: (input.causes || []).slice(0, 100), authority_refs: (input.authority_refs || []).slice(0, 100), evidence_refs: (input.evidence_refs || []).slice(0, 100), agreement_refs: (input.agreement_refs || []).slice(0, 100), approval_refs: (input.approval_refs || []).slice(0, 100), counterfactuals: (input.counterfactuals || []).slice(0, 20) }
  return { ...receipt, receipt_digest: digest(receipt) }
}

export async function recordRegulatoryFeedback(organizationId: string, values: any) {
  const sb = serviceClient()
  const organizationDigest = digest({ organizationId, privacy_epoch: now().slice(0, 7) })
  const observation = { organization_digest: organizationDigest, domain: bounded(values.domain, 80), jurisdiction: bounded(values.jurisdiction || 'US-general', 80), finding_code: bounded(values.finding_code, 120), result: ['finding','accepted','remediated','withdrawn'].includes(values.result) ? values.result : 'finding', recommended_control: bounded(values.recommended_control, 240) || null }
  if (!observation.domain || !observation.finding_code) throw createError({ statusCode: 400, message: 'feedback_domain_and_finding_required' })
  const observationDigest = digest({ ...observation, source_ref: bounded(values.source_ref, 240) })
  const { error } = await sb.from('regulatory_feedback_observations').upsert({ ...observation, observation_digest: observationDigest }, { onConflict: 'observation_digest' })
  if (error) throw createError({ statusCode: 500, message: error.message })
  const { data: observations } = await sb.from('regulatory_feedback_observations').select('*').eq('domain', observation.domain).eq('jurisdiction', observation.jurisdiction).eq('finding_code', observation.finding_code).limit(5000)
  const [pattern] = aggregateRegulatoryFeedback({ outcomes: observations || [], minimum_cohort: 8 })
  if (pattern) {
    const patternDigest = digest({ key: pattern.pattern_key, cohort: pattern.cohort_size, rate: pattern.bounded_pattern.rate })
    await sb.from('regulatory_feedback_patterns').upsert({ ...pattern, pattern_digest: patternDigest }, { onConflict: 'pattern_digest' })
  }
  return { recorded: true, raw_details_stored: false, pattern_available: Boolean(pattern?.privacy_threshold_met), minimum_cohort: 8 }
}

async function upsertCounterfactual(organizationId: string, assessment: any, profile: any) {
  const ranked = rankRegulatoryCounterfactuals({ activity: assessment.activity, jurisdictions: assessment.signal?.jurisdictions || profile?.jurisdictions || ['US-general'], confidence: assessment.confidence, market_value_cents: assessment.estimated_market_value_cents })
  const candidate = ranked.recommended
  const opportunityDigest = digest({ organizationId, assessment: assessment.id, activity: assessment.activity, proposed_change: candidate.proposed_change })
  const row = { organization_id: organizationId, assessment_id: assessment.id, project_ref: assessment.signal?.project_ref || null, baseline: { activity: assessment.activity, verdict: assessment.verdict, regulated_core: assessment.regulated_core }, ...candidate, opportunity_digest: opportunityDigest, updated_at: now() }
  const { data, error } = await serviceClient().from('regulatory_counterfactual_opportunities').upsert(row, { onConflict: 'opportunity_digest' }).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  return data
}

export async function runRegulatoryOpportunityAutopilot(organizationId: string) {
  const sb = serviceClient()
  const [{ data: assessments }, { data: profile }, { data: paths }, { data: rooms }] = await Promise.all([
    sb.from('regulatory_activity_assessments').select('*,signal:regulatory_activity_signals(project_ref,jurisdictions)').eq('organization_id', organizationId).eq('status', 'current').in('verdict', ['not_covered','counsel_required']).limit(40),
    sb.from('regulatory_capability_profiles').select('*').eq('organization_id', organizationId).maybeSingle(),
    sb.from('regulatory_readiness_paths').select('*').eq('organization_id', organizationId).limit(50),
    sb.from('regulatory_evidence_rooms').select('*,items:regulatory_evidence_items(requirement_key,evidence_type,evidence_digest,verification_status)').eq('organization_id', organizationId).limit(50),
  ])
  const counterfactuals = await Promise.all((assessments || []).map((assessment: any) => upsertCounterfactual(organizationId, assessment, profile)))
  let portable = 0
  for (const path of paths || []) {
    const room: any = (rooms || []).find((item: any) => item.readiness_path_id === path.id)
    if (!room) continue
    for (const target of (profile?.jurisdictions || []).filter((j: string) => j !== path.jurisdiction).slice(0, 4)) {
      const result = calculateEvidencePortability({ organization_id: organizationId, evidence: (room.items || []).map((x: any) => ({ kind: x.requirement_key || x.evidence_type, digest: x.evidence_digest, verified: x.verification_status === 'verified', preparation_days: 5 })), daily_cost_cents: 50_000 })
      if (!result.portable_evidence.length) continue
      const opportunityDigest = digest({ organizationId, path: path.id, target, portable: result.portable_evidence.map((x: any) => x.digest) })
      await sb.from('regulatory_portability_opportunities').upsert({ organization_id: organizationId, source_capability: path.target_capability, target_capability: path.target_capability, source_jurisdiction: path.jurisdiction, target_jurisdiction: target, ...result, opportunity_digest: opportunityDigest }, { onConflict: 'opportunity_digest' })
      portable += 1
    }
  }
  for (const opportunity of counterfactuals) {
    const receipt = createCausalityReceipt({ subject_type: 'counterfactual', subject_id: opportunity.id, decision: 'proposed', causes: [{ type: 'activity_assessment', id: opportunity.assessment_id }], counterfactuals: [{ proposed_change: opportunity.proposed_change, expected_value_cents: opportunity.expected_value_cents }] })
    await sb.from('regulatory_causality_receipts').upsert({ organization_id: organizationId, ...receipt }, { onConflict: 'receipt_digest' })
  }
  return { counterfactuals_updated: counterfactuals.length, portability_opportunities_updated: portable }
}

export async function saveOpportunityAction(organizationId: string, userId: string, action: string, values: any) {
  const sb = serviceClient()
  if (action === 'select_counterfactual') {
    const { data: item } = await sb.from('regulatory_counterfactual_opportunities').select('*').eq('id', values.opportunity_id).eq('organization_id', organizationId).maybeSingle()
    if (!item) throw createError({ statusCode: 404, message: 'counterfactual_not_found' })
    await sb.from('regulatory_counterfactual_opportunities').update({ status: 'selected', updated_at: now() }).eq('id', item.id)
    return { opportunity: { ...item, status: 'selected' }, next_action: { type: 'prepare_shadow_variant', implementation_plan: item.implementation_plan, qa_plan: item.qa_plan, material_change_requires_approval: true } }
  }
  if (action === 'safe_harbor') {
    const compiled = compileSafeHarbor(values)
    const controlDigest = digest({ organizationId, project: values.project_ref, key: values.safe_harbor_key, jurisdiction: values.jurisdiction, authority_refs: values.authority_refs })
    const row = { organization_id: organizationId, project_ref: bounded(values.project_ref, 160), safe_harbor_key: bounded(values.safe_harbor_key, 160), jurisdiction: bounded(values.jurisdiction || 'US-general', 80), authority_refs: (values.authority_refs || []).slice(0, 20), ...compiled, enforcement_mode: values.activate === true ? 'enforced' : 'shadow', control_digest: controlDigest, updated_at: now() }
    if (!row.project_ref || !row.safe_harbor_key) throw createError({ statusCode: 400, message: 'project_and_safe_harbor_required' })
    if (values.activate === true && compiled.ready !== true) throw createError({ statusCode: 409, message: 'safe_harbor_conditions_not_verified' })
    return (await sb.from('regulatory_safe_harbor_controls').upsert(row, { onConflict: 'control_digest' }).select().single()).data
  }
  if (action === 'incident_twin') {
    const outcome = simulateRegulatoryIncident(values)
    const incidentDigest = digest({ organizationId, values, nonce: randomBytes(5).toString('hex') })
    return (await sb.from('regulatory_incident_twins').insert({ organization_id: organizationId, project_ref: bounded(values.project_ref, 160) || null, assumptions: values, ...outcome, incident_digest: incidentDigest }).select().single()).data
  }
  if (action === 'capacity') {
    if (values.explicit_approval !== true && values.status === 'available') throw createError({ statusCode: 400, message: 'explicit_capacity_approval_required' })
    const row = { organization_id: organizationId, relationship_id: values.relationship_id || null, capability: bounded(values.capability, 160), jurisdictions: (values.jurisdictions || []).slice(0, 30), capacity_units: Math.max(0, Number(values.capacity_units || 0)), used_units: 0, eligibility_constraints: (values.eligibility_constraints || []).slice(0, 30), pricing_model: values.pricing_model || {}, correlation_limits: values.correlation_limits || {}, consent_mode: 'per_match', status: values.status === 'available' ? 'available' : 'shadow', updated_at: now() }
    return (await sb.from('regulatory_supervisory_capacity').insert(row).select().single()).data
  }
  if (action === 'match_capacity') {
    const { data: offers } = await sb.from('regulatory_supervisory_capacity').select('*').eq('status', 'available').limit(200)
    return { matches: matchSupervisoryCapacity({ offers: offers || [], demand: { capability: bounded(values.capability, 160), jurisdiction: bounded(values.jurisdiction, 80), units: Math.max(1, Number(values.units || 1)), readiness_score: clamp(Number(values.readiness_score || 0)) } }), activation_requires_bilateral_approval: true }
  }
  throw createError({ statusCode: 400, message: 'unknown_opportunity_action' })
}

export async function opportunityCockpit(organizationId: string) {
  const sb = serviceClient()
  const [counterfactuals, portability, capacity, safeHarbors, incidents, feedback] = await Promise.all([
    sb.from('regulatory_counterfactual_opportunities').select('*').eq('organization_id', organizationId).in('status', ['proposed','selected','preparing']).order('expected_value_cents', { ascending: false }).limit(30),
    sb.from('regulatory_portability_opportunities').select('*').eq('organization_id', organizationId).eq('status', 'available').order('predicted_cost_saved_cents', { ascending: false }).limit(30),
    sb.from('regulatory_supervisory_capacity').select('*').eq('organization_id', organizationId).order('updated_at', { ascending: false }).limit(30),
    sb.from('regulatory_safe_harbor_controls').select('*').eq('organization_id', organizationId).eq('status', 'current').limit(30),
    sb.from('regulatory_incident_twins').select('*').eq('organization_id', organizationId).order('created_at', { ascending: false }).limit(20),
    sb.from('regulatory_feedback_patterns').select('*').eq('privacy_threshold_met', true).in('status', ['eligible','adopted']).order('support_score', { ascending: false }).limit(20),
  ])
  const opportunities = counterfactuals.data || []
  return { counterfactuals: opportunities, proactive_unlock: opportunities[0] || null, portability: portability.data || [], capacity: capacity.data || [], safe_harbors: safeHarbors.data || [], incident_twins: incidents.data || [], feedback_patterns: feedback.data || [], summary: { modeled_market_value_cents: opportunities.reduce((sum: number, x: any) => sum + Number(x.expected_value_cents || 0), 0), portable_time_saved_days: (portability.data || []).reduce((sum: number, x: any) => sum + Number(x.predicted_time_saved_days || 0), 0), eligible_feedback_patterns: (feedback.data || []).length } }
}
