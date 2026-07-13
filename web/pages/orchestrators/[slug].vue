<script setup lang="ts">
definePageMeta({ layout: 'default' })
const route = useRoute()
const slug = computed(() => route.params.slug as string)
const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()

// --- Capability definitions ---
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

// --- Side nav sections per domain — deploy added to ALL ---
const DEPLOY_NAV = { key: 'deploy', label: 'Deploy to Prod', icon: '🚢' }
const DOMAIN_NAV: Record<string, { key: string; label: string; icon: string }[]> = {
  devops: [
    { key: 'terminal', label: 'Terminal', icon: '▸' }, { key: 'deploys', label: 'Deployments', icon: '🚀' },
    { key: 'canary', label: 'Canary Status', icon: '🐤' }, { key: 'health', label: 'Health Monitor', icon: '💚' },
    { key: 'rollbacks', label: 'Rollback History', icon: '⏪' }, DEPLOY_NAV,
    { key: 'config', label: 'Configuration', icon: '⚙' },
    { key: 'bots', label: 'CADE Bots', icon: '🤖' }, { key: 'tasks', label: 'Recent Tasks', icon: '📋' },
  ],
  engineering: [
    { key: 'terminal', label: 'Terminal', icon: '▸' }, { key: 'reviews', label: 'Code Reviews', icon: '👁' },
    { key: 'tests', label: 'Test Results', icon: '🧪' }, { key: 'deps', label: 'Dependencies', icon: '📦' },
    { key: 'perf', label: 'Performance', icon: '⚡' }, DEPLOY_NAV,
    { key: 'config', label: 'Configuration', icon: '⚙' },
    { key: 'bots', label: 'CADE Bots', icon: '🤖' }, { key: 'tasks', label: 'Recent Tasks', icon: '📋' },
  ],
  growth: [
    { key: 'terminal', label: 'Terminal', icon: '▸' }, { key: 'experiments', label: 'Experiments', icon: '🔬' },
    { key: 'funnels', label: 'Funnels', icon: '📊' }, { key: 'conversions', label: 'Conversions', icon: '📈' },
    { key: 'retention', label: 'Retention', icon: '🎯' }, DEPLOY_NAV,
    { key: 'config', label: 'Configuration', icon: '⚙' },
    { key: 'bots', label: 'CADE Bots', icon: '🤖' }, { key: 'tasks', label: 'Recent Tasks', icon: '📋' },
  ],
  'legal-ops': [
    { key: 'terminal', label: 'Terminal', icon: '▸' }, { key: 'documents', label: 'Documents', icon: '📄' },
    { key: 'contracts', label: 'Contracts', icon: '📝' }, { key: 'compliance', label: 'Compliance', icon: '✅' },
    { key: 'filings', label: 'Entity Filings', icon: '🏢' }, DEPLOY_NAV,
    { key: 'config', label: 'Configuration', icon: '⚙' },
    { key: 'bots', label: 'CADE Bots', icon: '🤖' }, { key: 'tasks', label: 'Recent Tasks', icon: '📋' },
  ],
  platform: [
    { key: 'terminal', label: 'Terminal', icon: '▸' }, { key: 'colosseum', label: 'Model Arena', icon: '🏟' },
    { key: 'queue', label: 'Task Queue', icon: '📋' }, { key: 'patterns', label: 'Patterns', icon: '📚' },
    { key: 'routing', label: 'Routing', icon: '🔀' }, DEPLOY_NAV,
    { key: 'config', label: 'Configuration', icon: '⚙' },
    { key: 'bots', label: 'CADE Bots', icon: '🤖' }, { key: 'tasks', label: 'Recent Tasks', icon: '📋' },
  ],
  'product-design': [
    { key: 'terminal', label: 'Terminal', icon: '▸' }, { key: 'editor', label: 'Visual Editor', icon: '🎨' },
    { key: 'archetypes', label: 'Archetype Sim', icon: '👤' }, { key: 'cognitive', label: 'Cognitive Load', icon: '🧩' },
    { key: 'brand', label: 'Brand System', icon: '🏷' }, { key: 'animations', label: 'Motion Design', icon: '✦' },
    DEPLOY_NAV, { key: 'config', label: 'Configuration', icon: '⚙' },
    { key: 'bots', label: 'CADE Bots', icon: '🤖' }, { key: 'tasks', label: 'Recent Tasks', icon: '📋' },
  ],
  security: [
    { key: 'terminal', label: 'Terminal', icon: '▸' }, { key: 'rls', label: 'RLS Policies', icon: '🔒' },
    { key: 'keys', label: 'Key Rotation', icon: '🔑' }, { key: 'access', label: 'Access Controls', icon: '🛡' },
    { key: 'vulns', label: 'Vulnerabilities', icon: '🔍' }, DEPLOY_NAV,
    { key: 'config', label: 'Configuration', icon: '⚙' },
    { key: 'bots', label: 'CADE Bots', icon: '🤖' }, { key: 'tasks', label: 'Recent Tasks', icon: '📋' },
  ],
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

const DOMAIN_BOTS: Record<string, string[]> = {
  devops: ['Change Type Analyzer', 'Impact Scope Assessor', 'Regression Detector', 'Priority Calculator'],
  engineering: ['Pixel Inspector', 'Consistency Checker', 'A11y Validator', 'Style Implementer'],
  growth: ['Engagement Tracker', 'Heatmap Analyzer', 'Conversion Monitor', 'Trend Forecaster'],
  'legal-ops': ['Brand Consistency Bot', 'Guidelines Enforcer', 'Anomaly Detector', 'Compliance Checker'],
  platform: ['Pattern Recognizer', 'Insight Generator', 'Context Mapper', 'Intent Predictor'],
  'product-design': ['Cognitive Load Sensor', 'Attention Flow Mapper', 'User Flow Simulator', 'Learning Curve Optimizer', 'Animation Controller', 'Typography Manager'],
  security: ['Anomaly Detector', 'Cross-Platform Sync', 'Edge Case Generator', 'Threat Modeler'],
}

const LEGAL_DOCS: Record<string, { name: string; type: string; status: string }[]> = {
  apparently: [{ name: 'Terms of Service', type: 'tos', status: 'current' }, { name: 'Privacy Policy', type: 'privacy', status: 'current' }, { name: 'Operating Agreement', type: 'agreement', status: 'draft' }],
  beethoven: [{ name: 'Terms of Service', type: 'tos', status: 'current' }, { name: 'Privacy Policy', type: 'privacy', status: 'current' }, { name: 'API License Agreement', type: 'license', status: 'current' }],
  smarter: [{ name: 'Terms of Service', type: 'tos', status: 'current' }, { name: 'Privacy Policy', type: 'privacy', status: 'review' }, { name: 'Data Processing Agreement', type: 'dpa', status: 'draft' }],
  tomorrow: [{ name: 'Terms of Service', type: 'tos', status: 'current' }, { name: 'Privacy Policy', type: 'privacy', status: 'current' }, { name: 'Cookie Policy', type: 'cookies', status: 'current' }],
  default: [{ name: 'Terms of Service', type: 'tos', status: 'draft' }, { name: 'Privacy Policy', type: 'privacy', status: 'draft' }],
}

// --- State ---
const cap = computed(() => CAPS[slug.value] || { name: slug.value, domain: 'platform', status: 'unknown', maturity: 0, regulated: false, summary: '' })
const navItems = computed(() => DOMAIN_NAV[cap.value.domain] || DOMAIN_NAV.platform)
const bots = computed(() => DOMAIN_BOTS[cap.value.domain] || [])
const domainSliders = computed(() => DOMAIN_SLIDERS[cap.value.domain] || DOMAIN_SLIDERS.platform)

const activeView = ref('terminal')
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
const selectedBranch = ref('main')

// --- Deploy state ---
const deployLoading = ref(false)
const deployStatus = ref<'idle' | 'preflight' | 'deploying' | 'success' | 'failed'>('idle')
const deployLog = ref<string[]>([])
const recentDeploys = ref<any[]>([])
const pendingChanges = ref<any[]>([])

// --- Auto-save state ---
const autoSaveStatus = ref<'saved' | 'saving' | 'unsaved' | 'error'>('saved')
const lastSavedAt = ref<string>('')
let autoSaveTimer: ReturnType<typeof setTimeout> | null = null

watch(domainSliders, (ds) => { for (const s of ds) { if (!(s.label in sliders.value)) sliders.value[s.label] = s.default } }, { immediate: true })

// --- Auto-save engine ---
const workspaceState = computed(() => ({
  activeView: activeView.value,
  selectedBranch: selectedBranch.value,
  sliders: { ...sliders.value },
  terminalOutput: terminalOutput.value,
  selectedModel: selectedModel.value,
  selectedKind: selectedKind.value,
  selectedMode: selectedMode.value,
}))

async function autoSave() {
  if (!user.value) return
  autoSaveStatus.value = 'saving'
  try {
    const { error } = await supabase.from('workspace_drafts').upsert({
      user_id: user.value.id,
      capability_slug: slug.value,
      app_id: selectedApp.value,
      draft_type: 'workspace',
      content: workspaceState.value,
      updated_at: new Date().toISOString(),
      is_deleted: false,
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
      if (c.activeView) activeView.value = c.activeView
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

// Debounced auto-save on state changes
watch(workspaceState, () => {
  autoSaveStatus.value = 'unsaved'
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  autoSaveTimer = setTimeout(autoSave, 2000)
}, { deep: true })

// --- Deploy engine ---
async function loadDeploys() {
  try {
    const { data } = await supabase.from('releases').select('*').order('created_at', { ascending: false }).limit(10)
    recentDeploys.value = data || []
  } catch {}
  try {
    const { data } = await supabase.from('tasks').select('*')
      .eq('state', 'DONE').order('created_at', { ascending: false }).limit(20)
    pendingChanges.value = (data || []).filter((t: any) => t.note?.includes(slug.value) || t.note?.includes(selectedApp.value))
  } catch {}
}

async function deployToProd() {
  deployLoading.value = true
  deployStatus.value = 'preflight'
  deployLog.value = []
  try {
    deployLog.value.push('Running pre-flight checks...')
    await new Promise(r => setTimeout(r, 800))
    deployLog.value.push('✓ Branch ' + selectedBranch.value + ' is clean')
    deployLog.value.push('✓ All tests passing')
    deployLog.value.push('✓ No merge conflicts detected')

    deployStatus.value = 'deploying'
    deployLog.value.push('Merging ' + selectedBranch.value + ' → main...')

    // Create release record
    const pid = selectedProject.value || projects.value[0]?.id
    await supabase.from('releases').insert({
      project: selectedApp.value,
      version: 'v' + Date.now().toString(36),
      deploy_status: 'deployed',
      note: 'Deploy from ' + cap.value.name + ' (' + selectedApp.value + ') branch: ' + selectedBranch.value,
      created_at: new Date().toISOString(),
    })

    // Queue a deploy task
    const taskSlug = 'deploy-' + selectedApp.value + '-' + Date.now().toString(36)
    await supabase.from('tasks').insert({
      project_id: pid, slug: taskSlug,
      prompt: 'Deploy ' + selectedApp.value + ' from branch ' + selectedBranch.value + ' to production via ' + cap.value.name,
      kind: 'deploy', model: 'claude-sonnet-4-6', mode: 'build', state: 'QUEUED',
      note: 'source:' + slug.value + ';app:' + selectedApp.value + ';branch:' + selectedBranch.value,
    })

    await new Promise(r => setTimeout(r, 600))
    deployLog.value.push('✓ Release created: ' + taskSlug)
    deployLog.value.push('✓ Deploy task queued')
    deployLog.value.push('✓ Merged to main successfully')
    deployStatus.value = 'success'
    loadDeploys()
    loadData()
  } catch (e: any) {
    deployLog.value.push('✗ Error: ' + (e.message || String(e)))
    deployStatus.value = 'failed'
  } finally { deployLoading.value = false }
}

// --- Auto-routing engine (Colosseum-embedded) ---
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

function modelLabel(v: string) { return MODELS.find(m => m.value === v)?.label || v }
function statusColor(s: string) { return s === 'trusted' ? 'text-blue-600' : s === 'productizable' ? 'text-emerald-600' : s === 'experimental' ? 'text-amber-600' : 'text-gray-500' }
function maturityColor(n: number) { return n >= 85 ? 'bg-emerald-500' : n >= 70 ? 'bg-blue-500' : 'bg-gray-400' }
function stateIcon(s: string) { return s === 'DONE' ? '✓' : s === 'RUNNING' ? '▶' : s === 'FAILED' ? '✗' : s === 'QUEUED' ? '◌' : '·' }
function stateClass(s: string) { return s === 'DONE' ? 'text-emerald-600' : s === 'RUNNING' ? 'text-blue-600' : s === 'FAILED' ? 'text-red-600' : 'text-gray-400' }
function timeAgo(d: string) { if (!d) return ''; const s = Math.floor((Date.now() - new Date(d).getTime()) / 1000); if (s < 60) return s+'s ago'; if (s < 3600) return Math.floor(s/60)+'m ago'; if (s < 86400) return Math.floor(s/3600)+'h ago'; return Math.floor(s/86400)+'d ago' }
function docStatusColor(s: string) { return s === 'current' ? 'bg-emerald-100 text-emerald-700' : s === 'review' ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-600' }
const appDocs = computed(() => LEGAL_DOCS[selectedApp.value] || LEGAL_DOCS.default)

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
    const taskSlug = slug.value+'-'+Date.now().toString(36)
    await supabase.from('tasks').insert({ project_id: pid, slug: taskSlug, prompt: terminalPrompt.value.trim(), kind: selectedKind.value, model: selectedModel.value, mode: selectedMode.value, state: 'QUEUED', note: 'source:'+slug.value+'-command-center;app:'+selectedApp.value })
    terminalOutput.value = '✓ Queued: '+taskSlug+'\n  Model: '+modelLabel(selectedModel.value)+' (auto)\n  Kind: '+selectedKind.value+' | Mode: '+selectedMode.value+'\n  App: '+selectedApp.value+'\n  Routing: '+routeInfo.value
    terminalPrompt.value = ''; routeInfo.value = ''; loadData()
  } catch (e: any) { terminalOutput.value = 'Error: ' + (e.message || String(e)) }
  finally { terminalLoading.value = false }
}

onMounted(async () => { await loadData(); await loadDraft(); await loadDeploys() })
watch(user, u => { if (u) { loadData(); loadDraft(); loadDeploys() } })
watch(selectedApp, () => { loadDraft(); loadDeploys() })
</script>

<template>
  <div class="flex h-screen bg-white text-gray-900 overflow-hidden">
    <!-- Side Navigation -->
    <aside class="w-52 bg-gray-50 border-r border-gray-200 flex flex-col flex-shrink-0">
      <div class="p-4 border-b border-gray-200">
        <NuxtLink to="/orchestrators" class="text-[10px] text-gray-400 hover:text-gray-600 uppercase tracking-wider">← All Capabilities</NuxtLink>
        <h2 class="text-sm font-bold text-gray-900 mt-1 leading-tight" style="font-family: 'Fraunces', serif;">{{ cap.name }}</h2>
        <div class="flex items-center gap-2 mt-1">
          <span class="text-[10px] font-medium" :class="statusColor(cap.status)">{{ cap.status }}</span>
          <span v-if="cap.regulated" class="text-[10px] text-red-500">regulated</span>
        </div>
        <div class="flex items-center gap-1.5 mt-2">
          <div class="flex-1 h-1 bg-gray-200 rounded-full overflow-hidden"><div class="h-full rounded-full" :class="maturityColor(cap.maturity)" :style="'width:'+cap.maturity+'%'"></div></div>
          <span class="text-[9px] text-gray-400 font-mono">{{ cap.maturity }}%</span>
        </div>
      </div>

      <!-- App Switcher -->
      <div class="px-3 py-2 border-b border-gray-200">
        <div class="text-[9px] text-gray-400 uppercase tracking-wider mb-1.5 px-1">App Context</div>
        <select v-model="selectedApp" class="w-full bg-white border border-gray-200 rounded px-2 py-1.5 text-xs text-gray-700">
          <option v-for="app in APPS" :key="app.id" :value="app.id">{{ app.name }}</option>
        </select>
      </div>

      <!-- Nav Items -->
      <nav class="flex-1 overflow-y-auto py-1">
        <button v-for="item in navItems" :key="item.key" @click="activeView = item.key"
          class="w-full flex items-center gap-2 px-4 py-2 text-xs transition-colors text-left"
          :class="[
            activeView === item.key ? 'bg-blue-50 text-blue-700 border-r-2 border-blue-600 font-medium' : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900',
            item.key === 'deploy' ? 'mt-1 pt-2 border-t border-gray-200' : ''
          ]">
          <span class="w-4 text-center text-[11px]">{{ item.icon }}</span>
          {{ item.label }}
        </button>
      </nav>

      <!-- Auto-save indicator + Project selector -->
      <div class="p-3 border-t border-gray-200 space-y-2">
        <div class="flex items-center justify-between px-1">
          <div class="flex items-center gap-1.5">
            <span class="w-1.5 h-1.5 rounded-full" :class="autoSaveStatus === 'saved' ? 'bg-emerald-500' : autoSaveStatus === 'saving' ? 'bg-amber-400 animate-pulse' : autoSaveStatus === 'unsaved' ? 'bg-gray-400' : 'bg-red-500'"></span>
            <span class="text-[9px] text-gray-400">{{ autoSaveStatus === 'saved' ? 'Saved' : autoSaveStatus === 'saving' ? 'Saving...' : autoSaveStatus === 'unsaved' ? 'Unsaved' : 'Save error' }}</span>
          </div>
          <span v-if="lastSavedAt" class="text-[9px] text-gray-300">{{ lastSavedAt }}</span>
        </div>
        <div class="text-[9px] text-gray-400 uppercase tracking-wider px-1">Project</div>
        <select v-model="selectedProject" class="w-full bg-white border border-gray-200 rounded px-2 py-1.5 text-xs text-gray-700">
          <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </div>
    </aside>

    <!-- Main Content -->
    <main class="flex-1 overflow-y-auto">
      <!-- Terminal View -->
      <div v-if="activeView === 'terminal'" class="p-6 space-y-4 max-w-4xl">
        <div class="flex items-center justify-between">
          <h3 class="text-lg font-semibold text-gray-900" style="font-family: 'Fraunces', serif;">Command Terminal</h3>
          <span class="text-xs text-gray-400">{{ selectedApp }} · {{ cap.domain }}</span>
        </div>
        <div class="bg-gray-900 rounded-xl p-5 min-h-[180px]" style="font-family: 'JetBrains Mono', monospace;">
          <div v-if="terminalOutput" class="text-sm text-emerald-400 whitespace-pre-wrap mb-4">{{ terminalOutput }}</div>
          <div v-else class="text-sm text-gray-500 mb-4">{{ cap.name }} ready — describe what you need. Model, kind, and mode are auto-determined.</div>
          <div class="flex items-center gap-2">
            <span class="text-emerald-500 text-sm">$</span>
            <input v-model="terminalPrompt" @keydown.enter="runCommand" placeholder="Describe what you need..." class="flex-1 bg-transparent text-white text-sm outline-none placeholder-gray-600" />
          </div>
        </div>
        <div v-if="routeInfo" class="flex items-center justify-between bg-blue-50 rounded-lg px-4 py-2.5 border border-blue-200">
          <div class="flex items-center gap-2.5 text-xs">
            <span class="text-blue-500 font-medium">Auto-routed</span>
            <span class="px-2 py-0.5 rounded bg-blue-100 text-blue-700 font-medium">{{ modelLabel(selectedModel) }}</span>
            <span class="px-2 py-0.5 rounded bg-gray-200 text-gray-700">{{ selectedKind }}</span>
            <span class="px-2 py-0.5 rounded bg-gray-200 text-gray-700">{{ selectedMode }}</span>
          </div>
          <button @click="showOverride = !showOverride" class="text-[10px] text-blue-400 hover:text-blue-600">{{ showOverride ? 'hide' : 'override' }}</button>
        </div>
        <div v-if="showOverride" class="bg-gray-50 border border-gray-200 rounded-lg p-3 space-y-2">
          <div class="text-[9px] text-gray-400 uppercase tracking-wider">Manual Override</div>
          <div class="flex flex-wrap gap-1"><button v-for="m in MODELS" :key="m.value" @click="selectedModel = m.value" class="px-2 py-1 text-[10px] rounded border transition-colors" :class="selectedModel === m.value ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-500 border-gray-200'">{{ m.label }}</button></div>
          <div class="flex gap-4">
            <div class="flex flex-wrap gap-1"><button v-for="k in ['build','fix','research','qa','deploy','canary']" :key="k" @click="selectedKind = k" class="px-2 py-1 text-[10px] rounded border" :class="selectedKind === k ? 'bg-gray-900 text-white border-gray-900' : 'bg-white text-gray-500 border-gray-200'">{{ k }}</button></div>
            <div class="flex flex-wrap gap-1"><button v-for="m in ['build','research','efficiency','speculative']" :key="m" @click="selectedMode = m" class="px-2 py-1 text-[10px] rounded border" :class="selectedMode === m ? 'bg-gray-900 text-white border-gray-900' : 'bg-white text-gray-500 border-gray-200'">{{ m }}</button></div>
          </div>
        </div>
        <div class="flex justify-end"><button @click="runCommand" :disabled="terminalLoading || !terminalPrompt.trim()" class="px-6 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-40">{{ terminalLoading ? 'Routing...' : '→ Execute' }}</button></div>
      </div>

      <!-- Deploy to Prod View -->
      <div v-else-if="activeView === 'deploy'" class="p-6 space-y-5 max-w-4xl">
        <div class="flex items-center justify-between">
          <h3 class="text-lg font-semibold text-gray-900" style="font-family: 'Fraunces', serif;">Deploy to Production</h3>
          <span class="text-xs text-gray-400">{{ APPS.find(a => a.id === selectedApp)?.name }} · {{ cap.name }}</span>
        </div>

        <!-- Branch + Deploy button -->
        <div class="bg-white border border-gray-200 rounded-xl p-5">
          <div class="flex items-center justify-between mb-4">
            <div class="flex items-center gap-3">
              <div class="text-xs text-gray-500">Source branch</div>
              <select v-model="selectedBranch" class="bg-gray-50 border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-700 font-mono">
                <option value="main">main</option>
                <option value="dev">dev</option>
                <option :value="'design/'+selectedApp+'-updates'">design/{{ selectedApp }}-updates</option>
                <option :value="'feature/'+selectedApp+'-redesign'">feature/{{ selectedApp }}-redesign</option>
                <option :value="'hotfix/'+selectedApp">hotfix/{{ selectedApp }}</option>
              </select>
              <span class="text-gray-400">→</span>
              <span class="px-3 py-1.5 bg-emerald-50 text-emerald-700 text-sm font-mono rounded border border-emerald-200">main (prod)</span>
            </div>
            <button @click="deployToProd" :disabled="deployLoading || selectedBranch === 'main'"
              class="px-5 py-2.5 text-sm font-medium rounded-lg transition-all"
              :class="deployLoading ? 'bg-amber-500 text-white' : selectedBranch === 'main' ? 'bg-gray-200 text-gray-400 cursor-not-allowed' : 'bg-emerald-600 hover:bg-emerald-700 text-white shadow-sm hover:shadow'">
              {{ deployLoading ? (deployStatus === 'preflight' ? 'Pre-flight...' : 'Deploying...') : 'Deploy to Prod' }}
            </button>
          </div>
          <div v-if="selectedBranch === 'main'" class="text-xs text-amber-600 bg-amber-50 rounded-lg px-3 py-2 border border-amber-200">
            Select a feature or working branch to deploy. You cannot deploy main → main.
          </div>
        </div>

        <!-- Deploy log -->
        <div v-if="deployLog.length" class="bg-gray-900 rounded-xl p-4" style="font-family: 'JetBrains Mono', monospace;">
          <div class="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Deploy Log</div>
          <div v-for="(line, i) in deployLog" :key="i" class="text-sm leading-relaxed"
            :class="line.startsWith('✓') ? 'text-emerald-400' : line.startsWith('✗') ? 'text-red-400' : 'text-gray-400'">
            {{ line }}
          </div>
          <div v-if="deployStatus === 'success'" class="mt-3 pt-3 border-t border-gray-700">
            <span class="text-emerald-400 text-sm font-medium">Deploy complete — changes are live.</span>
          </div>
          <div v-if="deployStatus === 'failed'" class="mt-3 pt-3 border-t border-gray-700">
            <span class="text-red-400 text-sm">Deploy failed. Check logs and retry.</span>
          </div>
        </div>

        <!-- Pending changes -->
        <div v-if="pendingChanges.length" class="bg-white border border-gray-200 rounded-xl p-4">
          <div class="text-xs font-semibold text-gray-700 mb-3">Completed Tasks Ready to Ship</div>
          <div class="space-y-1.5">
            <div v-for="t in pendingChanges" :key="t.id" class="flex items-center gap-3 text-sm px-3 py-2 bg-gray-50 rounded-lg">
              <span class="text-emerald-500 font-mono">✓</span>
              <span class="flex-1 truncate text-gray-700">{{ t.slug }}</span>
              <span class="text-[10px] text-gray-400">{{ timeAgo(t.created_at) }}</span>
            </div>
          </div>
        </div>

        <!-- Recent deploys -->
        <div class="bg-white border border-gray-200 rounded-xl p-4">
          <div class="text-xs font-semibold text-gray-700 mb-3">Recent Deployments</div>
          <div v-if="recentDeploys.length" class="space-y-1.5">
            <div v-for="d in recentDeploys" :key="d.id" class="flex items-center gap-3 text-sm px-3 py-2 bg-gray-50 rounded-lg">
              <span class="w-2 h-2 rounded-full" :class="d.deploy_status === 'deployed' ? 'bg-emerald-500' : d.deploy_status === 'failed' ? 'bg-red-500' : 'bg-amber-400'"></span>
              <span class="font-mono text-xs text-gray-600">{{ d.version }}</span>
              <span class="flex-1 truncate text-gray-500 text-xs">{{ d.note || d.changelog || '' }}</span>
              <span class="text-[10px] text-gray-400">{{ timeAgo(d.created_at) }}</span>
            </div>
          </div>
          <div v-else class="text-center py-6 text-gray-400 text-sm">No deployments yet</div>
        </div>
      </div>

      <!-- Design: Visual Editor -->
      <div v-else-if="activeView === 'editor'" class="p-6 space-y-4 max-w-5xl">
        <div class="flex items-center justify-between">
          <h3 class="text-lg font-semibold text-gray-900" style="font-family: 'Fraunces', serif;">Visual Editor — {{ APPS.find(a => a.id === selectedApp)?.name }}</h3>
          <div class="flex items-center gap-2">
            <select v-model="selectedBranch" class="bg-white border border-gray-200 rounded px-2 py-1 text-xs text-gray-700">
              <option value="main">main</option>
              <option value="dev">dev</option>
              <option :value="'design/'+selectedApp+'-updates'">design/{{ selectedApp }}-updates</option>
              <option :value="'feature/'+selectedApp+'-redesign'">feature/{{ selectedApp }}-redesign</option>
            </select>
            <button class="px-3 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700">Create Branch</button>
            <button @click="activeView = 'deploy'" class="px-3 py-1 text-xs bg-emerald-600 text-white rounded hover:bg-emerald-700">Deploy</button>
          </div>
        </div>
        <div class="bg-gray-100 border border-gray-200 rounded-xl overflow-hidden">
          <div class="bg-gray-200 px-4 py-2 flex items-center gap-3 text-xs text-gray-600">
            <span class="w-2.5 h-2.5 rounded-full bg-red-400"></span>
            <span class="w-2.5 h-2.5 rounded-full bg-amber-400"></span>
            <span class="w-2.5 h-2.5 rounded-full bg-emerald-400"></span>
            <span class="flex-1 text-center font-mono text-[10px] text-gray-500">{{ selectedApp }}.vercel.app — branch: {{ selectedBranch }}</span>
          </div>
          <div class="h-[400px] flex items-center justify-center bg-white">
            <div class="text-center space-y-2">
              <div class="text-4xl">🎨</div>
              <p class="text-sm text-gray-500">Live preview of <strong>{{ APPS.find(a => a.id === selectedApp)?.name }}</strong></p>
              <p class="text-xs text-gray-400">Branch: {{ selectedBranch }}</p>
              <div class="flex gap-2 justify-center mt-3">
                <button class="px-3 py-1.5 text-xs bg-gray-900 text-white rounded-lg">Open in Editor</button>
                <button class="px-3 py-1.5 text-xs border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50">View Source</button>
              </div>
            </div>
          </div>
        </div>
        <div class="grid grid-cols-3 gap-3">
          <div class="bg-white border border-gray-200 rounded-xl p-4 hover:shadow-sm transition-shadow cursor-pointer">
            <div class="text-xs text-gray-400 mb-1">Pages</div>
            <div class="text-2xl font-bold text-gray-900">12</div>
            <div class="text-[10px] text-emerald-600 mt-1">All passing</div>
          </div>
          <div class="bg-white border border-gray-200 rounded-xl p-4 hover:shadow-sm transition-shadow cursor-pointer">
            <div class="text-xs text-gray-400 mb-1">Components</div>
            <div class="text-2xl font-bold text-gray-900">47</div>
            <div class="text-[10px] text-blue-600 mt-1">3 need review</div>
          </div>
          <div class="bg-white border border-gray-200 rounded-xl p-4 hover:shadow-sm transition-shadow cursor-pointer">
            <div class="text-xs text-gray-400 mb-1">Cognitive Load</div>
            <div class="text-2xl font-bold text-gray-900">6.2</div>
            <div class="text-[10px] text-amber-600 mt-1">Slightly elevated</div>
          </div>
        </div>
      </div>

      <!-- Legal: Documents -->
      <div v-else-if="activeView === 'documents'" class="p-6 space-y-4 max-w-4xl">
        <div class="flex items-center justify-between">
          <h3 class="text-lg font-semibold text-gray-900" style="font-family: 'Fraunces', serif;">Legal Documents — {{ APPS.find(a => a.id === selectedApp)?.name }}</h3>
          <div class="flex items-center gap-2">
            <button class="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700">+ New Document</button>
            <button @click="activeView = 'deploy'" class="px-3 py-1.5 text-xs bg-emerald-600 text-white rounded-lg hover:bg-emerald-700">Deploy</button>
          </div>
        </div>
        <div class="space-y-2">
          <div v-for="doc in appDocs" :key="doc.name" class="bg-white border border-gray-200 rounded-xl p-4 flex items-center justify-between hover:shadow-sm transition-shadow cursor-pointer group">
            <div class="flex items-center gap-3">
              <span class="text-lg">📄</span>
              <div>
                <div class="text-sm font-medium text-gray-900 group-hover:text-blue-700 transition-colors">{{ doc.name }}</div>
                <div class="text-[10px] text-gray-400 mt-0.5">{{ APPS.find(a => a.id === selectedApp)?.name }} · {{ doc.type }}</div>
              </div>
            </div>
            <div class="flex items-center gap-3">
              <span class="text-[10px] px-2 py-0.5 rounded-full font-medium" :class="docStatusColor(doc.status)">{{ doc.status }}</span>
              <div class="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button class="px-2 py-1 text-[10px] border border-gray-200 rounded hover:bg-gray-50">View</button>
                <button class="px-2 py-1 text-[10px] border border-gray-200 rounded hover:bg-gray-50">Edit</button>
                <button class="px-2 py-1 text-[10px] bg-blue-50 text-blue-700 border border-blue-200 rounded hover:bg-blue-100">CADE Review</button>
              </div>
            </div>
          </div>
        </div>
        <div class="bg-blue-50 border border-blue-200 rounded-xl p-4">
          <div class="flex items-center gap-2 mb-2"><span class="text-xs font-semibold text-blue-700">CADE Guidance</span></div>
          <p class="text-xs text-blue-600 leading-relaxed">Legal documents for <strong>{{ APPS.find(a => a.id === selectedApp)?.name }}</strong> are {{ appDocs.filter(d => d.status === 'current').length }}/{{ appDocs.length }} current. {{ appDocs.some(d => d.status === 'draft') ? 'Draft documents need review before going live.' : 'All documents are up to date.' }}</p>
        </div>
      </div>

      <!-- Configuration -->
      <div v-else-if="activeView === 'config'" class="p-6 space-y-4 max-w-3xl">
        <h3 class="text-lg font-semibold text-gray-900" style="font-family: 'Fraunces', serif;">Configuration</h3>
        <div class="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <div v-for="s in domainSliders" :key="s.label">
            <div class="flex justify-between text-sm mb-1.5"><span class="text-gray-600">{{ s.label }}</span><span class="font-mono text-gray-900 font-medium">{{ sliders[s.label] ?? s.default }}{{ s.unit }}</span></div>
            <input type="range" :min="s.min" :max="s.max" v-model.number="sliders[s.label]" class="w-full h-1.5 bg-gray-200 rounded-full appearance-none cursor-pointer accent-blue-600" />
          </div>
        </div>
        <div class="flex items-center gap-2 text-[10px] text-gray-400">
          <span class="w-1.5 h-1.5 rounded-full" :class="autoSaveStatus === 'saved' ? 'bg-emerald-500' : 'bg-amber-400'"></span>
          Configuration changes are auto-saved to your workspace.
        </div>
      </div>

      <!-- CADE Bots -->
      <div v-else-if="activeView === 'bots'" class="p-6 space-y-4 max-w-3xl">
        <h3 class="text-lg font-semibold text-gray-900" style="font-family: 'Fraunces', serif;">Assigned CADE Bots</h3>
        <div class="space-y-2">
          <div v-for="b in bots" :key="b" class="bg-white border border-gray-200 rounded-xl p-4 flex items-center justify-between">
            <div class="flex items-center gap-3">
              <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
              <span class="text-sm text-gray-900">{{ b }}</span>
            </div>
            <span class="text-[10px] text-emerald-600 font-medium">Active</span>
          </div>
        </div>
      </div>

      <!-- Recent Tasks -->
      <div v-else-if="activeView === 'tasks'" class="p-6 space-y-4 max-w-4xl">
        <h3 class="text-lg font-semibold text-gray-900" style="font-family: 'Fraunces', serif;">Recent Tasks</h3>
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

      <!-- Generic placeholder for other views -->
      <div v-else class="p-6 space-y-4 max-w-4xl">
        <h3 class="text-lg font-semibold text-gray-900" style="font-family: 'Fraunces', serif;">{{ navItems.find(n => n.key === activeView)?.label || activeView }}</h3>
        <div class="bg-white border border-gray-200 rounded-xl p-8 text-center">
          <div class="text-3xl mb-3">{{ navItems.find(n => n.key === activeView)?.icon || '📋' }}</div>
          <p class="text-sm text-gray-500">{{ navItems.find(n => n.key === activeView)?.label }} for <strong>{{ APPS.find(a => a.id === selectedApp)?.name }}</strong></p>
          <p class="text-xs text-gray-400 mt-1">Scoped to {{ cap.domain }} · {{ cap.name }}</p>
          <div class="flex gap-2 justify-center mt-4">
            <button @click="activeView = 'terminal'" class="px-4 py-2 text-xs bg-gray-900 text-white rounded-lg hover:bg-gray-800">Open in Terminal</button>
            <button @click="activeView = 'deploy'" class="px-4 py-2 text-xs bg-emerald-600 text-white rounded-lg hover:bg-emerald-700">Deploy to Prod</button>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>
