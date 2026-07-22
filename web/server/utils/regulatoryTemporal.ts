import { createHash, randomBytes } from 'node:crypto'
import { serviceClient } from './fleetSupabase'

const now = () => new Date().toISOString()
const bounded = (value: any, limit = 400) => String(value || '').trim().slice(0, limit)
const stable = (value: any): string => Array.isArray(value) ? `[${value.map(stable).join(',')}]` : value && typeof value === 'object' ? `{${Object.keys(value).sort().map(key => `${key}:${stable(value[key])}`).join(',')}}` : JSON.stringify(value)
const digest = (value: any) => createHash('sha256').update(stable(value)).digest('hex')
const addDays = (date: Date, days: number) => new Date(date.getTime() + days * 86400_000).toISOString()

export function simulateAuthorityTimeline(input: any) {
  const start = new Date(input.start_at || Date.now())
  const jurisdictions = (input.jurisdictions || ['US-general']).slice(0, 20)
  const growth = Math.max(0, Number(input.monthly_growth_rate || 0))
  const expiryDays = Math.max(1, Number(input.license_expires_in_days || 365))
  const ownershipChangeDays = input.ownership_change_in_days == null ? null : Math.max(0, Number(input.ownership_change_in_days))
  const lawChangeDays = input.law_change_in_days == null ? null : Math.max(0, Number(input.law_change_in_days))
  const baseReadiness = Math.max(0, Math.min(100, Number(input.readiness_score || 0)))
  const sequenced = jurisdictions.map((jurisdiction: string, index: number) => {
    const burden = Number(input.jurisdiction_burden?.[jurisdiction] ?? (35 + index * 8))
    const sponsorDays = Number(input.sponsor_days?.[jurisdiction] ?? 45)
    const licenseDays = Number(input.license_days?.[jurisdiction] ?? 180)
    const demand = Number(input.demand_score?.[jurisdiction] ?? Math.max(35, 90 - index * 8))
    const timingScore = Math.round(demand * .42 + baseReadiness * .28 + Math.max(0, 100 - burden) * .3)
    const route = sponsorDays < licenseDays * .55 ? 'sponsor_then_license' : 'license_direct'
    return { jurisdiction, order: index + 1, timing_score: timingScore, recommended_route: route, earliest_sponsor_at: addDays(start, sponsorDays), earliest_license_at: addDays(start, licenseDays), burden_score: burden, demand_score: demand }
  }).sort((a: any, b: any) => b.timing_score - a.timing_score).map((item: any, index: number) => ({ ...item, order: index + 1 }))
  const triggers = [
    { at: addDays(start, Math.max(1, expiryDays - 120)), type: 'renewal_window', effect: 'Begin renewal evidence and continuity plan.' },
    { at: addDays(start, expiryDays), type: 'license_expiry', effect: 'Authority becomes unavailable unless renewed or replaced.' },
    ownershipChangeDays == null ? null : { at: addDays(start, ownershipChangeDays), type: 'ownership_change', effect: 'Reassess control-person eligibility, disclosures, and change-of-control approvals.' },
    lawChangeDays == null ? null : { at: addDays(start, lawChangeDays), type: 'law_change', effect: 'Recompile affected activity boundaries and feature states.' },
    growth > .1 ? { at: addDays(start, 90), type: 'growth_threshold', effect: 'Reprice supervision and validate capital, complaint, and staffing capacity.' } : null,
  ].filter(Boolean)
  const confidence = Math.max(.35, Math.min(.92, .48 + Math.min(10, jurisdictions.length) * .025 + (input.verified_inputs || 0) * .035))
  return {
    jurisdiction_sequence: sequenced,
    authority_timeline: triggers,
    cade_prediction: {
      confidence: Number(confidence.toFixed(2)),
      predicted_best_entry: sequenced[0]?.jurisdiction || null,
      timing_advisory: sequenced[0] ? `Begin ${sequenced[0].recommended_route.replaceAll('_', ' ')} in ${sequenced[0].jurisdiction}; preserve optionality elsewhere until readiness or demand changes.` : 'Add jurisdictions and evidence to generate timing guidance.',
      uncertainty_drivers: ['regulator discretion', 'fact classification', 'processing time', 'counterparty capacity'],
    },
    recommended_plan: sequenced.slice(0, 5).map((item: any) => ({ order: item.order, jurisdiction: item.jurisdiction, route: item.recommended_route, start_at: addDays(start, Math.max(0, (item.order - 1) * 30)), decision_gate: item.recommended_route === 'sponsor_then_license' ? 'sponsor diligence and economics' : 'application readiness review' })),
    invalidation_triggers: triggers.map((trigger: any) => ({ type: trigger.type, re_simulate: true })),
  }
}

export function compileAgreementControls(input: any) {
  const terms = (input.terms || []).slice(0, 100)
  const controls: any[] = []
  const obligations: any[] = []
  for (const term of terms) {
    const text = bounded(term.text || term, 700)
    const key = bounded(term.key || digest(text).slice(0, 12), 80)
    if (/limit|maximum|cap|no more than|volume/i.test(text)) controls.push({ key, type: 'limit', source_text_digest: digest(text), enforcement: 'hold_and_review', value: term.value ?? null })
    if (/prior (written )?approval|consent|required before/i.test(text)) controls.push({ key, type: 'approval_gate', source_text_digest: digest(text), enforcement: 'require_explicit_approval' })
    if (/report|notice|deliver|provide.*within|monthly|quarterly/i.test(text)) obligations.push({ key, type: 'reporting', cadence: term.cadence || 'event_driven', due_days: Number(term.due_days || 10) })
    if (/terminate|suspend|immediately cease|material breach/i.test(text)) controls.push({ key, type: 'termination', source_text_digest: digest(text), enforcement: 'contain_then_escalate', cure_days: Number(term.cure_days || 0) })
    if (/service level|uptime|response time|sla/i.test(text)) obligations.push({ key, type: 'service_level', target: term.value || term.target || null, cadence: term.cadence || 'monthly' })
    if (/fee|payment|revenue share|commission|minimum/i.test(text)) obligations.push({ key, type: 'economic', target: term.value || null, cadence: term.cadence || 'monthly' })
  }
  return {
    interpreted_terms: { term_count: terms.length, raw_terms_stored: false },
    executable_controls: controls,
    approval_gates: controls.filter(control => control.type === 'approval_gate'),
    reporting_schedule: obligations.filter(obligation => obligation.type === 'reporting'),
    termination_rules: controls.filter(control => control.type === 'termination'),
    obligations,
    interpretation_confidence: Number(Math.min(.92, .45 + Math.min(20, controls.length + obligations.length) * .025).toFixed(2)),
  }
}

export function evaluateAgreementAction(controls: any[], action: any) {
  const reasons: any[] = []
  let decision: 'allow' | 'review' | 'block' = 'allow'
  for (const control of controls || []) {
    if (control.type === 'approval_gate' && action.material === true && action.approved !== true) {
      reasons.push({ control: control.key, reason: 'explicit_approval_required' }); decision = 'block'
    }
    if (control.type === 'limit' && control.value != null) {
      const actual = Number(action.metrics?.[control.key] ?? action.value ?? 0)
      if (actual > Number(control.value)) { reasons.push({ control: control.key, reason: 'agreement_limit_exceeded', actual, limit: Number(control.value) }); decision = 'block' }
    }
    if (control.type === 'termination' && action.material_breach === true) {
      reasons.push({ control: control.key, reason: 'termination_or_suspension_triggered' }); decision = 'block'
    }
  }
  if (decision === 'allow' && Number(action.confidence ?? 1) < .65) { decision = 'review'; reasons.push({ reason: 'insufficient_fact_confidence' }) }
  return { decision, reasons, evaluated_at: now(), default_allow_without_applicable_control: true }
}

export function evidenceRoomStatus(requirements: any[], items: any[], at = new Date()) {
  const byKey = new Map<string, any[]>(items.map(item => [item.requirement_key, [...(items.filter(candidate => candidate.requirement_key === item.requirement_key))]]))
  const results = requirements.map(requirement => {
    const evidence = byKey.get(requirement.key) || []
    const verified = evidence.find(item => item.verification_status === 'verified' && (!item.expires_at || new Date(item.expires_at) > at))
    const stale = evidence.some(item => item.verification_status === 'stale' || (item.expires_at && new Date(item.expires_at) <= at))
    const contradicted = evidence.some(item => item.verification_status === 'contradicted')
    return { key: requirement.key, label: requirement.label, required: requirement.required !== false, satisfied: Boolean(verified) && !contradicted, stale, contradicted }
  })
  const required = results.filter(item => item.required)
  const completeness = required.length ? Math.round(required.filter(item => item.satisfied).length / required.length * 100) : 100
  const freshness = required.length ? Math.round(required.filter(item => item.satisfied && !item.stale).length / required.length * 100) : 100
  return { completeness_score: completeness, freshness_score: freshness, contradiction_count: results.filter(item => item.contradicted).length, manifest: { requirements: results, generated_at: at.toISOString() }, status: completeness === 100 && freshness >= 90 ? 'application_ready' : completeness >= 70 ? 'review_ready' : 'building' }
}

export function planJurisdictionFeature(input: any) {
  const covered = Boolean(input.covered)
  const variants = [
    { state: 'disabled', label: 'Disable regulated action', changes: ['hide initiation control', 'block API execution', 'preserve read-only history'], residual_risk: 'low' },
    { state: 'adjusted', label: 'Use licensed-provider handoff', changes: ['replace execution with provider redirect', 'show provider identity', 'remove member discretion and fund control'], residual_risk: 'medium' },
    { state: 'adjusted', label: 'Referral/information-only mode', changes: ['remove recommendation and negotiation', 'use neutral factual copy', 'apply compensation boundary'], residual_risk: 'medium' },
    { state: 'enabled', label: 'Enable after authority verified', changes: ['verify relationship and jurisdiction', 'attach receipt to feature gate', 'monitor expiry and scope'], residual_risk: 'low' },
  ]
  const effectiveState = covered ? 'enabled' : input.preferred_variant === 'provider_handoff' ? 'adjusted' : 'shadow'
  return {
    required_authority: input.required_authority || { activity: input.activity, jurisdiction: input.jurisdiction },
    current_coverage: { covered, verified_at: input.coverage_verified_at || null },
    compliant_variants: variants,
    activation_plan: (covered ? variants[3] : variants[0]).changes.map((change, index) => ({ order: index + 1, change, reversible: true, qa_required: true })),
    effective_state: effectiveState,
    one_click_action: { action: covered ? 'activate_verified' : 'prepare_variant', variant: covered ? 'enabled' : 'disabled', requires_approval: true, requires_qa: true, rollback_required: true },
  }
}

export function compareLicenseStrategies(input: any) {
  const monthlyValue = Math.max(0, Number(input.monthly_value_cents || 100_000))
  const horizonMonths = Math.max(3, Number(input.horizon_months || 36))
  const options = [
    { option_type: 'obtain_license', title: 'Obtain the license', months: Number(input.license_months || 9), direct: Number(input.license_direct_cents || 250_000), monthly: Number(input.license_monthly_cents || 20_000), opportunity: Number(input.license_months || 9) * monthlyValue, control: 95, risk: 45 },
    { option_type: 'sponsor', title: 'Use a supervised sponsor', months: Number(input.sponsor_months || 2), direct: Number(input.sponsor_setup_cents || 75_000), monthly: Number(input.sponsor_monthly_cents || 50_000), opportunity: Number(input.sponsor_months || 2) * monthlyValue, control: 55, risk: 38 },
    { option_type: 'restructure', title: 'Restructure the regulated boundary', months: Number(input.restructure_months || 1), direct: Number(input.restructure_cents || 90_000), monthly: Number(input.restructure_monthly_cents || 8_000), opportunity: Number(input.restructure_months || 1) * monthlyValue, control: 75, risk: 55 },
    { option_type: 'acquire_entity', title: 'Acquire a regulated entity', months: Number(input.acquisition_months || 6), direct: Number(input.acquisition_cents || 2_500_000), monthly: Number(input.acquisition_monthly_cents || 80_000), opportunity: Number(input.acquisition_months || 6) * monthlyValue, control: 90, risk: 75 },
    { option_type: 'referral', title: 'Operate as referral only', months: 1, direct: Number(input.referral_setup_cents || 25_000), monthly: Number(input.referral_monthly_cents || 3_000), opportunity: Math.round(horizonMonths * monthlyValue * .55), control: 35, risk: 25 },
    { option_type: 'abandon', title: 'Do not enter', months: 0, direct: 0, monthly: 0, opportunity: horizonMonths * monthlyValue, control: 100, risk: 5 },
  ]
  return options.map(option => {
    const operating = option.monthly * horizonMonths
    const totalCost = option.direct + operating + option.opportunity
    const valueCaptured = Math.max(0, monthlyValue * Math.max(0, horizonMonths - option.months) - operating)
    const score = Math.round(Math.max(0, Math.min(100, valueCaptured / Math.max(1, monthlyValue * horizonMonths) * 55 + option.control * .25 + (100 - option.risk) * .2)))
    return {
      option_type: option.option_type, title: option.title,
      assumptions: { horizon_months: horizonMonths, monthly_value_cents: monthlyValue },
      timeline: { estimated_months: option.months, time_to_revenue_months: option.months },
      direct_costs: { setup_cents: option.direct, operating_cents: operating, total_cents: option.direct + operating },
      indirect_costs: { opportunity_cost_cents: option.opportunity, management_complexity: Math.round((100 - option.control) / 10) },
      expected_value: { value_captured_cents: valueCaptured, total_economic_cost_cents: totalCost },
      risks: [{ category: 'regulatory_execution', score: option.risk }, { category: 'dependency_control', score: 100 - option.control }],
      dependencies: option.option_type === 'sponsor' ? ['qualified sponsor', 'executed agreement', 'supervision activation'] : option.option_type === 'obtain_license' ? ['eligibility evidence', 'application', 'regulator action'] : [],
      cade_score: { score, confidence: .67, explanation: 'Score balances time, direct and indirect cost, retained control, execution risk, and expected value.' },
      activation_action: { assistance_type: option.option_type === 'sponsor' ? 'relationship' : option.option_type === 'obtain_license' ? 'application' : 'business_model', provider: option.option_type === 'sponsor' ? 'combined' : 'apparently', requires_explicit_approval: true },
    }
  }).sort((a, b) => b.cade_score.score - a.cade_score.score)
}

async function buildEvidenceRooms(organizationId: string) {
  const sb = serviceClient()
  const { data: paths } = await sb.from('regulatory_readiness_paths').select('*').eq('organization_id', organizationId).neq('simulation_status', 'paused')
  let updated = 0
  for (const path of paths || []) {
    let { data: room } = await sb.from('regulatory_evidence_rooms').select('*').eq('organization_id', organizationId).eq('target_capability', path.target_capability).eq('jurisdiction', path.jurisdiction).eq('purpose', 'shadow_license').maybeSingle()
    if (!room) {
      const seed = { organization_id: organizationId, readiness_path_id: path.id, target_capability: path.target_capability, jurisdiction: path.jurisdiction, purpose: 'shadow_license', manifest: {}, room_digest: digest({ organizationId, path: path.id, purpose: 'shadow_license' }) }
      room = (await sb.from('regulatory_evidence_rooms').insert(seed).select().single()).data
    }
    if (!room) continue
    const { data: items } = await sb.from('regulatory_evidence_items').select('*').eq('room_id', room.id)
    const status = evidenceRoomStatus(path.requirements || [], items || [])
    const eligibilityEffects = status.manifest.requirements.filter((item: any) => item.stale || item.contradicted).map((item: any) => ({ requirement_key: item.key, effect: item.contradicted ? 'may_make_ineligible' : 'may_delay_or_block', action: 'review_and_replace_evidence' }))
    await sb.from('regulatory_evidence_rooms').update({ ...status, eligibility_effects: eligibilityEffects, predicted_activation_at: path.earliest_eligible_at, updated_at: now() }).eq('id', room.id)
    updated += 1
  }
  return updated
}

async function generateStrategyOptions(organizationId: string) {
  const sb = serviceClient()
  const { data: paths } = await sb.from('regulatory_readiness_paths').select('*').eq('organization_id', organizationId).in('simulation_status', ['shadow','eligible','application_ready']).limit(20)
  let count = 0
  for (const path of paths || []) {
    const options = compareLicenseStrategies({ readiness_score: path.readiness_score })
    for (const option of options) {
      const optionDigest = digest({ organizationId, path: path.id, type: option.option_type, assumptions: option.assumptions })
      await sb.from('regulatory_strategy_options').upsert({ organization_id: organizationId, readiness_path_id: path.id, ...option, option_digest: optionDigest }, { onConflict: 'option_digest' })
      count += 1
    }
  }
  return count
}

async function generateTemporalScenarios(organizationId: string) {
  const sb = serviceClient()
  const [{ data: profile }, { data: paths }] = await Promise.all([
    sb.from('regulatory_capability_profiles').select('*').eq('organization_id', organizationId).maybeSingle(),
    sb.from('regulatory_readiness_paths').select('*').eq('organization_id', organizationId),
  ])
  const jurisdictions = profile?.jurisdictions?.length ? profile.jurisdictions : [...new Set((paths || []).map((path: any) => path.jurisdiction))]
  const readiness = (paths || []).length ? Math.round((paths || []).reduce((sum: number, path: any) => sum + Number(path.readiness_score || 0), 0) / paths!.length) : 0
  const simulation = simulateAuthorityTimeline({ jurisdictions: jurisdictions.length ? jurisdictions : ['US-general'], readiness_score: readiness, verified_inputs: (paths || []).filter((path: any) => path.readiness_score > 0).length })
  const scenarioDigest = digest({ organizationId, jurisdictions, readiness, day: now().slice(0, 10) })
  await sb.from('regulatory_temporal_scenarios').upsert({ organization_id: organizationId, scenario_type: 'combined', assumptions: { jurisdictions, readiness_score: readiness }, horizon_end: addDays(new Date(), 730), ...simulation, scenario_digest: scenarioDigest }, { onConflict: 'scenario_digest' })
  return 1
}

async function monitorObligations(organizationId: string) {
  const sb = serviceClient()
  const { data: obligations } = await sb.from('regulatory_obligation_ledger').select('*').eq('organization_id', organizationId).in('status', ['pending','at_risk']).limit(100)
  let atRisk = 0
  for (const obligation of obligations || []) {
    if (!obligation.due_at) continue
    const days = (new Date(obligation.due_at).getTime() - Date.now()) / 86400_000
    const status = days < 0 ? 'breached' : days <= 7 ? 'at_risk' : obligation.status
    if (status !== obligation.status) await sb.from('regulatory_obligation_ledger').update({ status, measured_at: now(), deviation: { type: days < 0 ? 'past_due' : 'due_soon', days: Math.round(days) } }).eq('id', obligation.id)
    if (['at_risk','breached'].includes(status)) atRisk += 1
  }
  return atRisk
}

export async function runTemporalRegulatoryAutopilot(organizationId: string) {
  const [evidenceRooms, strategyOptions, scenarios, obligationsAtRisk] = await Promise.all([
    buildEvidenceRooms(organizationId), generateStrategyOptions(organizationId), generateTemporalScenarios(organizationId), monitorObligations(organizationId),
  ])
  return { evidence_rooms_updated: evidenceRooms, strategy_options_updated: strategyOptions, scenarios_updated: scenarios, obligations_at_risk: obligationsAtRisk }
}

export async function saveTemporalScenario(organizationId: string, values: any) {
  const simulation = simulateAuthorityTimeline(values)
  const assumptions = { jurisdictions: values.jurisdictions || [], readiness_score: values.readiness_score || 0, monthly_growth_rate: values.monthly_growth_rate || 0, license_expires_in_days: values.license_expires_in_days || null, ownership_change_in_days: values.ownership_change_in_days ?? null, law_change_in_days: values.law_change_in_days ?? null }
  const row = { organization_id: organizationId, project_ref: bounded(values.project_ref, 160) || null, scenario_type: values.scenario_type || 'combined', assumptions, horizon_end: addDays(new Date(), Number(values.horizon_days || 730)), ...simulation, scenario_digest: digest({ organizationId, assumptions, nonce: randomBytes(5).toString('hex') }) }
  const { data, error } = await serviceClient().from('regulatory_temporal_scenarios').insert(row).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  return data
}

export async function saveAgreementControls(organizationId: string, userId: string, values: any) {
  const sb = serviceClient()
  const agreementRef = bounded(values.agreement_ref, 240)
  if (!agreementRef) throw createError({ statusCode: 400, message: 'agreement_ref_required' })
  const compiled = compileAgreementControls(values)
  const agreementDigest = digest({ organizationId, agreementRef, terms: (values.terms || []).map((term: any) => digest(bounded(term.text || term, 700))) })
  const status = values.activate === true ? 'active' : 'shadow'
  const { data: control, error } = await sb.from('regulatory_agreement_controls').insert({ organization_id: organizationId, relationship_id: values.relationship_id || null, agreement_ref: agreementRef, agreement_digest: agreementDigest, interpreted_terms: compiled.interpreted_terms, executable_controls: compiled.executable_controls, approval_gates: compiled.approval_gates, reporting_schedule: compiled.reporting_schedule, termination_rules: compiled.termination_rules, interpretation_confidence: compiled.interpretation_confidence, activation_approved_at: values.activate === true ? now() : null, activated_by: values.activate === true ? userId : null, status }).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  for (const obligation of compiled.obligations) await sb.from('regulatory_obligation_ledger').insert({ organization_id: organizationId, agreement_control_id: control.id, relationship_id: values.relationship_id || null, obligor_ref: bounded(values.obligor_ref || 'organization', 160), beneficiary_ref: bounded(values.beneficiary_ref, 160) || null, obligation_key: obligation.key, obligation_type: obligation.type, target_value: obligation.target == null ? null : { value: obligation.target }, due_at: obligation.due_days ? addDays(new Date(), obligation.due_days) : null })
  return { control, obligations_created: compiled.obligations.length, mode: status }
}

export async function saveFeatureControl(organizationId: string, userId: string, values: any) {
  const plan = planJurisdictionFeature(values)
  const activate = values.activate === true
  const row = { organization_id: organizationId, project_ref: bounded(values.project_ref, 160), feature_key: bounded(values.feature_key, 160), jurisdiction: bounded(values.jurisdiction || 'US-general', 80), activity: bounded(values.activity, 120), ...plan, enforcement_mode: activate ? 'enforced' : 'shadow', desired_state: values.desired_state || 'available_when_covered', effective_state: activate ? plan.effective_state : 'shadow', activated_at: activate ? now() : null, activated_by: activate ? userId : null, control_digest: digest({ organizationId, project: values.project_ref, feature: values.feature_key, jurisdiction: values.jurisdiction }) , updated_at: now() }
  if (!row.project_ref || !row.feature_key || !row.activity) throw createError({ statusCode: 400, message: 'project_feature_activity_required' })
  const { data, error } = await serviceClient().from('regulatory_feature_controls').upsert(row, { onConflict: 'organization_id,project_ref,feature_key,jurisdiction' }).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  return data
}

export async function electCadeSettlement(organizationId: string, values: any) {
  if (values.organization_approve !== true) throw createError({ statusCode: 400, message: 'explicit_settlement_election_required' })
  const row = { organization_id: organizationId, agreement_control_id: values.agreement_control_id, counterparty_organization_id: values.counterparty_organization_id || null, scope: values.scope || { contract_disputes: true, exclusions: ['criminal','injunctive_relief','non_arbitrable'] }, tier_structure: values.tier_structure || { initial: 'standard', appeal: 'enhanced', final: 'extreme' }, fee_structure: values.fee_structure || { initial_cents: 25_000, appeal_cents: 100_000, final_cents: 500_000, loser_pays: false }, evidence_rules: values.evidence_rules || { broad_submission: true, privilege_preserved: true, authenticity_required: true, adversarial_response: true }, governing_terms_ref: bounded(values.governing_terms_ref, 240) || null, organization_approved_at: now(), status: values.counterparty_organization_id ? 'pending_counterparty' : 'offered' }
  const { data, error } = await serviceClient().from('regulatory_cade_settlement_elections').upsert(row, { onConflict: 'agreement_control_id' }).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  return data
}

export async function selectStrategyOption(organizationId: string, optionId: string) {
  const sb = serviceClient()
  const { data: option } = await sb.from('regulatory_strategy_options').select('*').eq('id', optionId).eq('organization_id', organizationId).maybeSingle()
  if (!option) throw createError({ statusCode: 404, message: 'strategy_option_not_found' })
  await sb.from('regulatory_strategy_options').update({ status: 'selected' }).eq('id', option.id)
  return { option: { ...option, status: 'selected' }, next_action: option.activation_action, external_action_requires_confirmation: true }
}

export async function runtimeFeaturePolicy(organizationId: string, values: any) {
  const sb = serviceClient()
  const projectRef = bounded(values.project_ref, 160)
  const jurisdiction = bounded(values.jurisdiction || 'US-general', 80)
  const requested = (values.features || []).slice(0, 100).map((value: any) => bounded(value, 160))
  const { data } = await sb.from('regulatory_feature_controls').select('*').eq('organization_id', organizationId).eq('project_ref', projectRef).eq('jurisdiction', jurisdiction).in('feature_key', requested)
  const byFeature = new Map((data || []).map((control: any) => [control.feature_key, control]))
  return {
    organization_id: organizationId, project_ref: projectRef, jurisdiction,
    decisions: requested.map((featureKey: string) => {
      const control: any = byFeature.get(featureKey)
      if (!control) return { feature_key: featureKey, state: 'unchanged', enforcement: 'none', reason: 'no_applicable_control' }
      return { feature_key: featureKey, state: control.effective_state, enforcement: control.enforcement_mode, reason: control.current_coverage?.covered ? 'authority_verified' : 'authority_not_verified', plan: control.activation_plan, control_digest: control.control_digest }
    }),
    cache_ttl_seconds: 60,
  }
}

export async function runtimeAgreementPolicy(organizationId: string, values: any) {
  const sb = serviceClient()
  const { data: control } = await sb.from('regulatory_agreement_controls').select('*').eq('id', values.agreement_control_id).eq('organization_id', organizationId).eq('status', 'active').maybeSingle()
  if (!control) return { decision: 'review', reasons: [{ reason: 'active_agreement_control_not_found' }] }
  return { ...evaluateAgreementAction(control.executable_controls || [], values.action || {}), agreement_control_id: control.id, control_version: control.control_version }
}

export async function recordRuntimeEvidence(organizationId: string, values: any) {
  const boundedFacts = Object.fromEntries(Object.entries(values.bounded_facts || {}).slice(0, 30).map(([key, value]) => [bounded(key, 80), typeof value === 'string' ? bounded(value, 240) : value]))
  const evidenceDigest = digest({ organizationId, room: values.room_id, requirement: values.requirement_key, source: values.source_ref, boundedFacts })
  const { data, error } = await serviceClient().from('regulatory_evidence_items').upsert({ room_id: values.room_id, organization_id: organizationId, requirement_key: bounded(values.requirement_key, 120), evidence_type: bounded(values.evidence_type || 'runtime_receipt', 80), source_system: bounded(values.source_system, 120), source_ref: bounded(values.source_ref, 240), evidence_digest: evidenceDigest, bounded_facts: boundedFacts, observed_at: values.observed_at || now(), expires_at: values.expires_at || null, verification_status: values.verification_status === 'verified' ? 'verified' : 'unverified', verified_by: values.verification_status === 'verified' ? bounded(values.verified_by || values.source_system, 120) : null }, { onConflict: 'room_id,requirement_key,evidence_digest' }).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  return { evidence: data, raw_payload_stored: false }
}

export async function measureRuntimeObligation(organizationId: string, values: any) {
  const sb = serviceClient()
  const { data: obligation } = await sb.from('regulatory_obligation_ledger').select('*').eq('id', values.obligation_id).eq('organization_id', organizationId).maybeSingle()
  if (!obligation) throw createError({ statusCode: 404, message: 'obligation_not_found' })
  const satisfied = values.satisfied === true
  const status = satisfied ? 'satisfied' : values.disputed === true ? 'disputed' : 'at_risk'
  const measured = { value: values.value, unit: bounded(values.unit, 40), source_ref: bounded(values.source_ref, 240) }
  const { data, error } = await sb.from('regulatory_obligation_ledger').update({ measured_value: measured, direct_cost_cents: Math.max(0, Number(values.direct_cost_cents || 0)), indirect_cost_cents: Math.max(0, Number(values.indirect_cost_cents || 0)), evidence_refs: [{ source_ref: measured.source_ref, digest: digest(measured) }], deviation: satisfied ? null : { expected: obligation.target_value, actual: measured }, status, measured_at: now() }).eq('id', obligation.id).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  return data
}
