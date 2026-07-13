<script setup lang="ts">
definePageMeta({ layout: 'default' })
const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()
const HARDCODED_CAPS = [
  { slug: 'deploy-orchestrator', name: 'Deployment Orchestrator', domain: 'devops', status: 'trusted', maturity: 86, regulated: false, summary: 'Manages canary deployments, watches, rollbacks, and release gates.' },
  { slug: 'review-orchestrator', name: 'Code Review Orchestrator', domain: 'engineering', status: 'trusted', maturity: 91, regulated: false, summary: 'Automated multi-model code review, security scanning, and quality gating.' },
  { slug: 'optimize-orchestrator', name: 'Optimization Orchestrator', domain: 'engineering', status: 'trusted', maturity: 80, regulated: false, summary: 'Performance, cost, prompt caching, and resource optimization.' },
  { slug: 'preflight-inspector', name: 'Pre-flight Inspector', domain: 'engineering', status: 'trusted', maturity: 88, regulated: false, summary: 'Pre-execution validation of branch state, dependencies, and environment.' },
  { slug: 'remediation-orchestrator', name: 'Remediation Orchestrator', domain: 'engineering', status: 'trusted', maturity: 93, regulated: false, summary: 'Auto-diagnoses and repairs failing tests, builds, and blocked tasks.' },
  { slug: 'growth-orchestrator', name: 'Growth Orchestrator', domain: 'growth', status: 'trusted', maturity: 79, regulated: false, summary: 'Growth experiments, A/B tests, conversion optimization, and BD autopilot.' },
  { slug: 'entity-formation', name: 'Entity Formation Filing', domain: 'legal-ops', status: 'productizable', maturity: 95, regulated: false, summary: 'Jurisdiction-aware entity formation: Articles, EIN, Operating Agreements.' },
  { slug: 'legal-orchestrator', name: 'Legal Orchestrator', domain: 'legal-ops', status: 'trusted', maturity: 87, regulated: true, summary: 'Legal review, compliance, contracts, and regulatory workflows.' },
  { slug: 'colosseum-evaluator', name: 'Colosseum Evaluator', domain: 'platform', status: 'experimental', maturity: 72, regulated: false, summary: 'Head-to-head model evaluations for optimal task routing.' },
  { slug: 'learn-orchestrator', name: 'Learning Orchestrator', domain: 'platform', status: 'trusted', maturity: 81, regulated: false, summary: 'Pattern capture, shared knowledge building, and routing improvement.' },
  { slug: 'queue-orchestrator', name: 'Queue Orchestrator', domain: 'platform', status: 'trusted', maturity: 84, regulated: false, summary: 'Task grooming, slug conflicts, priority lanes, and throughput.' },
  { slug: 'design-orchestrator', name: 'Chief Design Orchestrator', domain: 'product-design', status: 'trusted', maturity: 82, regulated: false, summary: 'UI/UX improvements, creative generation, and brand consistency.' },
  { slug: 'security-orchestrator', name: 'Security Orchestrator', domain: 'security', status: 'trusted', maturity: 89, regulated: true, summary: 'RLS policies, access controls, key rotation, and security posture.' },
]
const capabilities = ref<any[]>([...HARDCODED_CAPS])
const loops = ref<any[]>([])
const projects = ref<any[]>([])
const loading = ref(false)
const activeTab = ref<'capabilities' | 'bots' | 'loops' | 'terminal'>('capabilities')
const terminalPrompt = ref('')
const terminalLoading = ref(false)
const terminalOutput = ref('')
const selectedModel = ref('claude-sonnet-4-6')
const selectedKind = ref('build')
const selectedMode = ref('build')
const selectedProject = ref('')
const MODELS = [
  { label: 'Sonnet 4.6', value: 'claude-sonnet-4-6' }, { label: 'Haiku 4.5', value: 'claude-haiku-4-5-20251001' },
  { label: 'Opus 4.8', value: 'claude-opus-4-8' }, { label: 'GPT-4o', value: 'gpt-4o' },
  { label: 'GPT-4o Mini', value: 'gpt-4o-mini' }, { label: 'Gemini 2.0 Flash', value: 'gemini/gemini-2.0-flash' },
  { label: 'Gemini 1.5 Pro', value: 'gemini/gemini-1.5-pro' }, { label: 'Qwen2.5 Coder', value: 'ollama/qwen2.5-coder:7b' },
  { label: 'Cowork Executor', value: 'cowork-executor' },
]
const KINDS = ['build', 'fix', 'research', 'qa', 'deploy', 'canary']
const MODES = ['build', 'research', 'efficiency', 'speculative']
const QUICK_ACTIONS = [
  { label: 'Run full CADE audit', domain: 'platform', cmd: 'Run full CADE audit on all apps' },
  { label: 'Cognitive load analysis', domain: 'product-design', cmd: 'Analyze cognitive load across entire portfolio' },
  { label: 'A/B test recommendations', domain: 'growth', cmd: 'Generate A/B test recommendations across all projects' },
  { label: 'Brand consistency check', domain: 'product-design', cmd: 'Check brand consistency score across portfolio' },
  { label: 'Accessibility compliance', domain: 'engineering', cmd: 'Review accessibility compliance across all apps' },
  { label: 'Archetype simulation', domain: 'product-design', cmd: 'Run archetype simulation against latest changes' },
  { label: 'Model evaluation', domain: 'platform', cmd: 'Evaluate model performance head-to-head in Colosseum' },
  { label: 'Security RLS audit', domain: 'security', cmd: 'Security RLS audit across all Supabase projects' },
  { label: 'Queue grooming pass', domain: 'platform', cmd: 'Queue grooming pass — resolve slug conflicts and re-prioritize' },
  { label: 'Legal compliance scan', domain: 'legal-ops', cmd: 'Legal compliance scan across portfolio' },
  { label: 'Deploy canary all projects', domain: 'devops', cmd: 'Deploy canary to all projects with rollback gates' },
  { label: 'Conditioning cue audit', domain: 'product-design', cmd: 'Audit operant conditioning cue effectiveness' },
]
const PIPELINE_STAGES = ['Classification', 'Placement', 'Design Gen', 'Behavioral Review', 'Analytics', 'Archetype Sim', 'Approval Gate', 'Deploy', 'Measure']
const BOT_GROUPS = [
  { id: 1, name: 'Change Classification', bots: ['Change Type Analyzer', 'Impact Scope Assessor', 'Priority Calculator', 'Complexity Estimator'] },
  { id: 2, name: 'Placement Intelligence', bots: ['Layout Optimizer', 'Placement Predictor', 'Density Analyzer', 'Grid Harmonizer'] },
  { id: 3, name: 'Design Execution', bots: ['Style Implementer', 'Animation Controller', 'Typography Manager', 'Color System Bot'] },
  { id: 4, name: 'Quality Assurance', bots: ['Pixel Inspector', 'Consistency Checker', 'Regression Detector', 'A11y Validator'] },
  { id: 5, name: 'Analytics Engine', bots: ['Engagement Tracker', 'Heatmap Analyzer', 'Conversion Monitor', 'Session Recorder'] },
  { id: 6, name: 'Intelligence Layer', bots: ['Pattern Recognizer', 'Anomaly Detector', 'Trend Forecaster', 'Insight Generator'] },
  { id: 7, name: 'Brand Guardian', bots: ['Brand Consistency Bot', 'Asset Manager', 'Guidelines Enforcer', 'Cross-App Harmonizer'] },
  { id: 8, name: 'Simulation Engine', bots: ['User Flow Simulator', 'Load Tester', 'Stress Analyzer', 'Edge Case Generator'] },
  { id: 9, name: 'Cognitive Analysis', bots: ['Cognitive Load Sensor', 'Attention Flow Mapper', 'Decision Fatigue Monitor', 'Learning Curve Optimizer'] },
  { id: 10, name: 'Advanced Systems', bots: ['Cross-Platform Sync', 'Multi-Modal Adapter', 'Predictive UI Engine', 'Context Aware Bot'] },
  { id: 11, name: 'Autonomous Intelligence', bots: ['Temporal Design Intel', 'Competitive Radar', 'Design Debt Quantifier', 'Collaborative Memory'] },
  { id: 12, name: 'Self-Operating Design', bots: ['Zero-State Intel', 'Micro-Funnel Optimizer', 'Accessibility Generator', 'Sentiment Engine'] },
  { id: 13, name: 'Contextual Intelligence', bots: ['Context Mapper', 'Intent Predictor', 'Behavior Modeler', 'Situation Analyzer'] },
  { id: 14, name: 'Adaptive Content', bots: ['Content Personalizer', 'Dynamic Copy Engine', 'Tone Adjuster', 'Reading Level Adapter'] },
  { id: 15, name: 'Behavioral Conditioning', bots: ['Reward System Bot', 'Streak Manager', 'Celebration Engine', 'Progress Tracker'] },
]
const DOMAIN_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  devops: { bg: 'bg-blue-50', text: 'text-blue-700', border: 'border-blue-200' },
  engineering: { bg: 'bg-indigo-50', text: 'text-indigo-700', border: 'border-indigo-200' },
  growth: { bg: 'bg-emerald-50', text: 'text-emerald-700', border: 'border-emerald-200' },
  'legal-ops': { bg: 'bg-red-50', text: 'text-red-700', border: 'border-red-200' },
  platform: { bg: 'bg-purple-50', text: 'text-purple-700', border: 'border-purple-200' },
  'product-design': { bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200' },
  security: { bg: 'bg-rose-50', text: 'text-rose-700', border: 'border-rose-200' },
}
const DOMAIN_LABELS: Record<string, string> = { devops: 'DevOps', engineering: 'Engineering', growth: 'Growth', 'legal-ops': 'Legal Ops', platform: 'Platform', 'product-design': 'Product & Design', security: 'Security' }
function domainStyle(d: string) { return DOMAIN_COLORS[d] || { bg: 'bg-gray-50', text: 'text-gray-700', border: 'border-gray-200' } }
function statusColor(s: string) { return s === 'trusted' ? 'bg-blue-100 text-blue-700' : s === 'productizable' ? 'bg-emerald-100 text-emerald-700' : s === 'experimental' ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-600' }
function maturityColor(n: number) { return n >= 85 ? 'bg-emerald-500' : n >= 70 ? 'bg-blue-500' : 'bg-gray-400' }
function actionColor(d: string) {
  const m: Record<string, string> = { devops: 'bg-blue-50 text-blue-700 border-blue-200 hover:bg-blue-100', engineering: 'bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100', growth: 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100', 'legal-ops': 'bg-red-50 text-red-700 border-red-200 hover:bg-red-100', platform: 'bg-purple-50 text-purple-700 border-purple-200 hover:bg-purple-100', 'product-design': 'bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100', security: 'bg-rose-50 text-rose-700 border-rose-200 hover:bg-rose-100' }
  return m[d] || 'bg-gray-50 text-gray-700 border-gray-200 hover:bg-gray-100'
}
function healthColor(h: string) { return h === 'healthy' ? 'text-emerald-600' : h === 'degraded' ? 'text-amber-600' : h === 'down' ? 'text-red-600' : 'text-gray-500' }
const grouped = computed(() => {
  const g: Record<string, any[]> = {}
  for (const c of capabilities.value) { const d = c.domain || 'other'; if (!g[d]) g[d] = []; g[d].push(c) }
  return Object.entries(g).sort((a, b) => a[0].localeCompare(b[0]))
})
async function loadAll() {
  loading.value = true
  try {
    const [caps, lps, prj] = await Promise.all([supabase.from('capabilities').select('*').order('domain'), supabase.from('loops').select('*').order('project'), supabase.from('projects').select('*').order('name')])
    if (caps.data?.length) {
      const merged = [...HARDCODED_CAPS]
      for (const db of caps.data) { const idx = merged.findIndex(h => h.slug === db.slug); if (idx >= 0) merged[idx] = { ...merged[idx], ...db, maturity: Number(db.maturity) || merged[idx].maturity }; else merged.push({ ...db, maturity: Number(db.maturity) || 0 }) }
      capabilities.value = merged
    }
    loops.value = lps.data || []; projects.value = prj.data || []
    if (projects.value.length && !selectedProject.value) selectedProject.value = projects.value[0].id
  } catch {}
  loading.value = false
}
async function toggleLoop(l: any) { await supabase.from('loops').update({ enabled: !l.enabled }).eq('id', l.id); l.enabled = !l.enabled }
async function runTerminalCommand() {
  if (!terminalPrompt.value.trim()) return
  terminalLoading.value = true; terminalOutput.value = ''
  try {
    const pid = selectedProject.value || projects.value[0]?.id
    if (!pid) { terminalOutput.value = 'Error: No project selected'; return }
    const slug = 'terminal-' + Date.now().toString(36)
    await supabase.from('tasks').insert({ project_id: pid, slug, prompt: terminalPrompt.value.trim(), kind: selectedKind.value, model: selectedModel.value, mode: selectedMode.value, state: 'QUEUED', note: 'source:command-terminal' })
    terminalOutput.value = '✓ Task queued: '+slug+'\nModel: '+selectedModel.value+'\nKind: '+selectedKind.value+' | Mode: '+selectedMode.value
    terminalPrompt.value = ''
  } catch (e: any) { terminalOutput.value = 'Error: ' + (e.message || String(e)) }
  finally { terminalLoading.value = false }
}
onMounted(() => loadAll())
watch(user, u => { if (u) loadAll() })
</script>
<template>
  <div class="min-h-screen bg-white text-gray-900">
    <div class="max-w-6xl mx-auto px-6 py-6 space-y-6">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-bold text-gray-900" style="font-family: 'Fraunces', serif;">Orchestrators & Capabilities</h1>
          <p class="text-sm text-gray-500 mt-0.5">{{ capabilities.length }} capabilities · {{ BOT_GROUPS.length * 4 }} CADE bots · command terminal</p>
        </div>
        <button @click="loadAll" class="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm rounded-lg border border-gray-200 transition-colors">↻ Refresh</button>
      </div>
      <div class="flex gap-1 bg-gray-100 rounded-lg p-1">
        <button v-for="tab in [{ key: 'capabilities', label: 'Capabilities', count: capabilities.length }, { key: 'bots', label: 'CADE Bots', count: BOT_GROUPS.length * 4 }, { key: 'loops', label: 'Automation Loops', count: loops.length }, { key: 'terminal', label: 'Command Terminal' }]" :key="tab.key" @click="activeTab = tab.key as any" class="flex-1 px-4 py-2 text-sm rounded-md transition-colors" :class="activeTab === tab.key ? 'bg-white text-gray-900 font-medium shadow-sm' : 'text-gray-500 hover:text-gray-700'">{{ tab.label }}<span v-if="tab.count != null" class="ml-1 text-xs text-gray-400">({{ tab.count }})</span></button>
      </div>
      <div v-if="activeTab === 'capabilities'" class="space-y-6">
        <div v-for="[domain, caps] in grouped" :key="domain">
          <h3 class="text-xs uppercase tracking-[0.15em] text-gray-400 font-medium mb-3">{{ DOMAIN_LABELS[domain] || domain }}</h3>
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            <NuxtLink v-for="c in caps" :key="c.slug" :to="'/orchestrators/'+c.slug" class="bg-white border border-gray-200 rounded-xl p-4 hover:shadow-md hover:border-gray-300 transition-all group">
              <div class="flex items-start justify-between gap-2 mb-2"><h4 class="text-sm font-semibold text-gray-900 leading-tight group-hover:text-blue-700 transition-colors">{{ c.name }}</h4><span class="text-[10px] px-2 py-0.5 rounded-full font-medium flex-shrink-0" :class="statusColor(c.status)">{{ c.status }}</span></div>
              <div class="flex items-center gap-2 mb-2"><span class="text-[10px] px-2 py-0.5 rounded border font-medium" :class="[domainStyle(c.domain).bg, domainStyle(c.domain).text, domainStyle(c.domain).border]">{{ c.domain }}</span><span v-if="c.regulated" class="text-[10px] px-1.5 py-0.5 rounded bg-red-50 text-red-600 border border-red-200">regulated</span></div>
              <p class="text-xs text-gray-500 mb-3 leading-relaxed line-clamp-2">{{ c.summary }}</p>
              <div class="flex items-center gap-2"><div class="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden"><div class="h-full rounded-full" :class="maturityColor(c.maturity)" :style="'width: '+c.maturity+'%'"></div></div><span class="text-[10px] text-gray-400 font-mono">{{ c.maturity }}%</span></div>
              <div class="mt-3 text-xs text-blue-600 font-medium opacity-0 group-hover:opacity-100 transition-opacity">→ Open Command Center</div>
            </NuxtLink>
          </div>
        </div>
      </div>
      <div v-else-if="activeTab === 'bots'" class="space-y-4">
        <p class="text-sm text-gray-500">{{ BOT_GROUPS.length }} groups · {{ BOT_GROUPS.length * 4 }} specialized bots.</p>
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <div v-for="g in BOT_GROUPS" :key="g.id" class="bg-white border border-gray-200 rounded-xl p-4 hover:shadow-md transition-shadow">
            <div class="flex items-center justify-between mb-3"><div class="flex items-center gap-2"><span class="w-6 h-6 rounded-lg bg-blue-100 text-blue-700 flex items-center justify-center text-xs font-bold">{{ g.id }}</span><h3 class="text-sm font-semibold text-gray-900">{{ g.name }}</h3></div><span class="w-2 h-2 rounded-full bg-emerald-500"></span></div>
            <div class="space-y-1"><div v-for="bot in g.bots" :key="bot" class="flex items-center gap-2 text-xs text-gray-600 py-0.5"><span class="w-1 h-1 rounded-full bg-gray-300"></span>{{ bot }}</div></div>
          </div>
        </div>
      </div>
      <div v-else-if="activeTab === 'loops'" class="space-y-4">
        <div v-if="loops.length === 0" class="text-center py-12 text-gray-400">No loops configured</div>
        <div v-else class="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <table class="w-full text-sm">
            <thead><tr class="bg-gray-50 text-gray-500 text-xs uppercase tracking-wider"><th class="text-left px-4 py-3 font-medium">Project</th><th class="text-left px-4 py-3 font-medium">Type</th><th class="text-left px-4 py-3 font-medium">Cadence</th><th class="text-left px-4 py-3 font-medium">Health</th><th class="text-right px-4 py-3 font-medium">Status</th></tr></thead>
            <tbody class="divide-y divide-gray-100"><tr v-for="l in loops" :key="l.id" class="hover:bg-gray-50"><td class="px-4 py-3 text-gray-900 font-medium">{{ l.project }}</td><td class="px-4 py-3"><span class="text-xs px-2 py-0.5 rounded-full font-medium" :class="l.type === 'remediate' ? 'bg-red-50 text-red-700' : l.type === 'optimize' ? 'bg-blue-50 text-blue-700' : l.type === 'learn' ? 'bg-purple-50 text-purple-700' : 'bg-gray-100 text-gray-600'">{{ l.type }}</span></td><td class="px-4 py-3 text-gray-500 font-mono text-xs">{{ l.cadence_seconds ? l.cadence_seconds+'s' : '—' }}</td><td class="px-4 py-3 text-xs font-medium" :class="healthColor(l.health)">{{ l.health || '—' }}</td><td class="px-4 py-3 text-right"><button @click="toggleLoop(l)" class="px-3 py-1 text-xs rounded-full border transition-colors" :class="l.enabled ? 'border-emerald-300 text-emerald-700 bg-emerald-50 hover:bg-red-50 hover:text-red-700' : 'border-gray-300 text-gray-500 hover:bg-emerald-50 hover:text-emerald-700'">{{ l.enabled ? 'enabled' : 'disabled' }}</button></td></tr></tbody>
          </table>
        </div>
      </div>
      <div v-else-if="activeTab === 'terminal'" class="space-y-4">
        <div class="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div class="px-5 py-3 border-b border-gray-200 flex items-center gap-3"><span class="text-emerald-600 text-xs font-bold">→</span><span class="text-sm font-semibold text-gray-900" style="font-family: 'Fraunces', serif;">Command Terminal</span><span class="text-xs text-gray-400">Queue tasks to the CADE orchestration pipeline</span></div>
          <div class="p-5 space-y-4">
            <div class="bg-gray-900 rounded-lg p-4 min-h-[160px]" style="font-family: 'JetBrains Mono', monospace;">
              <div v-if="terminalOutput" class="text-sm text-emerald-400 whitespace-pre-wrap mb-3">{{ terminalOutput }}</div>
              <div v-else class="text-sm text-gray-500 mb-3">Ready. Select model, kind, mode, and project below, then type a command.</div>
              <div class="flex items-center gap-2"><span class="text-emerald-500">$</span><input v-model="terminalPrompt" @keydown.enter="runTerminalCommand" placeholder="Type a command..." class="flex-1 bg-transparent text-white text-sm outline-none placeholder-gray-600" /></div>
            </div>
            <div><div class="text-xs text-gray-400 uppercase tracking-wider mb-2">AI Model</div><div class="flex flex-wrap gap-1.5"><button v-for="m in MODELS" :key="m.value" @click="selectedModel = m.value" class="px-3 py-1.5 text-xs rounded-lg border transition-colors" :class="selectedModel === m.value ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-200 hover:border-blue-300'">{{ m.label }}</button></div></div>
            <div class="grid grid-cols-2 gap-4">
              <div><div class="text-xs text-gray-400 uppercase tracking-wider mb-2">Kind</div><div class="flex flex-wrap gap-1.5"><button v-for="k in KINDS" :key="k" @click="selectedKind = k" class="px-3 py-1.5 text-xs rounded-lg border transition-colors" :class="selectedKind === k ? 'bg-gray-900 text-white border-gray-900' : 'bg-white text-gray-600 border-gray-200 hover:border-gray-400'">{{ k }}</button></div></div>
              <div><div class="text-xs text-gray-400 uppercase tracking-wider mb-2">Mode</div><div class="flex flex-wrap gap-1.5"><button v-for="m in MODES" :key="m" @click="selectedMode = m" class="px-3 py-1.5 text-xs rounded-lg border transition-colors" :class="selectedMode === m ? 'bg-gray-900 text-white border-gray-900' : 'bg-white text-gray-600 border-gray-200 hover:border-gray-400'">{{ m }}</button></div></div>
            </div>
            <div class="flex items-end gap-3">
              <div class="flex-1"><div class="text-xs text-gray-400 uppercase tracking-wider mb-2">Project</div><select v-model="selectedProject" class="w-full bg-white border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700"><option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option></select></div>
              <button @click="runTerminalCommand" :disabled="terminalLoading || !terminalPrompt.trim()" class="px-6 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-40">{{ terminalLoading ? 'Queuing...' : '→ Execute' }}</button>
            </div>
            <div class="border-t border-gray-200 pt-4"><div class="text-xs text-gray-400 uppercase tracking-wider mb-2">Quick Actions</div><div class="grid grid-cols-2 md:grid-cols-3 gap-2"><button v-for="a in QUICK_ACTIONS" :key="a.label" @click="terminalPrompt = a.cmd" class="px-3 py-2 text-xs rounded-lg border transition-colors text-left" :class="actionColor(a.domain)">{{ a.label }}</button></div></div>
            <div class="border-t border-gray-200 pt-4"><div class="text-xs text-gray-400 uppercase tracking-wider mb-3">CADE Pipeline Stages</div><div class="flex items-center gap-0 overflow-x-auto pb-2"><template v-for="(stage, i) in PIPELINE_STAGES" :key="stage"><div class="flex flex-col items-center flex-shrink-0"><div class="w-8 h-8 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center text-xs font-bold border-2 border-blue-200">{{ i + 1 }}</div><span class="text-[9px] text-gray-500 mt-1 text-center max-w-[70px] leading-tight">{{ stage }}</span></div><div v-if="i < PIPELINE_STAGES.length - 1" class="w-6 h-0.5 bg-blue-200 flex-shrink-0 mt-[-12px]"></div></template></div></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
