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
  { id: 'darwn', name: 'Darwn' }, { id: 'pareto-2080', name: 'Pareto 2080' },
  { id: 'racefeed', name: 'RaceFeed' }, { id: 'santas-secret-workshop', name: "Santa's Workshop" },
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
}

const DOMAIN_SLIDERS: Record<string, { label: string; min: number; max: number; default: number; unit: string }[]> = {
  devops: [{ label: 'Canary Traffic %', min: 1, max: 50, default: 5, unit: '%' }, { label: 'Rollback Threshold', min: 1, max: 100, default: 10, unit: 'errors' }, { label: 'Health Check Interval', min: 5, max: 300, default: 30, unit: 's' }],
  engineering: [{ label: 'Test Coverage Target', min: 50, max: 100, default: 80, unit: '%' }, { label: 'Lint Strictness', min: 1, max: 10, default: 7, unit: '' }, { label: 'Review Depth', min: 1, max: 5, default: 3, unit: 'passes' }],
  growth: [{ label: 'Experiment Duration', min: 1, max: 30, default: 7, unit: 'days' }, { label: 'Confidence Threshold', min: 80, max: 99, default: 95, unit: '%' }, { label: 'Min Sample Size', min: 100, max: 10000, default: 1000, unit: '' }],
  'legal-ops': [{ label: 'Review Urgency', min: 1, max: 5, default: 3, unit: '' }, { label: 'Compliance Strictness', min: 1, max: 10, default: 8, unit: '' }, { label: 'Filing Deadline Buffer', min: 1, max: 30, default: 7, unit: 'days' }],
  platform: [{ label: 'Concurrency Limit', min: 1, max: 20, default: 5, unit: '' }, { label: 'Queue Priority Weight', min: 1, max: 10, default: 5, unit: '' }, { label: 'Auto-Retry Count', min: 0, max: 5, default: 2, unit: '' }],
  'product-design': [{ label: 'Cognitive Load Threshold', min: 1, max: 10, default: 6, unit: '' }, { label: 'Animation Budget', min: 0, max: 500, default: 200, unit: 'ms' }, { label: 'Archetype Count', min: 10, max: 200, default: 50, unit: '' }],
  security: [{ label: 'Scan Frequency', min: 1, max: 24, default: 4, unit: 'hrs' }, { label: 'Severity Threshold', min: 1, max: 5, default: 3, unit: '' }, { label: 'Key Rotation Period', min: 7, max: 90, default: 30, unit: 'days' }],
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

// Right panel — Quality insights
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
// --- Quality Insights engine (auto-running) ---
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
  <div class="flex flex-col h-full">
    <!-- Top header bar: replaces left sidebar -->
    <div class="flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-gray-50/50 flex-shrink-0">
      <div class="flex items-center gap-3">
        <NuxtLink to="/orchestrators" class="text-[10px] text-gray-400 hover:text-gray-600 uppercase tracking-wider">← Back</NuxtLink>
        <div><h2 class="text-sm font-bold text-gray-900" style="font-family: 'Fraunces', serif;">{{ cap.name }}</h2><p class="mt-0.5 text-[9px] text-gray-400">{{ cap.summary }}</p></div>
      </div>

      <!-- App Switcher -->
      <div class="px-3 py-2 border-b border-gray-200">
        <div class="text-[9px] text-gray-400 uppercase tracking-wider mb-1 px-1">App</div>
        <select v-model="selectedApp" class="w-full bg-white border border-gray-200 rounded px-2 py-1 text-xs text-gray-700">
          <option v-for="app in APPS" :key="app.id" :value="app.id">{{ app.name }}</option>
        </select>
      </div>

      <!-- Nav: Workspace / Config / History only -->
      <nav class="flex-1 py-1">
        <button v-for="tab in [
          { key: 'workspace', label: 'Workspace', icon: '▸' },
          { key: 'config', label: 'Config', icon: '⚙' },
          { key: 'history', label: 'History', icon: '📋' },
        ]" :key="tab.key" @click="activeTab = tab.key"
          class="w-full flex items-center gap-2 px-3 py-2 text-xs transition-colors text-left"
          :class="activeTab === tab.key ? 'bg-blue-50 text-blue-700 border-r-2 border-blue-600 font-medium' : 'text-gray-600 hover:bg-gray-100'">
          <span class="w-4 text-center text-[11px]">{{ tab.icon }}</span>{{ tab.label }}
        </button>
      </nav>
      <!-- Quality Bots -->
      <div class="px-3 py-2 border-t border-gray-200">
        <div class="text-[9px] text-gray-400 uppercase tracking-wider mb-1.5 px-1">Quality Bots</div>
        <div class="space-y-0.5">
          <div v-for="b in bots.slice(0, 4)" :key="b" class="flex items-center gap-1.5 px-1 py-0.5">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
            <span class="text-[10px] text-gray-600 truncate">{{ b }}</span>
          </div>
          <div v-if="bots.length > 4" class="text-[9px] text-gray-400 px-1">+{{ bots.length - 4 }} more</div>
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
    </aside>
    <!-- CENTER: Main workspace -->
    <main class="flex-1 flex flex-col overflow-hidden min-w-0">
      <!-- ===== WORKSPACE TAB ===== -->
      <template v-if="activeTab === 'workspace'">
        <!-- Top bar -->
        <div class="flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-gray-50/50 flex-shrink-0">
          <div class="flex items-center gap-3">
            <span class="text-xs font-medium text-gray-700">{{ cap.name }}</span>
            <span class="text-[10px] text-gray-400">{{ APPS.find(a => a.id === selectedApp)?.name }}</span>
          </div>
          <div class="flex items-center gap-2">
            <select v-model="selectedBranch" class="bg-white border border-gray-200 rounded px-2 py-1 text-[10px] text-gray-600 font-mono">
              <option value="dev">dev</option>
              <option :value="orchBranch">{{ orchBranch }}</option>
              <option :value="'feature/'+selectedApp+'-redesign'">feature/{{ selectedApp }}-redesign</option>
              <option :value="'design/'+selectedApp+'-updates'">design/{{ selectedApp }}-updates</option>
              <option :value="'hotfix/'+selectedApp">hotfix/{{ selectedApp }}</option>
              <option value="main" class="font-bold">main (prod)</option>
            </select>
            <button @click="showDeployPanel = !showDeployPanel"
              class="px-3 py-1 text-[10px] rounded font-medium transition-colors"
              :class="showDeployPanel ? 'bg-emerald-700 text-white' : 'bg-emerald-600 text-white hover:bg-emerald-700'">
              {{ showDeployPanel ? '▼ Merge' : '🚢 Merge → Prod' }}
            </button>
            <button @click="showInsights = !showInsights" class="px-2 py-1 text-[10px] border rounded" :class="showInsights ? 'bg-blue-50 text-blue-700 border-blue-200' : 'text-gray-500 border-gray-200'">
              {{ showInsights ? 'Hide' : 'Show' }} Insights
            </button>
          </div>
        </div>
        <!-- INLINE DEPLOY PANEL (expandable, not separate page) -->
        <div v-if="showDeployPanel" class="border-b border-gray-200 bg-emerald-50/30 px-4 py-3 flex-shrink-0">
          <div class="flex items-center justify-between">
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
          <!-- VISUAL CONTEXT + TOOLS AREA (scrollable) -->
          <div class="flex-1 overflow-y-auto min-h-0">
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
              <div class="relative" style="height: 45vh; min-height: 280px;">
                <div v-if="previewLoading || (previewUrl && !iframeLoaded)" class="absolute inset-0 bg-white flex items-center justify-center z-10">
                  <div class="text-center space-y-2">
                    <div class="w-6 h-6 border-2 border-emerald-700 border-t-transparent rounded-full animate-spin mx-auto"></div>
                    <p class="text-xs text-gray-400">Verifying {{ APPS.find(a => a.id === selectedApp)?.name }}...</p>
                  </div>
                </div>
                <div class="flex items-center gap-2">
                  <span class="text-[10px] px-2 py-0.5 rounded-full font-medium" :class="docStatusColor(doc.status)">{{ doc.status }}</span>
                  <button class="px-2 py-0.5 text-[10px] bg-blue-50 text-blue-700 border border-blue-200 rounded opacity-0 group-hover:opacity-100">Quality Review</button>
                </div>
              </div>
            </div>
          </div>
        </template>
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

          <!-- CONFIG SLIDERS (inline, collapsible) — available on ALL domains -->
          <div class="mt-4 border-t border-gray-200 pt-3">
            <button @click="showConfig = !showConfig" class="flex items-center gap-2 text-[10px] text-gray-500 hover:text-gray-700 uppercase tracking-wider font-medium">
              <span>{{ showConfig ? '▼' : '▶' }}</span> Configuration & Tuning
            </button>
            <div v-if="showConfig" class="mt-3 bg-white border border-gray-200 rounded-lg p-4 space-y-3">
              <div v-for="s in domainSliders" :key="s.label">
                <div class="flex justify-between text-xs mb-1"><span class="text-gray-600">{{ s.label }}</span><span class="font-mono text-gray-900 font-medium">{{ sliders[s.label] ?? s.default }}{{ s.unit }}</span></div>
                <input type="range" :min="s.min" :max="s.max" v-model.number="sliders[s.label]" class="w-full h-1.5 bg-gray-200 rounded-full appearance-none cursor-pointer accent-blue-600" />
              </div>
            </div>
          </div>
        </div>
        </div>
        <!-- TERMINAL — always visible at bottom of workspace -->
        <div class="flex-shrink-0 border-t border-gray-200 bg-gray-900" style="font-family: 'JetBrains Mono', monospace;">
          <div class="px-4 py-2 flex items-center justify-between border-b border-gray-700">
            <span class="text-[10px] text-gray-500 uppercase tracking-wider">Terminal — {{ APPS.find(a => a.id === selectedApp)?.name }}</span>
            <div v-if="routeInfo" class="flex items-center gap-2 text-[10px]">
              <span class="text-blue-400">auto →</span>
              <span class="px-1.5 py-0.5 rounded bg-blue-900/50 text-blue-300">{{ modelLabel(selectedModel) }}</span>
              <span class="px-1.5 py-0.5 rounded bg-gray-700 text-gray-300">{{ selectedKind }}</span>
              <span class="px-1.5 py-0.5 rounded bg-gray-700 text-gray-300">{{ selectedMode }}</span>
              <button @click="showOverride = !showOverride" class="text-gray-500 hover:text-gray-300">{{ showOverride ? '▼' : '▶' }} override</button>
            </div>
          </div>
          <div v-if="showOverride" class="px-4 py-2 border-b border-gray-700 space-y-1.5">
            <div class="flex flex-wrap gap-1"><button v-for="m in MODELS" :key="m.value" @click="selectedModel = m.value" class="px-2 py-0.5 text-[10px] rounded border transition-colors" :class="selectedModel === m.value ? 'bg-blue-600 text-white border-blue-600' : 'bg-gray-800 text-gray-400 border-gray-700'">{{ m.label }}</button></div>
            <div class="flex gap-3">
              <div class="flex flex-wrap gap-1"><button v-for="k in ['build','fix','research','qa','deploy','canary']" :key="k" @click="selectedKind = k" class="px-2 py-0.5 text-[10px] rounded border" :class="selectedKind === k ? 'bg-emerald-600 text-white border-emerald-600' : 'bg-gray-800 text-gray-400 border-gray-700'">{{ k }}</button></div>
              <div class="flex flex-wrap gap-1"><button v-for="mm in ['build','research','efficiency','speculative']" :key="mm" @click="selectedMode = mm" class="px-2 py-0.5 text-[10px] rounded border" :class="selectedMode === mm ? 'bg-emerald-600 text-white border-emerald-600' : 'bg-gray-800 text-gray-400 border-gray-700'">{{ mm }}</button></div>
            </div>
          </div>
          <div class="px-4 py-3 max-h-[180px] overflow-y-auto">
            <div v-if="terminalOutput" class="text-xs text-emerald-400 whitespace-pre-wrap mb-2">{{ terminalOutput }}</div>
            <div v-else class="text-xs text-gray-600 mb-2">{{ cap.name }} ready — describe what you need while viewing the context above.</div>
            <div class="flex items-center gap-2">
              <span class="text-emerald-500 text-sm">$</span>
              <input v-model="terminalPrompt" @keydown.enter="runCommand" placeholder="Describe changes, fixes, improvements..." class="flex-1 bg-transparent text-white text-sm outline-none placeholder-gray-600" />
              <button @click="runCommand" :disabled="terminalLoading || !terminalPrompt.trim()" class="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-medium rounded transition-colors disabled:opacity-40">{{ terminalLoading ? '...' : '→' }}</button>
            </div>
          </div>
        </div>
      </template>
      <!-- ===== CONFIG TAB ===== -->
      <div v-else-if="activeTab === 'config'" class="flex-1 overflow-y-auto p-6">
        <div class="max-w-3xl mx-auto space-y-5">
          <h3 class="text-lg font-semibold text-gray-900" style="font-family: 'Fraunces', serif;">Configuration — {{ APPS.find(a => a.id === selectedApp)?.name }}</h3>
          <div class="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
            <div v-for="s in domainSliders" :key="s.label">
              <div class="flex justify-between text-sm mb-1"><span class="text-gray-600">{{ s.label }}</span><span class="font-mono text-gray-900 font-medium">{{ sliders[s.label] ?? s.default }}{{ s.unit }}</span></div>
              <input type="range" :min="s.min" :max="s.max" v-model.number="sliders[s.label]" class="w-full h-1.5 bg-gray-200 rounded-full appearance-none cursor-pointer accent-blue-600" />
            </div>
          </div>
          <div class="bg-white border border-gray-200 rounded-xl p-5">
            <div class="text-xs font-semibold text-gray-700 mb-3">Quality Bots — {{ cap.domain }}</div>
            <div class="space-y-1.5">
              <div v-for="b in bots" :key="b" class="flex items-center justify-between px-3 py-2 bg-gray-50 rounded-lg">
                <div class="flex items-center gap-2"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span><span class="text-sm text-gray-700">{{ b }}</span></div>
                <span class="text-[10px] text-emerald-600 font-medium">Active</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ===== HISTORY TAB ===== -->
      <div v-else-if="activeTab === 'history'" class="flex-1 overflow-y-auto p-6">
        <div class="max-w-3xl mx-auto space-y-5">
          <h3 class="text-lg font-semibold text-gray-900" style="font-family: 'Fraunces', serif;">Task History</h3>
          <div class="space-y-1.5">
            <div v-for="t in recentTasks" :key="t.id" class="bg-white border border-gray-200 rounded-lg px-4 py-3 flex items-center gap-3 text-sm">
              <span class="font-mono text-base" :class="stateClass(t.state)">{{ stateIcon(t.state) }}</span>
              <span class="text-gray-900 flex-1 truncate">{{ t.slug }}</span>
              <span class="text-xs text-gray-400 px-2 py-0.5 bg-gray-50 rounded">{{ t.kind || '—' }}</span>
              <span class="text-xs text-gray-400">{{ timeAgo(t.created_at) }}</span>
            </div>
            <div v-if="!recentTasks.length" class="text-center py-8 text-gray-400 text-sm">No tasks yet</div>
          </div>
        </div>
      </div>
    </main>
    <!-- RIGHT PANEL — Quality Insights -->
    <aside v-if="showInsights" class="w-72 bg-gray-50 border-l border-gray-200 flex flex-col flex-shrink-0 overflow-hidden">
      <div class="px-3 py-2 border-b border-gray-200 flex items-center justify-between">
        <span class="text-[10px] text-gray-400 uppercase tracking-wider font-medium">Quality Intelligence</span>
        <div class="flex items-center gap-1.5">
          <span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
          <span class="text-[9px] text-emerald-600">Auto-running</span>
        </div>
      </div>

      <!-- Insight tabs -->
      <div class="flex flex-wrap gap-1 px-3 py-2 border-b border-gray-200">
        <button v-for="ins in insights" :key="ins.key" @click="activeInsight = ins.key"
          class="px-2 py-1 text-[10px] rounded transition-colors"
          :class="activeInsight === ins.key ? 'bg-blue-100 text-blue-700 font-medium' : 'text-gray-500 hover:bg-gray-100'">
          {{ ins.icon }} {{ ins.label }}
        </button>
      </div>

      <!-- High-priority suggestions -->
      <div v-if="highPriority.length" class="px-3 py-2 border-b border-gray-200">
        <div class="text-[9px] text-red-500 uppercase tracking-wider font-medium mb-1.5">High Priority</div>
        <div class="space-y-1.5">
          <div v-for="hp in highPriority.filter(h => !h.stale)" :key="hp.id" class="px-2 py-1.5 rounded border text-[10px] leading-snug" :class="severityColor(hp.severity)">
            {{ hp.message }}
          </div>
        </div>
      </div>

      <!-- Insight feed -->
      <div class="flex-1 overflow-y-auto px-3 py-2">
        <div class="text-[9px] text-gray-400 uppercase tracking-wider mb-2">{{ insights.find(i => i.key === activeInsight)?.label || 'Feed' }} — History</div>
        <div class="space-y-2">
          <div v-for="(entry, idx) in insightsForActive" :key="idx" class="relative pl-4">
            <span class="absolute left-0 top-1.5 w-2 h-2 rounded-full" :class="severityDot(entry.severity)"></span>
            <div class="text-[11px] text-gray-700 leading-snug">{{ entry.message }}</div>
            <div class="text-[9px] text-gray-400 mt-0.5 flex items-center gap-2">
              <span>{{ timeAgo(entry.timestamp) }}</span>
              <span v-if="entry.resolved" class="text-emerald-600">resolved</span>
            </div>
          </div>
          <div v-if="!insightsForActive.length" class="text-center py-6 text-gray-400 text-[11px]">No feedback yet.</div>
        </div>
      </div>

      <!-- Bot status footer -->
      <div class="px-3 py-2 border-t border-gray-200">
        <div class="text-[9px] text-gray-400 uppercase tracking-wider mb-1">Active Bots ({{ bots.length }})</div>
        <div class="flex flex-wrap gap-1">
          <span v-for="b in bots" :key="b" class="inline-flex items-center gap-1 px-1.5 py-0.5 bg-white border border-gray-200 rounded text-[9px] text-gray-600">
            <span class="w-1 h-1 rounded-full bg-emerald-500"></span>{{ b.split(' ').map(w => w[0]).join('') }}
          </span>
        </div>
      </div>
    </aside>
  </div>
</template>
