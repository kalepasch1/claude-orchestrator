import { createHmac } from 'node:crypto'
import { CANONICAL_NAVIGATION, NAVIGATION_CONTRACT_VERSION } from '~/config/navigation'
import { serviceClient } from './fleetSupabase'
import { organizationContext, requireOrgAdmin } from './adaptiveFabric'

const DEFAULT_SKILLS = [
  { skill_key: 'portfolio-operator', label: 'Portfolio operator', description: 'Interprets portfolio state and resolves operational constraints.', capability_grants: ['portfolio:read', 'queue:operate'] },
  { skill_key: 'governed-connector-admin', label: 'Governed connector administrator', description: 'Configures delegated providers and understands least-privilege consent.', capability_grants: ['connectors:admin'] },
  { skill_key: 'change-simulator', label: 'Change simulator', description: 'Uses CADE evidence and guardrails before execution.', capability_grants: ['simulation:run'] },
]

export async function ensureEvolutionDefaults(user: any) {
  const sb = serviceClient(); const context = await organizationContext(user); const organizationId = context.membership.organization_id
  await Promise.all([
    sb.from('private_learning_profiles').upsert({ user_id: user.id, organization_id: organizationId }, { onConflict: 'user_id', ignoreDuplicates: true }),
    sb.from('accessibility_profiles').upsert({ user_id: user.id, organization_id: organizationId }, { onConflict: 'user_id', ignoreDuplicates: true }),
    ...DEFAULT_SKILLS.map(skill => sb.from('organizational_skills').upsert({ organization_id: organizationId, ...skill, evidence_policy: { minimum_demonstrations: 1, admin_verification_for_level: 3 }, created_by: user.id }, { onConflict: 'organization_id,skill_key', ignoreDuplicates: true })),
  ])
  return context
}

export async function evolutionContext(user: any) {
  const sb = serviceClient(); const context = await ensureEvolutionDefaults(user); const organizationId = context.membership.organization_id
  const [skills, evidence, privacy, accessibility, simulations, trust, lifecycle, outcomes] = await Promise.all([
    sb.from('organizational_skills').select('*').eq('organization_id', organizationId).order('created_at'),
    sb.from('member_skill_evidence').select('*,skill:organizational_skills(skill_key,label,capability_grants)').eq('user_id', user.id),
    sb.from('private_learning_profiles').select('*').eq('user_id', user.id).single(),
    sb.from('accessibility_profiles').select('*').eq('user_id', user.id).single(),
    sb.from('interface_twin_simulations').select('id,objective,proposal,projected_outcome,status,created_at').eq('user_id', user.id).order('created_at', { ascending: false }).limit(3),
    sb.from('federated_passport_credentials').select('id,capabilities,claims,status,expires_at,created_at,issuer:orchestrator_organizations!federated_passport_credentials_issuer_organization_id_fkey(name,slug)').eq('subject_organization_id', organizationId).eq('status', 'active'),
    sb.from('connector_lifecycle_events').select('provider,event,status,next_action_at,created_at').eq('organization_id', organizationId).order('created_at', { ascending: false }).limit(30),
    sb.from('capability_route_outcomes').select('provider,succeeded,quality,latency_ms,realized_cost_usd,policy_incidents').eq('organization_id', organizationId).limit(500),
  ])
  const performance: Record<string, any> = {}
  for (const row of outcomes.data || []) { const value = performance[row.provider] ||= { runs: 0, successes: 0, quality: 0, cost: 0, latency: 0, incidents: 0 }; value.runs++; value.successes += row.succeeded ? 1 : 0; value.quality += Number(row.quality); value.cost += Number(row.realized_cost_usd || 0); value.latency += Number(row.latency_ms || 0); value.incidents += row.policy_incidents || 0 }
  for (const value of Object.values(performance) as any[]) { value.reliability = value.runs ? value.successes / value.runs : .9; value.average_quality = value.runs ? value.quality / value.runs : 0; value.average_cost_usd = value.runs ? value.cost / value.runs : 0; value.average_latency_ms = value.runs ? Math.round(value.latency / value.runs) : 0 }
  let cohort_learning: any = { status: 'disabled', routes: [] }
  if (privacy.data?.enabled && privacy.data?.share_aggregate) {
    const cutoff = new Date(Date.now() - Number(privacy.data.retention_days || 30) * 86400_000).toISOString(); const { data: cohortEvents } = await sb.from('interface_learning_events').select('user_id,route').eq('organization_id', organizationId).gte('created_at', cutoff).limit(5000); const contributors = new Set((cohortEvents || []).map((row: any) => row.user_id)); const minimum = Number(privacy.data.minimum_cohort || 5)
    if (contributors.size < minimum) cohort_learning = { status: 'withheld', reason: `Requires at least ${minimum} contributors`, contributors: contributors.size, routes: [] }
    else { const counts: Record<string, number> = {}; for (const row of cohortEvents || []) if (row.route) counts[row.route] = (counts[row.route] || 0) + 1; const noise = Number(privacy.data.noise_level || 0); cohort_learning = { status: 'available', contributors: contributors.size, privacy: { minimum_cohort: minimum, bounded_noise: noise, user_ids_disclosed: false }, routes: Object.entries(counts).map(([route,count]) => ({ route, approximate_visits: Math.max(0, Math.round(count * (1 + (Math.random() - .5) * noise))) })).sort((a,b) => b.approximate_visits - a.approximate_visits).slice(0,5) } }
  }
  return { role: context.membership.role, organization: context.membership.organization, skills: skills.data || [], evidence: evidence.data || [], privacy: privacy.data, cohort_learning, accessibility: accessibility.data, simulations: simulations.data || [], trusted_credentials: trust.data || [], lifecycle: lifecycle.data || [], provider_performance: performance, navigation_contract: { version: NAVIGATION_CONTRACT_VERSION, invariant_routes: CANONICAL_NAVIGATION.map(item => item.to) } }
}

export async function simulateInterfaceTwin(user: any, objective: string) {
  const sb = serviceClient(); const context = await ensureEvolutionDefaults(user); const organizationId = context.membership.organization_id
  const { data: events } = await sb.from('interface_learning_events').select('route,event').eq('user_id', user.id).order('created_at', { ascending: false }).limit(500)
  const frequencies: Record<string, number> = {}; for (const row of events || []) if (row.route) frequencies[row.route] = (frequencies[row.route] || 0) + 1
  const preferred = Object.entries(frequencies).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([route, visits]) => ({ route, visits }))
  const proposal = { objective, suggested_next_actions: preferred, layout_changes: [], navigation_changes: [], rule: 'Recommendations adapt; canonical destinations never move.' }
  const evidence = Math.min(1, (events?.length || 0) / 50); const projected = { time_to_action_reduction: Number((.08 + evidence * .22).toFixed(2)), expected_completion_lift: Number((.05 + evidence * .18).toFixed(2)), confidence: Number((.55 + evidence * .35).toFixed(2)), exposure_risk: 0 }
  const { data, error } = await sb.from('interface_twin_simulations').insert({ user_id: user.id, organization_id: organizationId, objective, current_contract_version: NAVIGATION_CONTRACT_VERSION, proposal, projected_outcome: projected, invariant_routes: CANONICAL_NAVIGATION.map(item => item.to) }).select().single()
  if (error) throw createError({ statusCode: 500, message: 'interface_twin_simulation_failed' })
  return data
}

export async function updateEvolutionPreferences(user: any, kind: 'privacy' | 'accessibility', values: any) {
  const sb = serviceClient(); const context = await ensureEvolutionDefaults(user); const organization_id = context.membership.organization_id
  if (kind === 'privacy') { const allowed = { enabled: values.enabled !== false, share_aggregate: values.share_aggregate !== false, retention_days: Math.max(1, Math.min(365, Number(values.retention_days || 30))), minimum_cohort: Math.max(3, Math.min(100, Number(values.minimum_cohort || 5))), noise_level: Math.max(0, Math.min(1, Number(values.noise_level ?? .1))), updated_at: new Date().toISOString() }; return (await sb.from('private_learning_profiles').upsert({ user_id: user.id, organization_id, ...allowed }).select().single()).data }
  const allowed = { density: ['compact','comfortable','spacious'].includes(values.density) ? values.density : 'comfortable', explanation_depth: ['concise','balanced','detailed'].includes(values.explanation_depth) ? values.explanation_depth : 'balanced', motion: ['system','reduced','none'].includes(values.motion) ? values.motion : 'system', contrast: values.contrast === 'high' ? 'high' : 'system', text_scale: Math.max(.9, Math.min(1.5, Number(values.text_scale || 1))), keyboard_first: !!values.keyboard_first, updated_at: new Date().toISOString() }; return (await sb.from('accessibility_profiles').upsert({ user_id: user.id, organization_id, ...allowed }).select().single()).data
}

export async function recordSkillEvidence(actor: any, values: any) {
  const sb = serviceClient(); const context = await ensureEvolutionDefaults(actor); const skillId = String(values.skill_id || ''); const targetUser = String(values.user_id || actor.id)
  const { data: skill } = await sb.from('organizational_skills').select('id').eq('id', skillId).eq('organization_id', context.membership.organization_id).maybeSingle(); if (!skill) throw createError({ statusCode: 404, message: 'organizational_skill_not_found' })
  const verified = targetUser === actor.id && Number(values.level || 1) < 3 ? false : true; if (targetUser !== actor.id || Number(values.level || 1) >= 3) requireOrgAdmin(context)
  const row = { organization_id: context.membership.organization_id, user_id: targetUser, skill_id: skillId, level: Math.max(1, Math.min(5, Number(values.level || 1))), status: verified ? 'verified' : 'observed', evidence: values.evidence || { source: 'demonstrated_workflow' }, verified_by: verified ? actor.id : null, verified_at: verified ? new Date().toISOString() : null }
  return (await sb.from('member_skill_evidence').upsert(row, { onConflict: 'user_id,skill_id' }).select().single()).data
}

function trustSignature(payload: string) { const key = process.env.CONNECTOR_VAULT_KEY; if (!key) throw createError({ statusCode: 503, message: 'trust_signing_key_unavailable' }); return createHmac('sha256', key).update(payload).digest('base64url') }
export async function issueFederatedCredential(actor: any, values: any) {
  const sb = serviceClient(); const context = await ensureEvolutionDefaults(actor); requireOrgAdmin(context)
  const subjectSlug = String(values.subject_slug || '').trim(); const { data: subject } = await sb.from('orchestrator_organizations').select('id,name,slug').eq('slug', subjectSlug).maybeSingle(); if (!subject) throw createError({ statusCode: 404, message: 'subject_organization_not_found' })
  const capabilities = [...new Set((values.capabilities || []).map((item: any) => String(item)).filter(Boolean))]; const expiresAt = new Date(Date.now() + Math.max(1, Math.min(365, Number(values.days || 90))) * 86400_000).toISOString(); const claims = { issuer: context.membership.organization_id, subject: subject.id, capabilities, passport_version: context.passport.version, issued_at: new Date().toISOString(), expires_at: expiresAt }; const signature = trustSignature(JSON.stringify(claims))
  const { data, error } = await sb.from('federated_passport_credentials').insert({ subject_organization_id: subject.id, issuer_organization_id: context.membership.organization_id, capabilities, claims, signature, expires_at: expiresAt, issued_by: actor.id }).select('id,capabilities,expires_at,status').single(); if (error) throw createError({ statusCode: 500, message: 'federated_credential_issue_failed' }); return data
}
