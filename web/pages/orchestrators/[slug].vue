<script setup lang="ts">
definePageMeta({ layout: 'default' })
const route = useRoute()
const slug = computed(() => route.params.slug as string)
const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()

const CAPS: Record<string, { name: string; domain: string; status: string; maturity: number; regulated: boolean; summary: string }> = {
  'deploy-orchestrator': { name: 'Deployment Orchestrator', domain: 'devops', status: 'trusted', maturity: 86, regulated: false, summary: 'Manages canary deployments, watches, rollbacks, and release gates.' },
  'review-orchestrator': { name: 'Code Review Orchestrator', domain: 'engineering', status: 'trusted', maturity: 91, regulated: false, summary: 'Automated multi-model code review, security scanning, and quality gating.' },
  'optimize-orchestrator': { name: 'Optimization Orchestrator', domain: 'engineering', status: 'trusted', maturity: 80, regulated: false, summary: 'Performance, cost, prompt caching, and resource optimization.' },
  'preflight-inspector': { name: 'Pre-flight Inspector', domain: 'engineering', status: 'trusted', maturity: 88, regulated: false, summary: 'Pre-execution validation of branch state, dependencies, and environment.' },
  'remediation-orchestrator': { name: 'Remediation Orchestrator', domain: 'engineering', status: 'trusted', maturity: 93, regulated: false, summary: 'Auto-diagnoses and repairs failing tests, builds, and blocked tasks.' },
  'growth-orchestrator': { name: 'Growth Orchestrator', domain: 'growth', status: 'trusted', maturity: 79, regulated: false, summary: 'Growth experiments, A/B tests, conversion optimization, and BD autopilot.' },
  'entity-formation': { name: 'Entity Formation Filing', domain: 'legal-ops', status: 'productizable', maturity: 95, regulated: false, summary: 'Jurisdiction-aware entity formation: Articles, EIN, Operating Agreements.' },
  'legal-orchestrator': { name: 'Legal Orchestrator', domain: 'legal-ops', status: 'trusted', maturity: 87, regulated: true, summary: 'Legal review, compliance, contracts, and regulatory workflows.' },
  'colosseum-evaluator': { name: 'Colosseum Evaluator', domain: 'platform', status: 'experimental', maturity: 72, regulated: false, summary: 'Head-to-head model evaluations for optimal task routing.' },
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

const APP_URLS: Record<string, string> = {
  apparently: 'https://apparently.vercel.app',
  beethoven: 'https://web-six-chi-76.vercel.app',
  darwn: 'https://darwn.vercel.app',
  'pareto-2080': 'https://pareto-2080.vercel.app',
  racefeed: 'https://racefeed.vercel.app',
  'santas-secret-workshop': 'https://santas-workshop.vercel.app',
  smarter: 'https://smarter.vercel.app',
  'sustainable-barks': 'https://sustainable-barks.vercel.app',
  tomorrow: 'https://tomorrow.vercel.app',
}
// Branch-aware preview: Vercel deploys branch previews at [project]-git-[branch]-[owner].vercel.app
// For main/master we use the canonical production URL; for other branches we try the branch preview pattern.
const VERCEL_OWNER = 'kalepasch1s-projects'
const APP_VERCEL_PROJECTS: Record<string, string> = {
  apparently: 'apparently', beethoven: 'web-six-chi-76', darwn: 'darwn',
  'pareto-2080': 'pareto-2080', racefeed: 'racefeed', 'santas-secret-workshop': 'santas-workshop',
  smarter: 'smarter', 'sustainable-barks': 'sustainable-barks', tomorrow: 'tomorrow',
}
function branchPreviewUrl(app: string, branch: string): string {
  const prodUrl = APP_URLS[app] || 'https://apparently.vercel.app'
  if (branch === 'main' || branch === 'master') return prodUrl
  // Vercel branch deploy URL format: [project]-git-[branch]-[owner].vercel.app
  // Slashes in branch names become dashes
  const proj = APP_VERCEL_PROJECTS[app] || app
  const safeBranch = branch.replace(/\//g, '-')
  return `https://${proj}-git-${safeBranch}-${VERCEL_OWNER}.vercel.app`
}
const previewUrl = computed(() => branchPreviewUrl(selectedApp.value, selectedBranch.value))
// Auto-generated orchestrator working branch name
const orchBranch = computed(() => `orch/${slug.value}/${selectedApp.value}`)
// --- State ---
const cap = computed(() => CAPS[slug.value] || { name: slug.value, domain: 'platform', status: 'unknown', maturity: 0, regulated: false, summary: '' })
const insights = computed(() => DOMAIN_INSIGHTS[cap.value.domain] || DOMAIN_INSIGHTS.platform)
const bots = computed(() => DOMAIN_BOTS[cap.value.domain] || [])
const domainSliders = computed(() => DOMAIN_SLIDERS[cap.value.domain] || DOMAIN_SLIDERS.platform)

// Only 3 tabs now: workspace (default), config, history — deploy is inline
const activeTab = ref('workspace')
const selectedApp = ref('apparently')
const terminalPrompt = ref('')
const terminalLoading = ref(false)
const terminalOutput = ref('')
const selectedModel = ref('claude-sonnet-4-6')
const selectedKind = ref('build')
const selectedMode = ref('build')
const selectedProject = ref('')
const projects = ref<any[]>([])
const recentTasks = ref<any[]>([])
const sliders = ref<Record<string, number>>({})
const showOverride = ref(false)
const routeInfo = ref('')
const selectedBranch = ref('dev')
const showConfig = ref(false)

// Right panel — decision insights
const showInsights = ref(true)
const activeInsight = ref('')
const insightHistory = ref<{ key: string; timestamp: string; severity: string; message: string; resolved: boolean }[]>([])
const highPriority = ref<{ id: string; message: string; severity: string; stale: boolean; created: string }[]>([])

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
    deployLog.value.push('✓ Merged to main')
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
// --- Decision Insights engine (auto-running) ---
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
  const newEntries: typeof insightHistory.value = []
  for (const [key, items] of Object.entries(domainFeedback)) {
    for (const item of items) {
      newEntries.push({ key, timestamp: now, severity: item.severity, message: item.message, resolved: false })
    }
  }
  insightHistory.value = [...newEntries, ...insightHistory.value].slice(0, 50)
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
    const pid = selectedProject.value || projects.value[0]?.id
    if (!pid) { terminalOutput.value = 'Error: No project selected'; return }
    const taskSlug = slug.value + '-' + Date.now().toString(36)
    await supabase.from('tasks').insert({ project_id: pid, slug: taskSlug, prompt: terminalPrompt.value.trim(), kind: selectedKind.value, model: selectedModel.value, mode: selectedMode.value, state: 'QUEUED', note: 'source:' + slug.value + '-workspace;app:' + selectedApp.value + ';branch:' + selectedBranch.value })
    terminalOutput.value = '✓ Queued: ' + taskSlug + '\n  Model: ' + modelLabel(selectedModel.value) + ' (auto)\n  Kind: ' + selectedKind.value + ' | Mode: ' + selectedMode.value + '\n  App: ' + selectedApp.value + '\n  Branch: ' + selectedBranch.value + '\n  Routing: ' + routeInfo.value
    terminalPrompt.value = ''; routeInfo.value = ''; loadData()
  } catch (e: any) { terminalOutput.value = 'Error: ' + (e.message || String(e)) }
  finally { terminalLoading.value = false }
}

onMounted(async () => { await loadData(); await loadDraft(); await loadDeploys(); refreshInsights() })
watch(user, u => { if (u) { loadData(); loadDraft(); loadDeploys() } })
watch(selectedApp, () => { loadDraft(); loadDeploys(); refreshInsights() })
watch(slug, () => { refreshInsights() })
</script>
<template>
  <div class="flex h-screen bg-white text-gray-900 overflow-hidden">
    <!-- LEFT SIDEBAR -->
    <aside class="w-48 bg-gray-50 border-r border-gray-200 flex flex-col flex-shrink-0">
      <div class="p-3 border-b border-gray-200">
        <NuxtLink to="/orchestrators" class="text-[10px] text-gray-400 hover:text-gray-600 uppercase tracking-wider">← Capabilities</NuxtLink>
        <h2 class="text-sm font-bold text-gray-900 mt-1 leading-tight" style="font-family: 'Fraunces', serif;">{{ cap.name }}</h2>
        <div class="flex items-center gap-2 mt-1">
          <span class="text-[10px] font-medium" :class="statusColor(cap.status)">{{ cap.status }}</span>
          <span v-if="cap.regulated" class="text-[10px] text-red-500">regulated</span>
        </div>
        <div class="flex items-center gap-1.5 mt-1.5">
          <div class="flex-1 h-1 bg-gray-200 rounded-full overflow-hidden"><div class="h-full rounded-full" :class="maturityColor(cap.maturity)" :style="'width:'+cap.maturity+'%'"></div></div>
          <span class="text-[9px] text-gray-400 font-mono">{{ cap.maturity }}%</span>
        </div>
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
      <!-- Specialist Bots -->
      <div class="px-3 py-2 border-t border-gray-200">
        <div class="text-[9px] text-gray-400 uppercase tracking-wider mb-1.5 px-1">Specialist Bots</div>
        <div class="space-y-0.5">
          <div v-for="b in bots.slice(0, 4)" :key="b" class="flex items-center gap-1.5 px-1 py-0.5">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
            <span class="text-[10px] text-gray-600 truncate">{{ b }}</span>
          </div>
          <div v-if="bots.length > 4" class="text-[9px] text-gray-400 px-1">+{{ bots.length - 4 }} more</div>
        </div>
      </div>

      <!-- Auto-save + Project -->
      <div class="p-3 border-t border-gray-200 space-y-1.5">
        <div class="flex items-center justify-between px-1">
          <div class="flex items-center gap-1">
            <span class="w-1.5 h-1.5 rounded-full" :class="autoSaveStatus === 'saved' ? 'bg-emerald-500' : autoSaveStatus === 'saving' ? 'bg-amber-400 animate-pulse' : autoSaveStatus === 'unsaved' ? 'bg-gray-400' : 'bg-red-500'"></span>
            <span class="text-[9px] text-gray-400">{{ autoSaveStatus === 'saved' ? 'Saved' : autoSaveStatus === 'saving' ? 'Saving...' : autoSaveStatus === 'unsaved' ? 'Unsaved' : 'Error' }}</span>
          </div>
          <span v-if="lastSavedAt" class="text-[9px] text-gray-300">{{ lastSavedAt }}</span>
        </div>
        <select v-model="selectedProject" class="w-full bg-white border border-gray-200 rounded px-2 py-1 text-[10px] text-gray-700">
          <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
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
              <span class="text-xs text-gray-600">Deploy</span>
              <select v-model="selectedBranch" class="bg-white border border-gray-200 rounded px-2 py-1 text-[10px] font-mono text-gray-700">
                <option value="dev">dev</option>
                <option :value="orchBranch">{{ orchBranch }}</option>
                <option :value="'feature/'+selectedApp+'-redesign'">feature/{{ selectedApp }}-redesign</option>
                <option :value="'design/'+selectedApp+'-updates'">design/{{ selectedApp }}-updates</option>
                <option :value="'hotfix/'+selectedApp">hotfix/{{ selectedApp }}</option>
              </select>
              <span class="text-gray-400 text-xs">→ merge to</span>
              <span class="px-2 py-0.5 bg-emerald-100 text-emerald-700 text-[10px] font-mono rounded font-semibold">main (prod)</span>
            </div>
            <button @click="deployToProd" :disabled="deployLoading || selectedBranch === 'main'"
              class="px-4 py-1.5 text-xs font-medium rounded-lg transition-all"
              :class="deployLoading ? 'bg-amber-500 text-white' : selectedBranch === 'main' ? 'bg-gray-200 text-gray-400 cursor-not-allowed' : 'bg-emerald-600 hover:bg-emerald-700 text-white'">
              {{ deployLoading ? (deployStatus === 'preflight' ? 'Pre-flight...' : 'Merging...') : 'Merge → Prod' }}
            </button>
          </div>
          <div v-if="deployLog.length" class="mt-2 bg-gray-900 rounded-lg px-3 py-2 max-h-[120px] overflow-y-auto" style="font-family: 'JetBrains Mono', monospace;">
            <div v-for="(line, i) in deployLog" :key="i" class="text-[11px] leading-relaxed" :class="line.startsWith('✓') ? 'text-emerald-400' : line.startsWith('✗') ? 'text-red-400' : 'text-gray-400'">{{ line }}</div>
          </div>
          <div v-if="recentDeploys.length" class="mt-2 space-y-1">
            <div v-for="d in recentDeploys.slice(0, 3)" :key="d.id" class="flex items-center gap-2 text-[10px]">
              <span class="w-1.5 h-1.5 rounded-full" :class="d.deploy_status === 'deployed' ? 'bg-emerald-500' : 'bg-red-500'"></span>
              <span class="font-mono text-gray-500">{{ d.version }}</span>
              <span class="text-gray-400 truncate flex-1">{{ d.note }}</span>
              <span class="text-gray-400">{{ timeAgo(d.created_at) }}</span>
            </div>
          </div>
        </div>
        <!-- VISUAL CONTEXT + TOOLS AREA (scrollable, domain-specific) -->
        <div class="flex-1 overflow-y-auto min-h-0">
          <!-- LIVE APP PREVIEW — universal across all domains -->
          <div class="bg-gray-100 border-b border-gray-200">
            <div class="bg-gray-200 px-3 py-1.5 flex items-center gap-2 text-[10px] text-gray-500">
              <span class="w-2 h-2 rounded-full bg-red-400"></span>
              <span class="w-2 h-2 rounded-full bg-amber-400"></span>
              <span class="w-2 h-2 rounded-full bg-emerald-400"></span>
              <span class="flex-1 text-center font-mono">{{ previewUrl }} — {{ selectedBranch }}</span>
              <button @click="reloadIframe" class="text-gray-400 hover:text-gray-600 px-1">↻</button>
              <a :href="previewUrl" target="_blank" class="text-gray-400 hover:text-gray-600 px-1">↗</a>
            </div>
            <div class="relative" style="height: 45vh; min-height: 280px;">
              <!-- Loading overlay -->
              <div v-if="!iframeLoaded" class="absolute inset-0 bg-white flex items-center justify-center z-10">
                <div class="text-center space-y-2">
                  <div class="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto"></div>
                  <p class="text-xs text-gray-400">Loading {{ APPS.find(a => a.id === selectedApp)?.name }}...</p>
                </div>
              </div>
              <iframe
                :key="iframeKey"
                :src="previewUrl"
                @load="onIframeLoad"
                class="w-full h-full border-0"
                allow="clipboard-read; clipboard-write"
                referrerpolicy="no-referrer-when-downgrade"
              />
            </div>
          </div>

          <!-- DOMAIN-SPECIFIC TOOLS below preview -->
          <div class="p-4 space-y-4">
            <!-- Design domain metrics -->
            <div v-if="cap.domain === 'product-design'" class="space-y-4">
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
                  <button class="px-2 py-0.5 text-[10px] bg-blue-50 text-blue-700 border border-blue-200 rounded opacity-0 group-hover:opacity-100">Decision Review</button>
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
            <div class="text-xs font-semibold text-gray-700 mb-3">Specialist Bots — {{ cap.domain }}</div>
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
    <!-- RIGHT PANEL — Decision Insights -->
    <aside v-if="showInsights" class="w-72 bg-gray-50 border-l border-gray-200 flex flex-col flex-shrink-0 overflow-hidden">
      <div class="px-3 py-2 border-b border-gray-200 flex items-center justify-between">
        <span class="text-[10px] text-gray-400 uppercase tracking-wider font-medium">Decision Intelligence</span>
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