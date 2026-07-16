import { createHash, randomBytes } from 'node:crypto'
import { organizationContext } from './adaptiveFabric'
import { appBaseUrl, serviceClient } from './fleetSupabase'
import { runTemporalRegulatoryAutopilot } from './regulatoryTemporal'
import { frontierCockpit, runRegulatoryFrontierAutopilot } from './regulatoryFrontier'

type ActivitySource = {
  source_type?: string
  source_ref?: string
  project_ref?: string
  summary?: string
  indicators?: string[]
  jurisdictions?: string[]
  materiality?: string
}

type RuleTemplate = {
  rule_key: string
  domain: string
  patterns: RegExp
  activity: string
  trigger_summary: string
  coverage_models: Array<{ type: string; label: string; conditions: string[] }>
  eligibility_requirements: Array<{ key: string; label: string; kind: string; required: boolean }>
  alternatives: Array<{ type: string; label: string; boundary: string; compensation?: string }>
  prohibited_shortcuts: string[]
}

const RULES: RuleTemplate[] = [
  {
    rule_key: 'us-securities-intermediation', domain: 'securities', activity: 'securities_intermediation',
    patterns: /securit|broker|placement agent|transaction.?based|investor solicitation|capital raise|commission/i,
    trigger_summary: 'Solicitation, negotiation, execution, or transaction-linked compensation may require a registered securities structure.',
    coverage_models: [
      { type: 'associated_person', label: 'Operate as a supervised associated person', conditions: ['principal supervision', 'required individual qualification', 'approved compensation path'] },
      { type: 'referral', label: 'Bounded referral to a registered firm', conditions: ['no transaction participation', 'compensation reviewed', 'clear customer disclosure'] },
    ],
    eligibility_requirements: [
      { key: 'qualified_principal', label: 'Qualified supervising principal', kind: 'relationship', required: true },
      { key: 'individual_qualification', label: 'Required individual exams and registration', kind: 'credential', required: true },
      { key: 'supervisory_procedures', label: 'Written supervisory procedures', kind: 'document', required: true },
    ],
    alternatives: [
      { type: 'referral', label: 'Introduction-only workflow', boundary: 'Do not solicit, negotiate, recommend, handle funds, or execute.', compensation: 'Use counsel-reviewed fixed or non-transaction-linked consideration only where permitted.' },
      { type: 'technology_provider', label: 'Technology-only provider', boundary: 'Provide neutral infrastructure without transaction discretion or investor-facing sales activity.' },
    ],
    prohibited_shortcuts: ['license lending', 'unregistered entity receiving commissions', 'activity outside sponsor supervision'],
  },
  {
    rule_key: 'us-money-transmission', domain: 'payments', activity: 'money_transmission',
    patterns: /wallet|money transmi|send money|remittance|stored value|custod|hold funds|payment flow|payout/i,
    trigger_summary: 'Receiving, holding, or transmitting value for another person can trigger federal and state money-services requirements.',
    coverage_models: [
      { type: 'authorized_delegate', label: 'Authorized delegate or agent', conditions: ['principal approval', 'jurisdiction coverage', 'AML allocation', 'transaction monitoring'] },
      { type: 'service_provider', label: 'Licensed provider is merchant/customer counterparty', conditions: ['funds never controlled by member', 'provider disclosures', 'API and ledger controls'] },
    ],
    eligibility_requirements: [
      { key: 'control_person_review', label: 'Control-person and ownership review', kind: 'identity', required: true },
      { key: 'aml_program', label: 'AML and sanctions program', kind: 'document', required: true },
      { key: 'bonding_capital', label: 'Required bonding and capital', kind: 'financial', required: true },
      { key: 'operating_history', label: 'Documented operating history where required', kind: 'history', required: false },
    ],
    alternatives: [
      { type: 'service_provider', label: 'Provider-controlled payment flow', boundary: 'Licensed provider contracts, controls funds, performs KYC/AML, and settles directly.' },
      { type: 'administrative_services', label: 'Administrative reconciliation only', boundary: 'Never receive or control customer funds, credentials, or payment instructions.' },
    ],
    prohibited_shortcuts: ['nominal agent without principal control', 'undisclosed flow-of-funds control', 'assuming federal agent treatment resolves state law'],
  },
  {
    rule_key: 'us-insurance-distribution', domain: 'insurance', activity: 'insurance_distribution',
    patterns: /insurance|premium|policyholder|underwrit|coverage recommendation|producer|claims adjust/i,
    trigger_summary: 'Selling, soliciting, negotiating, recommending, or adjusting insurance may require producer licensing and appointments.',
    coverage_models: [
      { type: 'appointment', label: 'Licensed and appointed producer', conditions: ['individual/entity license', 'carrier appointment where required', 'product authority'] },
      { type: 'referral', label: 'Referral to licensed producer', conditions: ['no policy advice', 'compensation boundary', 'handoff disclosure'] },
    ],
    eligibility_requirements: [
      { key: 'producer_license', label: 'Producer license', kind: 'credential', required: true },
      { key: 'carrier_appointment', label: 'Carrier appointment where required', kind: 'relationship', required: true },
      { key: 'continuing_education', label: 'Continuing education', kind: 'training', required: true },
    ],
    alternatives: [
      { type: 'referral', label: 'Licensed-producer handoff', boundary: 'Limit member activity to a neutral introduction and factual product routing.' },
      { type: 'technology_provider', label: 'Non-advisory comparison infrastructure', boundary: 'Avoid recommendations, negotiation, binding, premium handling, and claims adjustment.' },
    ],
    prohibited_shortcuts: ['unappointed solicitation', 'advice disguised as education', 'sharing commissions with an unlicensed entity'],
  },
  {
    rule_key: 'us-mortgage-origination', domain: 'mortgage', activity: 'mortgage_origination',
    patterns: /mortgage|loan originat|residential loan|rate quote|borrower application|loan officer/i,
    trigger_summary: 'Taking applications, offering or negotiating terms, or holding out as an MLO can require individual licensing and company sponsorship.',
    coverage_models: [
      { type: 'sponsor', label: 'Company-sponsored MLO', conditions: ['company relationship', 'regulator-accepted sponsorship', 'individual state license', 'supervision'] },
      { type: 'referral', label: 'Lead referral to licensed originator', conditions: ['no application or terms activity', 'RESPA compensation review', 'disclosure'] },
    ],
    eligibility_requirements: [
      { key: 'prelicense_education', label: 'Pre-licensing education', kind: 'training', required: true },
      { key: 'exam', label: 'Required examination', kind: 'credential', required: true },
      { key: 'background', label: 'Background and financial responsibility review', kind: 'identity', required: true },
      { key: 'company_sponsorship', label: 'Company sponsorship', kind: 'relationship', required: true },
    ],
    alternatives: [
      { type: 'referral', label: 'Qualified lead handoff', boundary: 'Do not take an application, recommend a product, quote terms, or negotiate.' },
      { type: 'administrative_services', label: 'Post-selection administrative support', boundary: 'Operate under documented lender controls without loan-originator activity.' },
    ],
    prohibited_shortcuts: ['sponsorship without supervision', 'unlicensed rate negotiation', 'compensation that violates referral restrictions'],
  },
  {
    rule_key: 'privacy-data-use', domain: 'privacy', activity: 'regulated_data_processing',
    patterns: /biometric|health data|precise location|children|credit report|consumer report|personal data sale|targeted advertising/i,
    trigger_summary: 'Sensitive-data collection, inference, sharing, or advertising can create consent, assessment, registration, and contract obligations.',
    coverage_models: [
      { type: 'service_provider', label: 'Processor/service-provider boundary', conditions: ['purpose limitation', 'contract restrictions', 'no independent use', 'deletion and audit controls'] },
    ],
    eligibility_requirements: [
      { key: 'data_inventory', label: 'Data inventory and purpose map', kind: 'evidence', required: true },
      { key: 'privacy_assessment', label: 'Applicable privacy impact assessment', kind: 'document', required: true },
      { key: 'rights_workflow', label: 'Consumer-rights workflow', kind: 'operations', required: true },
    ],
    alternatives: [
      { type: 'technology_provider', label: 'Minimized processor mode', boundary: 'Process only documented instructions; disable independent profiling, reuse, and data sale.' },
      { type: 'business_model', label: 'Non-targeted business model', boundary: 'Use contextual delivery or subscription revenue instead of regulated data sharing or targeting.' },
    ],
    prohibited_shortcuts: ['consent dark patterns', 'processor label without contractual and technical limits', 'collect now and classify later'],
  },
]

const OFFICIAL_SOURCES: Record<string, Array<{ authority: string; url: string; scope: string }>> = {
  'us-securities-intermediation': [{ authority: 'SEC', url: 'https://www.sec.gov/about/divisions-offices/division-trading-markets/division-trading-markets-compliance-guides/guide-broker-dealer-registration', scope: 'broker-dealer and associated-person registration indicators' }],
  'us-money-transmission': [{ authority: 'FinCEN', url: 'https://www.fincen.gov/resources/statutes-regulations/guidance/interagency-interpretive-guidance-providing-banking', scope: 'MSB registration and agent context; state analysis remains separate' }],
  'us-insurance-distribution': [{ authority: 'NAIC', url: 'https://content.naic.org/sites/default/files/inline-files/Chapter%2011.pdf', scope: 'producer licensing and appointment model guidance' }],
  'us-mortgage-origination': [{ authority: 'NMLS', url: 'https://mortgage.nationwidelicensingsystem.org/slr/resources/Help%20Documents/Add%20Sponsorship.pdf', scope: 'individual license sponsorship workflow' }],
  'privacy-data-use': [{ authority: 'FTC', url: 'https://www.ftc.gov/business-guidance/privacy-security', scope: 'federal privacy and data-security business guidance' }],
}

const now = () => new Date().toISOString()
const bounded = (value: any, limit = 600) => String(value || '').trim().slice(0, limit)
const stable = (value: any): string => Array.isArray(value) ? `[${value.map(stable).join(',')}]` : value && typeof value === 'object' ? `{${Object.keys(value).sort().map(key => `${key}:${stable(value[key])}`).join(',')}}` : JSON.stringify(value)
const digest = (value: any) => createHash('sha256').update(stable(value)).digest('hex')

export function detectRegulatoryActivities(source: ActivitySource) {
  const text = [source.summary, ...(source.indicators || [])].map(value => bounded(value, 240)).join(' ')
  return RULES.filter(rule => rule.patterns.test(text)).map(rule => ({ rule, confidence: Number(Math.min(.94, .58 + Math.min(6, (text.match(rule.patterns) || []).length) * .06).toFixed(2)) }))
}

export function noLicenseAlternatives(ruleKey: string) {
  return RULES.find(rule => rule.rule_key === ruleKey)?.alternatives || []
}

export function calculateReadiness(requirements: RuleTemplate['eligibility_requirements'], evidence: Record<string, any> = {}) {
  const scored = requirements.map(requirement => ({
    ...requirement,
    satisfied: Boolean(evidence[requirement.key]?.verified || evidence[requirement.key] === true),
    evidence_ref: evidence[requirement.key]?.ref || null,
  }))
  const required = scored.filter(item => item.required)
  const satisfied = required.filter(item => item.satisfied).length
  const readiness_score = required.length ? Math.round(satisfied / required.length * 100) : 100
  return { readiness_score, requirements: scored, blockers: required.filter(item => !item.satisfied).map(item => ({ key: item.key, label: item.label })) }
}

export function priceSponsorRelationship(input: any) {
  const base = Number(input.base_monthly_cents || 25_000)
  const volume = Math.max(0, Number(input.expected_monthly_transactions || 0))
  const complaintRate = Math.max(0, Number(input.complaint_rate || 0))
  const monitoring = Math.max(1, Number(input.monitoring_hours || 4))
  const capital = Math.max(0, Number(input.capital_consumption_cents || 0))
  const evidenceDiscount = Math.min(.35, Math.max(0, Number(input.clean_months || 0)) * .015)
  const riskMultiplier = 1 + Math.min(2, complaintRate * 20) + (input.risk_tier === 'elevated' ? .45 : input.risk_tier === 'restricted' ? 1 : 0)
  const supervisory = Math.round(monitoring * Number(input.hourly_supervision_cents || 15_000))
  const variable = Math.round(volume * Number(input.per_transaction_cents || 25))
  const reserve = Math.round(capital * Number(input.capital_charge_rate || .015))
  const gross = Math.round((base + supervisory + variable + reserve) * riskMultiplier)
  return {
    monthly_price_cents: Math.round(gross * (1 - evidenceDiscount)),
    reserve_cents: reserve,
    evidence_discount_bps: Math.round(evidenceDiscount * 10_000),
    drivers: { base_cents: base, supervision_cents: supervisory, volume_cents: variable, capital_charge_cents: reserve, risk_multiplier: Number(riskMultiplier.toFixed(2)) },
  }
}

async function ensureCatalog() {
  const sb = serviceClient()
  const rows = RULES.map(rule => ({
    rule_key: rule.rule_key, domain: rule.domain, jurisdiction: 'US-general',
    activity_patterns: [rule.patterns.source], trigger_summary: rule.trigger_summary,
    coverage_models: rule.coverage_models, eligibility_requirements: rule.eligibility_requirements,
    prohibited_shortcuts: rule.prohibited_shortcuts, source_refs: OFFICIAL_SOURCES[rule.rule_key] || [], version: '2026-07-15.1', status: 'guidance', updated_at: now(),
  }))
  await sb.from('regulatory_rule_catalog').upsert(rows, { onConflict: 'rule_key' })
}

async function inferredSources(organizationId: string): Promise<ActivitySource[]> {
  const sb = serviceClient()
  const [{ data: bundles }, { data: opportunities }] = await Promise.all([
    sb.from('hivemind_execution_bundles').select('id,objective,step_graph,status,created_at').eq('organization_id', organizationId).order('created_at', { ascending: false }).limit(80),
    sb.from('hivemind_opportunities').select('id,title,explanation,opportunity_type,source_refs,created_at').eq('organization_id', organizationId).order('created_at', { ascending: false }).limit(80),
  ])
  const bundleSources = (bundles || []).map((item: any) => ({
    source_type: 'code', source_ref: `execution_bundle:${item.id}`,
    summary: bounded(item.objective, 400),
    indicators: (Array.isArray(item.step_graph) ? item.step_graph : []).slice(0, 12).flatMap((step: any) => [step.type, step.domain, step.action]).filter(Boolean),
    materiality: 'unknown',
  }))
  const opportunitySources = (opportunities || []).map((item: any) => ({
    source_type: 'product', source_ref: `opportunity:${item.id}`,
    summary: `${bounded(item.opportunity_type, 80)} ${bounded(item.title, 180)} ${bounded(item.explanation, 260)}`,
    indicators: Object.keys(item.source_refs || {}).slice(0, 12), materiality: 'unknown',
  }))
  return [...bundleSources, ...opportunitySources]
}

export async function ingestRegulatorySource(organizationId: string, source: ActivitySource) {
  const sb = serviceClient()
  const detected = detectRegulatoryActivities(source)
  if (!detected.length) return { signal: null, assessments: [] }
  const boundedIndicators = {
    terms: (source.indicators || []).slice(0, 20).map(value => bounded(value, 80)),
    summary: bounded(source.summary, 600), raw_payload_stored: false,
  }
  const sourceDigest = digest({ organizationId, source_ref: source.source_ref, boundedIndicators })
  const { data: signal, error } = await sb.from('regulatory_activity_signals').upsert({
    organization_id: organizationId, project_ref: bounded(source.project_ref, 160) || null,
    source_type: ['code','product','marketing','contract','operations','user','integration'].includes(String(source.source_type)) ? source.source_type : 'user',
    source_ref: bounded(source.source_ref || `manual:${sourceDigest.slice(0, 12)}`, 240), source_digest: sourceDigest,
    bounded_indicators: boundedIndicators, detected_activities: detected.map(item => item.rule.activity),
    jurisdictions: (source.jurisdictions || ['US-general']).slice(0, 20),
    materiality: ['non_material','material'].includes(String(source.materiality)) ? source.materiality : 'unknown',
    confidence: Math.max(...detected.map(item => item.confidence)), last_seen_at: now(), status: 'active',
  }, { onConflict: 'organization_id,source_digest' }).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  const { data: catalog } = await sb.from('regulatory_rule_catalog').select('id,rule_key').in('rule_key', detected.map(item => item.rule.rule_key))
  const ids = new Map((catalog || []).map((item: any) => [item.rule_key, item.id]))
  const assessments = []
  for (const item of detected) {
    const assessment = {
      organization_id: organizationId, signal_id: signal.id, rule_id: ids.get(item.rule.rule_key) || null,
      activity: item.rule.activity,
      regulated_core: { trigger: item.rule.trigger_summary, must_be_performed_by_covered_party: true },
      unregulated_components: item.rule.alternatives,
      verdict: 'counsel_required', reasons: [{ code: 'activity_signal_detected', explanation: item.rule.trigger_summary }, { code: 'jurisdiction_confirmation_required' }],
      required_actions: [{ type: 'confirm_facts' }, { type: 'select_coverage_or_alternative' }, { type: 'apparently_review' }],
      safe_alternatives: item.rule.alternatives, confidence: item.confidence,
      assessment_digest: digest({ signal: signal.id, rule: item.rule.rule_key, sourceDigest }), status: 'current',
    }
    const { data } = await sb.from('regulatory_activity_assessments').upsert(assessment, { onConflict: 'assessment_digest' }).select().single()
    if (data) assessments.push(data)
  }
  return { signal, assessments }
}

async function updateReadiness(organizationId: string) {
  const sb = serviceClient()
  const { data: catalog } = await sb.from('regulatory_rule_catalog').select('*').neq('status', 'retired')
  const { data: existing } = await sb.from('regulatory_readiness_paths').select('*').eq('organization_id', organizationId)
  const existingByRule = new Map((existing || []).map((path: any) => [path.rule_id, path]))
  let updated = 0
  for (const rule of catalog || []) {
    const current = existingByRule.get(rule.id)
    const readiness = calculateReadiness(rule.eligibility_requirements || [], current?.evidence || {})
    await sb.from('regulatory_readiness_paths').upsert({
      organization_id: organizationId, rule_id: rule.id, target_capability: rule.domain,
      jurisdiction: rule.jurisdiction, requirements: readiness.requirements, evidence: current?.evidence || {}, blockers: readiness.blockers,
      next_actions: readiness.blockers.slice(0, 3).map((blocker: any) => ({ type: 'collect_or_prepare', key: blocker.key, label: blocker.label, provider: 'apparently' })),
      readiness_score: readiness.readiness_score, simulation_status: readiness.readiness_score === 100 ? 'application_ready' : 'shadow',
      assistance_enabled: Boolean(current?.assistance_enabled), updated_at: now(),
    }, { onConflict: 'organization_id,target_capability,jurisdiction' })
    updated += 1
  }
  return updated
}

async function monitorRelationships(organizationId: string) {
  const sb = serviceClient()
  const { data: relationships } = await sb.from('regulatory_relationships').select('*').eq('organization_id', organizationId).eq('status', 'active')
  const { data: signals } = await sb.from('regulatory_activity_signals').select('*').eq('organization_id', organizationId).eq('status', 'active').gte('last_seen_at', new Date(Date.now() - 7 * 86400_000).toISOString())
  let alerts = 0
  for (const relationship of relationships || []) {
    const covered = new Set(relationship.covered_activities || [])
    for (const signal of signals || []) {
      const outside = (signal.detected_activities || []).filter((activity: string) => !covered.has(activity))
      if (!outside.length) continue
      const facts = { source_ref: signal.source_ref, outside_covered_activities: outside, confidence: signal.confidence, raw_payload_stored: false }
      const eventDigest = digest({ relationship: relationship.id, signal: signal.id, outside })
      await sb.from('regulatory_relationship_events').upsert({
        relationship_id: relationship.id, organization_id: organizationId, event_type: signal.source_type === 'marketing' ? 'marketing_change' : 'code_change',
        severity: Number(signal.confidence) >= .8 ? 'high' : 'warning', bounded_facts: facts,
        obligation_refs: [{ type: 'authority_limits', relationship_id: relationship.id }],
        action_taken: 'New affected activity held outside sponsor coverage pending review.', event_digest: eventDigest, status: 'contained',
      }, { onConflict: 'event_digest' })
      alerts += 1
    }
  }
  return alerts
}

export async function runRegulatoryAutopilot(organizationId: string, trigger: 'session' | 'schedule' | 'event' | 'operator' = 'session') {
  const sb = serviceClient()
  if (trigger === 'session') {
    const { data: recent } = await sb.from('regulatory_autopilot_runs').select('*').eq('organization_id', organizationId).gte('created_at', new Date(Date.now() - 15 * 60_000).toISOString()).order('created_at', { ascending: false }).limit(1).maybeSingle()
    if (recent) return recent
  }
  await ensureCatalog()
  const sources = await inferredSources(organizationId)
  let assessmentsCreated = 0
  for (const source of sources) assessmentsCreated += (await ingestRegulatorySource(organizationId, source)).assessments.length
  const pathsUpdated = await updateReadiness(organizationId)
  const relationshipAlerts = await monitorRelationships(organizationId)
  const temporal = await runTemporalRegulatoryAutopilot(organizationId)
  const frontier = await runRegulatoryFrontierAutopilot(organizationId)
  const outcomes = [
    assessmentsCreated ? { kind: 'regulatory', title: `${assessmentsCreated} activity boundar${assessmentsCreated === 1 ? 'y' : 'ies'} checked` } : null,
    pathsUpdated ? { kind: 'readiness', title: `${pathsUpdated} license path${pathsUpdated === 1 ? '' : 's'} refreshed` } : null,
    temporal.evidence_rooms_updated ? { kind: 'evidence', title: `${temporal.evidence_rooms_updated} evidence room${temporal.evidence_rooms_updated === 1 ? '' : 's'} refreshed` } : null,
    temporal.obligations_at_risk ? { kind: 'agreement', title: `${temporal.obligations_at_risk} agreement obligation${temporal.obligations_at_risk === 1 ? '' : 's'} need attention` } : null,
    frontier.systemic_risk_score >= 50 ? { kind: 'resilience', title: 'A concentrated relationship dependency needs attention' } : null,
  ].filter(Boolean)
  const exceptions = [
    ...(relationshipAlerts ? [{ kind: 'relationship', severity: 'high', title: 'Activity outside current relationship coverage', outcome: `${relationshipAlerts} change${relationshipAlerts === 1 ? '' : 's'} contained pending review.` }] : []),
    ...(temporal.obligations_at_risk ? [{ kind: 'agreement', severity: 'high', title: 'Agreement performance is drifting', outcome: `${temporal.obligations_at_risk} obligation${temporal.obligations_at_risk === 1 ? '' : 's'} are due soon or past due.` }] : []),
    ...(frontier.systemic_risk_score >= 50 ? [{ kind: 'resilience', severity: 'high', title: 'Contract network concentration detected', outcome: `Cascade exposure is modeled at ${frontier.systemic_risk_score}/100; lawful operation continues while mitigations are prepared.` }] : []),
  ]
  const run = {
    organization_id: organizationId, trigger, signals_processed: sources.length, assessments_created: assessmentsCreated,
    paths_updated: pathsUpdated, relationship_alerts: relationshipAlerts, outcomes, exceptions,
    run_digest: digest({ organizationId, trigger, sources: sources.map(source => source.source_ref), nonce: randomBytes(5).toString('hex') }),
    status: exceptions.length ? 'attention_required' : 'completed',
  }
  const { data, error } = await sb.from('regulatory_autopilot_runs').insert(run).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  return data
}

export async function regulatoryCockpit(user: any) {
  const context = await organizationContext(user)
  const organizationId = context.membership.organization_id
  const sb = serviceClient()
  let autopilot = null
  try { autopilot = await runRegulatoryAutopilot(organizationId, 'session') } catch {}
  const frontier = await frontierCockpit(organizationId)
  let { data: profile } = await sb.from('regulatory_capability_profiles').select('*').eq('organization_id', organizationId).maybeSingle()
  if (!profile) {
    const created = await sb.from('regulatory_capability_profiles').upsert({ organization_id: organizationId, updated_by: user.id }).select().single()
    profile = created.data
  }
  const [assessments, paths, relationships, events, assistance, scenarios, agreementControls, obligations, evidenceRooms, featureControls, strategyOptions, settlementElections] = await Promise.all([
    sb.from('regulatory_activity_assessments').select('*, signal:regulatory_activity_signals(source_type,source_ref,project_ref,materiality,last_seen_at)').eq('organization_id', organizationId).eq('status', 'current').order('created_at', { ascending: false }).limit(40),
    sb.from('regulatory_readiness_paths').select('*').eq('organization_id', organizationId).order('readiness_score', { ascending: false }).limit(30),
    sb.from('regulatory_relationships').select('*').eq('organization_id', organizationId).order('updated_at', { ascending: false }).limit(30),
    sb.from('regulatory_relationship_events').select('*').eq('organization_id', organizationId).in('status', ['open','contained']).order('created_at', { ascending: false }).limit(40),
    sb.from('regulatory_assistance_requests').select('*').eq('organization_id', organizationId).order('created_at', { ascending: false }).limit(30),
    sb.from('regulatory_temporal_scenarios').select('*').eq('organization_id', organizationId).eq('status', 'current').order('created_at', { ascending: false }).limit(12),
    sb.from('regulatory_agreement_controls').select('*').eq('organization_id', organizationId).order('updated_at', { ascending: false }).limit(30),
    sb.from('regulatory_obligation_ledger').select('*').eq('organization_id', organizationId).order('due_at', { ascending: true }).limit(80),
    sb.from('regulatory_evidence_rooms').select('*').eq('organization_id', organizationId).order('updated_at', { ascending: false }).limit(30),
    sb.from('regulatory_feature_controls').select('*').eq('organization_id', organizationId).order('updated_at', { ascending: false }).limit(40),
    sb.from('regulatory_strategy_options').select('*').eq('organization_id', organizationId).eq('status', 'available').order('created_at', { ascending: false }).limit(60),
    sb.from('regulatory_cade_settlement_elections').select('*').eq('organization_id', organizationId).order('created_at', { ascending: false }).limit(30),
  ])
  return {
    role: context.membership.role, profile, autopilot,
    attention: events.data || [], assessments: assessments.data || [], paths: paths.data || [], relationships: relationships.data || [], assistance: assistance.data || [],
    foresight: { scenarios: scenarios.data || [] },
    agreements: { controls: agreementControls.data || [], obligations: obligations.data || [], settlement_elections: settlementElections.data || [] },
    evidence_rooms: evidenceRooms.data || [], feature_controls: featureControls.data || [], strategy_options: strategyOptions.data || [],
    frontier,
    summary: {
      active_relationships: (relationships.data || []).filter((item: any) => item.status === 'active').length,
      application_ready: (paths.data || []).filter((item: any) => item.simulation_status === 'application_ready').length,
      boundaries_to_review: (assessments.data || []).filter((item: any) => ['not_covered','counsel_required'].includes(item.verdict)).length,
      contained_changes: (events.data || []).filter((item: any) => item.status === 'contained').length,
      obligations_at_risk: (obligations.data || []).filter((item: any) => ['at_risk','breached','disputed'].includes(item.status)).length,
      evidence_rooms_ready: (evidenceRooms.data || []).filter((item: any) => ['review_ready','application_ready'].includes(item.status)).length,
      authority_changes_to_review: frontier.summary.authority_changes_to_review,
      releases_held_for_authority: frontier.summary.releases_held,
    },
    disclaimer: 'Decision support only. Coverage depends on verified facts, jurisdiction, executed agreements, required registrations, and regulator acceptance where applicable.',
  }
}

export async function updateRegulatoryProfile(user: any, values: any) {
  const context = await organizationContext(user)
  const autonomy = {
    continuous_detection: values.autonomy?.continuous_detection !== false,
    auto_non_material: values.autonomy?.auto_non_material !== false,
    material_changes: Boolean(values.autonomy?.material_changes),
    external_sharing: Boolean(values.autonomy?.external_sharing),
  }
  const { data, error } = await serviceClient().from('regulatory_capability_profiles').upsert({
    organization_id: context.membership.organization_id,
    jurisdictions: (values.jurisdictions || []).slice(0, 30).map((value: any) => bounded(value, 80)),
    business_models: (values.business_models || []).slice(0, 30).map((value: any) => bounded(value, 80)),
    autonomy, risk_tolerance: ['conservative','growth'].includes(values.risk_tolerance) ? values.risk_tolerance : 'standard',
    updated_by: user.id, updated_at: now(),
  }, { onConflict: 'organization_id' }).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  return data
}

export async function createRegulatoryRelationship(user: any, values: any) {
  const context = await organizationContext(user)
  const economics = priceSponsorRelationship(values.economics || {})
  const row = {
    organization_id: context.membership.organization_id,
    counterparty_organization_id: values.counterparty_organization_id || null,
    counterparty_name: bounded(values.counterparty_name, 160), relationship_type: bounded(values.relationship_type || 'other', 40),
    covered_activities: (values.covered_activities || []).slice(0, 30).map((value: any) => bounded(value, 80)),
    jurisdictions: (values.jurisdictions || []).slice(0, 30).map((value: any) => bounded(value, 80)),
    authority_limits: values.authority_limits || { material_changes_require_approval: true, volume_cap: null },
    economics, agreement_refs: [],
    supervision_plan: values.supervision_plan || { continuous_bounded_monitoring: true, complaints_shared: true, stop_authority: true, raw_code_shared: false },
    organization_approved_at: values.organization_approve ? now() : null,
    status: values.organization_approve ? 'pending_counterparty' : 'draft', updated_at: now(),
  }
  if (!row.counterparty_name) throw createError({ statusCode: 400, message: 'counterparty_name_required' })
  const { data, error } = await serviceClient().from('regulatory_relationships').insert(row).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  return data
}

export async function requestRegulatoryAssistance(user: any, values: any) {
  const context = await organizationContext(user)
  if (values.confirm_external_share !== true) throw createError({ statusCode: 400, message: 'explicit_external_share_approval_required' })
  const organizationId = context.membership.organization_id
  const brief = {
    objective: bounded(values.objective, 280), assistance_type: bounded(values.assistance_type || 'eligibility', 40),
    assessment_id: values.assessment_id || null, readiness_path_id: values.readiness_path_id || null, relationship_id: values.relationship_id || null,
    constraints: { no_legal_conclusion_without_review: true, no_filing_without_fresh_approval: true, no_raw_code_or_documents: true },
  }
  const provider = ['smarter','combined'].includes(values.provider) ? values.provider : 'apparently'
  const { data: request, error } = await serviceClient().from('regulatory_assistance_requests').insert({
    organization_id: organizationId, assessment_id: brief.assessment_id, readiness_path_id: brief.readiness_path_id,
    relationship_id: brief.relationship_id, provider, assistance_type: brief.assistance_type, bounded_brief: brief,
    external_share_approved_at: now(), status: 'approved', created_by: user.id,
  }).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  const providers = provider === 'combined' ? ['apparently','smarter'] : [provider]
  const results: any[] = []
  for (const target of providers) {
    const base = appBaseUrl(target)
    if (!base) { results.push({ provider: target, status: 'setup_required' }); continue }
    try {
      const response = await fetch(`${base}/api/fleet/intake`, {
        method: 'POST', headers: { 'content-type': 'application/json', 'x-fleet-secret': process.env.FLEET_SHARED_SECRET || '' },
        body: JSON.stringify({ source: 'madeus-regulatory-network', organization_id: organizationId, request_id: request.id, brief }),
      })
      results.push({ provider: target, status: response.ok ? 'queued' : 'failed', ref: response.headers.get('x-request-id') })
    } catch { results.push({ provider: target, status: 'failed' }) }
  }
  const status = results.every(item => item.status === 'setup_required') ? 'setup_required' : results.some(item => item.status === 'queued') ? 'queued' : 'failed'
  await serviceClient().from('regulatory_assistance_requests').update({ status, execution_ref: results.map(item => `${item.provider}:${item.ref || item.status}`).join(',').slice(0, 240), updated_at: now() }).eq('id', request.id)
  return { request: { ...request, status }, providers: results, payload_scope: 'bounded_brief_only' }
}

export async function ingestUserRegulatorySource(user: any, values: any) {
  const context = await organizationContext(user)
  return ingestRegulatorySource(context.membership.organization_id, { ...values, source_type: values.source_type || 'user', source_ref: values.source_ref || `user:${randomBytes(6).toString('hex')}` })
}
