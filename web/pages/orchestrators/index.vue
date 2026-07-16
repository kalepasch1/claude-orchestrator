<script setup lang="ts">
definePageMeta({ layout: 'default' })
const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()

const CAPS = [
  { slug: 'deploy-orchestrator', name: 'Deployment', domain: 'devops', icon: '🚀', status: 'trusted', maturity: 86, summary: 'Canary deployments, rollbacks, release gates' },
  { slug: 'review-orchestrator', name: 'Code Review', domain: 'engineering', icon: '👁', status: 'trusted', maturity: 91, summary: 'Multi-model code review, security scanning' },
  { slug: 'optimize-orchestrator', name: 'Optimization', domain: 'engineering', icon: '⚡', status: 'trusted', maturity: 80, summary: 'Performance, cost, and prompt optimization' },
  { slug: 'preflight-inspector', name: 'Pre-flight', domain: 'engineering', icon: '✈', status: 'trusted', maturity: 88, summary: 'Pre-execution validation of state and deps' },
  { slug: 'remediation-orchestrator', name: 'Remediation', domain: 'engineering', icon: '🔧', status: 'trusted', maturity: 93, summary: 'Auto-diagnose and repair failing builds' },
  { slug: 'growth-orchestrator', name: 'Growth', domain: 'growth', icon: '📈', status: 'trusted', maturity: 79, summary: 'Growth experiments, A/B tests, conversions' },
  { slug: 'entity-formation', name: 'Entity Formation', domain: 'legal-ops', icon: '🏢', status: 'productizable', maturity: 95, summary: 'Jurisdiction-aware entity formation filings' },
  { slug: 'legal-orchestrator', name: 'Legal', domain: 'legal-ops', icon: '⚖', status: 'trusted', maturity: 87, summary: 'Legal review, compliance, contracts' },
  { slug: 'design-orchestrator', name: 'Chief Design', domain: 'product-design', icon: '🎨', status: 'trusted', maturity: 82, summary: 'UI/UX improvements, brand consistency' },
  { slug: 'security-orchestrator', name: 'Security', domain: 'security', icon: '🔒', status: 'trusted', maturity: 89, summary: 'RLS, access controls, key rotation' },
  { slug: 'colosseum-evaluator', name: 'Model Arena', domain: 'platform', icon: '🏟', status: 'experimental', maturity: 72, summary: 'Embedded model evaluation powering all routing' },
  { slug: 'learn-orchestrator', name: 'Learning', domain: 'platform', icon: '📚', status: 'trusted', maturity: 81, summary: 'Pattern capture and shared knowledge' },
  { slug: 'queue-orchestrator', name: 'Queue', domain: 'platform', icon: '📋', status: 'trusted', maturity: 84, summary: 'Task grooming, priority lanes, throughput' },
]

const DOMAINS = [
  { key: 'all', label: 'All Capabilities', icon: '◎' },
  { key: 'engineering', label: 'Engineering', icon: '⚙' },
  { key: 'devops', label: 'DevOps', icon: '🚀' },
  { key: 'product-design', label: 'Design', icon: '🎨' },
  { key: 'legal-ops', label: 'Legal', icon: '⚖' },
  { key: 'growth', label: 'Growth', icon: '📈' },
  { key: 'security', label: 'Security', icon: '🔒' },
  { key: 'platform', label: 'Platform', icon: '🏗' },
  { key: 'terminal', label: 'Command Terminal', icon: '▸' },
  { key: 'bots', label: 'Specialist Bots', icon: '🤖' },
]

const MODELS = [
  { label: 'Sonnet 4.6', value: 'claude-sonnet-4-6' }, { label: 'Haiku 4.5', value: 'claude-haiku-4-5-20251001' },
  { label: 'Opus 4.8', value: 'claude-opus-4-8' }, { label: 'GPT-4o', value: 'gpt-4o' },
  { label: 'GPT-4o Mini', value: 'gpt-4o-mini' }, { label: 'Gemini 2.0 Flash', value: 'gemini/gemini-2.0-flash' },
  { label: 'Gemini 1.5 Pro', value: 'gemini/gemini-1.5-pro' }, { label: 'Qwen2.5 Coder', value: 'ollama/qwen2.5-coder:7b' },
  { label: 'Cowork Executor', value: 'cowork-executor' },
]

const SPECIALIST_BOTS = [
  { name: 'Change Type Analyzer', group: 'Triage', status: 'active' },
  { name: 'Impact Scope Assessor', group: 'Triage', status: 'active' },
  { name: 'Regression Detector', group: 'Triage', status: 'active' },
  { name: 'Pixel Inspector', group: 'Quality', status: 'active' },
  { name: 'Consistency Checker', group: 'Quality', status: 'active' },
  { name: 'A11y Validator', group: 'Quality', status: 'active' },
  { name: 'Engagement Tracker', group: 'Analytics', status: 'active' },
  { name: 'Heatmap Analyzer', group: 'Analytics', status: 'active' },
  { name: 'Brand Consistency Bot', group: 'Brand', status: 'active' },
  { name: 'Cognitive Load Sensor', group: 'UX', status: 'active' },
  { name: 'Attention Flow Mapper', group: 'UX', status: 'active' },
  { name: 'Anomaly Detector', group: 'Security', status: 'active' },
  { name: 'Threat Modeler', group: 'Security', status: 'active' },
  { name: 'Pattern Recognizer', group: 'Learning', status: 'active' },
  { name: 'Intent Predictor', group: 'Learning', status: 'active' },
]

const activeDomain = ref('all')
const terminalPrompt = ref('')
const terminalLoading = ref(false)
const terminalOutput = ref('')
const selectedModel = ref('claude-sonnet-4-6')
const selectedKind = ref('build')
const selectedMode = ref('build')
const routeInfo = ref('')
const showOverride = ref(false)
const projects = ref<any[]>([])
const selectedProject = ref('')
const recentTasks = ref<any[]>([])

const filteredCaps = computed(() => activeDomain.value === 'all' ? CAPS : CAPS.filter(c => c.domain === activeDomain.value))
function modelLabel(v: string) { return MODELS.find(m => m.value === v)?.label || v }
function statusColor(s: string) { return s === 'trusted' ? 'text-blue-600' : s === 'productizable' ? 'text-emerald-600' : s === 'experimental' ? 'text-amber-600' : 'text-gray-500' }
function maturityColor(n: number) { return n >= 85 ? 'bg-emerald-500' : n >= 70 ? 'bg-blue-500' : 'bg-gray-400' }
function stateIcon(s: string) { return s === 'DONE' ? '✓' : s === 'RUNNING' ? '▶' : s === 'FAILED' ? '✗' : '◌' }
function stateClass(s: string) { return s === 'DONE' ? 'text-emerald-600' : s === 'RUNNING' ? 'text-blue-600' : s === 'FAILED' ? 'text-red-600' : 'text-gray-400' }
function timeAgo(d: string) { const s = Math.floor((Date.now() - new Date(d).getTime()) / 1000); if (s < 60) return s+'s ago'; if (s < 3600) return Math.floor(s/60)+'m ago'; if (s < 86400) return Math.floor(s/3600)+'h ago'; return Math.floor(s/86400)+'d ago' }

function routePrompt(prompt: string): { model: string; kind: string; mode: string; reason: string } {
  const p = prompt.toLowerCase()
  let model = 'claude-sonnet-4-6', kind = 'build', mode = 'build', reason = ''
  if (/\b(fix|bug|broken|error|fail|crash|repair|debug|patch|resolv|remediat)\b/.test(p)) { kind = 'fix'; reason = 'fix' }
  else if (/\b(research|analyz|investigat|compar|evaluat|study|audit|review|assess|inspect|check|scan|report)\b/.test(p)) { kind = 'research'; reason = 'research' }
  else if (/\b(test|qa|quality|validat|verif|assert|regression|coverage)\b/.test(p)) { kind = 'qa'; reason = 'qa' }
  else if (/\b(deploy|release|ship|rollout|push|publish|launch)\b/.test(p)) { kind = 'deploy'; reason = 'deploy' }
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
    const taskSlug = 'cmd-'+Date.now().toString(36)
    await supabase.from('tasks').insert({ project_id: pid, slug: taskSlug, prompt: terminalPrompt.value.trim(), kind: selectedKind.value, model: selectedModel.value, mode: selectedMode.value, state: 'QUEUED', note: 'source:command-center' })
    terminalOutput.value = '✓ Queued: '+taskSlug+'\n  Model: '+modelLabel(selectedModel.value)+' (auto)\n  Kind: '+selectedKind.value+' | Mode: '+selectedMode.value+'\n  Routing: '+routeInfo.value
    terminalPrompt.value = ''; routeInfo.value = ''; loadData()
  } catch (e: any) { terminalOutput.value = 'Error: ' + (e.message || String(e)) }
  finally { terminalLoading.value = false }
}

onMounted(() => loadData())
watch(user, u => { if (u) loadData() })
</script>

<template>
  <div class="flex h-screen bg-white text-gray-900 overflow-hidden">
    <!-- Side Navigation -->
    <aside class="w-52 bg-gray-50 border-r border-gray-200 flex flex-col flex-shrink-0">
      <div class="p-4 border-b border-gray-200">
        <h1 class="text-base font-bold text-gray-900" style="font-family: 'Fraunces', serif;">Orchestrators</h1>
        <p class="text-[10px] text-gray-400 mt-0.5">AI Command Center</p>
      </div>
      <nav class="flex-1 overflow-y-auto py-1">
        <button v-for="d in DOMAINS" :key="d.key" @click="activeDomain = d.key"
          class="w-full flex items-center gap-2.5 px-4 py-2.5 text-xs transition-colors text-left"
          :class="activeDomain === d.key ? 'bg-blue-50 text-blue-700 border-r-2 border-blue-600 font-medium' : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'">
          <span class="w-4 text-center text-[11px]">{{ d.icon }}</span>
          {{ d.label }}
        </button>
      </nav>
      <div class="p-3 border-t border-gray-200 space-y-2">
        <div class="text-[9px] text-gray-400 uppercase tracking-wider px-1">Active Project</div>
        <select v-model="selectedProject" class="w-full bg-white border border-gray-200 rounded px-2 py-1.5 text-xs text-gray-700">
          <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </div>
    </aside>

    <!-- Main Content -->
    <main class="flex-1 overflow-y-auto">
      <!-- Capabilities Grid -->
      <div v-if="activeDomain !== 'terminal' && activeDomain !== 'bots'" class="p-6 max-w-5xl">
        <div class="flex items-center justify-between mb-5">
          <h2 class="text-lg font-semibold text-gray-900" style="font-family: 'Fraunces', serif;">{{ DOMAINS.find(d => d.key === activeDomain)?.label || 'Capabilities' }}</h2>
          <span class="text-xs text-gray-400">{{ filteredCaps.length }} capabilities</span>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          <NuxtLink v-for="c in filteredCaps" :key="c.slug" :to="'/orchestrators/'+c.slug"
            class="bg-white border border-gray-200 rounded-xl p-4 hover:shadow-md hover:border-blue-200 transition-all group cursor-pointer">
            <div class="flex items-start justify-between mb-2">
              <span class="text-xl">{{ c.icon }}</span>
              <span class="text-[10px] font-medium px-1.5 py-0.5 rounded" :class="statusColor(c.status)">{{ c.status }}</span>
            </div>
            <h3 class="text-sm font-semibold text-gray-900 group-hover:text-blue-700 transition-colors mb-1">{{ c.name }}</h3>
            <p class="text-[11px] text-gray-500 leading-relaxed mb-3">{{ c.summary }}</p>
            <div class="flex items-center gap-2">
              <div class="flex-1 h-1 bg-gray-100 rounded-full overflow-hidden"><div class="h-full rounded-full" :class="maturityColor(c.maturity)" :style="'width:'+c.maturity+'%'"></div></div>
              <span class="text-[9px] text-gray-400 font-mono">{{ c.maturity }}%</span>
            </div>
          </NuxtLink>
        </div>
        <!-- Recent Tasks -->
        <div v-if="recentTasks.length" class="mt-8">
          <h3 class="text-sm font-semibold text-gray-700 mb-3">Recent Tasks</h3>
          <div class="space-y-1.5">
            <div v-for="t in recentTasks" :key="t.id" class="bg-white border border-gray-200 rounded-lg px-4 py-2.5 flex items-center gap-3 text-sm">
              <span class="font-mono text-base" :class="stateClass(t.state)">{{ stateIcon(t.state) }}</span>
              <span class="text-gray-900 flex-1 truncate">{{ t.slug }}</span>
              <span class="text-xs text-gray-400 px-2 py-0.5 bg-gray-50 rounded">{{ t.kind || '—' }}</span>
              <span class="text-xs text-gray-400">{{ timeAgo(t.created_at) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Command Terminal -->
      <div v-else-if="activeDomain === 'terminal'" class="p-6 max-w-4xl space-y-4">
        <h2 class="text-lg font-semibold text-gray-900" style="font-family: 'Fraunces', serif;">Command Terminal</h2>
        <div class="bg-gray-900 rounded-xl p-5 min-h-[200px]" style="font-family: 'JetBrains Mono', monospace;">
          <div v-if="terminalOutput" class="text-sm text-emerald-400 whitespace-pre-wrap mb-4">{{ terminalOutput }}</div>
          <div v-else class="text-sm text-gray-500 mb-4">Ready — describe what you need. Model, kind, and mode are auto-determined from your prompt.</div>
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
            <div class="flex flex-wrap gap-1"><button v-for="md in ['build','research','efficiency','speculative']" :key="md" @click="selectedMode = md" class="px-2 py-1 text-[10px] rounded border" :class="selectedMode === md ? 'bg-gray-900 text-white border-gray-900' : 'bg-white text-gray-500 border-gray-200'">{{ md }}</button></div>
          </div>
        </div>
        <div class="flex items-center gap-3">
          <select v-model="selectedProject" class="bg-white border border-gray-200 rounded px-2 py-2 text-xs text-gray-700">
            <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
          <button @click="runCommand" :disabled="terminalLoading || !terminalPrompt.trim()" class="px-6 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-40">{{ terminalLoading ? 'Routing...' : '→ Execute' }}</button>
        </div>
      </div>

      <!-- Specialist Bots -->
      <div v-else-if="activeDomain === 'bots'" class="p-6 max-w-4xl space-y-4">
        <h2 class="text-lg font-semibold text-gray-900" style="font-family: 'Fraunces', serif;">Specialist Bot Fleet</h2>
        <p class="text-xs text-gray-500">60 bots across 15 groups powering automated quality, analytics, and optimization.</p>
        <div class="space-y-2">
          <div v-for="b in SPECIALIST_BOTS" :key="b.name" class="bg-white border border-gray-200 rounded-xl p-4 flex items-center justify-between">
            <div class="flex items-center gap-3">
              <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
              <div>
                <div class="text-sm text-gray-900">{{ b.name }}</div>
                <div class="text-[10px] text-gray-400">{{ b.group }}</div>
              </div>
            </div>
            <span class="text-[10px] text-emerald-600 font-medium">{{ b.status }}</span>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>
