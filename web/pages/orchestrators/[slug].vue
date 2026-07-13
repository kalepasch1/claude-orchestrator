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
const MODELS = [
  { label: 'Sonnet 4.6', value: 'claude-sonnet-4-6' }, { label: 'Haiku 4.5', value: 'claude-haiku-4-5-20251001' },
  { label: 'Opus 4.8', value: 'claude-opus-4-8' }, { label: 'GPT-4o', value: 'gpt-4o' },
  { label: 'GPT-4o Mini', value: 'gpt-4o-mini' }, { label: 'Gemini 2.0 Flash', value: 'gemini/gemini-2.0-flash' },
  { label: 'Gemini 1.5 Pro', value: 'gemini/gemini-1.5-pro' }, { label: 'Qwen2.5 Coder', value: 'ollama/qwen2.5-coder:7b' },
  { label: 'Cowork Executor', value: 'cowork-executor' },
]
const KINDS = ['build', 'fix', 'research', 'qa', 'deploy', 'canary']
const MODES = ['build', 'research', 'efficiency', 'speculative']
const DOMAIN_TOOLS: Record<string, { label: string; icon: string }[]> = {
  devops: [{ label: 'Canary Deploy', icon: '🚀' }, { label: 'Rollback Gate', icon: '⏪' }, { label: 'Health Monitor', icon: '💚' }, { label: 'Release Notes', icon: '📋' }, { label: 'Infra Scan', icon: '🔍' }],
  engineering: [{ label: 'Code Review', icon: '👁' }, { label: 'Test Runner', icon: '🧪' }, { label: 'Lint & Format', icon: '✨' }, { label: 'Dependency Audit', icon: '📦' }, { label: 'Perf Profiler', icon: '⚡' }],
  growth: [{ label: 'A/B Test Setup', icon: '🔬' }, { label: 'Funnel Analysis', icon: '📊' }, { label: 'Conversion Optimizer', icon: '📈' }, { label: 'BD Autopilot', icon: '🤝' }, { label: 'Retention Tracker', icon: '🎯' }],
  'legal-ops': [{ label: 'Contract Analyzer', icon: '📄' }, { label: 'Entity Filing', icon: '🏢' }, { label: 'Compliance Check', icon: '✅' }, { label: 'Regulatory Monitor', icon: '⚖️' }, { label: 'Policy Generator', icon: '📝' }],
  platform: [{ label: 'Model Tournament', icon: '🏟' }, { label: 'Queue Manager', icon: '📋' }, { label: 'Pattern Library', icon: '📚' }, { label: 'Routing Optimizer', icon: '🔀' }, { label: 'Knowledge Base', icon: '🧠' }],
  'product-design': [{ label: 'UI Generator', icon: '🎨' }, { label: 'Archetype Sim', icon: '👤' }, { label: 'Cognitive Load', icon: '🧩' }, { label: 'Brand Checker', icon: '🏷' }, { label: 'Animation Studio', icon: '✦' }],
  security: [{ label: 'RLS Auditor', icon: '🔒' }, { label: 'Key Rotation', icon: '🔑' }, { label: 'Access Controls', icon: '🛡' }, { label: 'Vuln Scanner', icon: '🔍' }, { label: 'Incident Response', icon: '🚨' }],
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
  devops: ['Change Type Analyzer', 'Impact Scope Assessor', 'Regression Detector'],
  engineering: ['Pixel Inspector', 'Consistency Checker', 'A11y Validator', 'Style Implementer'],
  growth: ['Engagement Tracker', 'Heatmap Analyzer', 'Conversion Monitor', 'Trend Forecaster'],
  'legal-ops': ['Brand Consistency Bot', 'Guidelines Enforcer', 'Anomaly Detector'],
  platform: ['Pattern Recognizer', 'Insight Generator', 'Context Mapper', 'Intent Predictor'],
  'product-design': ['Cognitive Load Sensor', 'Attention Flow Mapper', 'User Flow Simulator', 'Learning Curve Optimizer', 'Animation Controller', 'Typography Manager'],
  security: ['Anomaly Detector', 'Cross-Platform Sync', 'Edge Case Generator'],
}
const cap = computed(() => CAPS[slug.value] || { name: slug.value, domain: 'platform', status: 'unknown', maturity: 0, regulated: false, summary: '' })
const tools = computed(() => DOMAIN_TOOLS[cap.value.domain] || DOMAIN_TOOLS.platform)
const bots = computed(() => DOMAIN_BOTS[cap.value.domain] || [])
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
const domainSliders = computed(() => DOMAIN_SLIDERS[cap.value.domain] || DOMAIN_SLIDERS.platform)
watch(domainSliders, (ds) => { for (const s of ds) { if (!(s.label in sliders.value)) sliders.value[s.label] = s.default } }, { immediate: true })
function statusColor(s: string) { return s === 'trusted' ? 'bg-blue-100 text-blue-700' : s === 'productizable' ? 'bg-emerald-100 text-emerald-700' : s === 'experimental' ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-600' }
function maturityColor(n: number) { return n >= 85 ? 'bg-emerald-500' : n >= 70 ? 'bg-blue-500' : 'bg-gray-400' }
function stateIcon(s: string) { return s === 'DONE' ? '✓' : s === 'RUNNING' ? '▶' : s === 'FAILED' ? '✗' : s === 'QUEUED' ? '◌' : '·' }
function stateClass(s: string) { return s === 'DONE' ? 'text-emerald-600' : s === 'RUNNING' ? 'text-blue-600' : s === 'FAILED' ? 'text-red-600' : 'text-gray-400' }
function timeAgo(d: string) { const s = Math.floor((Date.now() - new Date(d).getTime()) / 1000); if (s < 60) return s+'s ago'; if (s < 3600) return Math.floor(s/60)+'m ago'; if (s < 86400) return Math.floor(s/3600)+'h ago'; return Math.floor(s/86400)+'d ago' }
async function loadData() {
  try {
    const [prj, tasks] = await Promise.all([supabase.from('projects').select('*').order('name'), supabase.from('tasks').select('*').order('created_at', { ascending: false }).limit(10)])
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
    await supabase.from('tasks').insert({ project_id: pid, slug: taskSlug, prompt: terminalPrompt.value.trim(), kind: selectedKind.value, model: selectedModel.value, mode: selectedMode.value, state: 'QUEUED', note: 'source:'+slug.value+'-command-center' })
    terminalOutput.value = '✓ Task queued: '+taskSlug+'\nCapability: '+cap.value.name+'\nModel: '+selectedModel.value+'\nKind: '+selectedKind.value+' | Mode: '+selectedMode.value+'\n\nRouting through CADE pipeline...'
    terminalPrompt.value = ''; loadData()
  } catch (e: any) { terminalOutput.value = 'Error: ' + (e.message || String(e)) }
  finally { terminalLoading.value = false }
}
onMounted(() => loadData())
watch(user, u => { if (u) loadData() })
</script>
<template>
  <div class="min-h-screen bg-white text-gray-900">
    <div class="max-w-6xl mx-auto px-6 py-6 space-y-6">
      <div class="flex items-center gap-3">
        <NuxtLink to="/orchestrators" class="text-gray-400 hover:text-gray-600 text-sm">← Back</NuxtLink>
        <div class="flex-1">
          <div class="flex items-center gap-3">
            <h1 class="text-xl font-bold text-gray-900" style="font-family: 'Fraunces', serif;">{{ cap.name }}</h1>
            <span class="text-[10px] px-2 py-0.5 rounded-full font-medium" :class="statusColor(cap.status)">{{ cap.status }}</span>
            <span v-if="cap.regulated" class="text-[10px] px-1.5 py-0.5 rounded bg-red-50 text-red-600 border border-red-200">regulated</span>
          </div>
          <p class="text-sm text-gray-500 mt-0.5">{{ cap.summary }}</p>
        </div>
        <div class="flex items-center gap-2">
          <div class="w-24 h-1.5 bg-gray-100 rounded-full overflow-hidden"><div class="h-full rounded-full" :class="maturityColor(cap.maturity)" :style="'width: '+cap.maturity+'%'"></div></div>
          <span class="text-xs text-gray-400 font-mono">{{ cap.maturity }}%</span>
        </div>
      </div>
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="lg:col-span-2 space-y-4">
          <div class="bg-white border border-gray-200 rounded-xl overflow-hidden">
            <div class="px-4 py-2.5 border-b border-gray-200 flex items-center gap-2"><span class="text-emerald-600 text-xs font-bold">→</span><span class="text-sm font-semibold text-gray-900">Command Terminal</span><span class="text-xs text-gray-400">{{ cap.domain }}</span></div>
            <div class="p-4">
              <div class="bg-gray-900 rounded-lg p-4 min-h-[120px]" style="font-family: 'JetBrains Mono', monospace;">
                <div v-if="terminalOutput" class="text-sm text-emerald-400 whitespace-pre-wrap mb-3">{{ terminalOutput }}</div>
                <div v-else class="text-sm text-gray-500 mb-3">{{ cap.name }} command center ready.</div>
                <div class="flex items-center gap-2"><span class="text-emerald-500">$</span><input v-model="terminalPrompt" @keydown.enter="runCommand" placeholder="Type a command..." class="flex-1 bg-transparent text-white text-sm outline-none placeholder-gray-600" /></div>
              </div>
            </div>
          </div>
          <div class="bg-white border border-gray-200 rounded-xl p-4 space-y-3">
            <div class="text-xs text-gray-400 uppercase tracking-wider">AI Model</div>
            <div class="flex flex-wrap gap-1.5"><button v-for="m in MODELS" :key="m.value" @click="selectedModel = m.value" class="px-3 py-1.5 text-xs rounded-lg border transition-colors" :class="selectedModel === m.value ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-200 hover:border-blue-300'">{{ m.label }}</button></div>
            <div class="grid grid-cols-2 gap-4 pt-2">
              <div><div class="text-xs text-gray-400 uppercase tracking-wider mb-1.5">Kind</div><div class="flex flex-wrap gap-1.5"><button v-for="k in KINDS" :key="k" @click="selectedKind = k" class="px-3 py-1.5 text-xs rounded-lg border transition-colors" :class="selectedKind === k ? 'bg-gray-900 text-white border-gray-900' : 'bg-white text-gray-600 border-gray-200 hover:border-gray-400'">{{ k }}</button></div></div>
              <div><div class="text-xs text-gray-400 uppercase tracking-wider mb-1.5">Mode</div><div class="flex flex-wrap gap-1.5"><button v-for="m in MODES" :key="m" @click="selectedMode = m" class="px-3 py-1.5 text-xs rounded-lg border transition-colors" :class="selectedMode === m ? 'bg-gray-900 text-white border-gray-900' : 'bg-white text-gray-600 border-gray-200 hover:border-gray-400'">{{ m }}</button></div></div>
            </div>
            <div class="flex items-end gap-3 pt-2">
              <div class="flex-1"><div class="text-xs text-gray-400 uppercase tracking-wider mb-1.5">Project</div><select v-model="selectedProject" class="w-full bg-white border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700"><option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option></select></div>
              <button @click="runCommand" :disabled="terminalLoading || !terminalPrompt.trim()" class="px-6 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-40">{{ terminalLoading ? 'Queuing...' : '→ Execute' }}</button>
            </div>
          </div>
          <div class="bg-white border border-gray-200 rounded-xl p-4">
            <div class="text-xs text-gray-400 uppercase tracking-wider mb-3">{{ cap.domain }} Tools</div>
            <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2"><button v-for="t in tools" :key="t.label" class="flex flex-col items-center gap-1.5 p-3 rounded-lg border border-gray-200 hover:border-blue-300 hover:bg-blue-50 transition-colors group"><span class="text-lg">{{ t.icon }}</span><span class="text-[11px] text-gray-600 group-hover:text-blue-700 font-medium text-center leading-tight">{{ t.label }}</span></button></div>
          </div>
        </div>
        <div class="space-y-4">
          <div class="bg-white border border-gray-200 rounded-xl p-4">
            <div class="text-xs text-gray-400 uppercase tracking-wider mb-3">Status</div>
            <div class="space-y-2">
              <div class="flex justify-between text-sm"><span class="text-gray-500">Domain</span><span class="font-medium text-gray-900">{{ cap.domain }}</span></div>
              <div class="flex justify-between text-sm"><span class="text-gray-500">Status</span><span class="font-medium">{{ cap.status }}</span></div>
              <div class="flex justify-between text-sm"><span class="text-gray-500">Regulated</span><span class="font-medium" :class="cap.regulated ? 'text-red-600' : 'text-gray-400'">{{ cap.regulated ? 'Yes' : 'No' }}</span></div>
              <div class="flex justify-between text-sm"><span class="text-gray-500">Maturity</span><span class="font-mono text-gray-900">{{ cap.maturity }}%</span></div>
            </div>
          </div>
          <div class="bg-white border border-gray-200 rounded-xl p-4">
            <div class="text-xs text-gray-400 uppercase tracking-wider mb-3">Configuration</div>
            <div class="space-y-3"><div v-for="s in domainSliders" :key="s.label"><div class="flex justify-between text-xs mb-1"><span class="text-gray-600">{{ s.label }}</span><span class="font-mono text-gray-900">{{ sliders[s.label] ?? s.default }}{{ s.unit }}</span></div><input type="range" :min="s.min" :max="s.max" v-model.number="sliders[s.label]" class="w-full h-1.5 bg-gray-200 rounded-full appearance-none cursor-pointer accent-blue-600" /></div></div>
          </div>
          <div class="bg-white border border-gray-200 rounded-xl p-4">
            <div class="text-xs text-gray-400 uppercase tracking-wider mb-3">Assigned CADE Bots</div>
            <div class="space-y-1.5"><div v-for="b in bots" :key="b" class="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-gray-50 text-xs"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span><span class="text-gray-700">{{ b }}</span></div><div v-if="!bots.length" class="text-xs text-gray-400 italic">No bots assigned</div></div>
          </div>
          <div class="bg-white border border-gray-200 rounded-xl p-4">
            <div class="text-xs text-gray-400 uppercase tracking-wider mb-3">Recent Tasks</div>
            <div class="space-y-1.5"><div v-for="t in recentTasks.slice(0, 6)" :key="t.id" class="flex items-center gap-2 text-xs py-1"><span class="font-mono" :class="stateClass(t.state)">{{ stateIcon(t.state) }}</span><span class="text-gray-700 truncate flex-1">{{ t.slug }}</span><span class="text-gray-400 text-[10px]">{{ timeAgo(t.created_at) }}</span></div><div v-if="!recentTasks.length" class="text-xs text-gray-400 italic">No recent tasks</div></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
