import { createHash, randomBytes } from 'node:crypto'
import { serviceClient } from './fleetSupabase'
import { createCausalityReceipt } from './regulatoryOpportunity'

const now = () => new Date().toISOString()
const bounded = (value: any, limit = 400) => String(value || '').trim().slice(0, limit)
const clamp = (value: number, min = 0, max = 100) => Math.max(min, Math.min(max, value))
const stable = (value: any): string => Array.isArray(value) ? `[${value.map(stable).join(',')}]` : value && typeof value === 'object' ? `{${Object.keys(value).sort().map(key => `${key}:${stable(value[key])}`).join(',')}}` : JSON.stringify(value)
const digest = (value: any) => createHash('sha256').update(stable(value)).digest('hex')

export function optimizeRegulatoryWorldlines(input: any) {
  const jurisdictions = (input.jurisdictions || ['US-general']).slice(0, 20)
  const routes = (input.routes || ['sponsor_then_license', 'license_direct', 'restructure']).slice(0, 8)
  const demand = Math.max(0, Number(input.monthly_value_cents || 1_000_000))
  const readiness = clamp(Number(input.readiness_score || 0))
  const riskTolerance = clamp(Number(input.risk_tolerance || 35))
  const candidates = jurisdictions.flatMap((jurisdiction: string, j: number) => routes.map((route: string) => {
    const routeMonths = route === 'sponsor_then_license' ? 2 + j : route === 'license_direct' ? 7 + j * 2 : 1 + j
    const directCost = route === 'license_direct' ? 180_000 + j * 25_000 : route === 'sponsor_then_license' ? 95_000 + j * 18_000 : 35_000 + j * 8_000
    const authority = route === 'license_direct' ? 95 : route === 'sponsor_then_license' ? 82 : 55
    const dependency = route === 'sponsor_then_license' ? 62 : route === 'license_direct' ? 20 : 35
    const readinessFit = 100 - Math.abs(readiness - (route === 'license_direct' ? 80 : 45))
    const value = demand * Math.max(0, 12 - routeMonths) / 12
    const score = Math.round(clamp(value / Math.max(demand, 1) * 35 + authority * .25 + readinessFit * .2 + (100 - dependency) * .1 + riskTolerance * .1))
    return { jurisdiction, route, score, months_to_authority: routeMonths, first_year_direct_cost_cents: directCost, modeled_first_year_value_cents: Math.round(value), authority_score: authority, dependency_score: dependency }
  })).sort((a: any, b: any) => b.score - a.score)
  return {
    recommended: candidates[0], alternatives: candidates.slice(1, 6),
    ordering: [...new Set(candidates.slice(0, jurisdictions.length * 2).map((x: any) => x.jurisdiction))],
    uncertainty: { confidence: Number(Math.min(.92, .48 + Math.min(10, Number(input.verified_inputs || 0)) * .04).toFixed(2)), invalidates_on: ['authority_source_change','ownership_change','material_product_change','evidence_expiry'] },
  }
}

export function calculateContractNetworkRisk(input: any) {
  const nodes = (input.nodes || []).slice(0, 500)
  const edges = (input.edges || []).slice(0, 2_000)
  const totalExposure = edges.reduce((sum: number, edge: any) => sum + Math.max(0, Number(edge.exposure_cents || 0)), 0)
  const exposure = new Map<string, number>()
  const dependents = new Map<string, number>()
  for (const edge of edges) {
    exposure.set(String(edge.to), (exposure.get(String(edge.to)) || 0) + Math.max(0, Number(edge.exposure_cents || 0)))
    dependents.set(String(edge.to), (dependents.get(String(edge.to)) || 0) + 1)
  }
  const concentrations = [...exposure.entries()].map(([node, cents]) => ({ node, exposure_cents: cents, exposure_share: totalExposure ? Number((cents / totalExposure).toFixed(4)) : 0, dependents: dependents.get(node) || 0 })).sort((a, b) => b.exposure_cents - a.exposure_cents)
  const maxShare = concentrations[0]?.exposure_share || 0
  const cascade = clamp(maxShare * 100 * .65 + Math.min(100, (concentrations[0]?.dependents || 0) * 8) * .35)
  return { node_count: nodes.length, edge_count: edges.length, total_exposure_cents: totalExposure, concentration_score: Math.round(maxShare * 100), cascade_risk_score: Math.round(cascade), critical_counterparties: concentrations.slice(0, 8), mitigations: cascade > 50 ? ['add_redundant_provider','reduce_single_counterparty_cap','increase_monitoring','pre-negotiate_transition_rights'] : ['maintain_monitoring'] }
}

export function rehearseRegulatoryExamination(input: any) {
  const completeness = clamp(Number(input.completeness_score || 0))
  const freshness = clamp(Number(input.freshness_score || 0))
  const contradictions = Math.max(0, Number(input.contradiction_count || 0))
  const overdue = Math.max(0, Number(input.overdue_obligations || 0))
  const score = Math.round(clamp(completeness * .45 + freshness * .3 + Math.max(0, 100 - contradictions * 18) * .15 + Math.max(0, 100 - overdue * 15) * .1))
  const findings = [
    completeness < 85 && { severity: 'material', issue: 'evidence_completeness', requested_action: 'supply_missing_requirement_evidence' },
    freshness < 80 && { severity: 'material', issue: 'stale_evidence', requested_action: 'refresh_time_sensitive_records' },
    contradictions > 0 && { severity: 'critical', issue: 'contradictory_evidence', requested_action: 'reconcile_and_preserve_audit_trail' },
    overdue > 0 && { severity: 'critical', issue: 'overdue_obligations', requested_action: 'cure_or_document_exception' },
  ].filter(Boolean)
  return { examination_readiness_score: score, predicted_result: score >= 85 ? 'ready_for_review' : score >= 65 ? 'remediation_likely' : 'material_findings_likely', findings, adversarial_questions: findings.map((item: any) => `Show contemporaneous, independently verifiable support for ${item.issue.replaceAll('_',' ')}.`), appeal_record_ready: contradictions === 0 && completeness >= 80 }
}

export function modelRegulatedEntityAcquisition(input: any) {
  const purchase = Math.max(0, Number(input.purchase_price_cents || 0))
  const liabilities = Math.max(0, Number(input.estimated_liabilities_cents || 0))
  const integration = Math.max(0, Number(input.integration_cost_cents || 0))
  const transferability = clamp(Number(input.transferability_score || 0))
  const changeControlMonths = Math.max(0, Number(input.change_control_months || 6))
  const probability = Number((transferability / 100 * Math.max(.2, 1 - changeControlMonths / 36)).toFixed(2))
  return { all_in_cost_cents: purchase + liabilities + integration, closing_probability: probability, months_to_operating_authority: changeControlMonths, blockers: [transferability < 70 && 'authority_transfer_or_change_control_uncertain', liabilities > purchase * .35 && 'legacy_liability_concentration'].filter(Boolean), required_diligence: ['license_good_standing','change_control_requirements','complaints_and_enforcement','capital_and_bonding','data_and_cyber','contracts_and_supervision'] }
}

export function optimizeRegulatoryCapital(input: any) {
  const volume = Math.max(0, Number(input.monthly_volume_cents || 0))
  const required = Math.max(0, Number(input.minimum_capital_cents || 0))
  const volatility = clamp(Number(input.volume_volatility || 20)) / 100
  const complaint = clamp(Number(input.complaint_risk || 10)) / 100
  const stress = Math.round(volume * (.025 + volatility * .045 + complaint * .03))
  const buffer = Math.round(Math.max(required * .25, stress))
  const target = required + buffer
  return { minimum_capital_cents: required, stress_loss_cents: stress, recommended_buffer_cents: buffer, target_capital_cents: target, instruments: [{ type: 'cash_reserve', allocation_bps: 6000 }, { type: 'surety_or_bond', allocation_bps: 2500 }, { type: 'insurance_or_guarantee', allocation_bps: 1500 }], release_triggers: ['volume_downshift_verified','complaint_rate_improves','regulator_approval'], escalation_triggers: ['growth_above_model','loss_event','complaint_spike'] }
}

export function compileDisputePrevention(input: any) {
  const terms = (input.terms || []).slice(0, 200).map((term: any, index: number) => ({ key: bounded(term.key || `term_${index + 1}`, 80), text: bounded(term.text || term, 800) }))
  const ambiguous = terms.filter((term: any) => /reasonable|material|prompt|best efforts|satisfactory|appropriate|as needed/i.test(term.text))
  const missing = ['acceptance_criteria','measurement_source','notice','cure_period','evidence_standard','change_control','cade_election'].filter(key => !terms.some((term: any) => term.text.toLowerCase().includes(key.replaceAll('_',' '))))
  return { ambiguity_score: Math.round(clamp((ambiguous.length / Math.max(terms.length, 1)) * 100 + missing.length * 5)), ambiguous_terms: ambiguous.map((term: any) => term.key), missing_controls: missing, proposed_controls: missing.map(key => ({ control: key, mode: 'shadow', requires_counterparty_acceptance: true })), evidence_schedule: { preserve_at: ['approval','delivery','acceptance','exception','cure'], store: 'system_of_record', madeus_retains: 'digest_and_bounded_facts_only' } }
}

export function evaluateAuthorityGate(input: any) {
  const capabilities = (input.requested_capabilities || []).slice(0, 100)
  const evidence = input.authority_evidence || {}
  const decisions = capabilities.map((capability: any) => {
    const key = bounded(capability.key || capability, 160)
    const proof = evidence[key] || {}
    const verified = proof.verified === true && (!proof.expires_at || new Date(proof.expires_at).getTime() > Date.now())
    return { capability: key, decision: verified ? 'allow' : proof.prohibited === true ? 'block' : 'hold', reason: verified ? 'current_authority_verified' : proof.prohibited === true ? 'activity_prohibited' : 'current_authority_not_verified' }
  })
  const decision = decisions.some((x: any) => x.decision === 'block') ? 'block' : decisions.some((x: any) => x.decision === 'hold') ? 'hold' : 'allow'
  return { decision, capability_decisions: decisions, required_actions: decisions.filter((x: any) => x.decision !== 'allow').map((x: any) => ({ capability: x.capability, action: x.decision === 'block' ? 'remove_or_replace_capability' : 'supply_current_authority_evidence' })), expires_at: new Date(Date.now() + 15 * 60_000).toISOString() }
}

export function detectAuthorityDrift(input: any) {
  const changed = bounded(input.prior_digest, 128) !== bounded(input.current_digest, 128)
  const affected = (input.dependencies || []).slice(0, 500)
  const material = changed && affected.some((item: any) => item.enforced === true || item.customer_facing === true)
  return { changed, materiality: !changed ? 'non_material' : material ? 'material' : 'unknown', affected_rules: [...new Set(affected.map((x: any) => x.rule_key).filter(Boolean))], affected_projects: [...new Set(affected.map((x: any) => x.project_ref).filter(Boolean))], affected_controls: [...new Set(affected.map((x: any) => x.control_id).filter(Boolean))], containment_action: material ? 'hold_affected_release_and_preserve_lawful_variants' : changed ? 'shadow_reassessment' : 'none' }
}

async function saveRun(organizationId: string, runType: string, values: any, outcome: any) {
  const row = { organization_id: organizationId, project_ref: bounded(values.project_ref, 160) || null, run_type: runType, assumptions: values.assumptions || values, outcome, recommended_actions: outcome.mitigations || outcome.required_actions || outcome.proposed_controls || [], confidence: Number(outcome.uncertainty?.confidence ?? values.confidence ?? .65), run_digest: digest({ organizationId, runType, values, nonce: randomBytes(5).toString('hex') }) }
  const { data, error } = await serviceClient().from('regulatory_frontier_runs').insert(row).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  return data
}

export async function executeFrontierRun(organizationId: string, action: string, values: any) {
  const runners: Record<string, (value: any) => any> = { worldline: optimizeRegulatoryWorldlines, systemic_risk: calculateContractNetworkRisk, examination: rehearseRegulatoryExamination, acquisition: modelRegulatedEntityAcquisition, capital: optimizeRegulatoryCapital, dispute_prevention: compileDisputePrevention }
  const runner = runners[action]
  if (!runner) throw createError({ statusCode: 400, message: 'unknown_frontier_run' })
  return saveRun(organizationId, action, values, runner(values))
}

export async function runtimeDeploymentGate(organizationId: string, values: any) {
  const outcome = evaluateAuthorityGate(values)
  const policyDigest = digest({ organizationId, project: values.project_ref, jurisdiction: values.jurisdiction, authority: values.authority_evidence })
  const row = { organization_id: organizationId, project_ref: bounded(values.project_ref, 160), release_ref: bounded(values.release_ref, 240), jurisdiction: bounded(values.jurisdiction || 'US-general', 80), requested_capabilities: (values.requested_capabilities || []).slice(0, 100), authority_snapshot: { digest: digest(values.authority_evidence || {}), raw_evidence_stored: false }, decision: outcome.decision, reasons: outcome.capability_decisions, required_actions: outcome.required_actions, policy_digest: policyDigest, receipt_digest: digest({ policyDigest, release: values.release_ref, outcome, nonce: randomBytes(5).toString('hex') }), expires_at: outcome.expires_at }
  if (!row.project_ref || !row.release_ref) throw createError({ statusCode: 400, message: 'project_and_release_required' })
  const { data, error } = await serviceClient().from('regulatory_deployment_gates').insert(row).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  const receipt = createCausalityReceipt({ subject_type: 'deployment_gate', subject_id: data.id, decision: data.decision, causes: data.reasons, authority_refs: [{ policy_digest: data.policy_digest }], evidence_refs: [{ digest: data.authority_snapshot?.digest }], counterfactuals: data.required_actions })
  await serviceClient().from('regulatory_causality_receipts').upsert({ organization_id: organizationId, ...receipt }, { onConflict: 'receipt_digest' })
  return data
}

export async function recordAuthoritySource(organizationId: string, values: any) {
  const sb = serviceClient()
  const sourceKey = bounded(values.source_key, 160)
  const currentDigest = bounded(values.content_digest, 128)
  if (!sourceKey || !currentDigest || !values.source_url) throw createError({ statusCode: 400, message: 'source_key_url_digest_required' })
  const { data: prior } = await sb.from('regulatory_authority_sources').select('*').eq('organization_id', organizationId).eq('source_key', sourceKey).eq('status', 'current').order('version', { ascending: false }).limit(1).maybeSingle()
  const drift = detectAuthorityDrift({ prior_digest: prior?.content_digest, current_digest: currentDigest, dependencies: values.dependencies || [] })
  if (prior && drift.changed) await sb.from('regulatory_authority_sources').update({ status: 'superseded' }).eq('id', prior.id)
  const { data: source, error } = await sb.from('regulatory_authority_sources').insert({ organization_id: organizationId, source_key: sourceKey, authority: bounded(values.authority, 160), jurisdiction: bounded(values.jurisdiction || 'US-general', 80), source_url: bounded(values.source_url, 500), effective_at: values.effective_at || null, content_digest: currentDigest, bounded_change_summary: values.bounded_change_summary || {}, verified_at: values.verified === true ? now() : null, version: Number(prior?.version || 0) + 1, status: values.verified === true ? 'current' : 'unverified' }).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  if (drift.changed) await sb.from('regulatory_authority_drift_events').insert({ organization_id: organizationId, authority_source_id: source.id, prior_digest: prior?.content_digest || null, current_digest: currentDigest, ...drift, review_required: drift.materiality !== 'non_material' })
  return { source, drift }
}

export async function grantBoundedRegulatorAccess(organizationId: string, userId: string, values: any) {
  if (values.explicit_approval !== true) throw createError({ statusCode: 400, message: 'explicit_access_approval_required' })
  const hours = Math.max(1, Math.min(720, Number(values.duration_hours || 72)))
  const allowedFields = (values.allowed_fields || ['requirement_key','verification_status','observed_at','evidence_digest']).filter((field: string) => ['requirement_key','evidence_type','source_system','evidence_digest','bounded_facts','observed_at','expires_at','verification_status'].includes(field)).slice(0, 20)
  const manifest = { room_id: values.evidence_room_id, allowed_fields: allowedFields, raw_evidence_available: false, export_generated_at: now() }
  const row = { organization_id: organizationId, evidence_room_id: values.evidence_room_id, grantee_name: bounded(values.grantee_name, 200), grantee_domain: bounded(values.grantee_domain, 200) || null, purpose: bounded(values.purpose, 400), allowed_fields: allowedFields, allowed_evidence_types: (values.allowed_evidence_types || []).slice(0, 30), export_manifest: { ...manifest, manifest_digest: digest(manifest) }, grant_digest: digest({ organizationId, values, nonce: randomBytes(6).toString('hex') }), approved_by: userId, expires_at: new Date(Date.now() + hours * 3600_000).toISOString() }
  const { data, error } = await serviceClient().from('regulatory_access_grants').insert(row).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  return data
}

export async function runRegulatoryFrontierAutopilot(organizationId: string) {
  const sb = serviceClient()
  const [{ data: relationships }, { data: obligations }, { data: rooms }] = await Promise.all([
    sb.from('regulatory_relationships').select('id,counterparty_name,status,economics').eq('organization_id', organizationId).limit(200),
    sb.from('regulatory_obligation_ledger').select('id,relationship_id,status,direct_cost_cents,indirect_cost_cents').eq('organization_id', organizationId).limit(500),
    sb.from('regulatory_evidence_rooms').select('id,completeness_score,freshness_score,contradiction_count').eq('organization_id', organizationId).limit(100),
  ])
  const edges = (obligations || []).filter((x: any) => x.relationship_id).map((x: any) => ({ from: organizationId, to: x.relationship_id, exposure_cents: Number(x.direct_cost_cents || 0) + Number(x.indirect_cost_cents || 0) }))
  const risk = calculateContractNetworkRisk({ nodes: relationships || [], edges })
  const room = [...(rooms || [])].sort((a: any, b: any) => Number(a.completeness_score || 0) - Number(b.completeness_score || 0))[0]
  const examination = room ? rehearseRegulatoryExamination({ ...room, overdue_obligations: (obligations || []).filter((x: any) => x.status === 'breached').length }) : null
  const saved = await Promise.all([saveRun(organizationId, 'systemic_risk', { source: 'scheduled' }, risk), ...(examination ? [saveRun(organizationId, 'examination', { source: 'scheduled', room_id: room.id }, examination)] : [])])
  return { runs_updated: saved.length, systemic_risk_score: risk.cascade_risk_score, examination_readiness_score: examination?.examination_readiness_score ?? null }
}

export async function frontierCockpit(organizationId: string) {
  const sb = serviceClient()
  const [{ data: runs }, { data: gates }, { data: drift }, { data: grants }] = await Promise.all([
    sb.from('regulatory_frontier_runs').select('*').eq('organization_id', organizationId).eq('status', 'current').order('created_at', { ascending: false }).limit(30),
    sb.from('regulatory_deployment_gates').select('*').eq('organization_id', organizationId).order('created_at', { ascending: false }).limit(20),
    sb.from('regulatory_authority_drift_events').select('*').eq('organization_id', organizationId).eq('review_required', true).order('created_at', { ascending: false }).limit(20),
    sb.from('regulatory_access_grants').select('*').eq('organization_id', organizationId).order('created_at', { ascending: false }).limit(20),
  ])
  const latestByType = Object.fromEntries((runs || []).filter((run: any, index: number, all: any[]) => all.findIndex(x => x.run_type === run.run_type) === index).map((run: any) => [run.run_type, run]))
  return { latest_by_type: latestByType, gates: gates || [], open_drift: drift || [], access_grants: grants || [], summary: { releases_held: (gates || []).filter((x: any) => x.decision !== 'allow').length, authority_changes_to_review: (drift || []).length, active_regulator_grants: (grants || []).filter((x: any) => x.status === 'active' && new Date(x.expires_at).getTime() > Date.now()).length } }
}
