import { createHash, createHmac, randomBytes } from 'node:crypto'
import { organizationContext } from './adaptiveFabric'
import { serviceClient } from './fleetSupabase'
import { runRegulatoryAutopilot } from './regulatoryCapability'

type CreditRow = {
  amount_cents: number | string
  status: string
  event_type: string
  expires_at?: string | null
}

const now = () => new Date().toISOString()
const stable = (value: any): string => Array.isArray(value)
  ? `[${value.map(stable).join(',')}]`
  : value && typeof value === 'object'
    ? `{${Object.keys(value).sort().map(key => `${key}:${stable(value[key])}`).join(',')}}`
    : JSON.stringify(value)
const digest = (value: any) => createHash('sha256').update(stable(value)).digest('hex')
const bounded = (value: any, length = 160) => String(value || '').trim().slice(0, length)

function signingKey() {
  const secret = process.env.CONNECTOR_VAULT_KEY
  if (!secret) throw createError({ statusCode: 503, message: 'connector_vault_key_required' })
  return createHash('sha256').update(secret).digest()
}

function sign(value: any) {
  return createHmac('sha256', signingKey()).update(stable(value)).digest('base64url')
}

export function evaluateLicensePolicy(license: any, claims: any) {
  const limits = license.execution_limits || {}
  const allowedScopes = new Set<string>(license.scopes || [])
  const requestedScopes = [...new Set<string>((claims.scopes || []).map(String))]
  const reasons: string[] = []
  if (license.status !== 'active') reasons.push('license_not_active')
  if (new Date(license.expires_at).getTime() <= Date.now()) reasons.push('license_expired')
  if (requestedScopes.some(scope => !allowedScopes.has(scope))) reasons.push('scope_not_granted')
  if (Number(claims.projects || 1) > Number(limits.max_projects || 1)) reasons.push('project_limit_exceeded')
  if (Number(claims.monthly_executions || 1) > Number(limits.max_executions_per_month || 1)) reasons.push('execution_limit_exceeded')
  if (claims.training_use) reasons.push('training_use_denied')
  if (claims.resale) reasons.push('resale_denied')
  if (claims.redelegated) reasons.push('redelegation_denied')
  return {
    passed: reasons.length === 0,
    reasons,
    evaluated_claims: {
      scopes: requestedScopes,
      projects: Number(claims.projects || 1),
      monthly_executions: Number(claims.monthly_executions || 1),
      prohibited_uses_asserted_false: !claims.training_use && !claims.resale && !claims.redelegated,
    },
  }
}

export function computeCreditAccount(rows: CreditRow[], riskTier = 'standard', at = new Date()) {
  const expired = rows.filter(row => row.expires_at && new Date(row.expires_at) <= at && row.status === 'available')
  const live = rows.filter(row => !row.expires_at || new Date(row.expires_at) > at)
  const positive = (status: string) => live
    .filter(row => row.status === status && Number(row.amount_cents) > 0)
    .reduce((sum, row) => sum + Number(row.amount_cents), 0)
  const accrued = positive('accrued')
  const grossAvailable = positive('available')
  const reserveRate = riskTier === 'elevated' ? .25 : riskTier === 'restricted' ? .5 : riskTier === 'low' ? .05 : .1
  const reserve = Math.round(grossAvailable * reserveRate)
  const deductions = Math.abs(live
    .filter(row => Number(row.amount_cents) < 0 && ['available', 'settled'].includes(row.status))
    .reduce((sum, row) => sum + Number(row.amount_cents), 0))
  const lifetimeEarned = rows.filter(row => Number(row.amount_cents) > 0).reduce((sum, row) => sum + Number(row.amount_cents), 0)
  const lifetimeUsed = Math.abs(rows.filter(row => Number(row.amount_cents) < 0 || row.status === 'settled').reduce((sum, row) => sum + Math.min(0, Number(row.amount_cents)), 0))
  const expiries = live.map(row => row.expires_at).filter(Boolean).sort()
  return {
    accrued_cents: accrued,
    available_cents: Math.max(0, grossAvailable - reserve - deductions),
    reserved_cents: reserve,
    pending_settlement_cents: accrued,
    lifetime_earned_cents: lifetimeEarned,
    lifetime_used_cents: lifetimeUsed,
    expired_cents: expired.reduce((sum, row) => sum + Math.max(0, Number(row.amount_cents)), 0),
    next_expiry_at: expiries[0] || null,
    risk_tier: riskTier,
  }
}

export function classifyFailureEvidence(evidence: any) {
  const sample = Number(evidence.aggregate_result?.sample_size || 0)
  const independent = Boolean(evidence.verification?.independent)
  const boundaries = evidence.boundary_conditions || {}
  const boundaryCount = [boundaries.stage, boundaries.runtime, ...(boundaries.constraints || [])].filter(Boolean).length
  const strong = sample >= 50 && independent
  const classification = !independent || sample < 20
    ? 'insufficient_evidence'
    : boundaryCount >= 3 && !strong
      ? 'context_mismatch'
      : 'portable_failure'
  const confidence = classification === 'insufficient_evidence' ? .35 : Math.min(.96, .55 + Math.log10(Math.max(20, sample)) * .12 + (independent ? .12 : 0))
  return {
    classification,
    confidence: Number(confidence.toFixed(3)),
    causal_factors: {
      attempted_pattern: evidence.attempted_pattern,
      measured_effect: evidence.aggregate_result?.effect,
      independent_verification: independent,
      sample_size: sample,
    },
    applicable_contexts: classification === 'portable_failure' ? { problem_class: evidence.problem_class } : boundaries,
    excluded_contexts: classification === 'context_mismatch' ? { outside_boundary_conditions: true } : {},
    recommendation: classification === 'portable_failure'
      ? 'Avoid this pattern unless materially new evidence changes the causal case.'
      : classification === 'context_mismatch'
        ? 'Treat this as a context mismatch; test only where the stated boundaries differ.'
        : 'Do not generalize yet; collect an independently verified aggregate of at least 20 observations.',
  }
}

export function simulateConstitution(proposal: any, conflicts: any[] = []) {
  const domain = proposal.policy_domain
  const rule = String(proposal.proposed_policy?.rule || '')
  const broad = /all|unlimited|permanent|mandatory|remove|disable/i.test(rule)
  const rightsSensitive = ['privacy', 'prohibited_use', 'licensing'].includes(domain)
  const materialConflicts = conflicts.filter(item => item.material_interest).length
  const captureScore = Math.min(100, materialConflicts * 20 + (broad ? 35 : 5) + (proposal.organization_id ? 5 : 0))
  const rightsScore = Math.min(100, (rightsSensitive ? 35 : 10) + (broad ? 35 : 0))
  const recommendation = captureScore >= 60 || rightsScore >= 70 ? 'revise' : 'proceed'
  return {
    archetype_results: [
      { archetype: 'solo_founder', expected_effect: broad ? 'high_variance' : 'bounded', operational_burden: 'low' },
      { archetype: 'multi_company_operator', expected_effect: 'portfolio_compounding', operational_burden: broad ? 'medium' : 'low' },
      { archetype: 'regulated_team', expected_effect: rightsSensitive ? 'review_required' : 'bounded', operational_burden: 'medium' },
      { archetype: 'capability_provider', expected_effect: domain === 'rebates' ? 'economic_change' : 'bounded', operational_burden: 'low' },
    ],
    rights_impact: { score: rightsScore, domains: rightsSensitive ? [domain] : [], irreversible_change_denied: true },
    capture_risk: { score: captureScore, material_conflicts: materialConflicts, token_weighting: false },
    minority_safeguards: {
      privacy_floor: true,
      prohibited_use_floor: true,
      minority_appeal: true,
      supermajority_for_rights_changes: true,
      proposer_recusal_when_materially_interested: true,
    },
    recommendation,
  }
}

export async function recordExecutionProof(user: any, values: any) {
  const context = await organizationContext(user)
  const organizationId = context.membership.organization_id
  const sb = serviceClient()
  const { data: license } = await sb.from('hivemind_executable_licenses').select('*')
    .eq('id', String(values.license_id || ''))
    .or(`licensor_organization_id.eq.${organizationId},licensee_organization_id.eq.${organizationId}`)
    .maybeSingle()
  if (!license) throw createError({ statusCode: 404, message: 'organization_license_required' })
  const executionRef = bounded(values.execution_ref, 200)
  const inputCommitment = bounded(values.input_commitment, 256)
  const outputCommitment = bounded(values.output_commitment, 256)
  if (!executionRef || !inputCommitment || !outputCommitment) throw createError({ statusCode: 400, message: 'execution_commitments_required' })
  const evaluation = evaluateLicensePolicy(license, values.claims || {})
  const { data: previous } = await sb.from('hivemind_license_execution_proofs').select('proof_digest')
    .eq('license_id', license.id).order('created_at', { ascending: false }).limit(1).maybeSingle()
  const receipt = {
    license_id: license.id,
    organization_id: organizationId,
    execution_ref: executionRef,
    claims: evaluation.evaluated_claims,
    policy_evaluation: evaluation,
    input_commitment: inputCommitment,
    output_commitment: outputCommitment,
    previous_proof_digest: previous?.proof_digest || null,
    verdict: evaluation.passed ? 'verified' : 'breach',
  }
  const proofDigest = digest(receipt)
  const { data, error } = await sb.from('hivemind_license_execution_proofs').upsert({
    ...receipt,
    proof_digest: proofDigest,
    signature: sign({ proof_digest: proofDigest, license_digest: license.license_digest }),
  }, { onConflict: 'license_id,execution_ref' }).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  await sb.from('hivemind_executable_licenses').update({
    proof_status: evaluation.passed ? 'verified' : 'failed',
    last_verified_at: evaluation.passed ? now() : license.last_verified_at,
  }).eq('id', license.id)
  return { receipt: data, payloads_stored: false }
}

async function classifyUnprocessedFailures(organizationId: string) {
  const sb = serviceClient()
  const { data: evidence } = await sb.from('hivemind_negative_evidence').select('*').eq('organization_id', organizationId).in('status', ['verified', 'published']).limit(50)
  if (!evidence?.length) return 0
  const { data: existing } = await sb.from('hivemind_negative_evidence_intelligence').select('negative_evidence_id').in('negative_evidence_id', evidence.map(item => item.id))
  const seen = new Set((existing || []).map(item => item.negative_evidence_id))
  const rows = evidence.filter(item => !seen.has(item.id)).map(item => {
    const intelligence = classifyFailureEvidence(item)
    return {
      negative_evidence_id: item.id,
      organization_id: organizationId,
      ...intelligence,
      intelligence_digest: digest({ negative_evidence_id: item.id, intelligence }),
    }
  })
  if (rows.length) await sb.from('hivemind_negative_evidence_intelligence').insert(rows)
  return rows.length
}

async function simulateOpenProposals(organizationId: string) {
  const sb = serviceClient()
  const { data: proposals } = await sb.from('hivemind_governance_proposals').select('*').in('status', ['draft', 'open']).limit(50)
  if (!proposals?.length) return 0
  const { data: existing } = await sb.from('hivemind_governance_simulations').select('proposal_id').in('proposal_id', proposals.map(item => item.id))
  const seen = new Set((existing || []).map(item => item.proposal_id))
  let created = 0
  for (const proposal of proposals.filter(item => !seen.has(item.id))) {
    const { data: conflicts } = await sb.from('hivemind_governance_conflicts').select('*').eq('proposal_id', proposal.id)
    const simulation = simulateConstitution(proposal, conflicts || [])
    const simulationDigest = digest({ proposal_id: proposal.id, simulation })
    await sb.from('hivemind_governance_simulations').insert({
      proposal_id: proposal.id,
      organization_id: proposal.organization_id,
      ...simulation,
      simulation_digest: simulationDigest,
    })
    if (simulation.recommendation === 'revise' && proposal.status === 'open') {
      await sb.from('hivemind_governance_proposals').update({ status: 'draft' }).eq('id', proposal.id)
    }
    created += 1
  }
  return created
}

async function clearTreasury(organizationId: string) {
  const sb = serviceClient()
  const { data: rows } = await sb.from('hivemind_rebate_ledger').select('amount_cents,status,event_type,expires_at').eq('organization_id', organizationId)
  const account = computeCreditAccount((rows || []) as CreditRow[])
  const snapshotDigest = digest({ organizationId, account, day: now().slice(0, 10) })
  await sb.from('hivemind_credit_accounts').upsert({
    organization_id: organizationId,
    ...account,
    snapshot_digest: snapshotDigest,
    updated_at: now(),
  }, { onConflict: 'organization_id' })
  const date = new Date()
  const periodStart = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1)).toISOString()
  const periodEnd = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 1)).toISOString()
  const exportSummary = {
    schema: 'madeus.hivemind.credit-clearing.v1',
    currency: 'USD_CREDIT',
    organization_id: organizationId,
    period_start: periodStart,
    period_end: periodEnd,
    available_cents: account.available_cents,
    reserve_cents: account.reserved_cents,
    raw_ledger_included: false,
  }
  await sb.from('hivemind_credit_clearing_runs').upsert({
    organization_id: organizationId,
    period_start: periodStart,
    period_end: periodEnd,
    gross_credit_cents: account.available_cents + account.reserved_cents,
    reserve_cents: account.reserved_cents,
    expired_cents: account.expired_cents,
    net_available_cents: account.available_cents,
    accounting_export: exportSummary,
    clearing_digest: digest(exportSummary),
  }, { onConflict: 'organization_id,period_start,period_end' })
  return account
}

async function containImmuneSignals(organizationId: string) {
  const sb = serviceClient()
  const { data: signals } = await sb.from('hivemind_immune_signals').select('*').eq('status', 'active').in('severity', ['high', 'critical']).limit(50)
  if (!signals?.length) return { contained: 0, alerts: [] as any[] }
  const contributionIds = [...new Set(signals.map(item => item.contribution_id).filter(Boolean))]
  const { data: escrows } = contributionIds.length
    ? await sb.from('hivemind_capability_escrows').select('id,contribution_id').in('contribution_id', contributionIds)
    : { data: [] as any[] }
  const escrowIds = (escrows || []).map(item => item.id)
  const { data: licenses } = escrowIds.length
    ? await sb.from('hivemind_executable_licenses').select('*').in('escrow_id', escrowIds).eq('status', 'active').or(`licensor_organization_id.eq.${organizationId},licensee_organization_id.eq.${organizationId}`)
    : { data: [] as any[] }
  let contained = 0
  const alerts: any[] = []
  for (const license of licenses || []) {
    const escrow = (escrows || []).find(item => item.id === license.escrow_id)
    const signal = signals.find(item => item.contribution_id === escrow?.contribution_id)
    if (!signal) continue
    const actions = ['suspend affected license scopes', 'freeze new executions', 'preserve last verified adapter', 'queue targeted regression proof']
    const response = {
      organization_id: organizationId,
      signal_id: signal.id,
      license_id: license.id,
      contribution_id: escrow?.contribution_id || null,
      actions,
      affected_scope: { scopes: license.scopes, organization_only: true },
      customer_impact: 'New affected executions paused; healthy services remain on the last verified adapter.',
      rollback_ready: true,
      status: 'contained',
    }
    await sb.from('hivemind_executable_licenses').update({
      status: 'suspended',
      proof_status: 'failed',
      suspended_reason: `immune_signal:${signal.id}`,
    }).eq('id', license.id)
    await sb.from('hivemind_immune_response_receipts').upsert({
      ...response,
      response_digest: digest(response),
    }, { onConflict: 'signal_id,organization_id,license_id' })
    contained += 1
    alerts.push({ kind: 'protection', severity: signal.severity, title: 'A shared capability was contained', outcome: response.customer_impact })
  }
  return { contained, alerts }
}

async function deriveFollowOnOpportunities(organizationId: string) {
  const sb = serviceClient()
  const { data: bundles } = await sb.from('hivemind_execution_bundles').select('*').eq('organization_id', organizationId).eq('status', 'verified').limit(20)
  if (!bundles?.length) return 0
  const { data: derivations } = await sb.from('hivemind_opportunity_derivations').select('parent_bundle_id').eq('organization_id', organizationId)
  const seen = new Set((derivations || []).map(item => item.parent_bundle_id))
  let created = 0
  for (const bundle of bundles.filter(item => !seen.has(item.id))) {
    const { data: parentDerivation } = bundle.opportunity_id
      ? await sb.from('hivemind_opportunity_derivations').select('generation').eq('child_opportunity_id', bundle.opportunity_id).maybeSingle()
      : { data: null }
    const generation = Number(parentDerivation?.generation || 0) + 1
    if (generation > 3) continue
    const opportunity = {
      organization_id: organizationId,
      opportunity_type: 'verified_follow_on',
      title: `Compound the verified outcome: ${bounded(bundle.objective, 100)}`,
      explanation: 'Madeus detected a bounded follow-on that reuses the verified result while preserving the original consent, privacy, and rollback boundaries.',
      predicted_value_cents: 0,
      confidence: .72,
      source_refs: { parent_bundle_id: bundle.id, parent_opportunity_id: bundle.opportunity_id },
      consent_requirements: { inherited_scope_only: true, fresh_consent_if_material: true },
      next_action: { type: 'simulate_then_bundle', automatic_non_material_only: true },
      status: 'open',
    }
    const { data: child } = await sb.from('hivemind_opportunities').insert(opportunity).select().single()
    if (!child) continue
    const causalBasis = { verified_bundle: bundle.id, status: bundle.status, inherited_rollback: bundle.rollback_plan }
    await sb.from('hivemind_opportunity_derivations').insert({
      organization_id: organizationId,
      parent_opportunity_id: bundle.opportunity_id,
      parent_bundle_id: bundle.id,
      child_opportunity_id: child.id,
      generation,
      causal_basis: causalBasis,
      guardrails: { max_generation: 3, diminishing_risk: true, no_scope_amplification: true, material_change_requires_consent: true },
      derivation_digest: digest({ organizationId, bundle: bundle.id, child: child.id, causalBasis }),
    })
    created += 1
  }
  return created
}

export async function runOrganizationAutopilot(organizationId: string, trigger: 'session' | 'schedule' | 'event' | 'operator' = 'session') {
  const sb = serviceClient()
  if (trigger === 'session') {
    const cutoff = new Date(Date.now() - 10 * 60_000).toISOString()
    const { data: recent } = await sb.from('hivemind_autopilot_runs').select('*').eq('organization_id', organizationId).gte('started_at', cutoff).order('started_at', { ascending: false }).limit(1).maybeSingle()
    if (recent) return recent
  }
  const startedAt = now()
  const [failures, simulations, treasury, immunity, derivations, regulatory] = await Promise.all([
    classifyUnprocessedFailures(organizationId),
    simulateOpenProposals(organizationId),
    clearTreasury(organizationId),
    containImmuneSignals(organizationId),
    deriveFollowOnOpportunities(organizationId),
    runRegulatoryAutopilot(organizationId, trigger).catch((error: any) => ({ status: 'failed', outcomes: [], exceptions: [], error: bounded(error?.message, 120) })),
  ])
  const outcomes = [
    failures ? { kind: 'learning', title: `${failures} failure pattern${failures === 1 ? '' : 's'} made reusable` } : null,
    simulations ? { kind: 'governance', title: `${simulations} proposal${simulations === 1 ? '' : 's'} simulated before voting` } : null,
    derivations ? { kind: 'opportunity', title: `${derivations} verified follow-on opportunit${derivations === 1 ? 'y' : 'ies'} found` } : null,
    treasury.available_cents ? { kind: 'earnings', title: 'Credits cleared and ready', amount_cents: treasury.available_cents } : null,
    immunity.contained ? { kind: 'protection', title: `${immunity.contained} affected permission set${immunity.contained === 1 ? '' : 's'} contained` } : null,
    ...(regulatory.outcomes || []),
  ].filter(Boolean)
  const exceptions = [...immunity.alerts, ...(regulatory.exceptions || [])]
  const operations = {
    failures_classified: failures,
    proposals_simulated: simulations,
    opportunities_derived: derivations,
    immune_containments: immunity.contained,
    treasury_snapshot_digest: digest(treasury),
    regulatory_run_status: regulatory.status,
    private_payloads_processed: false,
  }
  const run = {
    organization_id: organizationId,
    trigger,
    outcomes,
    exceptions,
    operations,
    status: exceptions.length ? 'attention_required' : 'completed',
    started_at: startedAt,
    completed_at: now(),
  }
  const { data, error } = await sb.from('hivemind_autopilot_runs').insert({ ...run, run_digest: digest({ organizationId, startedAt, operations, nonce: randomBytes(6).toString('hex') }) }).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  return data
}

export async function runUserAutopilot(user: any, trigger: 'session' | 'operator' = 'session') {
  const context = await organizationContext(user)
  return runOrganizationAutopilot(context.membership.organization_id, trigger)
}

export async function declareGovernanceConflict(user: any, values: any) {
  const context = await organizationContext(user)
  const organizationId = context.membership.organization_id
  const proposalId = String(values.proposal_id || '')
  const relationshipClass = bounded(values.relationship_class || 'none', 80)
  const materialInterest = Boolean(values.material_interest)
  if (!proposalId) throw createError({ statusCode: 400, message: 'proposal_required' })
  const disclosure = {
    proposal_id: proposalId,
    organization_id: organizationId,
    relationship_class: relationshipClass,
    material_interest: materialInterest,
    recusal_required: materialInterest,
  }
  const { data, error } = await serviceClient().from('hivemind_governance_conflicts').upsert({
    ...disclosure,
    disclosure_digest: digest(disclosure),
  }, { onConflict: 'proposal_id,organization_id' }).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  return data
}

export async function outcomeCockpit(user: any) {
  const context = await organizationContext(user)
  const organizationId = context.membership.organization_id
  const sb = serviceClient()
  let autopilot: any = null
  try { autopilot = await runOrganizationAutopilot(organizationId, 'session') } catch (error: any) {
    if (!['connector_vault_key_required'].includes(error?.message)) throw error
  }
  const [account, opportunities, bundles, licenses, proofs, immune, proposals, simulations, failures, clearing] = await Promise.all([
    sb.from('hivemind_credit_accounts').select('*').eq('organization_id', organizationId).maybeSingle(),
    sb.from('hivemind_opportunities').select('*').eq('organization_id', organizationId).eq('status', 'open').order('predicted_value_cents', { ascending: false }).limit(12),
    sb.from('hivemind_execution_bundles').select('*').eq('organization_id', organizationId).order('created_at', { ascending: false }).limit(12),
    sb.from('hivemind_executable_licenses').select('*').or(`licensor_organization_id.eq.${organizationId},licensee_organization_id.eq.${organizationId}`).order('created_at', { ascending: false }).limit(30),
    sb.from('hivemind_license_execution_proofs').select('id,license_id,verdict,proof_digest,created_at').eq('organization_id', organizationId).order('created_at', { ascending: false }).limit(30),
    sb.from('hivemind_immune_response_receipts').select('*').eq('organization_id', organizationId).order('created_at', { ascending: false }).limit(20),
    sb.from('hivemind_governance_proposals').select('*').in('status', ['open', 'accepted', 'enacted']).order('created_at', { ascending: false }).limit(20),
    sb.from('hivemind_governance_simulations').select('*').order('created_at', { ascending: false }).limit(20),
    sb.from('hivemind_negative_evidence_intelligence').select('*').eq('organization_id', organizationId).order('created_at', { ascending: false }).limit(20),
    sb.from('hivemind_credit_clearing_runs').select('*').eq('organization_id', organizationId).order('period_end', { ascending: false }).limit(6),
  ])
  const simulationByProposal = new Map((simulations.data || []).map(item => [item.proposal_id, item]))
  return {
    role: context.membership.role,
    autopilot,
    account: account.data || { accrued_cents: 0, available_cents: 0, reserved_cents: 0, lifetime_earned_cents: 0 },
    outcomes: autopilot?.outcomes || [],
    attention: autopilot?.exceptions || [],
    earn: { clearing: clearing.data || [], failures: failures.data || [] },
    adopt: { opportunities: opportunities.data || [], bundles: bundles.data || [] },
    protect: { licenses: licenses.data || [], proofs: proofs.data || [], immune: immune.data || [] },
    govern: { proposals: (proposals.data || []).map(item => ({ ...item, simulation: simulationByProposal.get(item.id) || null })) },
    privacy: { raw_payloads_stored: false, cross_organization_models_collected: false },
  }
}

export async function runScheduledAutopilot() {
  const sb = serviceClient()
  const { data: policies, error } = await sb.from('hivemind_sharing_policies').select('organization_id')
  if (error) throw createError({ statusCode: 500, message: error.message })
  const results = []
  for (const policy of policies || []) {
    try {
      const run = await runOrganizationAutopilot(policy.organization_id, 'schedule')
      results.push({ organization_id: policy.organization_id, status: run.status })
    } catch (error: any) {
      results.push({ organization_id: policy.organization_id, status: 'failed', error: bounded(error?.message, 120) })
    }
  }
  return { processed: results.length, results }
}
