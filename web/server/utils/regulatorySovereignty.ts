import { createHash, randomBytes } from 'node:crypto'
import { serviceClient } from './fleetSupabase'

const now = () => new Date().toISOString()
const bounded = (value: any, limit = 400) => String(value || '').trim().slice(0, limit)
const clamp = (value: number, min = 0, max = 100) => Math.max(min, Math.min(max, value))
const stable = (value: any): string => Array.isArray(value) ? `[${value.map(stable).join(',')}]` : value && typeof value === 'object' ? `{${Object.keys(value).sort().map(key => `${key}:${stable(value[key])}`).join(',')}}` : JSON.stringify(value)
const digest = (value: any) => createHash('sha256').update(stable(value)).digest('hex')

export function attestProductBehavior(input: any) {
  const proofSets: Record<string, any[]> = {
    authority: input.authority_receipts || [], agreement: input.agreement_receipts || [], evidence: input.evidence_receipts || [],
    prediction: input.prediction_receipts || [], approval: input.approval_receipts || [], fallback: input.fallback_receipt ? [input.fallback_receipt] : [], rollback: input.rollback_receipt ? [input.rollback_receipt] : [],
  }
  const required = (input.required_proofs || ['authority','evidence','fallback','rollback']).slice(0, 20)
  const missing = required.filter((key: string) => !(proofSets[key] || []).some((proof: any) => proof.valid !== false && (!proof.expires_at || new Date(proof.expires_at).getTime() > Date.now())))
  const expires = Object.values(proofSets).flat().map((x: any) => x?.expires_at && new Date(x.expires_at).getTime()).filter(Boolean)
  const expiresAt = new Date(Math.min(Date.now() + 24 * 3600_000, ...(expires.length ? expires : [Date.now() + 15 * 60_000]))).toISOString()
  return { authority_receipts: proofSets.authority, agreement_receipts: proofSets.agreement, evidence_receipts: proofSets.evidence, prediction_receipts: proofSets.prediction, approval_receipts: proofSets.approval, fallback_receipt: input.fallback_receipt || {}, rollback_receipt: input.rollback_receipt || {}, effective_behavior: missing.length ? { state: 'held', lawful_fallback: input.fallback_receipt?.mode || 'disabled' } : input.effective_behavior || { state: 'enabled' }, missing_proofs: missing, expires_at: expiresAt, status: missing.length ? 'incomplete' : 'valid' }
}

export function compileEntityJurisdictionStructure(input: any) {
  const markets = (input.markets || []).slice(0, 50)
  const entities = (input.entities || [{ key: 'parent', jurisdiction: input.parent_jurisdiction || 'US' }]).slice(0, 50)
  const plan = markets.map((market: any, index: number) => {
    const own = Number(market.license_months || 12); const sponsor = Number(market.sponsor_months || 2)
    const route = market.sponsor_available && sponsor < own * .6 ? 'sponsor_then_local_entity' : market.acquisition_available && Number(market.acquisition_months || 9) < own ? 'acquire_regulated_entity' : 'local_entity_and_license'
    return { order: index + 1, jurisdiction: market.jurisdiction, route, authority_months: route === 'sponsor_then_local_entity' ? sponsor : route === 'acquire_regulated_entity' ? Number(market.acquisition_months || 9) : own, change_control_required: route === 'acquire_regulated_entity', regulator_preclearance: Boolean(market.regulator_preclearance) }
  }).sort((a, b) => a.authority_months - b.authority_months)
  const setup = plan.reduce((sum, x) => sum + (x.route === 'acquire_regulated_entity' ? 750_000 : x.route === 'sponsor_then_local_entity' ? 150_000 : 300_000), 0)
  return { entity_graph: { entities, ownership_edges: entities.slice(1).map((entity: any) => ({ from: 'parent', to: entity.key, control: 'subject_to_local_requirements' })) }, jurisdiction_plan: plan, ownership_controls: ['change_control_preclearance','beneficial_owner_monitoring','fit_and_proper_refresh'], intercompany_agreements: ['services_and_ip','data_processing','cost_allocation','supervision_and_escalation'], staffing_plan: plan.map(x => ({ jurisdiction: x.jurisdiction, roles: ['responsible_officer','compliance_contact'], before_activation: true })), authority_plan: plan, tax_coordination_flags: ['permanent_establishment','transfer_pricing','withholding','indirect_tax'], timeline: { critical_path_months: Math.max(0, ...plan.map(x => x.authority_months)), sequencing: plan.map(x => x.jurisdiction) }, costs: { setup_cents: setup, annual_carry_cents: plan.length * 120_000 }, expected_value_cents: markets.reduce((s: number, x: any) => s + Number(x.expected_value_cents || 0), 0), residual_risks: ['local_counsel_confirmation','tax_advice_required','regulator_discretion','counterparty_acceptance'], execution_requires_separate_approvals: true }
}

export function simulateRegulatoryCatastrophe(input: any) {
  const shocks = (input.shocks || []).slice(0, 100)
  const dependencies = (input.dependencies || []).slice(0, 2_000)
  const failed = new Set(shocks.map((x: any) => String(x.target)))
  let changed = true
  while (changed) { changed = false; for (const edge of dependencies) if (failed.has(String(edge.from)) && Number(edge.transmission_probability || 1) >= Number(input.propagation_threshold || .5) && !failed.has(String(edge.to))) { failed.add(String(edge.to)); changed = true } }
  const exposure = dependencies.filter((x: any) => failed.has(String(x.to))).reduce((s: number, x: any) => s + Number(x.exposure_cents || 0), 0)
  const fallbackCoverage = clamp(Number(input.fallback_coverage_score || 0))
  const expected = Math.round(exposure * (1 - fallbackCoverage / 100) * .45)
  return { shocks, cascade: [...failed].map((id, index) => ({ order: index + 1, node: id })), affected_capabilities: [...failed], liquidity_effects: { expected_outflow_cents: expected, reserve_shortfall_cents: Math.max(0, expected - Number(input.available_reserve_cents || 0)) }, authority_effects: [...failed].map(node => ({ node, state: 'reverify_or_fallback' })), customer_effects: [{ type: 'service_degradation', mitigated_by_fallback_pct: fallbackCoverage }], containment_plan: ['isolate_failed_dependency','activate_lawful_fallbacks','preserve_customer_access_and_exports','freeze_unproven_activity','open_evidence_room'], recovery_plan: ['replace_or_restore_dependency','refresh_authority_and_contract_receipts','rehearse_exam','canary_reentry'], expected_loss_cents: expected, tail_loss_cents: Math.round(exposure * (1 - fallbackCoverage / 100)), recovery_hours: Math.max(1, failed.size * 8 - fallbackCoverage / 5), resilience_score: Math.round(clamp(100 - failed.size * 8 + fallbackCoverage * .5)) }
}

export function runLaunchTournament(input: any) {
  const candidates = (input.candidates || []).slice(0, 20).map((x: any) => {
    const authority = clamp(Number(x.authority_confidence || 0)); const safety = clamp(100 - Number(x.violation_rate_bps || 0) * 2 - Number(x.critical_events || 0) * 35); const evidence = clamp(Number(x.evidence_completeness || 0)); const value = clamp(Number(x.value_score || 0)); const reversibility = clamp(Number(x.reversibility_score || 0))
    return { ...x, score: Math.round(authority * .25 + safety * .25 + evidence * .2 + value * .2 + reversibility * .1), disqualified: Number(x.critical_events || 0) > 0 || x.authority_valid === false }
  }).sort((a: any, b: any) => Number(a.disqualified) - Number(b.disqualified) || b.score - a.score)
  const winner = candidates.find((x: any) => !x.disqualified) || null
  return { candidates, evaluation_metrics: { weights: { authority: .25, safety: .25, evidence: .2, value: .2, reversibility: .1 }, fail_closed: ['critical_event','invalid_authority'] }, winner, promotion_receipt: winner ? { candidate_key: winner.key, score: winner.score, promotion_requires_approval: true, restart_at: 'shadow' } : null, status: winner ? 'winner_ready' : 'shadow' }
}

export function prepareSupervisoryPacket(input: any) {
  const facts = Object.fromEntries(Object.entries(input.bounded_facts || {}).slice(0, 50))
  const contradictions = (input.evidence || []).filter((x: any) => x.status === 'contradicted').map((x: any) => ({ key: x.key, refs: x.refs || [] }))
  const issues = (input.issues || []).slice(0, 50).map((issue: any, index: number) => ({ order: index + 1, question: bounded(issue.question || issue, 300), rule: issue.rule_ref || null, facts: issue.fact_refs || [], unresolved: issue.resolved !== true }))
  return { issue_tree: issues, bounded_facts: facts, authority_refs: (input.authority_refs || []).slice(0, 50), evidence_manifest: (input.evidence || []).slice(0, 100).map((x: any) => ({ key: x.key, digest: x.digest, status: x.status })), contradictions, options: (input.options || []).slice(0, 20), recommended_questions: issues.filter(x => x.unresolved).map(x => `What evidence would resolve: ${x.question}`), draft_determination: { recommendation: input.recommendation || 'review_required', confidence: Number(input.confidence || .5), not_final: true }, human_judgment_required: ['legal_interpretation','materiality','external_representation','approval_or_signature','conflict_waiver'] }
}

export function valueRegulatoryOption(input: any) {
  const replacement = Math.max(0, Number(input.replacement_cost_cents || 0)); const days = Math.max(0, Number(input.time_to_replace_days || 0)); const carry = Math.max(0, Number(input.annual_carry_cost_cents || 0)); const probability = Math.max(0, Math.min(1, Number(input.probability_of_use || 0))); const enabled = (input.enabled_paths || []).reduce((s: number, x: any) => s + Number(x.expected_value_cents || 0), 0)
  const timeValue = days * Math.max(0, Number(input.daily_delay_cost_cents || 25_000)); const gross = (replacement + timeValue + enabled * .15) * probability
  return { replacement_cost_cents: replacement, time_to_replace_days: days, annual_carry_cost_cents: carry, probability_of_use: probability, strategic_option_value_cents: Math.max(0, Math.round(gross - carry)), decay_triggers: input.decay_triggers || ['expiry','ownership_change','evidence_stale','supervisor_departure','capital_shortfall'], preservation_actions: input.preservation_actions || ['renew_before_window','preserve_clean_history','refresh_evidence','maintain_fallback_provider','retain_required_staff'] }
}

export function forecastExaminerQuestions(input: any) {
  const gaps = (input.missing_evidence || []).slice(0, 50); const incidents = (input.incidents || []).slice(0, 50); const changes = (input.material_changes || []).slice(0, 50)
  const questions = [{ theme: 'authority', question: 'Show how each customer-facing activity maps to current operating authority.', priority: 100 }, ...gaps.map((x: any) => ({ theme: 'evidence', question: `Provide current support for ${x.label || x.key}.`, priority: 85 })), ...incidents.map((x: any) => ({ theme: 'incident', question: `Explain detection, containment, customer impact, and remediation for ${x.type || x.id}.`, priority: 90 })), ...changes.map((x: any) => ({ theme: 'change_management', question: `Show pre-launch analysis, approval, testing, and monitoring for ${x.feature || x.id}.`, priority: 80 }))].sort((a, b) => b.priority - a.priority)
  return { predicted_questions: questions.slice(0, 30), likely_findings: [gaps.length && { code: 'evidence_gap', likelihood: Math.min(.95, .45 + gaps.length * .08) }, incidents.some((x: any) => !x.closed) && { code: 'open_incident', likelihood: .8 }, changes.some((x: any) => !x.authority_receipt) && { code: 'change_without_authority_receipt', likelihood: .85 }].filter(Boolean), missing_evidence: gaps, answer_packets: questions.slice(0, 10).map(x => ({ theme: x.theme, evidence_refs: [], status: 'prepare' })), confidence: Number(Math.min(.92, .5 + Number(input.verified_inputs || 0) * .03).toFixed(2)), invalidation_triggers: ['new_exam_scope','new_authority_source','material_product_change','new_incident'] }
}

export function measureReviewEffectiveness(input: any) {
  const minutes = Math.max(1, Number(input.minutes_spent || 0)); const riskDelta = Number(input.risk_before || 0) - Number(input.risk_after || 0); const valueDelta = Number(input.value_after_cents || 0) - Number(input.value_before_cents || 0); const approvalDelta = Number(input.approval_probability_after || 0) - Number(input.approval_probability_before || 0); const deficiency = Number(input.deficiency_delta || 0)
  const score = Number((riskDelta * .4 + approvalDelta * 100 * .25 + Math.min(100, valueDelta / Math.max(1, Number(input.value_scale_cents || 100_000))) * .2 - deficiency * 5 + Math.min(15, 60 / minutes * 15)).toFixed(2))
  return { minutes_spent: minutes, risk_before: Number(input.risk_before || 0), risk_after: Number(input.risk_after || 0), value_before_cents: Number(input.value_before_cents || 0), value_after_cents: Number(input.value_after_cents || 0), deficiency_delta: deficiency, approval_probability_before: Number(input.approval_probability_before || 0), approval_probability_after: Number(input.approval_probability_after || 0), effectiveness_score: score, lessons: [riskDelta <= 0 && 'review_did_not_reduce_risk', approvalDelta <= 0 && 'review_did_not_improve_approval_probability', valueDelta > 0 && 'review_unlocked_value', minutes > 120 && 'consider_better_apprentice_packet'].filter(Boolean) }
}

export async function saveSovereigntyAction(organizationId: string, action: string, values: any) {
  const sb = serviceClient()
  const insert = async (table: string, row: any) => { const { data, error } = await sb.from(table).insert(row).select().single(); if (error) throw createError({ statusCode: 500, message: error.message }); return data }
  if (action === 'product_attestation') { const result = attestProductBehavior(values); return insert('regulatory_product_attestations', { organization_id: organizationId, project_ref: bounded(values.project_ref, 160), feature_key: bounded(values.feature_key, 160), jurisdiction: bounded(values.jurisdiction, 80), release_ref: bounded(values.release_ref, 240), ...result, attestation_digest: digest({ organizationId, values, result, nonce: randomBytes(4).toString('hex') }) }) }
  if (action === 'structure') { const result = compileEntityJurisdictionStructure(values); return insert('regulatory_structuring_scenarios', { organization_id: organizationId, objective: bounded(values.objective, 500), assumptions: values, ...result, scenario_digest: digest({ organizationId, values, nonce: randomBytes(4).toString('hex') }) }) }
  if (action === 'catastrophe') { const result = simulateRegulatoryCatastrophe(values); return insert('regulatory_catastrophe_scenarios', { organization_id: organizationId, scenario_name: bounded(values.scenario_name || 'combined authority shock', 200), ...result, scenario_digest: digest({ organizationId, values, nonce: randomBytes(4).toString('hex') }) }) }
  if (action === 'launch_tournament') { const result = runLaunchTournament(values); return insert('regulatory_launch_tournaments', { organization_id: organizationId, opportunity_id: values.opportunity_id || null, jurisdiction: bounded(values.jurisdiction, 80), ...result, tournament_digest: digest({ organizationId, values, nonce: randomBytes(4).toString('hex') }) }) }
  if (action === 'review_effectiveness') { const result = measureReviewEffectiveness(values); return insert('regulatory_review_effectiveness', { organization_id: organizationId, allocation_id: values.allocation_id || null, reviewer_ref: bounded(values.reviewer_ref, 160) || null, subject_ref: bounded(values.subject_ref, 240), outcome_refs: (values.outcome_refs || []).slice(0, 50), ...result, measurement_digest: digest({ organizationId, values }) }) }
  throw createError({ statusCode: 400, message: 'unknown_sovereignty_action' })
}

export async function runRegulatorySovereigntyAutopilot(organizationId: string) {
  const sb = serviceClient()
  const [{ data: rooms }, { data: launches }, { data: attention }, { data: relationships }] = await Promise.all([
    sb.from('regulatory_evidence_rooms').select('*').eq('organization_id', organizationId).limit(50), sb.from('regulatory_jurisdiction_launches').select('*').eq('organization_id', organizationId).limit(50), sb.from('regulatory_attention_allocations').select('*').eq('organization_id', organizationId).eq('status', 'recommended').limit(50), sb.from('regulatory_relationships').select('*').eq('organization_id', organizationId).limit(100),
  ])
  let forecasts = 0; for (const room of rooms || []) { const result = forecastExaminerQuestions({ missing_evidence: (room.manifest?.requirements || []).filter((x: any) => !x.satisfied), incidents: [], material_changes: [], verified_inputs: Number(room.completeness_score || 0) / 10 }); const forecastDigest = digest({ organizationId, room: room.id, result, day: now().slice(0, 10) }); await sb.from('regulatory_examiner_forecasts').upsert({ organization_id: organizationId, target_capability: room.target_capability, jurisdiction: room.jurisdiction, examination_type: room.purpose, ...result, forecast_digest: forecastDigest }, { onConflict: 'forecast_digest' }); forecasts++ }
  let packets = 0; for (const allocation of attention || []) { const result = prepareSupervisoryPacket({ issues: [{ question: `Review ${allocation.work_type}`, resolved: false }], bounded_facts: allocation.explanation, evidence: [], recommendation: 'review_required' }); const packetDigest = digest({ organizationId, allocation: allocation.id, result }); await sb.from('regulatory_supervisory_packets').upsert({ organization_id: organizationId, allocation_id: allocation.id, subject_ref: allocation.work_ref, ...result, packet_digest: packetDigest }, { onConflict: 'packet_digest' }); packets++ }
  let options = 0; for (const relationship of relationships || []) { const result = valueRegulatoryOption({ replacement_cost_cents: Number(relationship.economics?.monthly_price_cents || 0) * 6, time_to_replace_days: 90, annual_carry_cost_cents: Number(relationship.economics?.monthly_price_cents || 0) * 12, probability_of_use: relationship.status === 'active' ? .75 : .25, enabled_paths: (relationship.covered_activities || []).map((x: string) => ({ key: x, expected_value_cents: 500_000 })) }); const valuationDigest = digest({ organizationId, relationship: relationship.id, month: now().slice(0, 7), result }); await sb.from('regulatory_option_value_ledger').upsert({ organization_id: organizationId, asset_type: 'relationship', asset_ref: relationship.id, jurisdictions: relationship.jurisdictions || [], enabled_paths: relationship.covered_activities || [], ...result, valuation_digest: valuationDigest }, { onConflict: 'valuation_digest' }); options++ }
  return { examiner_forecasts_updated: forecasts, review_packets_updated: packets, option_values_updated: options, launch_proofs_monitored: (launches || []).length }
}

export async function sovereigntyCockpit(organizationId: string) {
  const sb = serviceClient(); const [attestations, structures, catastrophes, tournaments, packets, options, forecasts, effectiveness] = await Promise.all([
    sb.from('regulatory_product_attestations').select('*').eq('organization_id', organizationId).order('created_at', { ascending: false }).limit(30), sb.from('regulatory_structuring_scenarios').select('*').eq('organization_id', organizationId).order('created_at', { ascending: false }).limit(20), sb.from('regulatory_catastrophe_scenarios').select('*').eq('organization_id', organizationId).order('created_at', { ascending: false }).limit(20), sb.from('regulatory_launch_tournaments').select('*').eq('organization_id', organizationId).order('updated_at', { ascending: false }).limit(20), sb.from('regulatory_supervisory_packets').select('*').eq('organization_id', organizationId).order('created_at', { ascending: false }).limit(30), sb.from('regulatory_option_value_ledger').select('*').eq('organization_id', organizationId).eq('status', 'current').order('strategic_option_value_cents', { ascending: false }).limit(50), sb.from('regulatory_examiner_forecasts').select('*').eq('organization_id', organizationId).eq('status', 'current').order('created_at', { ascending: false }).limit(30), sb.from('regulatory_review_effectiveness').select('*').eq('organization_id', organizationId).order('measured_at', { ascending: false }).limit(50),
  ])
  return { attestations: attestations.data || [], structures: structures.data || [], catastrophes: catastrophes.data || [], tournaments: tournaments.data || [], supervisory_packets: packets.data || [], option_values: options.data || [], examiner_forecasts: forecasts.data || [], review_effectiveness: effectiveness.data || [], summary: { valid_product_proofs: (attestations.data || []).filter((x: any) => x.status === 'valid' && new Date(x.expires_at).getTime() > Date.now()).length, proof_gaps: (attestations.data || []).filter((x: any) => x.status !== 'valid' || new Date(x.expires_at).getTime() <= Date.now()).length, preserved_option_value_cents: (options.data || []).reduce((s: number, x: any) => s + Number(x.strategic_option_value_cents || 0), 0), predicted_examiner_questions: (forecasts.data || []).reduce((s: number, x: any) => s + (x.predicted_questions || []).length, 0), average_review_effectiveness: (effectiveness.data || []).length ? Math.round((effectiveness.data || []).reduce((s: number, x: any) => s + Number(x.effectiveness_score || 0), 0) / effectiveness.data!.length) : null } }
}
