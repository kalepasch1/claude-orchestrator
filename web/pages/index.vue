<script setup lang="ts">
definePageMeta({ layout: 'default', alias: ['/index'] })

const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()

// ── Auth ──────────────────────────────────────────────────────────────────
const signingIn = ref(false)
async function signInWithGoogle() {
  signingIn.value = true
  try {
    await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: typeof window !== 'undefined' ? window.location.origin : undefined },
    })
  } finally { signingIn.value = false }
}
async function signOut() { await supabase.auth.signOut() }

async function authedFetch<T = any>(url: string, opts: any = {}): Promise<T> {
  const { data: { session } } = await supabase.auth.getSession()
  return $fetch<T>(url, {
    ...opts,
    headers: { ...(opts.headers || {}), ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}) },
  })
}

// ── State ─────────────────────────────────────────────────────────────────
const tasks = ref<any[]>([])
const approvals = ref<any[]>([])
const projects = ref<any[]>([])
const runners = ref<any[]>([])
const providerSpend = ref<any[]>([])
const outcomes = ref<any[]>([])
const controls = ref<any[]>([])
const expandedTask = ref<string | null>(null)

const newTask = reactive({ project_id: '', slug: '', prompt: '', kind: 'build', model: 'claude-sonnet-4-6', mode: 'build' })
const queueLoading = ref(false)
const stopLoading = ref(false)
const globalPaused = ref(false)
const approvalError = ref('')
const bulkApproving = ref(false)

// ── Models & modes ────────────────────────────────────────────────────────
const MODEL_OPTIONS = [
  { label: 'Claude Sonnet 4.6', value: 'claude-sonnet-4-6' },
  { label: 'Claude Haiku 4.5', value: 'claude-haiku-4-5-20251001' },
  { label: 'Claude Opus 4.8', value: 'claude-opus-4-8' },
  { label: 'GPT-4o', value: 'gpt-4o' },
  { label: 'GPT-4o Mini', value: 'gpt-4o-mini' },
  { label: 'Gemini 2.0 Flash', value: 'gemini/gemini-2.0-flash' },
  { label: 'Gemini 1.5 Pro', value: 'gemini/gemini-1.5-pro' },
  { label: 'Qwen2.5 Coder (local)', value: 'ollama/qwen2.5-coder:7b' },
  { label: 'Cowork Executor', value: 'cowork-executor' },
]
const MODE_OPTIONS = [
  { label: 'Build', value: 'build' },
  { label: 'Research', value: 'research' },
  { label: 'Efficiency', value: 'efficiency' },
  { label: 'Speculative', value: 'speculative' },
]
const KIND_OPTIONS = ['build', 'fix', 'research', 'qa', 'deploy', 'canary']

// ── Helpers ───────────────────────────────────────────────────────────────
const PROJECT_PRIORITY: Record<string, number> = {
  tomorrow: 2, apparently: 3, smarter: 4, 'pareto-2080': 5, beethoven: 1,
  hisanta: 6, galop: 7, 'sustainable-barks': 8,
}
function projectRank(name: any) { return PROJECT_PRIORITY[String(name || '').toLowerCase()] ?? 9 }
function sortProjects(rows: any[]) { return [...rows].sort((a, b) => projectRank(a.name) - projectRank(b.name)) }

function alive(r: any) { return (Date.now() - new Date(r.last_seen).getTime()) < 60000 }
function ago(ts: string) {
  const d = Math.round((Date.now() - new Date(ts).getTime()) / 60000)
  return d < 60 ? `${d}m ago` : d < 1440 ? `${Math.round(d / 60)}h ago` : `${Math.round(d / 1440)}d ago`
}
function makeSlug(text: string) {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 48) || `task-${Date.now()}`
}
function optimizedImprovementPrompt(text: string, projectName: string) {
  return [
    `USER-DRIVEN IMPROVEMENT for ${projectName || 'selected app'}`, '',
    text.trim(), '',
    'Route this through the orchestration pipeline:',
    '1. Use the shared orchestration contract: cheap capable preflight, cross-provider strategy planning, best available coding agent, independent QA, automatic dev merge, and batch production release.',
    '2. Coordinate with continuous improvement loops already running for this app: reuse prior shipped solutions, avoid duplicate work, and do not delete or overwrite queued improvements from other bots.',
    '3. Pick fixed-price/subscription capacity first; fall back to configured paid API routes only when that is the highest-value available path for the task.',
    '4. Use cross-model/cross-bot review before merge: one model plans, one coder implements, another model family checks the diff and legal/regulatory posture.',
    '5. Do not create manual approval, blocked_task, or paused-session interruptions unless the work would force a licensing/registration/custody/transmission/advice posture change or needs a missing secret.',
  ].join('\n')
}

const OPERATOR_KINDS = ['operator', 'legal', 'secret', 'deploy']
const isCodeMerge = (a: any) => Boolean(a.slug || /\bmerge of\b/i.test(String(a.title || '')))
const isOperatorApproval = (a: any) => {
  if (isCodeMerge(a)) return false
  const text = `${a.title || ''} ${a.why || ''}`.toLowerCase()
  return OPERATOR_KINDS.includes(a.kind) ||
    (a.kind === 'material' && /\b(legal|regulatory|compliance|business[- ]model)\b/i.test(text)) ||
    (a.kind === 'self' && /\b(credential|secret|api key|token)\b/i.test(text))
}

// ── Computed KPIs ─────────────────────────────────────────────────────────
const isNotional = (p: any) => String(p ?? '').includes('notional')
const cashMtd = computed(() => providerSpend.value.filter(s => !isNotional(s.provider)).reduce((n, s) => n + Number(s.spent || 0), 0))
const liveRunnerCount = computed(() => runners.value.filter(alive).length)
const operatorApprovals = computed(() => approvals.value.filter(isOperatorApproval).slice(0, 3))
const pendingSignOffsCount = computed(() => approvals.value.filter(isOperatorApproval).length)
const backlogCount = computed(() => tasks.value.filter(t => ['QUEUED', 'RETRY', 'BLOCKED', 'CONFLICT', 'TESTFAIL', 'WAITING'].includes(t.state)).length)
const mergedCount = computed(() => tasks.value.filter(t => t.state === 'MERGED').length)
const totalOutcomes = computed(() => outcomes.value.length)
const mergeRate = computed(() => totalOutcomes.value ? Math.round((outcomes.value.filter(o => o.integrated).length / totalOutcomes.value) * 100) : 0)
const usdPerMerge = computed(() => {
  const merged = outcomes.value.filter(o => o.integrated)
  const spend = merged.reduce((n, o) => n + Number(o.usd || 0), 0)
  return merged.length ? (spend / merged.length).toFixed(2) : null
})
const recentTasks = computed(() => tasks.value.slice(0, 20))

// ── Data loading ──────────────────────────────────────────────────────────
async function loadAll() {
  const [t, a, p, r, ps, o, ctrl] = await Promise.all([
    supabase.from('tasks').select('*').order('created_at', { ascending: false }).limit(50),
    supabase.from('approvals').select('*').eq('status', 'pending').order('created_at'),
    supabase.from('projects').select('*').order('name'),
    supabase.from('runner_heartbeats').select('*'),
    supabase.from('v_provider_spend_mtd').select('*'),
    supabase.from('outcomes').select('model,usd,project,tests_passed,integrated,created_at,slug').order('created_at').limit(500),
    supabase.from('controls').select('*'),
  ])
  tasks.value = t.data || []
  approvals.value = a.data || []
  projects.value = sortProjects(p.data || [])
  runners.value = r.data || []
  providerSpend.value = ps.data || []
  outcomes.value = o.data || []
  controls.value = ctrl.data || []
  globalPaused.value = (ctrl.data || []).some((c: any) => c.scope === 'global' && c.paused)
  if (!newTask.project_id && projects.value[0]) newTask.project_id = projects.value[0].id
}

// ── Actions ───────────────────────────────────────────────────────────────
async function queueTask(researchFirst = false) {
  if (!newTask.project_id || !newTask.prompt.trim()) return
  queueLoading.value = true
  try {
    const project = projects.value.find((p: any) => p.id === newTask.project_id)
    const slug = newTask.slug || makeSlug(newTask.prompt)
    const prompt = researchFirst
      ? `RESEARCH FIRST:\n${newTask.prompt.trim()}\n\nAfter research, produce an implementation plan and queue the build tasks.`
      : optimizedImprovementPrompt(newTask.prompt, project?.name || '')
    await supabase.from('tasks').insert({
      project_id: newTask.project_id, slug,
      prompt, kind: newTask.kind, state: 'QUEUED',
      model: newTask.model,
      note: 'pipeline:dashboard-user-driven; triage-plan-code-qa-devmerge-release',
    })
    newTask.slug = ''; newTask.prompt = ''
    await loadAll()
  } finally { queueLoading.value = false }
}

async function decide(id: string, status: 'approved' | 'denied') {
  const approver = user.value?.email || 'dashboard'
  approvalError.value = ''
  try {
    const res = await authedFetch<any>('/api/approvals/decide', { method: 'POST', body: { id, status, approver } })
    const next = res?.approval
    if (next?.status === 'pending') {
      const idx = approvals.value.findIndex(x => x.id === id)
      if (idx >= 0) approvals.value[idx] = next
    } else {
      approvals.value = approvals.value.filter(x => x.id !== id)
    }
  } catch (e: any) {
    approvalError.value = e?.data?.message || e?.message || String(e)
    alert('Sign-off failed: ' + approvalError.value)
  }
}

async function approveAll() {
  if (!operatorApprovals.value.length) return
  if (!confirm(`Approve ${operatorApprovals.value.length} sign-off(s)?`)) return
  bulkApproving.value = true
  try {
    for (const a of [...operatorApprovals.value]) {
      try { await decide(a.id, 'approved') } catch {}
    }
  } finally { bulkApproving.value = false }
}

async function stopAll() {
  stopLoading.value = true
  try {
    await supabase.from('controls').upsert({
      scope: 'global', project: null, paused: true,
      reason: 'manual stop from dashboard', updated_by: user.value?.email,
      updated_at: new Date().toISOString(),
    }, { onConflict: 'scope,project' })
    globalPaused.value = true
  } finally { stopLoading.value = false }
}

async function resumeAll() {
  stopLoading.value = true
  try {
    await supabase.from('controls').upsert({
      scope: 'global', project: null, paused: false,
      updated_by: user.value?.email, updated_at: new Date().toISOString(),
    }, { onConflict: 'scope,project' })
    globalPaused.value = false
  } finally { stopLoading.value = false }
}

// ── State color helpers ───────────────────────────────────────────────────
function stateColor(state: string) {
  const s = (state || '').toUpperCase()
  if (s === 'RUNNING') return 'text-blue-400 bg-blue-400/10'
  if (s === 'DONE') return 'text-green-400 bg-green-400/10'
  if (s === 'MERGED') return 'text-emerald-400 bg-emerald-400/10'
  if (s === 'QUEUED') return 'text-amber-400 bg-amber-400/10'
  if (['BLOCKED', 'CONFLICT', 'TESTFAIL'].includes(s)) return 'text-red-400 bg-red-400/10'
  if (s === 'RETRY') return 'text-orange-400 bg-orange-400/10'
  return 'text-slate-400 bg-slate-400/10'
}

// ── Lifecycle ─────────────────────────────────────────────────────────────
let refreshTimer: any = null
let realtimeSub: any = null

onMounted(async () => {
  if (user.value) await loadAll()
  refreshTimer = setInterval(() => { if (user.value) loadAll() }, 30000)

  realtimeSub = supabase.channel('index-live')
    .on('postgres_changes', { event: '*', schema: 'public', table: 'tasks' }, () => loadAll())
    .on('postgres_changes', { event: '*', schema: 'public', table: 'approvals' }, () => loadAll())
    .subscribe()
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  if (realtimeSub) supabase.removeChannel(realtimeSub)
})

watch(user, async (u) => { if (u) await loadAll() })
</script>

<template>
  <!-- Login gate -->
  <div v-if="!user" class="flex items-center justify-center min-h-screen bg-[#0d1117]">
    <div class="text-center space-y-6 p-8">
      <div class="text-5xl">⬡</div>
      <div>
        <h1 class="text-2xl font-bold text-white">Claude Orchestrator</h1>
        <p class="text-slate-400 mt-2">AI Platform Control Interface</p>
      </div>
      <button @click="signInWithGoogle" :disabled="signingIn"
        class="px-6 py-3 bg-blue-600 hover:bg-blue-500 text-white font-medium rounded-lg transition-colors disabled:opacity-50">
        {{ signingIn ? 'Signing in…' : 'Sign in with Google' }}
      </button>
    </div>
  </div>

  <!-- Main interface -->
  <div v-else class="min-h-screen bg-[#0d1117] text-slate-300">

    <!-- KPI Bar -->
    <div class="border-b border-slate-800 bg-slate-900/50 px-6 py-2">
      <div class="flex items-center gap-6 flex-wrap">
        <div class="flex items-center gap-1.5">
          <span class="w-2 h-2 rounded-full" :class="liveRunnerCount > 0 ? 'bg-green-400 animate-pulse' : 'bg-slate-600'"></span>
          <span class="text-xs text-slate-400">{{ liveRunnerCount }} runners</span>
        </div>
        <div class="text-xs text-slate-400">Backlog <span class="text-amber-300 font-mono font-bold">{{ backlogCount }}</span></div>
        <div class="text-xs text-slate-400">Cash MtD <span class="text-white font-mono font-bold">${{ cashMtd.toFixed(2) }}</span></div>
        <div class="text-xs text-slate-400">Merge rate <span class="text-green-300 font-mono font-bold">{{ mergeRate }}%</span></div>
        <div v-if="usdPerMerge" class="text-xs text-slate-400">$/merge <span class="text-blue-300 font-mono font-bold">${{ usdPerMerge }}</span></div>
        <NuxtLink to="/sign-offs" class="flex items-center gap-1.5 ml-auto">
          <span class="text-xs" :class="pendingSignOffsCount > 0 ? 'text-red-300' : 'text-slate-500'">
            {{ pendingSignOffsCount }} pending sign-off{{ pendingSignOffsCount !== 1 ? 's' : '' }}
          </span>
          <span v-if="pendingSignOffsCount > 0" class="inline-flex items-center justify-center w-5 h-5 bg-red-500 text-white text-xs rounded-full font-bold">!</span>
        </NuxtLink>
        <button @click="globalPaused ? resumeAll() : stopAll()" :disabled="stopLoading"
          class="px-3 py-1 text-xs rounded border transition-colors"
          :class="globalPaused ? 'border-green-600 text-green-400 hover:bg-green-400/10' : 'border-red-700 text-red-400 hover:bg-red-400/10'">
          {{ stopLoading ? '…' : globalPaused ? '▶ Resume All' : '⏹ Stop All' }}
        </button>
        <button @click="signOut" class="text-xs text-slate-600 hover:text-slate-400 transition-colors">Sign out</button>
      </div>
    </div>

    <div class="max-w-6xl mx-auto px-6 py-6 space-y-6">

      <!-- AI Command Terminal -->
      <div class="bg-slate-900 border border-slate-700 rounded-xl overflow-hidden">
        <div class="px-5 py-3 border-b border-slate-800 flex items-center gap-2">
          <span class="text-blue-400">⌘</span>
          <span class="text-sm font-semibold text-white">Command Terminal</span>
          <span class="text-xs text-slate-500 ml-1">Queue tasks directly into the orchestration pipeline</span>
        </div>
        <div class="p-5 space-y-3">
          <!-- Row 1: selectors -->
          <div class="flex gap-3 flex-wrap">
            <select v-model="newTask.project_id" class="select-dark flex-1 min-w-32">
              <option value="" disabled>Project…</option>
              <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
            <select v-model="newTask.model" class="select-dark flex-1 min-w-40">
              <option v-for="m in MODEL_OPTIONS" :key="m.value" :value="m.value">{{ m.label }}</option>
            </select>
            <select v-model="newTask.kind" class="select-dark w-32">
              <option v-for="k in KIND_OPTIONS" :key="k" :value="k">{{ k }}</option>
            </select>
            <select v-model="newTask.mode" class="select-dark w-36">
              <option v-for="m in MODE_OPTIONS" :key="m.value" :value="m.value">{{ m.label }}</option>
            </select>
          </div>
          <!-- Row 2: prompt -->
          <textarea v-model="newTask.prompt" rows="4"
            placeholder="Describe what to build, fix, or change…"
            class="w-full bg-[#0d1117] border border-slate-700 rounded-lg px-4 py-3 text-sm text-slate-200 placeholder-slate-600 resize-none focus:outline-none focus:border-blue-500 font-mono">
          </textarea>
          <!-- Optional slug -->
          <input v-model="newTask.slug" type="text" placeholder="Slug (auto-generated if blank)"
            class="w-full bg-[#0d1117] border border-slate-800 rounded-lg px-4 py-2 text-sm text-slate-300 placeholder-slate-600 focus:outline-none focus:border-slate-600" />
          <!-- Row 3: actions -->
          <div class="flex gap-3">
            <button @click="queueTask(false)" :disabled="queueLoading || !newTask.prompt.trim() || !newTask.project_id"
              class="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2">
              <span>{{ queueLoading ? 'Queuing…' : '🚀 Route & Execute' }}</span>
            </button>
            <button @click="queueTask(true)" :disabled="queueLoading || !newTask.prompt.trim() || !newTask.project_id"
              class="px-5 py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm font-medium rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2">
              <span>🔍 Research First</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Pending Sign-offs Quick Panel -->
      <div v-if="operatorApprovals.length > 0" class="bg-slate-900 border border-amber-800/40 rounded-xl overflow-hidden">
        <div class="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="text-amber-400">⚠️</span>
            <span class="text-sm font-semibold text-white">Pending Sign-offs</span>
            <span class="text-xs bg-red-500/20 text-red-300 px-2 py-0.5 rounded-full">{{ pendingSignOffsCount }}</span>
          </div>
          <div class="flex items-center gap-2">
            <button @click="approveAll" :disabled="bulkApproving"
              class="px-3 py-1 bg-green-700/40 hover:bg-green-700/60 text-green-300 text-xs rounded-lg transition-colors disabled:opacity-50">
              {{ bulkApproving ? 'Approving…' : `Approve All (${operatorApprovals.length})` }}
            </button>
            <NuxtLink to="/sign-offs" class="text-xs text-blue-400 hover:text-blue-300 transition-colors">View all →</NuxtLink>
          </div>
        </div>
        <div class="divide-y divide-slate-800">
          <div v-for="a in operatorApprovals" :key="a.id" class="px-5 py-3 flex items-start gap-4">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 mb-1">
                <span class="text-xs px-2 py-0.5 rounded-full font-medium"
                  :class="a.kind === 'legal' ? 'bg-red-500/20 text-red-300' : a.kind === 'deploy' ? 'bg-blue-500/20 text-blue-300' : 'bg-amber-500/20 text-amber-300'">
                  {{ a.kind }}
                </span>
                <span v-if="a.project" class="text-xs text-slate-500">{{ a.project }}</span>
              </div>
              <div class="text-sm text-slate-200 font-medium truncate">{{ a.title }}</div>
              <div v-if="a.why" class="text-xs text-slate-500 mt-0.5 line-clamp-1">{{ a.why }}</div>
            </div>
            <div class="flex gap-2 flex-shrink-0">
              <button @click="decide(a.id, 'approved')" class="px-3 py-1 bg-green-700/30 hover:bg-green-700/50 text-green-300 text-xs rounded-lg transition-colors">Approve</button>
              <button @click="decide(a.id, 'denied')" class="px-3 py-1 bg-red-700/30 hover:bg-red-700/50 text-red-300 text-xs rounded-lg transition-colors">Deny</button>
            </div>
          </div>
        </div>
        <div v-if="approvalError" class="px-5 py-2 text-xs text-red-400 bg-red-500/10 border-t border-red-800/30">{{ approvalError }}</div>
      </div>

      <!-- Live Activity Feed -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <div class="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="text-green-400">●</span>
            <span class="text-sm font-semibold text-white">Live Activity</span>
            <span class="text-xs text-slate-500">last 20 tasks</span>
          </div>
          <NuxtLink to="/queue" class="text-xs text-blue-400 hover:text-blue-300 transition-colors">Full queue →</NuxtLink>
        </div>
        <div class="divide-y divide-slate-800/60">
          <div v-if="recentTasks.length === 0" class="px-5 py-8 text-center text-slate-600 text-sm">No tasks yet</div>
          <div v-for="t in recentTasks" :key="t.id"
            class="px-5 py-3 hover:bg-slate-800/30 transition-colors cursor-pointer"
            @click="expandedTask = expandedTask === t.id ? null : t.id">
            <div class="flex items-center gap-3">
              <span class="text-xs px-2 py-0.5 rounded-full font-mono font-medium" :class="stateColor(t.state)">
                {{ t.state }}
              </span>
              <span class="text-sm text-slate-200 truncate flex-1 font-mono">{{ t.slug }}</span>
              <span v-if="t.project_id" class="text-xs text-slate-500 hidden sm:block">{{ projects.find(p=>p.id===t.project_id)?.name }}</span>
              <span v-if="t.model" class="text-xs text-slate-600 hidden md:block truncate max-w-24">{{ t.model }}</span>
              <span class="text-xs text-slate-600 flex-shrink-0">{{ t.created_at ? ago(t.created_at) : '' }}</span>
              <span :class="t.state === 'RUNNING' ? 'text-blue-400 animate-pulse' : 'text-slate-700'" class="text-xs">▼</span>
            </div>
            <!-- Expandable log_tail -->
            <div v-if="expandedTask === t.id" class="mt-3 p-3 bg-[#0d1117] rounded-lg border border-slate-800">
              <div class="text-xs text-slate-500 mb-2">{{ t.prompt?.slice(0, 200) }}{{ t.prompt?.length > 200 ? '…' : '' }}</div>
              <pre v-if="t.log_tail" class="text-xs text-green-300 font-mono whitespace-pre-wrap overflow-x-auto max-h-48 overflow-y-auto">{{ t.log_tail }}</pre>
              <div v-else class="text-xs text-slate-600 italic">No log output yet</div>
            </div>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>

<style scoped>
.select-dark {
  @apply bg-slate-800 border border-slate-700 text-slate-200 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 cursor-pointer;
}
</style>
