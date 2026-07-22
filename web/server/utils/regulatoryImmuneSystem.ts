import { createHash, randomBytes } from 'node:crypto'
import { serviceClient } from './fleetSupabase'

const clamp = (n: number, min = 0, max = 100) => Math.max(min, Math.min(max, n))
const text = (v: any, n = 300) => String(v || '').trim().slice(0, n)
const stable = (v: any): string => Array.isArray(v) ? `[${v.map(stable).join(',')}]` : v && typeof v === 'object' ? `{${Object.keys(v).sort().map(k => `${k}:${stable(v[k])}`).join(',')}}` : JSON.stringify(v)
const digest = (v: any) => createHash('sha256').update(stable(v)).digest('hex')

export function compileLawToRuntime(input: any) {
  const provisions = (input.provisions || []).slice(0, 100)
  const unresolved = provisions.filter((p: any) => !p.authority_citation || Number(p.interpretation_confidence || 0) < .75).map((p: any) => ({ provision_key: p.key, reason: !p.authority_citation ? 'missing_authority_citation' : 'interpretation_confidence_below_threshold' }))
  const controls = provisions.map((p: any) => ({ key: p.key, boundary: p.boundary || 'feature', predicate: p.predicate || {}, effect: p.effect || 'hold', fallback: p.fallback || 'disabled', activation: unresolved.some((x: any) => x.provision_key === p.key) ? 'shadow_only' : 'approval_required' }))
  return { provisions, runtime_controls: controls, traceability: controls.map((c: any) => ({ control_key: c.key, provision_key: c.key, authority_citation: provisions.find((p: any) => p.key === c.key)?.authority_citation || null })), test_vectors: controls.flatMap((c: any) => [{ control_key: c.key, case: 'predicate_true', expected: c.effect }, { control_key: c.key, case: 'proof_missing', expected: c.fallback }]), unresolved_interpretations: unresolved, status: unresolved.length ? 'review' : 'shadow' }
}

export function runSupervisoryCertificationSwarm(input: any) {
  const history = input.shadow_history || {}
  const facts = { evidence: clamp(Number(history.evidence_completeness || 0)), authority: clamp(Number(history.authority_coverage || 0)), qa: clamp(Number(history.qa_pass_rate || 0)), complaints: Number(history.open_complaints || 0), incidents: Number(history.material_incidents || 0), contradictions: Number(history.contradictions || 0), operating_days: Number(history.operating_days || 0) }
  const agents = [
    { agent: 'authority_specialist', score: facts.authority, findings: facts.authority < 90 ? ['authority_coverage_below_certification_floor'] : [] },
    { agent: 'evidence_examiner', score: facts.evidence, findings: facts.evidence < 85 ? ['evidence_incomplete'] : [] },
    { agent: 'operational_resilience', score: clamp(facts.qa - facts.incidents * 40), findings: facts.incidents ? ['material_incident_history'] : [] },
    { agent: 'consumer_outcomes', score: clamp(100 - facts.complaints * 12), findings: facts.complaints > 2 ? ['open_complaint_pattern'] : [] },
    { agent: 'adversarial_dissenter', score: clamp(Math.min(facts.evidence, facts.authority, facts.qa) - facts.contradictions * 25), findings: [...(facts.contradictions ? ['unresolved_contradictions'] : []), ...(facts.operating_days < 30 ? ['insufficient_shadow_history'] : [])] },
  ]
  const findings = [...new Set(agents.flatMap(a => a.findings))]
  const materialRisks = findings.filter(x => ['material_incident_history','authority_coverage_below_certification_floor'].includes(x))
  const gaps = findings.filter(x => ['evidence_incomplete','insufficient_shadow_history'].includes(x))
  const contradictions = findings.filter(x => x === 'unresolved_contradictions')
  const variance = Math.max(...agents.map(a => a.score)) - Math.min(...agents.map(a => a.score))
  if (variance > 25) contradictions.push('agent_assessment_divergence')
  const confidence = Number((agents.reduce((s, a) => s + a.score, 0) / agents.length / 100).toFixed(2))
  const reasons = [...new Set([...materialRisks, ...gaps, ...contradictions, ...(confidence < .8 ? ['swarm_confidence_below_threshold'] : [])])]
  const escalate = reasons.length > 0
  return { shadow_history: history, agent_assessments: agents, reconciled_findings: findings, contradictions, material_risks: materialRisks, evidence_gaps: gaps, confidence, human_escalation_required: escalate, escalation_reasons: reasons, recommendation: escalate ? 'human_review_required' : 'swarm_eligible_for_sponsor_review', status: escalate ? 'human_review' : 'swarm_reviewed' }
}

export function buildRegulatoryImmuneResponse(input: any) {
  const severity = input.invalid_authority || input.customer_harm ? 'critical' : input.material ? 'high' : 'warning'
  const affected = { project_ref: input.project_ref, feature_key: input.feature_key, jurisdiction: input.jurisdiction, activity: input.activity }
  return { affected_boundary: affected, diagnosis: { signal_type: input.signal_type || 'authority_degradation', invalid_authority: Boolean(input.invalid_authority), evidence_stale: Boolean(input.evidence_stale), confidence: Number(input.confidence || .7) }, isolation_plan: ['hold_affected_boundary','preserve_unaffected_lawful_behavior','capture_runtime_evidence'], lawful_substitute: { mode: input.fallback_mode || 'read_only_or_provider_handoff', activation: 'bounded_reversible' }, remediation_evidence: (input.evidence_refs || []).slice(0, 50), reentry_plan: ['restore_current_proof','run_shadow_qa','agentic_swarm_review','approval_if_material','canary_reentry'], autonomous_actions: ['notify_owner','hold_affected_boundary','activate_preapproved_fallback','open_evidence_room'], approval_required_actions: ['change_legal_position','external_representation','sign_or_file','production_reentry_if_material'], severity, status: 'contained' }
}

export function clearCrossBorderAuthority(input: any) {
  const requirements = (input.requirements || []).slice(0, 100)
  const candidates = (input.candidates || []).slice(0, 100).map((c: any) => { const coverage = requirements.filter((r: any) => (c.capabilities || []).includes(r.key) && (!r.jurisdiction || (c.jurisdictions || []).includes(r.jurisdiction))).length; const score = Math.round(coverage / Math.max(1, requirements.length) * 55 + clamp(Number(c.reliability || 0)) * .2 + clamp(Number(c.evidence_score || 0)) * .15 + clamp(100 - Number(c.conflict_score || 0)) * .1); return { ...c, coverage, score, eligible: c.consent_available !== false && c.authority_valid !== false } }).sort((a: any, b: any) => Number(b.eligible) - Number(a.eligible) || b.score - a.score)
  const selected: any[] = []; const remaining = new Set(requirements.map((r: any) => r.key)); for (const candidate of candidates.filter((c: any) => c.eligible)) { const adds = (candidate.capabilities || []).filter((x: string) => remaining.has(x)); if (!adds.length) continue; selected.push({ candidate_ref: candidate.key, covers: adds, score: candidate.score }); adds.forEach((x: string) => remaining.delete(x)); if (!remaining.size) break }
  return { requirements, candidates, recommended_bundle: { providers: selected, uncovered_requirements: [...remaining], activation: remaining.size ? 'blocked' : 'permission_required' }, conflicts: candidates.filter((c: any) => Number(c.conflict_score || 0) > 30).map((c: any) => ({ candidate_ref: c.key, score: c.conflict_score })), economics: { estimated_monthly_cents: selected.reduce((s, x) => s + Number(candidates.find((c: any) => c.key === x.candidate_ref)?.monthly_cents || 0), 0) }, execution_plan: ['obtain_member_consent','counterparty_diligence','negotiate_agreements','verify_authority','shadow_integration','separate_activation_approval'], consent_requirements: selected.map(x => ({ candidate_ref: x.candidate_ref, affirmative: true })), status: remaining.size ? 'modeled' : 'permission_required' }
}

export function priceProofPortability(input: any) {
  const verifiedUses = Math.max(0, Number(input.verified_uses || 0)); const hours = Math.max(0, Number(input.hours_saved_per_use || 0)); const hourly = Math.max(0, Number(input.blended_hourly_cost_cents || 0)); const savings = Math.round(verifiedUses * hours * hourly); const rate = Math.max(0, Math.min(.5, Number(input.rebate_rate || .2)))
  return { portability_constraints: input.portability_constraints || ['recipient_revalidates_local_law','no_identity_or_raw_evidence_transfer','purpose_limited_use','revocable_consent'], privacy_tier: input.privacy_tier || 'aggregate', verified_uses: verifiedUses, recipient_savings_cents: savings, contributor_rebate_cents: Math.round(savings * rate), status: input.share_approved ? 'permissioned' : 'private' }
}

export function designRegulatorEvidenceStream(input: any) {
  const allowed = new Set((input.grant_fields || []).map(String)); const requested = (input.requested_fields || []).map(String); const delivered = requested.filter(x => allowed.has(x)); const denied = requested.filter(x => !allowed.has(x))
  return { field_allowlist: [...allowed], source_refs: (input.source_refs || []).slice(0, 50), delivery_manifest: delivered.map(field => ({ field, mode: 'bounded_fact_or_digest', raw_record: false })), denied_fields: denied, cadence: input.cadence || 'on_change', status: input.grant_active && !denied.length ? 'active' : 'shadow' }
}

export function rehearseEnforcement(input: any) {
  const findings = (input.alleged_findings || []).slice(0, 50); const customers = Math.max(0, Number(input.affected_customers || 0)); const perCustomer = Math.max(0, Number(input.restitution_per_customer_cents || 0)); const severity = findings.reduce((s: number, f: any) => s + Number(f.severity || 1), 0)
  return { alleged_findings: findings, enforcement_path: ['information_request','examination_or_investigation','preliminary_findings','response_and_remediation','order_or_closure','appeal_if_available'], remediation_orders: findings.map((f: any) => ({ finding: f.code, actions: f.remediation || ['stop_or_limit_activity','customer_review','control_remediation','independent_validation'] })), customer_restitution_cents: customers * perCustomer, interruption_days: Math.max(0, severity * Number(input.days_per_severity || 5)), defense_options: ['correct_factual_record','produce_contemporaneous_evidence','remediate_without_admission_where_available','challenge_scope_or_authority','appeal_or_settle_with_separate_approval'], evidence_gaps: findings.filter((f: any) => !f.evidence_refs?.length).map((f: any) => f.code), containment_actions: ['preserve_evidence','hold_affected_activity','protect_customers','notify_required_parties_after_approval'] }
}

export function calculateAuthorityDecay(input: any) {
  const value = Math.max(0, Number(input.current_value_cents || 0)); const days = Math.max(0, Math.ceil((new Date(input.material_loss_at || Date.now() + 90 * 864e5).getTime() - Date.now()) / 864e5)); const rate = days ? value / days : value; const options = (input.preservation_options || []).map((x: any) => ({ ...x, roi: Number(x.cost_cents || 0) ? Math.round((Number(x.value_preserved_cents || value) / Number(x.cost_cents)) * 100) / 100 : 999 })).sort((a: any, b: any) => b.roi - a.roi)
  return { current_value_cents: value, decay_rate_daily: Math.round(rate), days_to_material_loss: days, triggers: input.triggers || ['expiry','ownership_change','evidence_stale','staff_departure','agreement_termination'], preservation_options: options, recommended_action: options[0] || { action: 'refresh_evidence_and_authority', separate_approval: false }, priority_score: Math.round(clamp((100 - Math.min(100, days)) * .55 + Math.min(100, value / 100_000) * .45)) }
}

export async function saveImmuneSystemAction(organizationId: string, action: string, values: any) {
  const sb = serviceClient(); const insert = async (table: string, row: any) => { const { data, error } = await sb.from(table).insert(row).select().single(); if (error) throw createError({ statusCode: 500, message: error.message }); return data }
  if (action === 'compile_law') { const result = compileLawToRuntime(values); return insert('regulatory_compiled_controls', { organization_id: organizationId, source_ref: text(values.source_ref), source_digest: digest(values.source_content || values.provisions), effective_from: values.effective_from || null, expires_at: values.expires_at || null, ...result, compiler_digest: digest({ organizationId, values, nonce: randomBytes(4).toString('hex') }) }) }
  if (action === 'swarm_certification') { const result = runSupervisoryCertificationSwarm(values); return insert('regulatory_swarm_certifications', { organization_id: organizationId, subject_ref: text(values.subject_ref), sponsor_relationship_id: values.sponsor_relationship_id || null, ...result, certification_digest: digest({ organizationId, values, nonce: randomBytes(4).toString('hex') }) }) }
  if (action === 'immune_response') { const result = buildRegulatoryImmuneResponse(values); return insert('regulatory_immune_events', { organization_id: organizationId, signal_ref: text(values.signal_ref), ...result, event_digest: digest({ organizationId, values, nonce: randomBytes(4).toString('hex') }) }) }
  if (action === 'authority_clearing') { const result = clearCrossBorderAuthority(values); return insert('regulatory_clearing_matches', { organization_id: organizationId, activity: text(values.activity), jurisdictions: values.jurisdictions || [], ...result, match_digest: digest({ organizationId, values, nonce: randomBytes(4).toString('hex') }) }) }
  if (action === 'proof_module') { const result = priceProofPortability(values); return insert('regulatory_proof_modules', { organization_id: organizationId, module_key: text(values.module_key), control_family: text(values.control_family), jurisdiction_scope: values.jurisdiction_scope || [], proof_manifest: values.proof_manifest || {}, ...result, module_digest: digest({ organizationId, values, nonce: randomBytes(4).toString('hex') }) }) }
  if (action === 'evidence_stream') { const result = designRegulatorEvidenceStream(values); return insert('regulatory_evidence_streams', { organization_id: organizationId, grant_id: values.grant_id || null, recipient_ref: text(values.recipient_ref), purpose: text(values.purpose), expires_at: values.expires_at, stream_digest: digest({ organizationId, values, nonce: randomBytes(4).toString('hex') }), ...result }) }
  if (action === 'enforcement_rehearsal') { const result = rehearseEnforcement(values); return insert('regulatory_enforcement_rehearsals', { organization_id: organizationId, target_ref: text(values.target_ref), ...result, rehearsal_digest: digest({ organizationId, values, nonce: randomBytes(4).toString('hex') }) }) }
  if (action === 'authority_decay') { const result = calculateAuthorityDecay(values); return insert('regulatory_authority_decay_budget', { organization_id: organizationId, asset_type: text(values.asset_type), asset_ref: text(values.asset_ref), ...result, budget_digest: digest({ organizationId, values, day: new Date().toISOString().slice(0, 10) }) }) }
  throw createError({ statusCode: 400, message: 'unknown_regulatory_immune_action' })
}

export async function runRegulatoryImmuneAutopilot(organizationId: string) {
  const sb = serviceClient()
  const [{ data: attestations }, { data: options }] = await Promise.all([
    sb.from('regulatory_product_attestations').select('*').eq('organization_id', organizationId).limit(100),
    sb.from('regulatory_option_value_ledger').select('*').eq('organization_id', organizationId).eq('status', 'current').limit(100),
  ])
  let contained = 0
  for (const attestation of attestations || []) {
    if (attestation.status === 'valid' && new Date(attestation.expires_at).getTime() > Date.now()) continue
    const result = buildRegulatoryImmuneResponse({ signal_type: 'product_proof_gap', signal_ref: attestation.id, project_ref: attestation.project_ref, feature_key: attestation.feature_key, jurisdiction: attestation.jurisdiction, evidence_stale: new Date(attestation.expires_at).getTime() <= Date.now(), fallback_mode: attestation.fallback_receipt?.mode })
    const eventDigest = digest({ organizationId, attestation: attestation.id, status: attestation.status, expires: attestation.expires_at })
    await sb.from('regulatory_immune_events').upsert({ organization_id: organizationId, signal_ref: attestation.id, ...result, event_digest: eventDigest }, { onConflict: 'event_digest' })
    contained++
  }
  let decayUpdated = 0
  for (const option of options || []) {
    const result = calculateAuthorityDecay({ current_value_cents: option.strategic_option_value_cents, material_loss_at: option.valued_at ? new Date(new Date(option.valued_at).getTime() + Math.max(30, Number(option.time_to_replace_days || 90)) * 864e5).toISOString() : undefined, triggers: option.decay_triggers, preservation_options: (option.preservation_actions || []).map((action: string, index: number) => ({ action, cost_cents: 25_000 * (index + 1), value_preserved_cents: option.strategic_option_value_cents })) })
    const budgetDigest = digest({ organizationId, option: option.id, month: new Date().toISOString().slice(0, 7) })
    await sb.from('regulatory_authority_decay_budget').upsert({ organization_id: organizationId, asset_type: option.asset_type, asset_ref: option.asset_ref, ...result, budget_digest: budgetDigest }, { onConflict: 'budget_digest' })
    decayUpdated++
  }
  return { proof_gaps_contained: contained, decay_budgets_updated: decayUpdated }
}

export async function immuneSystemCockpit(organizationId: string) {
  const sb = serviceClient(); const tables = ['regulatory_compiled_controls','regulatory_swarm_certifications','regulatory_immune_events','regulatory_clearing_matches','regulatory_proof_modules','regulatory_evidence_streams','regulatory_enforcement_rehearsals','regulatory_authority_decay_budget']; const rows = await Promise.all(tables.map(table => sb.from(table).select('*').eq('organization_id', organizationId).order('created_at', { ascending: false }).limit(30)))
  const [compiled, certifications, immuneEvents, clearing, modules, streams, rehearsals, decay] = rows.map(x => x.data || [])
  return { compiled_controls: compiled, swarm_certifications: certifications, immune_events: immuneEvents, clearing_matches: clearing, proof_modules: modules, evidence_streams: streams, enforcement_rehearsals: rehearsals, authority_decay: decay, summary: { active_compiled_controls: compiled.filter((x: any) => x.status === 'active').length, swarm_cleared: certifications.filter((x: any) => !x.human_escalation_required).length, human_escalations: certifications.filter((x: any) => x.human_escalation_required).length, contained_immune_events: immuneEvents.filter((x: any) => x.status === 'contained').length, contributor_rebates_cents: modules.reduce((s: number, x: any) => s + Number(x.contributor_rebate_cents || 0), 0), active_evidence_streams: streams.filter((x: any) => x.status === 'active' && new Date(x.expires_at).getTime() > Date.now()).length, urgent_decay_actions: decay.filter((x: any) => Number(x.priority_score) >= 70).length } }
}
