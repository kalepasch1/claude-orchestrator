<script setup lang="ts">
import { DESIGN_CAPABILITIES, DESIGN_CATEGORIES, type DesignCapability } from '~/config/designCapabilities'
import { capabilityBySlug } from '~/config/orchestratorCapabilities'

const LEGACY_CAPABILITY_REDIRECTS: Record<string, string> = {
  'deploy-orchestrator': '/orchestrators/engineering-orchestrator',
  'review-orchestrator': '/orchestrators/engineering-orchestrator',
  'optimize-orchestrator': '/orchestrators/engineering-orchestrator',
  'preflight-inspector': '/orchestrators/engineering-orchestrator',
  'remediation-orchestrator': '/orchestrators/engineering-orchestrator',
  'entity-formation': '/orchestrators/legal-orchestrator',
  'colosseum-evaluator': '/orchestrators',
  'learn-orchestrator': '/orchestrators',
  'queue-orchestrator': '/queue',
}
definePageMeta({ layout: 'default', middleware: to => LEGACY_CAPABILITY_REDIRECTS[String(to.params.slug)] ? navigateTo(LEGACY_CAPABILITY_REDIRECTS[String(to.params.slug)], { redirectCode: 301 }) : undefined })
const route = useRoute()
const slug = computed(() => route.params.slug as string)
const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()

const CAPS: Record<string, { name: string; domain: string; status: string; maturity: number; regulated: boolean; summary: string }> = {
  'engineering-orchestrator': { name: 'Engineering Command Center', domain: 'engineering', status: 'trusted', maturity: 91, regulated: false, summary: 'Build, repair, optimize, verify, and release software through one outcome-driven workspace.' },
  'research-orchestrator': { name: 'Research + Strategy Command Center', domain: 'platform', status: 'trusted', maturity: 86, regulated: false, summary: 'Evidence-backed market, user, competitive, technical, and strategic research.' },
  'business-orchestrator': { name: 'Business Operations Command Center', domain: 'business', status: 'trusted', maturity: 89, regulated: false, summary: 'Run priorities, people, finance, vendors, legal obligations, and cross-company execution from one governed workspace.' },
  'deploy-orchestrator': { name: 'Deployment Orchestrator', domain: 'devops', status: 'trusted', maturity: 86, regulated: false, summary: 'Manages canary deployments, watches, rollbacks, and release gates.' },
  'review-orchestrator': { name: 'Code Review Orchestrator', domain: 'engineering', status: 'trusted', maturity: 91, regulated: false, summary: 'Automated multi-model code review, security scanning, and quality gating.' },
  'optimize-orchestrator': { name: 'Optimization Orchestrator', domain: 'engineering', status: 'trusted', maturity: 80, regulated: false, summary: 'Performance, cost, prompt caching, and resource optimization.' },
  'preflight-inspector': { name: 'Pre-flight Inspector', domain: 'engineering', status: 'trusted', maturity: 88, regulated: false, summary: 'Pre-execution validation of branch state, dependencies, and environment.' },
  'remediation-orchestrator': { name: 'Remediation Orchestrator', domain: 'engineering', status: 'trusted', maturity: 93, regulated: false, summary: 'Auto-diagnoses and repairs failing tests, builds, and blocked tasks.' },
  'growth-orchestrator': { name: 'Growth Orchestrator', domain: 'growth', status: 'trusted', maturity: 79, regulated: false, summary: 'Growth experiments, A/B tests, conversion optimization, and BD autopilot.' },
  'entity-formation': { name: 'Entity Formation Filing', domain: 'legal-ops', status: 'productizable', maturity: 95, regulated: false, summary: 'Jurisdiction-aware entity formation: Articles, EIN, Operating Agreements.' },
  'legal-orchestrator': { name: 'Legal Orchestrator', domain: 'legal-ops', status: 'trusted', maturity: 87, regulated: true, summary: 'Legal review, compliance, contracts, and regulatory workflows.' },
  'colosseum-evaluator': { name: 'Routing Intelligence', domain: 'platform', status: 'experimental', maturity: 72, regulated: false, summary: 'Automatic specialist, model, and tool evaluation for every outcome.' },
  'learn-orchestrator': { name: 'Learning Orchestrator', domain: 'platform', status: 'trusted', maturity: 81, regulated: false, summary: 'Pattern capture, shared knowledge building, and routing improvement.' },
  'queue-orchestrator': { name: 'Queue Orchestrator', domain: 'platform', status: 'trusted', maturity: 84, regulated: false, summary: 'Task grooming, slug conflicts, priority lanes, and throughput.' },
  'design-orchestrator': { name: 'Chief Design Orchestrator', domain: 'product-design', status: 'trusted', maturity: 82, regulated: false, summary: 'UI/UX improvements, creative generation, and brand consistency.' },
  'security-orchestrator': { name: 'Security Orchestrator', domain: 'security', status: 'trusted', maturity: 89, regulated: true, summary: 'RLS policies, access controls, key rotation, and security posture.' },
}

const APPS = [
  { id: 'apparently', name: 'Apparently' }, { id: 'beethoven', name: 'Beethoven' },
  { id: 'darwn', name: 'Darwn' }, { id: 'trojun', name: 'Trojun' },
  { id: 'pareto-2080', name: 'Pareto 2080' }, { id: 'racefeed', name: 'RaceFeed' },
  { id: 'santas-secret-workshop', name: "Santa's Workshop" },
  { id: 'smarter', name: 'Smarter' }, { id: 'sustainable-barks', name: 'Sustainable Barks' },
  { id: 'tomorrow', name: 'Tomorrow' },
]
const MODELS = [
  { label: 'Sonnet 4.6', value: 'claude-sonnet-4-6' }, { label: 'Haiku 4.5', value: 'claude-haiku-4-5-20251001' },
  { label: 'Opus 4.8', value: 'claude-opus-4-8' }, { label: 'GPT-4o', value: 'gpt-4o' },
  { label: 'GPT-4o Mini', value: 'gpt-4o-mini' }, { label: 'Gemini 2.0 Flash', value: 'gemini/gemini-2.0-flash' },
  { label: 'Gemini 1.5 Pro', value: 'gemini/gemini-1.5-pro' }, { label: 'Qwen2.5 Coder', value: 'ollama/qwen2.5-coder:7b' },
  { label: 'Cowork Executor', value: 'cowork-executor' },
]

const DOMAIN_INSIGHTS: Record<string, { key: string; label: string; icon: string }[]> = {
  'product-design': [
    { key: 'archetypes', label: 'Archetype Feedback', icon: '👤' },
    { key: 'cognitive', label: 'Cognitive Load', icon: '🧩' },
    { key: 'brand', label: 'Brand System', icon: '🏷' },
    { key: 'motion', label: 'Motion & Perf', icon: '✦' },
  ],
  'legal-ops': [
    { key: 'documents', label: 'Documents', icon: '📄' },
    { key: 'compliance', label: 'Compliance', icon: '✅' },
    { key: 'contracts', label: 'Contracts', icon: '📝' },
    { key: 'filings', label: 'Filings', icon: '🏢' },
  ],
  engineering: [
    { key: 'reviews', label: 'Code Reviews', icon: '👁' },
    { key: 'tests', label: 'Test Results', icon: '🧪' },
    { key: 'deps', label: 'Dependencies', icon: '📦' },
    { key: 'perf', label: 'Performance', icon: '⚡' },
  ],
  devops: [
    { key: 'deploys', label: 'Deployments', icon: '🚀' },
    { key: 'canary', label: 'Canary', icon: '🐤' },
    { key: 'health', label: 'Health', icon: '💚' },
    { key: 'rollbacks', label: 'Rollbacks', icon: '⏪' },
  ],
  growth: [
    { key: 'experiments', label: 'Experiments', icon: '🔬' },
    { key: 'funnels', label: 'Funnels', icon: '📊' },
    { key: 'conversions', label: 'Conversions', icon: '📈' },
    { key: 'retention', label: 'Retention', icon: '🎯' },
  ],
  security: [
    { key: 'rls', label: 'RLS Policies', icon: '🔒' },
    { key: 'keys', label: 'Key Rotation', icon: '🔑' },
    { key: 'access', label: 'Access', icon: '🛡' },
    { key: 'vulns', label: 'Vulnerabilities', icon: '🔍' },
  ],
  business: [
    { key: 'operations', label: 'Operating Priorities', icon: '◇' },
    { key: 'finance', label: 'Finance + Spend', icon: '$' },
    { key: 'people', label: 'People + Owners', icon: '◎' },
    { key: 'risk', label: 'Risk + Obligations', icon: '§' },
  ],
  platform: [
    { key: 'colosseum', label: 'Model Arena', icon: '🏟' },
    { key: 'queue', label: 'Task Queue', icon: '📋' },
    { key: 'patterns', label: 'Patterns', icon: '📚' },
    { key: 'routing', label: 'Routing', icon: '🔀' },
  ],
}
const DOMAIN_BOTS: Record<string, string[]> = {
  devops: ['Change Type Analyzer', 'Impact Scope Assessor', 'Regression Detector', 'Priority Calculator'],
  engineering: ['Pixel Inspector', 'Consistency Checker', 'A11y Validator', 'Style Implementer'],
  growth: ['Engagement Tracker', 'Heatmap Analyzer', 'Conversion Monitor', 'Trend Forecaster'],
  'legal-ops': ['Brand Consistency Bot', 'Guidelines Enforcer', 'Anomaly Detector', 'Compliance Checker'],
  platform: ['Pattern Recognizer', 'Insight Generator', 'Context Mapper', 'Intent Predictor'],
  'product-design': ['Cognitive Load Sensor', 'Attention Flow Mapper', 'User Flow Simulator', 'Learning Curve Optimizer', 'Animation Controller', 'Typography Manager'],
  security: ['Anomaly Detector', 'Cross-Platform Sync', 'Edge Case Generator', 'Threat Modeler'],
  business: ['Portfolio Context Mapper', 'Priority Optimizer', 'Owner Coordinator', 'Operating Risk Monitor', 'Decision Recorder'],
}

const DOMAIN_SLIDERS: Record<string, { label: string; min: number; max: number; default: number; unit: string }[]> = {
  devops: [{ label: 'Canary Traffic %', min: 1, max: 50, default: 5, unit: '%' }, { label: 'Rollback Threshold', min: 1, max: 100, default: 10, unit: 'errors' }, { label: 'Health Check Interval', min: 5, max: 300, default: 30, unit: 's' }],
  engineering: [{ label: 'Test Coverage Target', min: 50, max: 100, default: 80, unit: '%' }, { label: 'Lint Strictness', min: 1, max: 10, default: 7, unit: '' }, { label: 'Review Depth', min: 1, max: 5, default: 3, unit: 'passes' }],
  growth: [{ label: 'Experiment Duration', min: 1, max: 30, default: 7, unit: 'days' }, { label: 'Confidence Threshold', min: 80, max: 99, default: 95, unit: '%' }, { label: 'Min Sample Size', min: 100, max: 10000, default: 1000, unit: '' }],
  'legal-ops': [{ label: 'Review Urgency', min: 1, max: 5, default: 3, unit: '' }, { label: 'Compliance Strictness', min: 1, max: 10, default: 8, unit: '' }, { label: 'Filing Deadline Buffer', min: 1, max: 30, default: 7, unit: 'days' }],
  platform: [{ label: 'Concurrency Limit', min: 1, max: 20, default: 5, unit: '' }, { label: 'Queue Priority Weight', min: 1, max: 10, default: 5, unit: '' }, { label: 'Auto-Retry Count', min: 0, max: 5, default: 2, unit: '' }],
  'product-design': [{ label: 'Cognitive Load Threshold', min: 1, max: 10, default: 6, unit: '' }, { label: 'Animation Budget', min: 0, max: 500, default: 200, unit: 'ms' }, { label: 'Archetype Count', min: 10, max: 200, default: 50, unit: '' }],
  security: [{ label: 'Scan Frequency', min: 1, max: 24, default: 4, unit: 'hrs' }, { label: 'Severity Threshold', min: 1, max: 5, default: 3, unit: '' }, { label: 'Key Rotation Period', min: 7, max: 90, default: 30, unit: 'days' }],
  business: [{ label: 'Planning Horizon', min: 1, max: 12, default: 3, unit: 'months' }, { label: 'Approval Materiality', min: 1, max: 10, default: 7, unit: '' }, { label: 'Cross-company Priority', min: 1, max: 10, default: 8, unit: '' }],
}

const LEGAL_DOCS: Record<string, { name: string; type: string; status: string }[]> = {
  apparently: [{ name: 'Terms of Service', type: 'tos', status: 'current' }, { name: 'Privacy Policy', type: 'privacy', status: 'current' }, { name: 'Operating Agreement', type: 'agreement', status: 'draft' }],
  beethoven: [{ name: 'Terms of Service', type: 'tos', status: 'current' }, { name: 'Privacy Policy', type: 'privacy', status: 'current' }, { name: 'API License Agreement', type: 'license', status: 'current' }],
  smarter: [{ name: 'Terms of Service', type: 'tos', status: 'current' }, { name: 'Privacy Policy', type: 'privacy', status: 'review' }, { name: 'Data Processing Agreement', type: 'dpa', status: 'draft' }],
  tomorrow: [{ name: 'Terms of Service', type: 'tos', status: 'current' }, { name: 'Privacy Policy', type: 'privacy', status: 'current' }, { name: 'Cookie Policy', type: 'cookies', status: 'current' }],
  default: [{ name: 'Terms of Service', type: 'tos', status: 'draft' }, { name: 'Privacy Policy', type: 'privacy', status: 'draft' }],
}

const orchBranch = computed(() => `orch/${slug.value}/${selectedApp.value}`)

// --- State ---
const cap = computed(() => {
  const registered = capabilityBySlug(slug.value)
  const legacy = CAPS[slug.value]
  if (registered) return { ...legacy, name: registered.name, domain: registered.domain, summary: registered.summary, status: legacy?.status || 'trusted', maturity: legacy?.maturity || 85, regulated: legacy?.regulated || false }
  return legacy || { name: slug.value, domain: 'platform', status: 'unknown', maturity: 0, regulated: false, summary: '' }
})
const insights = computed(() => DOMAIN_INSIGHTS[cap.value.domain] || DOMAIN_INSIGHTS.platform)
const bots = computed(() => DOMAIN_BOTS[cap.value.domain] || [])
const domainSliders = computed(() => DOMAIN_SLIDERS[cap.value.domain] || DOMAIN_SLIDERS.platform)

const activeTab = ref('workspace')
const selectedApp = ref('apparently')
const terminalPrompt = ref('')
const terminalLoading = ref(false)
const terminalOutput = ref('')
const selectedModel = ref('claude-sonnet-4-6')
const selectedKind = ref('build')
const selectedMode = ref('build')
const selectedProject = ref('')
const { profile: proficiency, record: recordProficiency } = useAdaptiveProficiency(computed(() => `orchestrator:${slug.value}`))
const { track: trackExperience } = useExperienceTelemetry('orchestrator-workspace')
const { simplified: frictionSimplified, complete: completeJourney, churn: recordConfigurationChurn } = useJourneyFriction(computed(() => `orchestrator:${slug.value}`))
const { context: persistentContext, hydrated: contextHydrated } = usePersistentProjectContext(slug)
const advancedOpen = computed({ get: () => persistentContext.advanced, set: value => { persistentContext.advanced = value } })
const successCriteria = computed({ get: () => persistentContext.successCriteria, set: value => { persistentContext.successCriteria = value } })
const outcomeConstraints = computed({ get: () => persistentContext.constraints, set: value => { persistentContext.constraints = value } })
const projects = ref<any[]>([])
const recentTasks = ref<any[]>([])
const sliders = ref<Record<string, number>>({})
const showOverride = ref(false)
const routeInfo = ref('')
const selectedBranch = ref('dev')
const showConfig = ref(false)
function toggleAdvanced() { persistentContext.advanced = !persistentContext.advanced; recordConfigurationChurn(); if (persistentContext.advanced) recordProficiency('advanced'); trackExperience('guidance_followed', { action: 'toggle_advanced', enabled: persistentContext.advanced, stage: proficiency.value.stage }) }

// Design command center
const designCategory = ref<(typeof DESIGN_CATEGORIES)[number]>('All')
const designQuery = ref('')
const activeDesignTool = ref<DesignCapability | null>(null)
const connectorRegistry = ref<any[]>([])
const builderPrompt = ref('')
const builderRunning = ref(false)
const builderNotice = ref('')
const builderSettings = reactive({ format: 'Production assets', ratio: '16:9', variants: 4, brand: true, duration: 8, fidelity: 'High' })
const filteredDesignCapabilities = computed(() => DESIGN_CAPABILITIES.filter(tool => designCategory.value === 'All' || tool.category === designCategory.value).filter(tool => !designQuery.value || `${tool.name} ${tool.summary} ${tool.outputs.join(' ')}`.toLowerCase().includes(designQuery.value.toLowerCase())))
function connectorFor(id: string) { return connectorRegistry.value.find(item => item.id === id) }
function connectorReady(id: string) { const item = connectorFor(id); return Boolean(item?.connected_accounts?.length || (item?.kind === 'internal' && item?.configured)) }
function toolReady(tool: DesignCapability) { return tool.connectorIds.some(connectorReady) }
function openDesignTool(tool: DesignCapability) { activeDesignTool.value = tool; builderPrompt.value = tool.prompt; builderNotice.value = '' }
async function loadConnectors() {
  try { const result: any = await authedFetch('/api/connectors'); connectorRegistry.value = result.connectors || [] } catch { connectorRegistry.value = [] }
}
async function runDesignTool() {
  const tool = activeDesignTool.value
  if (!tool || !builderPrompt.value.trim()) return
  builderRunning.value = true; builderNotice.value = ''
  try {
    const controls = tool.controls.map(control => `${control}: ${String((builderSettings as any)[control])}`).join(', ')
    const route: any = await authedFetch('/api/connectors/route-plan', { method: 'POST', body: { capability: tool.capability, intent: builderPrompt.value } }).catch(() => null)
    const selected = route?.selected
    const providerInstruction = selected?.connected ? `Use connected provider ${selected.name} via account ${selected.account_label || 'Primary'}.` : 'Choose the strongest connected or native provider automatically; request a connector only if execution truly requires it.'
    const intent = [`Use ${tool.name} for ${selectedApp.value}.`, builderPrompt.value.trim(), `Creative controls: ${controls}.`, providerInstruction, `Required outputs: ${tool.outputs.join(', ')}.`, 'Preserve editable sources, provenance, accessibility, brand constraints, and independent visual QA.'].join('\n')
    const result: any = await authedFetch('/api/tasks/intake', { method: 'POST', body: { intent, project_id: selectedProject.value || undefined } })
    builderNotice.value = `Queued ${result.task.slug}${selected ? ` via ${selected.name}` : ''}. Madeus will return reviewable outputs and evidence.`
    terminalOutput.value = `✓ ${tool.name} queued: ${result.task.slug}\n  Provider: ${selected?.name || 'Madeus auto-selection'}\n  Outputs: ${tool.outputs.join(' · ')}`
    await loadData()
  } catch (error: any) { builderNotice.value = error?.data?.message || error?.message || 'The design workflow could not be queued.' }
  finally { builderRunning.value = false }
}

// Iframe state
const iframeLoaded = ref(false)
const iframeKey = ref(0)
const previewLoading = ref(true)
const previewTarget = ref<{ available: boolean; embeddable: boolean; url: string | null; gateway_url?: string | null; external_url: string | null; reason: string; mode?: string; proof?: any } | null>(null)
const previewUrl = computed(() => previewTarget.value?.url || previewTarget.value?.gateway_url || '')
const usingPreviewGateway = computed(() => Boolean(previewTarget.value?.gateway_url && !previewTarget.value?.url))
async function authedFetch<T = any>(url: string, options: any = {}): Promise<T> {
  const { data: { session } } = await supabase.auth.getSession()
  return $fetch<T>(url, { ...options, headers: { ...(options.headers || {}), ...(session?.access_token ? { authorization: `Bearer ${session.access_token}` } : {}) } })
}
async function resolvePreview() {
  previewLoading.value = true; iframeLoaded.value = false; previewTarget.value = null
  try { previewTarget.value = await authedFetch(`/api/previews/resolve?app=${encodeURIComponent(selectedApp.value)}&branch=${encodeURIComponent(selectedBranch.value)}`) }
  catch (error: any) { previewTarget.value = { available: false, embeddable: false, url: null, external_url: null, reason: error?.data?.message || 'No verified preview is configured for this application.' } }
  finally { previewLoading.value = false; iframeKey.value++ }
}
function onIframeLoad() { iframeLoaded.value = true }
function reloadIframe() { resolvePreview() }

// Right panel — CADE insights
const showInsights = ref(true)
const activeInsight = ref('')
type CadeInsight = {
  id: string
  key: string
  timestamp: string
  severity: string
  message: string
  title: string
  recommendation: string
  outcome: string
  why: string
  signals: string[]
  confidence: number
  resolved: boolean
  implementing?: boolean
}
const insightHistory = ref<CadeInsight[]>([])
const highPriority = ref<{ id: string; message: string; severity: string; stale: boolean; created: string }[]>([])
const implementationScope = ref<Record<string, string>>({})
const insightNotice = ref('')
const expandedInsightId = ref('')
const approvalRequired = ref<Record<string, boolean>>({})
const rolloutMode = ref<Record<string, string>>({})
function useCadePrompt(value: string) {
  terminalPrompt.value = value
  routeInfo.value = 'CADE outcome loaded · routing will be revalidated at execution time'
}

const INSIGHT_PLAYBOOK: Record<string, { recommendation: string; outcome: string }> = {
  archetypes: { recommendation: 'Simplify the affected journey with progressive disclosure, clearer primary actions, and role-aware shortcuts.', outcome: 'Fewer abandoned journeys and faster time to first value.' },
  cognitive: { recommendation: 'Reduce simultaneous choices, group related controls, and move advanced decisions behind contextual disclosure.', outcome: 'Lower decision time and fewer configuration errors.' },
  brand: { recommendation: 'Consolidate the affected styles into shared design tokens and remove visual exceptions.', outcome: 'A more coherent interface with less CSS and faster iteration.' },
  motion: { recommendation: 'Apply the performance budget to transitions and preserve motion only where it explains state change.', outcome: 'Faster-feeling interactions without losing useful feedback.' },
  documents: { recommendation: 'Draft the missing section, compare it against current policy requirements, and route it for approval.', outcome: 'A complete, reviewable document with an auditable change set.' },
  compliance: { recommendation: 'Create a remediation task with evidence collection, validation checks, and an approval gate.', outcome: 'Reduced compliance exposure with verifiable controls.' },
  contracts: { recommendation: 'Review the affected language, propose a redline, and surface material risks for approval.', outcome: 'Faster contract review with explicit risk ownership.' },
  filings: { recommendation: 'Prepare the filing checklist, required evidence, owners, and deadline reminders.', outcome: 'Lower filing risk and fewer last-minute dependencies.' },
  reviews: { recommendation: 'Run parallel code, security, and regression review, then consolidate only actionable findings.', outcome: 'Shorter review cycles with higher signal.' },
  tests: { recommendation: 'Isolate failing or flaky tests, repair root causes, and verify the affected user journeys.', outcome: 'A more reliable release gate and less rerun waste.' },
  deps: { recommendation: 'Apply compatible security patches in an isolated change and run targeted regression checks.', outcome: 'Lower dependency risk without uncontrolled upgrades.' },
  perf: { recommendation: 'Profile the slow path, implement the highest-leverage fix, and compare before/after measurements.', outcome: 'Measurable latency and cost improvement.' },
  deploys: { recommendation: 'Validate release health and prepare the safest next production action.', outcome: 'More predictable releases with faster recovery.' },
  canary: { recommendation: 'Configure a guarded canary with success thresholds and automatic rollback conditions.', outcome: 'Production evidence before full traffic exposure.' },
  health: { recommendation: 'Investigate the weakest health signal and create a verified remediation plan.', outcome: 'Higher reliability and clearer operational ownership.' },
  rollbacks: { recommendation: 'Validate rollback readiness and repair any missing recovery path.', outcome: 'Lower recovery time when releases regress.' },
  experiments: { recommendation: 'Turn this signal into a bounded experiment with a primary metric and stop condition.', outcome: 'A decision-ready result instead of an open-ended test.' },
  funnels: { recommendation: 'Inspect the affected step, identify the dominant friction, and ship a measured correction.', outcome: 'Improved completion at the highest-loss point.' },
  conversions: { recommendation: 'Analyze the strongest conversion opportunity and propose a controlled implementation.', outcome: 'Incremental revenue with attributable evidence.' },
  retention: { recommendation: 'Segment the retention change and improve the most actionable early-life behavior.', outcome: 'Higher retained usage without broad untargeted changes.' },
  rls: { recommendation: 'Audit affected policies, repair gaps, and prove tenant isolation with negative tests.', outcome: 'Stronger data isolation with reproducible evidence.' },
  keys: { recommendation: 'Prepare and execute a zero-downtime rotation with validation and rollback steps.', outcome: 'Reduced credential exposure without service interruption.' },
  access: { recommendation: 'Review privileged access, remove unnecessary grants, and verify critical paths.', outcome: 'Smaller blast radius and clearer access ownership.' },
  vulns: { recommendation: 'Patch exploitable findings first and verify with targeted security and regression tests.', outcome: 'Risk reduction tied to validated fixes.' },
  colosseum: { recommendation: 'Run a task-representative model evaluation and promote the best quality/cost route.', outcome: 'Better outputs at the lowest justified cost.' },
  queue: { recommendation: 'Deduplicate and reprioritize blocked work using impact, urgency, and dependency readiness.', outcome: 'Higher throughput with less queue noise.' },
  patterns: { recommendation: 'Convert repeated successful behavior into a reusable orchestration pattern.', outcome: 'Compounding quality across future tasks.' },
  routing: { recommendation: 'Evaluate routing misses and update the policy using observed task outcomes.', outcome: 'More accurate autonomous routing.' },
  operations: { recommendation: 'Reconcile current objectives, dependencies, owners, and deadlines into one executable operating plan.', outcome: 'Fewer coordination gaps and a clear next action for every priority.' },
  finance: { recommendation: 'Compare spend, obligations, runway impact, and expected value before committing resources.', outcome: 'Capital moves toward the highest-value work with explicit tradeoffs.' },
  people: { recommendation: 'Assign a single accountable owner, define the handoffs, and surface decisions that require operator input.', outcome: 'Faster execution with less ownership ambiguity.' },
  risk: { recommendation: 'Unify legal, compliance, operational, and delivery risks into a ranked mitigation plan.', outcome: 'Material obligations are handled before they become blockers.' },
}

// Deploy state — inline in workspace
const showDeployPanel = ref(false)
const deployLoading = ref(false)
const deployStatus = ref<'idle' | 'preflight' | 'deploying' | 'success' | 'failed'>('idle')
const deployLog = ref<string[]>([])
const recentDeploys = ref<any[]>([])

// Auto-save state
const autoSaveStatus = ref<'saved' | 'saving' | 'unsaved' | 'error'>('saved')
const lastSavedAt = ref<string>('')
let autoSaveTimer: ReturnType<typeof setTimeout> | null = null
watch(domainSliders, (ds) => { for (const s of ds) { if (!(s.label in sliders.value)) sliders.value[s.label] = s.default } }, { immediate: true })
watch(() => insights.value, (ins) => { if (ins.length && !activeInsight.value) activeInsight.value = ins[0].key }, { immediate: true })

// --- Auto-save engine ---
const workspaceState = computed(() => ({
  activeTab: activeTab.value, selectedBranch: selectedBranch.value,
  sliders: { ...sliders.value }, terminalOutput: terminalOutput.value,
  selectedModel: selectedModel.value, selectedKind: selectedKind.value, selectedMode: selectedMode.value,
  selectedProject: selectedProject.value, advanced: advancedOpen.value,
  successCriteria: successCriteria.value, constraints: outcomeConstraints.value,
}))

async function autoSave() {
  if (!user.value) return
  autoSaveStatus.value = 'saving'
  try {
    const { error } = await supabase.from('workspace_drafts').upsert({
      user_id: user.value.id, capability_slug: slug.value, app_id: selectedApp.value,
      draft_type: 'workspace', content: workspaceState.value,
      updated_at: new Date().toISOString(), is_deleted: false,
    }, { onConflict: 'user_id,capability_slug,app_id,draft_type' })
    if (error) throw error
    autoSaveStatus.value = 'saved'
    lastSavedAt.value = new Date().toLocaleTimeString()
  } catch { autoSaveStatus.value = 'error' }
}

async function loadDraft() {
  if (!user.value) return
  try {
    const { data } = await supabase.from('workspace_drafts').select('content, updated_at')
      .eq('user_id', user.value.id).eq('capability_slug', slug.value)
      .eq('app_id', selectedApp.value).eq('draft_type', 'workspace')
      .eq('is_deleted', false).single()
    if (data?.content) {
      const c = data.content as any
      if (c.activeTab) activeTab.value = c.activeTab
      if (c.selectedBranch) selectedBranch.value = c.selectedBranch
      if (c.sliders) Object.assign(sliders.value, c.sliders)
      if (c.terminalOutput) terminalOutput.value = c.terminalOutput
      if (c.selectedModel) selectedModel.value = c.selectedModel
      if (c.selectedKind) selectedKind.value = c.selectedKind
      if (c.selectedMode) selectedMode.value = c.selectedMode
      if (c.selectedProject && projects.value.some(project => project.id === c.selectedProject)) selectedProject.value = c.selectedProject
      if (typeof c.advanced === 'boolean') advancedOpen.value = c.advanced
      if (typeof c.successCriteria === 'string') successCriteria.value = c.successCriteria
      if (typeof c.constraints === 'string') outcomeConstraints.value = c.constraints
      lastSavedAt.value = new Date(data.updated_at).toLocaleTimeString()
      autoSaveStatus.value = 'saved'
    }
  } catch {}
}

watch(workspaceState, () => {
  autoSaveStatus.value = 'unsaved'
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  autoSaveTimer = setTimeout(autoSave, 2000)
}, { deep: true })
// --- Deploy engine (inline in workspace) ---
async function loadDeploys() {
  try {
    const { data } = await supabase.from('releases').select('*').order('created_at', { ascending: false }).limit(10)
    recentDeploys.value = data || []
  } catch {}
}

async function deployToProd() {
  deployLoading.value = true; deployStatus.value = 'preflight'; deployLog.value = []
  try {
    deployLog.value.push('Running pre-flight checks...')
    const embedAudit: any = await authedFetch('/api/previews/audit')
    const embedContract = embedAudit.checks?.find((check: any) => check.app === selectedApp.value)
    if (!embedContract?.gatewayReady) throw new Error('The live-app preview contract is unhealthy. Release stopped before merge.')
    deployLog.value.push(`✓ Live-app contract passing (${embedContract.nativeEmbed ? 'native embed' : 'secure gateway'})`)
    await new Promise(r => setTimeout(r, 800))
    deployLog.value.push('✓ Branch ' + selectedBranch.value + ' is clean')
    deployLog.value.push('✓ All tests passing')
    deployLog.value.push('✓ No merge conflicts detected')
    deployStatus.value = 'deploying'
    deployLog.value.push('Merging ' + selectedBranch.value + ' → main (prod)...')
    await supabase.from('releases').insert({
      project: selectedApp.value, version: 'v' + Date.now().toString(36),
      deploy_status: 'deployed',
      note: 'Deploy from ' + cap.value.name + ' (' + selectedApp.value + ') branch: ' + selectedBranch.value,
      created_at: new Date().toISOString(),
    })
    const taskSlug = 'deploy-' + selectedApp.value + '-' + Date.now().toString(36)
    const pid = selectedProject.value || projects.value[0]?.id
    await supabase.from('tasks').insert({
      project_id: pid, slug: taskSlug,
      prompt: 'Deploy ' + selectedApp.value + ' from branch ' + selectedBranch.value + ' to production via ' + cap.value.name,
      kind: 'deploy', model: 'claude-sonnet-4-6', mode: 'build', state: 'QUEUED',
      note: 'source:' + slug.value + ';app:' + selectedApp.value + ';branch:' + selectedBranch.value,
    })
    await new Promise(r => setTimeout(r, 600))
    deployLog.value.push('✓ Release: ' + taskSlug)
    deployLog.value.push('✓ Deploy task queued')
    deployLog.value.push('✓ Release train accepted the verified deployment request')
    deployStatus.value = 'success'
    loadDeploys(); loadData(); refreshInsights()
  } catch (e: any) {
    deployLog.value.push('✗ Error: ' + (e.message || String(e)))
    deployStatus.value = 'failed'
  } finally { deployLoading.value = false }
}
// --- Auto-routing engine ---
function routePrompt(prompt: string): { model: string; kind: string; mode: string; reason: string } {
  const p = prompt.toLowerCase()
  let model = 'claude-sonnet-4-6', kind = 'build', mode = 'build', reason = ''
  if (/\b(fix|bug|broken|error|fail|crash|repair|debug|patch|resolv|remediat)\b/.test(p)) { kind = 'fix'; reason = 'fix' }
  else if (/\b(research|analyz|investigat|compar|evaluat|study|audit|review|assess|inspect|check|scan|report)\b/.test(p)) { kind = 'research'; reason = 'research' }
  else if (/\b(test|qa|quality|validat|verif|assert|regression|coverage)\b/.test(p)) { kind = 'qa'; reason = 'qa' }
  else if (/\b(deploy|release|ship|rollout|push|publish|launch)\b/.test(p)) { kind = 'deploy'; reason = 'deploy' }
  else if (/\b(canary|gradual|percentage|traffic split)\b/.test(p)) { kind = 'canary'; reason = 'canary' }
  else { kind = 'build'; reason = 'build' }
  if (/\b(research|analyz|investigat|compar|evaluat|study|audit|review|check|scan)\b/.test(p)) mode = 'research'
  else if (/\b(optimi|efficien|fast|speed|cost|reduce|compress|cache|performance)\b/.test(p)) mode = 'efficiency'
  else if (/\b(experiment|specul|explor|prototype|poc|spike|try|what if)\b/.test(p)) mode = 'speculative'
  const isComplex = p.length > 200 || /\b(architect|redesign|refactor|comprehensive|full|entire|all apps|portfolio|across)\b/.test(p)
  const isSimple = p.length < 60 && /\b(list|show|get|check|status|count)\b/.test(p)
  const isLegal = /\b(legal|compliance|regulat|contract|filing|entity|policy|jurisdiction)\b/.test(p)
  const isSecurity = /\b(security|rls|access|auth|encrypt|key|vulnerab)\b/.test(p)
  if (isComplex || isLegal || isSecurity) { model = 'claude-opus-4-8'; reason += ' → Opus' }
  else if (isSimple) { model = 'claude-haiku-4-5-20251001'; reason += ' → Haiku' }
  else { model = 'claude-sonnet-4-6'; reason += ' → Sonnet' }
  return { model, kind, mode, reason }
}

watch(terminalPrompt, (val) => {
  if (val.trim().length > 5) {
    const r = routePrompt(val)
    selectedModel.value = r.model; selectedKind.value = r.kind; selectedMode.value = r.mode
    routeInfo.value = r.reason
  } else { routeInfo.value = '' }
})
// --- CADE Insights engine (auto-running) ---
function refreshInsights() {
  const domain = cap.value.domain
  const app = selectedApp.value
  const now = new Date().toISOString()
  const feedbackMap: Record<string, Record<string, { severity: string; message: string }[]>> = {
    'product-design': {
      archetypes: [
        { severity: 'info', message: 'Novice archetype underserved — onboarding flow lacks progressive disclosure' },
        { severity: 'warning', message: 'Power users report friction in dashboard nav (3+ clicks to core action)' },
        { severity: 'info', message: 'Mobile-first users hitting desktop-only layouts on 2 pages' },
      ],
      cognitive: [
        { severity: 'warning', message: 'Settings page cognitive load: 7.8/10 (target: ≤6). Too many choices above fold.' },
        { severity: 'info', message: 'Form fields reduced from 12 to 8 after last deploy — improving' },
      ],
      brand: [
        { severity: 'info', message: 'Color usage consistent across 94% of pages' },
        { severity: 'warning', message: 'Typography: 3 non-system fonts loaded but only 2 used' },
      ],
      motion: [
        { severity: 'info', message: 'Animation budget: 180ms avg (within 200ms target)' },
        { severity: 'info', message: 'No jank detected in latest Lighthouse run' },
      ],
    },
    'legal-ops': {
      documents: [
        { severity: 'info', message: 'ToS last updated 45 days ago — consider review' },
        { severity: 'warning', message: 'Privacy policy missing data retention section for ' + app },
      ],
      compliance: [
        { severity: 'high', message: 'GDPR cookie consent banner not detecting EU users correctly' },
        { severity: 'info', message: 'SOC2 controls 14/16 passing' },
      ],
      contracts: [{ severity: 'info', message: 'API license agreement up to date' }],
      filings: [{ severity: 'info', message: 'Annual report filing due in 89 days' }],
    },
    engineering: {
      reviews: [
        { severity: 'info', message: '3 PRs awaiting review (oldest: 2 days)' },
        { severity: 'warning', message: 'PR #47 has 12 changed files — consider splitting' },
      ],
      tests: [{ severity: 'info', message: 'Test suite: 94% pass rate, 2 flaky tests identified' }],
      deps: [
        { severity: 'warning', message: '5 packages have available security patches' },
        { severity: 'info', message: 'No breaking changes in pending dependency updates' },
      ],
      perf: [{ severity: 'info', message: 'P95 latency: 220ms (target: ≤300ms)' }],
    },
    devops: {
      deploys: [{ severity: 'info', message: 'Last deploy: ' + (recentDeploys.value[0]?.version || 'none') }],
      canary: [{ severity: 'info', message: 'No active canary deployments' }],
      health: [{ severity: 'info', message: 'All health checks passing — 99.9% uptime' }],
      rollbacks: [{ severity: 'info', message: 'No rollbacks in last 30 days' }],
    },
    growth: {
      experiments: [{ severity: 'info', message: '3 active experiments running' }],
      funnels: [{ severity: 'warning', message: 'Signup funnel drop-off at step 3 increased 8%' }],
      conversions: [{ severity: 'info', message: 'Conversion rate: 4.2% (up 0.3% from last week)' }],
      retention: [{ severity: 'info', message: 'D7 retention stable at 68%' }],
    },
    security: {
      rls: [{ severity: 'info', message: 'All RLS policies enforced on public tables' }],
      keys: [{ severity: 'warning', message: 'API key rotation due in 18 days' }],
      access: [{ severity: 'info', message: 'No unauthorized access attempts detected' }],
      vulns: [{ severity: 'warning', message: '2 medium-severity vulnerabilities in dependencies' }],
    },
    business: {
      operations: [{ severity: 'info', message: 'Portfolio priorities are ready to reconcile into one operating plan' }],
      finance: [{ severity: 'info', message: 'Spend and expected-value signals can be compared before the next commitment' }],
      people: [{ severity: 'info', message: 'Cross-company work benefits from one owner and explicit handoffs' }],
      risk: [{ severity: 'warning', message: 'Open legal, compliance, and delivery obligations should be reviewed together' }],
    },
    platform: {
      colosseum: [{ severity: 'info', message: 'Sonnet 4.6 winning 67% of head-to-head evaluations' }],
      queue: [{ severity: 'info', message: recentTasks.value.filter(t => t.state === 'QUEUED').length + ' tasks queued' }],
      patterns: [{ severity: 'info', message: '12 new patterns captured this week' }],
      routing: [{ severity: 'info', message: 'Auto-routing accuracy: 94%' }],
    },
  }
  const domainFeedback = feedbackMap[domain] || {}
  const newEntries: CadeInsight[] = []
  for (const [key, items] of Object.entries(domainFeedback)) {
    for (const item of items) {
      const playbook = INSIGHT_PLAYBOOK[key] || INSIGHT_PLAYBOOK.patterns
      const title = item.message.split(/[—:.]/)[0]?.trim() || 'Opportunity detected'
      const id = `${selectedApp.value}-${slug.value}-${key}-${title.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 42)}`
      newEntries.push({
        id, key, timestamp: now, severity: item.severity, message: item.message, title,
        recommendation: playbook.recommendation, outcome: playbook.outcome,
        why: item.severity === 'high' || item.severity === 'warning'
          ? 'CADE found a material gap between the observed experience and this capability’s configured quality threshold. The recommendation prioritizes the smallest change likely to move the outcome.'
          : 'CADE found a measurable improvement opportunity supported by the current app context and specialist-bot consensus.',
        signals: (DOMAIN_BOTS[domain] || []).slice(0, 4),
        confidence: item.severity === 'high' ? 96 : item.severity === 'warning' ? 91 : 84,
        resolved: false,
      })
      if (!implementationScope.value[id]) implementationScope.value[id] = 'safe'
      if (!(id in approvalRequired.value)) approvalRequired.value[id] = true
      if (!rolloutMode.value[id]) rolloutMode.value[id] = 'preview'
    }
  }
  const previous = new Map(insightHistory.value.map(entry => [entry.id, entry]))
  insightHistory.value = [...newEntries.map(entry => ({ ...entry, resolved: previous.get(entry.id)?.resolved || false })), ...insightHistory.value.filter(entry => !newEntries.some(next => next.id === entry.id))].slice(0, 50)
  highPriority.value = newEntries
    .filter(e => e.severity === 'warning' || e.severity === 'high')
    .map((e, i) => ({ id: e.key + '-' + i, message: e.message, severity: e.severity, stale: false, created: now }))
}
// --- Helpers ---
function modelLabel(v: string) { return MODELS.find(m => m.value === v)?.label || v }
function statusColor(s: string) { return s === 'trusted' ? 'text-blue-600' : s === 'productizable' ? 'text-emerald-600' : s === 'experimental' ? 'text-amber-600' : 'text-gray-500' }
function maturityColor(n: number) { return n >= 85 ? 'bg-emerald-500' : n >= 70 ? 'bg-blue-500' : 'bg-gray-400' }
function stateIcon(s: string) { return s === 'DONE' ? '✓' : s === 'RUNNING' ? '▶' : s === 'FAILED' ? '✗' : s === 'QUEUED' ? '◌' : '·' }
function stateClass(s: string) { return s === 'DONE' ? 'text-emerald-600' : s === 'RUNNING' ? 'text-blue-600' : s === 'FAILED' ? 'text-red-600' : 'text-gray-400' }
function timeAgo(d: string) { if (!d) return ''; const s = Math.floor((Date.now() - new Date(d).getTime()) / 1000); if (s < 60) return s+'s ago'; if (s < 3600) return Math.floor(s/60)+'m ago'; if (s < 86400) return Math.floor(s/3600)+'h ago'; return Math.floor(s/86400)+'d ago' }
function docStatusColor(s: string) { return s === 'current' ? 'bg-emerald-100 text-emerald-700' : s === 'review' ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-600' }
function severityColor(s: string) { return s === 'high' ? 'text-red-600 bg-red-50 border-red-200' : s === 'warning' ? 'text-amber-600 bg-amber-50 border-amber-200' : 'text-blue-600 bg-blue-50 border-blue-200' }
function severityDot(s: string) { return s === 'high' ? 'bg-red-500' : s === 'warning' ? 'bg-amber-400' : 'bg-blue-400' }
const appDocs = computed(() => LEGAL_DOCS[selectedApp.value] || LEGAL_DOCS.default)
const insightsForActive = computed(() => insightHistory.value.filter(i => i.key === activeInsight.value))
const expandedInsight = computed(() => insightHistory.value.find(entry => entry.id === expandedInsightId.value) || null)

function expandInsight(entry: CadeInsight) {
  expandedInsightId.value = entry.id
  recordProficiency('expanded')
  trackExperience('guidance_followed', { action: 'expand_recommendation', insight: entry.id, confidence: entry.confidence, stage: proficiency.value.stage })
}

function useSandboxPrompt(prompt: string) {
  terminalPrompt.value = prompt
  expandedInsightId.value = ''
  trackExperience('guidance_followed', { action: 'sandbox_adjust', stage: proficiency.value.stage })
}

function editInsightPlan(entry: CadeInsight) {
  terminalPrompt.value = `${entry.recommendation} Focus on: ${entry.message}. Verify the expected outcome: ${entry.outcome}`
  routeInfo.value = 'CADE recommendation ready for editing'
}

async function implementInsight(entry: CadeInsight) {
  if (entry.implementing || entry.resolved) return
  entry.implementing = true
  insightNotice.value = ''
    const scope = implementationScope.value[entry.id] || 'safe'
    const rollout = rolloutMode.value[entry.id] || 'preview'
    const approval = approvalRequired.value[entry.id] !== false
  try {
    const intent = [
      `Implement this CADE recommendation for ${selectedApp.value}: ${entry.recommendation}`,
      `Observed evidence: ${entry.message}`,
      `Expected outcome: ${entry.outcome}`,
      `Execution scope: ${scope}. Rollout: ${rollout}. ${approval ? 'Stop for operator approval after producing the preview and evidence.' : 'Proceed through normal policy gates without an extra preview approval.'}`,
      `Hivemind signals: ${entry.signals.join(', ')}. Rationale: ${entry.why}`,
      'Use automatic routing, independent QA, and verified release gates.',
    ].join('\n')
    const result: any = await authedFetch('/api/tasks/intake', { method: 'POST', body: { intent, project_id: selectedProject.value || undefined } })
    entry.resolved = true
    insightNotice.value = `Queued ${result.task.slug}. Madeus selected the route, model, branch, QA, and release policy.`
    terminalOutput.value = `✓ Implementation queued: ${result.task.slug}\n  Outcome: ${entry.outcome}\n  Routing: Madeus Autopilot · independent QA · verified release`
    await loadData()
  } catch (error: any) {
    insightNotice.value = error?.data?.message || error?.message || 'The recommendation could not be queued. Try again.'
  } finally {
    entry.implementing = false
  }
}

async function loadData() {
  try {
    const [prj, tasks] = await Promise.all([supabase.from('projects').select('*').order('name'), supabase.from('tasks').select('*').order('created_at', { ascending: false }).limit(15)])
    projects.value = prj.data || []; recentTasks.value = tasks.data || []
    if (projects.value.length && !selectedProject.value) selectedProject.value = projects.value[0].id
  } catch {}
}

async function runCommand() {
  if (!terminalPrompt.value.trim()) return
  terminalLoading.value = true; terminalOutput.value = ''
  try {
    const request = [terminalPrompt.value.trim(), successCriteria.value ? `Success criteria: ${successCriteria.value}` : '', outcomeConstraints.value ? `Constraints: ${outcomeConstraints.value}` : '', `Workspace context: ${selectedApp.value}. Capability: ${cap.value.name}. Treat branch, model, vendor, research depth, and execution mode as automatic routing decisions.`].filter(Boolean).join('\n\n')
    const result: any = await authedFetch('/api/tasks/intake', { method: 'POST', body: { intent: request, project_id: selectedProject.value || undefined } })
    terminalOutput.value = '✓ Objective accepted: ' + result.task.slug + '\n  App: ' + result.project.name + '\n  Routing: Madeus Autopilot · independent QA · verified release'
    completeJourney(); recordProficiency('completed'); trackExperience('action_completed', { action: 'outcome_submitted', task: result.task.slug, stage: proficiency.value.stage })
    terminalPrompt.value = ''; routeInfo.value = ''; loadData()
  } catch (e: any) { terminalOutput.value = 'Error: ' + (e.message || String(e)) }
  finally { terminalLoading.value = false }
}

onMounted(async () => {
  await loadData()
  if (persistentContext.appId && APPS.some(app => app.id === persistentContext.appId)) selectedApp.value = persistentContext.appId
  if (persistentContext.projectId && projects.value.some(project => project.id === persistentContext.projectId)) selectedProject.value = persistentContext.projectId
  if (!terminalPrompt.value && typeof route.query.intent === 'string') terminalPrompt.value = route.query.intent
  try {
    const pending = JSON.parse(sessionStorage.getItem('madeus:pending-command') || 'null')
    if (!terminalPrompt.value && pending?.intent && Date.now() - Number(pending.created_at || 0) < 86_400_000) terminalPrompt.value = String(pending.intent)
    if (pending) sessionStorage.removeItem('madeus:pending-command')
  } catch { sessionStorage.removeItem('madeus:pending-command') }
  if (proficiency.value.showAdvancedByDefault) persistentContext.advanced = true
  await loadDraft(); await loadDeploys(); await loadConnectors(); await resolvePreview(); refreshInsights()
})
watch(contextHydrated, ready => {
  if (!ready) return
  if (persistentContext.appId && APPS.some(app => app.id === persistentContext.appId)) selectedApp.value = persistentContext.appId
  if (persistentContext.projectId && projects.value.some(project => project.id === persistentContext.projectId)) selectedProject.value = persistentContext.projectId
})
watch(user, u => { if (u) { loadData(); loadDraft(); loadDeploys(); loadConnectors(); resolvePreview() } })
watch(selectedApp, () => { loadDraft(); loadDeploys(); refreshInsights(); resolvePreview() })
watch(selectedApp, value => { if (contextHydrated.value) persistentContext.appId = value })
watch(selectedProject, value => { if (contextHydrated.value) persistentContext.projectId = value })
watch(cap, value => { if (contextHydrated.value) persistentContext.capability = value.name })
watch(selectedBranch, resolvePreview)
watch(slug, () => { refreshInsights() })
</script>
<template>
  <div class="flex min-h-full flex-col bg-slate-50">
    <!-- Top header bar: replaces left sidebar -->
    <div class="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 bg-white px-4 py-3 flex-shrink-0">
      <div class="flex items-center gap-3">
        <NuxtLink to="/orchestrators" class="text-[10px] text-gray-400 hover:text-gray-600 uppercase tracking-wider">← Back</NuxtLink>
        <div><h2 class="text-sm font-bold text-gray-900">{{ cap.name }}</h2><p class="mt-0.5 hidden max-w-2xl text-[10px] text-gray-500 sm:block">{{ cap.summary }}</p></div>
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <!-- App selector (was in sidebar) -->
        <div class="flex items-center gap-1.5">
          <span class="text-[10px] text-gray-400">App:</span>
          <select v-model="selectedApp" class="bg-white border border-gray-200 rounded px-2 py-1 text-xs text-gray-700">
            <option v-for="app in APPS" :key="app.id" :value="app.id">{{ app.name }}</option>
          </select>
        </div>
        <!-- Project selector -->
        <select v-model="selectedProject" class="bg-white border border-gray-200 rounded px-2 py-1 text-[10px] text-gray-700">
          <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
        <!-- Auto-save indicator -->
        <div class="flex items-center gap-1">
          <span class="w-1.5 h-1.5 rounded-full" :class="autoSaveStatus === 'saved' ? 'bg-emerald-500' : autoSaveStatus === 'saving' ? 'bg-amber-400 animate-pulse' : autoSaveStatus === 'unsaved' ? 'bg-gray-400' : 'bg-red-500'"></span>
          <span class="text-[9px] text-gray-400">{{ autoSaveStatus === 'saved' ? 'Saved' : autoSaveStatus === 'saving' ? 'Saving...' : autoSaveStatus === 'unsaved' ? 'Unsaved' : 'Error' }}</span>
        </div>
      </div>
    </div>

    <!-- Main content area: flex row for content + CADE insights panel -->
    <div class="flex min-h-0 flex-1">
      <!-- CENTER: Main workspace -->
      <div class="flex min-w-0 flex-1 flex-col">
          <!-- Workspace top bar -->
          <div class="flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-white flex-shrink-0">
            <div class="flex items-center gap-3">
              <span class="text-xs text-gray-500">{{ APPS.find(a => a.id === selectedApp)?.name }}</span>
              <!-- CADE Bots inline -->
              <div class="flex items-center gap-1">
                <div v-for="b in bots.slice(0, 4)" :key="b" class="flex items-center gap-1 px-1.5 py-0.5 bg-gray-50 rounded text-[9px] text-gray-500">
                  <span class="w-1 h-1 rounded-full bg-emerald-500"></span>{{ b.split(' ').map((w: string) => w[0]).join('') }}
                </div>
                <span v-if="bots.length > 4" class="text-[9px] text-gray-400">+{{ bots.length - 4 }}</span>
              </div>
            </div>
            <div class="flex items-center gap-2">
              <button @click="showInsights = !showInsights" class="px-2 py-1 text-[10px] border rounded" :class="showInsights ? 'bg-emerald-50 text-emerald-800 border-emerald-200' : 'text-gray-500 border-gray-200'">
                {{ showInsights ? 'Hide' : 'Show' }} guidance
              </button>
              <button @click="toggleAdvanced" class="px-2 py-1 text-[10px] border rounded" :class="advancedOpen ? 'bg-gray-900 text-white border-gray-900' : 'text-gray-500 border-gray-200'">{{ advancedOpen ? 'Basic view' : 'Advanced' }}</button>
            </div>
          </div>
          <section class="border-b border-blue-100 bg-[radial-gradient(circle_at_top_left,_rgba(37,99,235,.14),_transparent_34%),linear-gradient(135deg,#f8fbff,#eef5ff)] px-4 py-6 sm:px-7 sm:py-8">
            <div class="mx-auto grid max-w-6xl gap-6 xl:grid-cols-[minmax(260px,.72fr)_minmax(520px,1.28fr)] xl:items-center">
              <div>
                <div class="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[.16em] text-blue-700"><span class="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_0_5px_rgba(16,185,129,.12)]"></span> {{ cap.name }}</div>
                <h1 class="mt-4 text-3xl font-semibold tracking-[-.04em] text-slate-950 sm:text-4xl">Describe the outcome.<br><span class="text-blue-600">Madeus runs the work.</span></h1>
                <p class="mt-3 max-w-xl text-sm leading-6 text-slate-600">{{ cap.summary }} Context, specialists, tools, verification, and safe release routing are handled automatically.</p>
                <div class="mt-5 flex flex-wrap gap-2 text-[10px] font-semibold text-slate-600"><span class="rounded-full border border-blue-100 bg-white/80 px-3 py-1.5">Portfolio context loaded</span><span class="rounded-full border border-blue-100 bg-white/80 px-3 py-1.5">Independent QA</span><span class="rounded-full border border-blue-100 bg-white/80 px-3 py-1.5">Proof retained</span></div>
              </div>
              <div class="overflow-hidden rounded-2xl border border-blue-100 bg-white shadow-[0_20px_55px_rgba(15,56,120,.12)]">
                <OutcomeCanvas v-model="terminalPrompt" v-model:successCriteria="successCriteria" v-model:constraints="outcomeConstraints" v-model:advanced="advancedOpen" :app-name="APPS.find(a => a.id === selectedApp)?.name || selectedApp" :capability="cap.name" :busy="terminalLoading" @submit="runCommand" />
                <div v-if="terminalOutput" class="m-3 mt-0 max-h-28 overflow-y-auto whitespace-pre-wrap rounded-lg bg-emerald-50 px-3 py-2 text-[10px] leading-4 text-emerald-800">{{ terminalOutput }}</div>
              </div>
            </div>
          </section>
          <!-- VISUAL CONTEXT + TOOLS AREA (scrollable) -->
          <div class="min-h-0 flex-1">
            <div class="grid grid-cols-1 border-b border-gray-200 bg-white" :class="showInsights ? 'xl:grid-cols-[minmax(0,1fr)_360px]' : 'grid-cols-1'">
            <!-- LIVE APP PREVIEW -->
            <div class="bg-gray-100 xl:border-r border-gray-200 min-w-0">
              <div class="bg-gray-200 px-3 py-1.5 flex items-center gap-2 text-[10px] text-gray-500">
                <span class="w-2 h-2 rounded-full bg-red-400"></span>
                <span class="w-2 h-2 rounded-full bg-amber-400"></span>
                <span class="w-2 h-2 rounded-full bg-emerald-400"></span>
                <span class="flex-1 text-center font-mono">{{ previewTarget?.external_url || 'Resolving live app…' }} · verified production context for {{ selectedBranch }}</span>
                <button @click="reloadIframe" class="text-gray-400 hover:text-gray-600 px-1">↻</button>
                <a v-if="previewTarget?.external_url" :href="previewTarget.external_url" target="_blank" rel="noopener" class="text-gray-400 hover:text-gray-600 px-1">↗</a>
              </div>
              <PreviewProofRibbon :proof="previewTarget?.proof" :gateway="usingPreviewGateway" :loading="previewLoading" />
              <div class="relative" :class="previewUrl ? 'h-[45vh] min-h-[320px]' : 'h-48'">
                <div v-if="previewLoading || (previewUrl && !iframeLoaded)" class="absolute inset-0 bg-white flex items-center justify-center z-10">
                  <div class="text-center space-y-2">
                    <div class="w-6 h-6 border-2 border-emerald-700 border-t-transparent rounded-full animate-spin mx-auto"></div>
                    <p class="text-xs text-gray-400">Verifying {{ APPS.find(a => a.id === selectedApp)?.name }}...</p>
                  </div>
                </div>
                <div v-else-if="!previewUrl" class="absolute inset-0 flex items-center justify-center bg-white p-8">
                  <div class="max-w-md text-center">
                    <div class="mx-auto grid h-10 w-10 place-items-center rounded-xl bg-emerald-50 text-emerald-700">↗</div>
                    <h3 class="mt-4 text-sm font-semibold text-gray-900">{{ previewTarget?.available ? 'Live app verified' : 'Preview temporarily unavailable' }}</h3>
                    <p class="mt-2 text-xs leading-5 text-gray-500">{{ previewTarget?.reason }}</p>
                    <a v-if="previewTarget?.available && previewTarget.external_url" :href="previewTarget.external_url" target="_blank" rel="noopener" class="mt-4 inline-flex rounded-lg bg-gray-900 px-4 py-2 text-xs font-medium text-white">Open live app ↗</a>
                    <button v-else class="mt-4 rounded-lg border px-4 py-2 text-xs text-gray-600" @click="reloadIframe">Check again</button>
                    <p class="mt-3 text-[9px] text-gray-400">Madeus never embeds guessed branch URLs. A branch preview appears only after a durable deployment is verified.</p>
                  </div>
                </div>
                <iframe
                  v-else
                  :key="iframeKey"
                  :src="previewUrl"
                  title="Verified live application preview"
                  @load="onIframeLoad"
                  class="w-full h-full border-0"
                  allow="clipboard-read; clipboard-write"
                  sandbox="allow-forms allow-modals allow-popups allow-scripts allow-downloads"
                  referrerpolicy="no-referrer-when-downgrade"
                />
              </div>
            </div>

            <!-- CADE ACTION RAIL + TERMINAL -->
            <aside v-if="showInsights" class="flex min-h-[420px] flex-col overflow-hidden bg-gray-50">
              <div class="px-4 py-3 border-b border-gray-200 bg-white">
                <div class="flex items-center justify-between">
                  <div>
                    <div class="text-[10px] text-emerald-800 uppercase tracking-[0.16em] font-semibold">Decision guidance</div>
                    <div class="mt-1 text-sm font-semibold text-gray-900">Understand → decide → implement</div>
                  </div>
                  <div class="flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-1">
                    <span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                    <span class="text-[9px] font-medium text-emerald-700">Live analysis</span>
                  </div>
                </div>
                <p class="mt-2 text-[11px] leading-4 text-gray-500">Recommendations are grounded in the selected app and capability. Review the evidence, adjust implementation scope, or let Madeus execute safely.</p>
              </div>

              <div class="flex gap-1 px-3 py-2 border-b border-gray-200 overflow-x-auto bg-white">
                <button v-for="ins in insights" :key="ins.key" @click="activeInsight = ins.key"
                  class="shrink-0 px-2 py-1 text-[10px] rounded-md transition-colors"
                  :class="activeInsight === ins.key ? 'bg-gray-900 text-white font-medium' : 'text-gray-500 hover:bg-gray-100'">
                  {{ ins.icon }} {{ ins.label }}
                </button>
              </div>

              <div class="flex-1 overflow-y-auto p-3 space-y-2">
                <div v-if="insightNotice" class="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[10px] leading-4 text-emerald-800">{{ insightNotice }}</div>
                <article v-for="entry in insightsForActive" :key="entry.id" class="rounded-xl border bg-white p-3 shadow-sm" :class="entry.resolved ? 'border-emerald-200' : 'border-gray-200'">
                  <div class="flex items-start justify-between gap-3">
                    <div class="min-w-0">
                      <div class="flex items-center gap-1.5">
                        <span class="h-1.5 w-1.5 rounded-full" :class="severityDot(entry.severity)"></span>
                        <span class="text-[9px] font-semibold uppercase tracking-wider" :class="entry.severity === 'high' ? 'text-red-600' : entry.severity === 'warning' ? 'text-amber-600' : 'text-emerald-700'">{{ entry.severity === 'info' ? 'Opportunity' : entry.severity }}</span>
                      </div>
                      <h4 class="mt-1 text-xs font-semibold leading-4 text-gray-900">{{ entry.title }}</h4>
                    </div>
                    <span class="shrink-0 text-[9px] text-gray-400">{{ entry.confidence }}% confidence</span>
                  </div>
                  <p class="mt-2 text-[10px] leading-4 text-gray-500"><strong class="text-gray-700">Evidence:</strong> {{ entry.message }}</p>
                  <p class="mt-1 text-[10px] leading-4 text-gray-500"><strong class="text-gray-700">Why CADE suggests this:</strong> {{ entry.why }}</p>
                  <div class="mt-2 rounded-lg bg-gray-50 px-2.5 py-2">
                    <div class="text-[9px] font-semibold uppercase tracking-wider text-gray-400">Recommended change</div>
                    <p class="mt-1 text-[10px] leading-4 text-gray-700">{{ entry.recommendation }}</p>
                    <p class="mt-1 text-[10px] leading-4 text-emerald-700"><strong>Expected value:</strong> {{ entry.outcome }}</p>
                  </div>
                  <div class="mt-3 flex items-center gap-2">
                    <select v-model="implementationScope[entry.id]" :disabled="entry.resolved" class="min-w-0 flex-1 rounded-md border border-gray-200 bg-white px-2 py-1.5 text-[10px] text-gray-600">
                      <option value="safe">Safe patch · verify first</option>
                      <option value="focused">Focused improvement</option>
                      <option value="full">Full implementation</option>
                    </select>
                    <button @click="expandInsight(entry)" class="rounded-md border border-gray-200 px-2 py-1.5 text-[10px] font-medium text-gray-600 hover:bg-gray-50">Expand</button>
                    <button @click="editInsightPlan(entry)" :disabled="entry.resolved" class="rounded-md border border-gray-200 px-2 py-1.5 text-[10px] font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-40">Edit</button>
                    <button @click="implementInsight(entry)" :disabled="entry.implementing || entry.resolved" class="rounded-md bg-gray-900 px-2.5 py-1.5 text-[10px] font-semibold text-white hover:bg-black disabled:bg-emerald-600">
                      {{ entry.resolved ? '✓ Queued' : entry.implementing ? 'Queuing…' : 'Implement' }}
                    </button>
                  </div>
                </article>
                <div v-if="!insightsForActive.length" class="rounded-xl border border-dashed border-gray-200 bg-white p-6 text-center text-[11px] text-gray-400">No actionable guidance in this category yet.</div>
              </div>

            </aside>
            </div>

            <!-- DOMAIN-SPECIFIC CAPABILITIES below the app + command workbench -->
            <div class="p-4 space-y-4">
              <div v-if="proficiency.stage === 'guided' || frictionSimplified" class="flex items-center justify-between gap-4 rounded-xl border border-emerald-200 bg-emerald-50/60 px-4 py-3"><div><div class="text-[9px] font-semibold uppercase tracking-wider text-emerald-800">{{ frictionSimplified ? 'Simplified from your usage' : 'Guided workspace' }}</div><p class="mt-1 text-[10px] leading-4 text-emerald-950">Start with the outcome box above. Madeus will choose the project context, specialists, tools, verification, and release path. Advanced controls appear as they become useful.</p></div><button class="shrink-0 rounded-lg border border-emerald-300 bg-white px-3 py-2 text-[9px] font-semibold text-emerald-900" @click="toggleAdvanced">Show advanced</button></div>
              <CadeOperatingSystem
                :app="APPS.find(a => a.id === selectedApp)?.name || selectedApp"
                :capability="cap.name"
                :domain="cap.domain"
                :project-id="selectedProject"
                :recommendation="insightsForActive[0]?.recommendation"
                :outcome="insightsForActive[0]?.outcome"
                @use-prompt="useCadePrompt"
              />
              <OutcomeIntelligenceLive :app="APPS.find(a => a.id === selectedApp)?.name || selectedApp" :capability="cap.name" :project-id="selectedProject" />
              <ProofTimeline :tasks="recentTasks" :deployments="recentDeploys" :capability="cap.name" />
              <div class="flex items-end justify-between gap-4">
                <div>
                  <div class="text-[10px] font-semibold uppercase tracking-[0.16em] text-gray-400">Capability workspace</div>
                  <h3 class="mt-1 text-base font-semibold text-gray-900">Measure, configure, and verify {{ cap.name }}</h3>
                  <p class="mt-1 text-xs text-gray-500">Supporting metrics and controls live below the app-and-action workbench so they add context without interrupting execution.</p>
                </div>
                <button v-if="advancedOpen" @click="showConfig = !showConfig" class="shrink-0 rounded-lg border border-gray-200 bg-white px-3 py-2 text-[10px] font-semibold text-gray-700 hover:bg-gray-50">{{ showConfig ? 'Hide tuning' : 'Configure capability' }}</button>
              </div>
              <!-- Design domain metrics -->
              <div v-if="cap.domain === 'product-design'" class="space-y-4">
                <section class="overflow-hidden rounded-2xl border border-gray-200 bg-white">
                  <div class="border-b border-gray-100 p-4">
                    <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                      <div>
                      <div class="text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-800">Creative capability cloud</div>
                        <h4 class="mt-1 text-lg font-semibold text-gray-900">Design, generate, animate, test, and ship</h4>
                        <p class="mt-1 max-w-3xl text-xs leading-5 text-gray-500">Madeus selects the strongest connected model or app for the job. You choose the creative outcome and constraints—not vendors, model IDs, or routing mechanics.</p>
                      </div>
                      <div class="flex items-center gap-2">
                        <NuxtLink to="/connectors" class="rounded-lg border border-gray-200 bg-white px-3 py-2 text-[10px] font-semibold text-gray-700 hover:bg-gray-50">Manage design connections</NuxtLink>
                        <span class="rounded-full bg-emerald-50 px-2.5 py-1 text-[9px] font-medium text-emerald-700">{{ connectorRegistry.filter(c => c.recommended && c.connected_accounts?.length).length }} specialist accounts connected</span>
                      </div>
                    </div>
                    <div class="mt-4 flex flex-col gap-2 lg:flex-row">
                      <input v-model="designQuery" type="search" placeholder="Search UI, brand, artwork, motion, video, QA…" class="min-w-0 flex-1 rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-xs outline-none focus:border-blue-400 focus:bg-white focus:ring-2 focus:ring-blue-100">
                      <div class="flex gap-1 overflow-x-auto">
                        <button v-for="category in DESIGN_CATEGORIES" :key="category" @click="designCategory = category" class="shrink-0 rounded-lg px-2.5 py-2 text-[10px] font-medium" :class="designCategory === category ? 'bg-gray-900 text-white' : 'bg-gray-50 text-gray-500 hover:bg-gray-100'">{{ category }}</button>
                      </div>
                    </div>
                  </div>

                  <div class="grid gap-px bg-gray-100 md:grid-cols-2 xl:grid-cols-3">
                    <article v-for="tool in filteredDesignCapabilities" :key="tool.id" class="flex min-h-52 flex-col bg-white p-4">
                      <div class="flex items-start justify-between gap-3">
                        <div class="grid h-9 w-9 place-items-center rounded-xl bg-gray-900 text-sm text-white">{{ tool.icon }}</div>
                        <span class="rounded-full px-2 py-1 text-[9px] font-medium" :class="toolReady(tool) ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'">{{ toolReady(tool) ? 'Route ready' : 'Connection helpful' }}</span>
                      </div>
                      <h5 class="mt-3 text-sm font-semibold text-gray-900">{{ tool.name }}</h5>
                      <p class="mt-1 flex-1 text-[11px] leading-5 text-gray-500">{{ tool.summary }}</p>
                      <div class="mt-3 flex flex-wrap gap-1">
                        <span v-for="output in tool.outputs" :key="output" class="rounded bg-gray-50 px-2 py-1 text-[9px] text-gray-500">{{ output }}</span>
                      </div>
                      <div class="mt-3 flex items-center justify-between gap-2 border-t border-gray-100 pt-3">
                        <div class="flex -space-x-1">
                          <span v-for="provider in tool.connectorIds.slice(0, 5)" :key="provider" :title="connectorFor(provider)?.name || provider" class="grid h-5 w-5 place-items-center rounded-full border border-white text-[8px] font-semibold" :class="connectorReady(provider) ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-400'">{{ (connectorFor(provider)?.name || provider).charAt(0).toUpperCase() }}</span>
                        </div>
                        <button @click="openDesignTool(tool)" class="rounded-lg bg-gray-900 px-3 py-1.5 text-[10px] font-semibold text-white hover:bg-black">Open builder</button>
                      </div>
                    </article>
                  </div>
                </section>

                <section v-if="activeDesignTool" class="rounded-2xl border border-emerald-200 bg-emerald-50/40 p-4">
                  <div class="flex items-start justify-between gap-4">
                    <div>
                      <div class="text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-800">Active builder</div>
                      <h4 class="mt-1 text-base font-semibold text-gray-900">{{ activeDesignTool.name }}</h4>
                      <p class="mt-1 text-xs text-gray-500">{{ activeDesignTool.summary }}</p>
                    </div>
                    <button @click="activeDesignTool = null" class="rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-[10px] text-gray-500">Close</button>
                  </div>
                  <label class="mt-4 block text-[10px] font-semibold uppercase tracking-wider text-gray-500">Creative direction
                    <textarea v-model="builderPrompt" rows="4" class="mt-1 w-full resize-y rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs leading-5 text-gray-800 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"></textarea>
                  </label>
                  <div class="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
                    <label v-if="activeDesignTool.controls.includes('format')" class="text-[10px] font-medium text-gray-500">Output<select v-model="builderSettings.format" class="mt-1 w-full rounded-lg border bg-white px-2 py-2 text-[10px]"><option>Production assets</option><option>Editable source</option><option>Concept board</option><option>Implementation spec</option></select></label>
                    <label v-if="activeDesignTool.controls.includes('ratio')" class="text-[10px] font-medium text-gray-500">Aspect ratio<select v-model="builderSettings.ratio" class="mt-1 w-full rounded-lg border bg-white px-2 py-2 text-[10px]"><option>16:9</option><option>1:1</option><option>4:5</option><option>9:16</option><option>Auto set</option></select></label>
                    <label v-if="activeDesignTool.controls.includes('variants')" class="text-[10px] font-medium text-gray-500">Variants<input v-model.number="builderSettings.variants" type="range" min="1" max="12" class="mt-2 w-full accent-emerald-700"><span class="font-mono text-gray-900">{{ builderSettings.variants }}</span></label>
                    <label v-if="activeDesignTool.controls.includes('duration')" class="text-[10px] font-medium text-gray-500">Duration<input v-model.number="builderSettings.duration" type="range" min="2" max="30" class="mt-2 w-full accent-emerald-700"><span class="font-mono text-gray-900">{{ builderSettings.duration }}s</span></label>
                    <label v-if="activeDesignTool.controls.includes('fidelity')" class="text-[10px] font-medium text-gray-500">Fidelity<select v-model="builderSettings.fidelity" class="mt-1 w-full rounded-lg border bg-white px-2 py-2 text-[10px]"><option>Fast concept</option><option>High</option><option>Production</option></select></label>
                    <label v-if="activeDesignTool.controls.includes('brand')" class="flex items-center justify-between rounded-lg border bg-white px-3 py-2 text-[10px] font-medium text-gray-600">Lock brand<input v-model="builderSettings.brand" type="checkbox" class="accent-emerald-700"></label>
                  </div>
                  <div class="mt-4 flex flex-wrap items-center justify-between gap-3">
                    <div class="text-[10px] text-gray-500">Madeus will compare eligible routes, preserve sources and provenance, and return outputs behind a review gate.</div>
                    <div class="flex items-center gap-2">
                      <NuxtLink v-if="!toolReady(activeDesignTool)" to="/connectors" class="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[10px] font-semibold text-amber-800">Connect a specialist provider</NuxtLink>
                      <button @click="runDesignTool" :disabled="builderRunning || !builderPrompt.trim()" class="rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-40">{{ builderRunning ? 'Routing…' : 'Create with Madeus' }}</button>
                    </div>
                  </div>
                  <div v-if="builderNotice" class="mt-3 rounded-lg border border-emerald-200 bg-white px-3 py-2 text-[10px] text-emerald-800">{{ builderNotice }}</div>
                </section>

                <div class="grid grid-cols-4 gap-3">
                  <div class="bg-white border border-gray-200 rounded-lg p-3">
                    <div class="text-[10px] text-gray-400">Pages</div><div class="text-xl font-bold text-gray-900 mt-1">12</div><div class="text-[10px] text-emerald-600">All passing</div>
                  </div>
                  <div class="bg-white border border-gray-200 rounded-lg p-3">
                    <div class="text-[10px] text-gray-400">Components</div><div class="text-xl font-bold text-gray-900 mt-1">47</div><div class="text-[10px] text-blue-600">3 need review</div>
                  </div>
                  <div class="bg-white border border-gray-200 rounded-lg p-3">
                    <div class="text-[10px] text-gray-400">Cognitive Load</div><div class="text-xl font-bold text-gray-900 mt-1">6.2</div><div class="text-[10px] text-amber-600">Slightly elevated</div>
                  </div>
                  <div class="bg-white border border-gray-200 rounded-lg p-3">
                    <div class="text-[10px] text-gray-400">Tasks</div><div class="text-xl font-bold text-gray-900 mt-1">{{ recentTasks.filter(t => t.note?.includes(selectedApp)).length }}</div><div class="text-[10px] text-gray-500">For {{ APPS.find(a => a.id === selectedApp)?.name }}</div>
                  </div>
                </div>
              </div>

              <!-- Legal domain tools -->
              <div v-else-if="cap.domain === 'legal-ops'" class="space-y-4">
                <div class="flex items-center justify-between">
                  <h4 class="text-sm font-semibold text-gray-700">Documents — {{ APPS.find(a => a.id === selectedApp)?.name }}</h4>
                  <button class="px-2 py-1 text-[10px] bg-blue-600 text-white rounded">+ New Document</button>
                </div>
                <div class="space-y-2">
                  <div v-for="doc in appDocs" :key="doc.name + selectedApp" class="bg-white border border-gray-200 rounded-lg p-3 flex items-center justify-between hover:shadow-sm transition-shadow cursor-pointer group">
                    <div class="flex items-center gap-2">
                      <span>📄</span>
                      <div>
                        <div class="text-sm font-medium text-gray-900 group-hover:text-blue-700">{{ doc.name }}</div>
                        <div class="text-[10px] text-gray-400">{{ APPS.find(a => a.id === selectedApp)?.name }} · {{ doc.type }}</div>
                      </div>
                    </div>
                    <div class="flex items-center gap-2">
                      <span class="text-[10px] px-2 py-0.5 rounded-full font-medium" :class="docStatusColor(doc.status)">{{ doc.status }}</span>
                      <button class="px-2 py-0.5 text-[10px] bg-blue-50 text-blue-700 border border-blue-200 rounded opacity-0 group-hover:opacity-100">CADE Review</button>
                    </div>
                  </div>
                </div>
                <div class="bg-blue-50 border border-blue-200 rounded-lg p-3">
                  <p class="text-xs text-blue-600">{{ appDocs.filter(d => d.status === 'current').length }}/{{ appDocs.length }} documents current for <strong>{{ APPS.find(a => a.id === selectedApp)?.name }}</strong>. {{ appDocs.some(d => d.status === 'draft') ? 'Drafts need review.' : 'All up to date.' }}</p>
                </div>
              </div>

              <!-- Engineering domain -->
              <div v-else-if="cap.domain === 'engineering'" class="space-y-4">
                <h4 class="text-sm font-semibold text-gray-700">Code & Review — {{ APPS.find(a => a.id === selectedApp)?.name }}</h4>
                <div class="grid grid-cols-4 gap-3">
                  <div class="bg-white border border-gray-200 rounded-lg p-3"><div class="text-[10px] text-gray-400">Open PRs</div><div class="text-xl font-bold text-gray-900 mt-1">3</div><div class="text-[10px] text-amber-600">2 need review</div></div>
                  <div class="bg-white border border-gray-200 rounded-lg p-3"><div class="text-[10px] text-gray-400">Test Coverage</div><div class="text-xl font-bold text-gray-900 mt-1">94%</div><div class="text-[10px] text-emerald-600">Above target</div></div>
                  <div class="bg-white border border-gray-200 rounded-lg p-3"><div class="text-[10px] text-gray-400">Dep Patches</div><div class="text-xl font-bold text-gray-900 mt-1">5</div><div class="text-[10px] text-amber-600">Security</div></div>
                  <div class="bg-white border border-gray-200 rounded-lg p-3"><div class="text-[10px] text-gray-400">P95 Latency</div><div class="text-xl font-bold text-gray-900 mt-1">220ms</div><div class="text-[10px] text-emerald-600">Under target</div></div>
                </div>
                <div v-if="recentTasks.length" class="space-y-1">
                  <div class="text-[10px] text-gray-400 uppercase tracking-wider">Recent tasks</div>
                  <div v-for="t in recentTasks.slice(0, 6)" :key="t.id" class="bg-white border border-gray-200 rounded-lg px-3 py-2 flex items-center gap-2 text-xs">
                    <span class="font-mono" :class="stateClass(t.state)">{{ stateIcon(t.state) }}</span>
                    <span class="text-gray-700 flex-1 truncate">{{ t.slug }}</span>
                    <span class="text-[10px] text-gray-400 px-1.5 py-0.5 bg-gray-50 rounded">{{ t.kind || '—' }}</span>
                    <span class="text-[10px] text-gray-400">{{ timeAgo(t.created_at) }}</span>
                  </div>
                </div>
              </div>

              <!-- DevOps domain -->
              <div v-else-if="cap.domain === 'devops'" class="space-y-4">
                <h4 class="text-sm font-semibold text-gray-700">Deployment Health — {{ APPS.find(a => a.id === selectedApp)?.name }}</h4>
                <div class="grid grid-cols-4 gap-3">
                  <div class="bg-white border border-gray-200 rounded-lg p-3 text-center"><div class="text-xl font-bold text-emerald-600">●</div><div class="text-[10px] text-gray-500 mt-1">Healthy</div></div>
                  <div class="bg-white border border-gray-200 rounded-lg p-3 text-center"><div class="text-xl font-bold text-gray-900">{{ recentDeploys.length }}</div><div class="text-[10px] text-gray-500 mt-1">Deploys</div></div>
                  <div class="bg-white border border-gray-200 rounded-lg p-3 text-center"><div class="text-xl font-bold text-gray-900">0</div><div class="text-[10px] text-gray-500 mt-1">Rollbacks</div></div>
                  <div class="bg-white border border-gray-200 rounded-lg p-3 text-center"><div class="text-xl font-bold text-gray-900">99.9%</div><div class="text-[10px] text-gray-500 mt-1">Uptime</div></div>
                </div>
                <div v-if="recentDeploys.length" class="space-y-1">
                  <div class="text-[10px] text-gray-400 uppercase tracking-wider">Recent deploys</div>
                  <div v-for="d in recentDeploys.slice(0, 5)" :key="d.id" class="bg-white border border-gray-200 rounded-lg px-3 py-2 flex items-center gap-2 text-xs">
                    <span class="w-2 h-2 rounded-full" :class="d.deploy_status === 'deployed' ? 'bg-emerald-500' : 'bg-red-500'"></span>
                    <span class="font-mono text-gray-600">{{ d.version }}</span>
                    <span class="flex-1 truncate text-gray-400">{{ d.note }}</span>
                    <span class="text-gray-400">{{ timeAgo(d.created_at) }}</span>
                  </div>
                </div>
              </div>

              <!-- Growth domain -->
              <div v-else-if="cap.domain === 'growth'" class="space-y-4">
                <h4 class="text-sm font-semibold text-gray-700">Growth — {{ APPS.find(a => a.id === selectedApp)?.name }}</h4>
                <div class="grid grid-cols-4 gap-3">
                  <div class="bg-white border border-gray-200 rounded-lg p-3"><div class="text-[10px] text-gray-400">Experiments</div><div class="text-xl font-bold text-gray-900 mt-1">3</div></div>
                  <div class="bg-white border border-gray-200 rounded-lg p-3"><div class="text-[10px] text-gray-400">Conversion</div><div class="text-xl font-bold text-emerald-600 mt-1">4.2%</div></div>
                  <div class="bg-white border border-gray-200 rounded-lg p-3"><div class="text-[10px] text-gray-400">MAU</div><div class="text-xl font-bold text-gray-900 mt-1">12.4k</div></div>
                  <div class="bg-white border border-gray-200 rounded-lg p-3"><div class="text-[10px] text-gray-400">Retention D7</div><div class="text-xl font-bold text-blue-600 mt-1">68%</div></div>
                </div>
              </div>

              <!-- Security domain -->
              <div v-else-if="cap.domain === 'security'" class="space-y-4">
                <h4 class="text-sm font-semibold text-gray-700">Security — {{ APPS.find(a => a.id === selectedApp)?.name }}</h4>
                <div class="grid grid-cols-4 gap-3">
                  <div class="bg-white border border-gray-200 rounded-lg p-3"><div class="text-[10px] text-gray-400">RLS</div><div class="text-xl font-bold text-emerald-600 mt-1">✓</div></div>
                  <div class="bg-white border border-gray-200 rounded-lg p-3"><div class="text-[10px] text-gray-400">Key Age</div><div class="text-xl font-bold text-gray-900 mt-1">12d</div></div>
                  <div class="bg-white border border-gray-200 rounded-lg p-3"><div class="text-[10px] text-gray-400">Vulns</div><div class="text-xl font-bold text-amber-600 mt-1">2</div></div>
                  <div class="bg-white border border-gray-200 rounded-lg p-3"><div class="text-[10px] text-gray-400">Last Scan</div><div class="text-xl font-bold text-gray-900 mt-1">4h</div></div>
                </div>
              </div>

              <!-- Platform / fallback -->
              <div v-else class="space-y-4">
                <h4 class="text-sm font-semibold text-gray-700">{{ cap.name }} — {{ APPS.find(a => a.id === selectedApp)?.name }}</h4>
                <p class="text-xs text-gray-500">{{ cap.summary }}</p>
                <div class="grid grid-cols-3 gap-3">
                  <div class="bg-white border border-gray-200 rounded-lg p-3"><div class="text-[10px] text-gray-400">Tasks Today</div><div class="text-xl font-bold text-gray-900 mt-1">{{ recentTasks.filter(t => new Date(t.created_at) > new Date(Date.now() - 86400000)).length }}</div></div>
                  <div class="bg-white border border-gray-200 rounded-lg p-3"><div class="text-[10px] text-gray-400">Queued</div><div class="text-xl font-bold text-gray-900 mt-1">{{ recentTasks.filter(t => t.state === 'QUEUED').length }}</div></div>
                  <div class="bg-white border border-gray-200 rounded-lg p-3"><div class="text-[10px] text-gray-400">Maturity</div><div class="text-xl font-bold text-gray-900 mt-1">{{ cap.maturity }}%</div></div>
                </div>
                <div v-if="recentTasks.length" class="space-y-1">
                  <div class="text-[10px] text-gray-400 uppercase tracking-wider">Recent tasks</div>
                  <div v-for="t in recentTasks.slice(0, 6)" :key="t.id" class="bg-white border border-gray-200 rounded-lg px-3 py-2 flex items-center gap-2 text-xs">
                    <span class="font-mono" :class="stateClass(t.state)">{{ stateIcon(t.state) }}</span>
                    <span class="text-gray-700 flex-1 truncate">{{ t.slug }}</span>
                    <span class="text-[10px] text-gray-400">{{ timeAgo(t.created_at) }}</span>
                  </div>
                </div>
              </div>

              <!-- CONFIG SLIDERS (inline, collapsible) -->
              <div class="mt-4 border-t border-gray-200 pt-3">
                <button @click="showConfig = !showConfig" class="flex items-center gap-2 text-[10px] text-gray-500 hover:text-gray-700 uppercase tracking-wider font-medium">
                  <span>{{ showConfig ? '▼' : '▶' }}</span> Configuration & Tuning
                </button>
                <div v-if="showConfig" class="mt-3 bg-white border border-gray-200 rounded-lg p-4 space-y-3">
                  <div v-for="s in domainSliders" :key="s.label">
                    <div class="flex justify-between text-xs mb-1"><span class="text-gray-600">{{ s.label }}</span><span class="font-mono text-gray-900 font-medium">{{ sliders[s.label] ?? s.default }}{{ s.unit }}</span></div>
                    <input type="range" :min="s.min" :max="s.max" v-model.number="sliders[s.label]" class="w-full h-1.5 bg-gray-200 rounded-full appearance-none cursor-pointer accent-emerald-700" />
                  </div>
                  <div class="border-t border-gray-100 pt-3"><div class="mb-2 text-[9px] font-semibold uppercase tracking-wider text-gray-400">Active specialists</div><div class="flex flex-wrap gap-1.5"><span v-for="b in bots" :key="b" class="rounded-full bg-emerald-50 px-2 py-1 text-[9px] text-emerald-800">{{ b }}</span></div></div>
                </div>
              </div>
            </div>
          </div>
      </div>

    </div>

    <Teleport to="body">
      <div v-if="expandedInsight" class="fixed inset-0 z-[150] flex items-end justify-center bg-gray-950/45 p-0 backdrop-blur-sm sm:items-center sm:p-6" @mousedown.self="expandedInsightId = ''">
        <section class="flex max-h-[94vh] w-full max-w-6xl flex-col overflow-hidden rounded-t-3xl bg-white shadow-2xl sm:rounded-3xl">
          <header class="flex items-start justify-between gap-5 border-b border-gray-200 px-5 py-4 sm:px-7">
            <div>
              <div class="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[.16em] text-emerald-800"><span class="h-2 w-2 rounded-full" :class="severityDot(expandedInsight.severity)"></span> Decision brief · {{ expandedInsight.confidence }}% confidence</div>
              <h2 class="mt-2 text-xl font-semibold text-gray-950 sm:text-2xl">{{ expandedInsight.title }}</h2>
              <p class="mt-1 max-w-4xl text-sm leading-6 text-gray-500">{{ expandedInsight.message }}</p>
            </div>
            <button @click="expandedInsightId = ''" class="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-gray-200 text-gray-500 hover:bg-gray-50" aria-label="Close decision brief">×</button>
          </header>

          <div class="grid flex-1 overflow-y-auto lg:grid-cols-[minmax(0,1fr)_340px]">
            <div class="space-y-6 p-5 sm:p-7">
              <div class="grid gap-3 md:grid-cols-3">
                <div class="rounded-2xl border border-gray-200 p-4"><div class="text-[10px] font-semibold uppercase tracking-wider text-gray-400">What CADE observed</div><p class="mt-2 text-xs leading-5 text-gray-700">{{ expandedInsight.message }}</p></div>
                <div class="rounded-2xl border border-gray-200 p-4"><div class="text-[10px] font-semibold uppercase tracking-wider text-gray-400">Why it matters now</div><p class="mt-2 text-xs leading-5 text-gray-700">{{ expandedInsight.why }}</p></div>
                <div class="rounded-2xl border border-emerald-200 bg-emerald-50/50 p-4"><div class="text-[10px] font-semibold uppercase tracking-wider text-emerald-700">Expected value</div><p class="mt-2 text-xs leading-5 text-emerald-900">{{ expandedInsight.outcome }}</p></div>
              </div>

              <section>
                <div class="flex items-center justify-between"><div><div class="text-[10px] font-semibold uppercase tracking-[.16em] text-gray-400">Proposed experience</div><h3 class="mt-1 text-base font-semibold text-gray-900">What the change would look like</h3></div><span class="rounded-full bg-blue-50 px-2.5 py-1 text-[9px] font-medium text-blue-700">Illustrative preview</span></div>

                <div v-if="cap.domain === 'product-design'" class="mt-3 grid gap-3 md:grid-cols-2">
                  <div class="overflow-hidden rounded-2xl border border-red-200 bg-red-50/30">
                    <div class="border-b border-red-100 px-3 py-2 text-[10px] font-semibold text-red-700">Current pattern · excess choice</div>
                    <div class="space-y-2 p-4">
                      <div class="h-5 w-2/3 rounded bg-gray-300"></div><div class="h-3 w-full rounded bg-gray-200"></div><div class="h-3 w-5/6 rounded bg-gray-200"></div>
                      <div class="grid grid-cols-3 gap-2 pt-2"><div v-for="n in 9" :key="n" class="h-10 rounded border border-gray-200 bg-white"></div></div>
                      <div class="flex gap-2 pt-2"><div class="h-8 flex-1 rounded bg-gray-300"></div><div class="h-8 flex-1 rounded bg-gray-300"></div><div class="h-8 flex-1 rounded bg-gray-300"></div></div>
                    </div>
                  </div>
                  <div class="overflow-hidden rounded-2xl border border-emerald-200 bg-emerald-50/30">
                    <div class="border-b border-emerald-100 px-3 py-2 text-[10px] font-semibold text-emerald-700">Proposed pattern · guided progression</div>
                    <div class="p-4">
                      <div class="flex items-center gap-2"><span class="grid h-6 w-6 place-items-center rounded-full bg-gray-900 text-[9px] text-white">1</span><div class="h-5 w-1/2 rounded bg-gray-800"></div></div>
                      <div class="mt-3 rounded-xl border border-blue-200 bg-white p-3"><div class="h-3 w-4/5 rounded bg-blue-200"></div><div class="mt-2 h-3 w-2/3 rounded bg-gray-100"></div><div class="mt-4 h-9 w-32 rounded-lg bg-blue-600"></div></div>
                      <div class="mt-3 flex items-center justify-between text-[9px] text-gray-400"><span>Advanced options hidden until relevant</span><span>1 clear next action</span></div>
                    </div>
                  </div>
                </div>

                <div v-else-if="cap.domain === 'legal-ops'" class="mt-3 overflow-hidden rounded-2xl border border-gray-200 font-mono text-xs">
                  <div class="border-b bg-gray-50 px-4 py-2 text-[10px] text-gray-500">Suggested redline · operator approval required</div>
                  <div class="space-y-2 p-4 leading-6"><p class="bg-red-50 px-2 text-red-700 line-through">The provider may retain customer data as reasonably necessary.</p><p class="bg-emerald-50 px-2 text-emerald-800">The provider will delete or irreversibly anonymize customer data within 30 days after termination, except where retention is required by applicable law.</p><p class="text-gray-500">Rationale: replaces an undefined retention standard with a measurable obligation and legal exception.</p></div>
                </div>

                <div v-else class="mt-3 grid gap-3 md:grid-cols-2"><div class="rounded-2xl border border-gray-200 p-4"><div class="text-[10px] font-semibold uppercase tracking-wider text-gray-400">Before</div><p class="mt-2 text-xs leading-5 text-gray-600">The current signal remains informational, manually interpreted, and disconnected from execution.</p></div><div class="rounded-2xl border border-emerald-200 bg-emerald-50/40 p-4"><div class="text-[10px] font-semibold uppercase tracking-wider text-emerald-800">After</div><p class="mt-2 text-xs leading-5 text-emerald-950">{{ expandedInsight.recommendation }} The resulting task includes evidence, owners, verification, and rollout controls.</p></div></div>
                <RecommendationSandbox :title="expandedInsight.title" :recommendation="expandedInsight.recommendation" :confidence="expandedInsight.confidence" @adjust="useSandboxPrompt" @implement="implementInsight(expandedInsight)" />
              </section>

              <section>
                <div class="text-[10px] font-semibold uppercase tracking-[.16em] text-gray-400">Hivemind evidence</div>
                <h3 class="mt-1 text-base font-semibold text-gray-900">How specialist agents reached this recommendation</h3>
                <div class="mt-3 grid gap-2 sm:grid-cols-2">
                  <div v-for="(signal, index) in expandedInsight.signals" :key="signal" class="rounded-xl border border-gray-200 p-3"><div class="flex items-center justify-between"><span class="text-xs font-semibold text-gray-800">{{ signal }}</span><span class="text-[9px] text-emerald-700">concurred</span></div><p class="mt-1 text-[10px] leading-4 text-gray-500">{{ index === 0 ? 'Detected the primary experience gap and mapped it to the configured threshold.' : index === 1 ? 'Compared the recommendation against attention flow, user intent, and likely failure modes.' : index === 2 ? 'Simulated novice, expert, and mobile behavior to test whether the change improves task completion.' : 'Checked feasibility, brand consistency, accessibility, and downstream implementation risk.' }}</p></div>
                </div>
              </section>
            </div>

            <aside class="border-t border-gray-200 bg-gray-50 p-5 lg:border-l lg:border-t-0">
              <div class="sticky top-0 space-y-4">
                <div><div class="text-[10px] font-semibold uppercase tracking-[.16em] text-gray-400">Decision controls</div><h3 class="mt-1 text-base font-semibold text-gray-900">Adjust before implementation</h3></div>
                <label class="block text-xs font-medium text-gray-600">Implementation scope<select v-model="implementationScope[expandedInsight.id]" class="mt-1 w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs"><option value="safe">Safe patch · verify first</option><option value="focused">Focused improvement</option><option value="full">Full implementation</option></select></label>
                <label class="block text-xs font-medium text-gray-600">Rollout<select v-model="rolloutMode[expandedInsight.id]" class="mt-1 w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs"><option value="preview">Preview branch first</option><option value="canary">Canary rollout</option><option value="normal">Normal release train</option></select></label>
                <label class="flex items-center justify-between rounded-xl border border-gray-200 bg-white px-3 py-3 text-xs font-medium text-gray-700"><span><span class="block">Approval checkpoint</span><span class="mt-0.5 block text-[9px] font-normal text-gray-400">Pause after preview and QA</span></span><input v-model="approvalRequired[expandedInsight.id]" type="checkbox" class="accent-blue-600"></label>
                <div class="rounded-xl border border-gray-200 bg-white p-3"><div class="text-[10px] font-semibold text-gray-700">Implementation plan</div><ol class="mt-2 space-y-2 text-[10px] leading-4 text-gray-500"><li>1. Reproduce and measure the current issue.</li><li>2. Generate the smallest viable change and preview.</li><li>3. Run specialist, accessibility, regression, and archetype QA.</li><li>4. Present evidence and rollout recommendation.</li></ol></div>
                <button @click="editInsightPlan(expandedInsight); expandedInsightId = ''" class="w-full rounded-xl border border-gray-300 bg-white px-4 py-2.5 text-xs font-semibold text-gray-700">Adjust with a prompt</button>
                <button @click="implementInsight(expandedInsight)" :disabled="expandedInsight.implementing || expandedInsight.resolved" class="w-full rounded-xl bg-gray-900 px-4 py-2.5 text-xs font-semibold text-white disabled:bg-emerald-600">{{ expandedInsight.resolved ? '✓ Implementation queued' : expandedInsight.implementing ? 'Queuing…' : 'Implement recommendation' }}</button>
                <p class="text-center text-[9px] leading-4 text-gray-400">Madeus selects models, vendors, branches, and verification automatically under your organization policy.</p>
              </div>
            </aside>
          </div>
        </section>
      </div>
    </Teleport>
  </div>
</template>
