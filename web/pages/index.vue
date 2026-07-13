<script setup lang="ts">
definePageMeta({ layout: 'default' })

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
const capabilities = ref<any[]>([])
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

// ── Capability helpers ────────────────────────────────────────────────────
function capStatusDot(status: string) {
  if (status === 'trusted') return 'bg-blue-500'
  if (status === 'experimental') return 'bg-yellow-500'
  return 'bg-gray-300'
}
function capMaturityColor(n: number) {
  if (n >= 80) return 'bg-emerald-500'
  if (n >= 50) return 'bg-emerald-400'
  return 'bg-gray-300'
}

// ── State color helpers ───────────────────────────────────────────────────
function stateColor(state: string) {
  const s = (state || '').toUpperCase()
  if (s === 'RUNNING') return 'text-blue-700 bg-blue-50'
  if (s === 'DONE') return 'text-emerald-700 bg-emerald-50'
  if (s === 'MERGED') return 'text-blue-600 bg-blue-50'
  if (s === 'QUEUED') return 'text-gray-600 bg-gray-100'
  if (['BLOCKED', 'CONFLICT', 'TESTFAIL'].includes(s)) return 'text-red-700 bg-red-50'
  if (s === 'RETRY') return 'text-orange-700 bg-orange-50'
  return 'text-gray-500 bg-gray-100'
}

// ── Data loading ──────────────────────────────────────────────────────────
async function loadAll() {
  const [t, a, p, r, ps, o, ctrl, cap] = await Promise.all([
    supabase.from('tasks').select('*').order('created_at', { ascending: false }).limit(50),
    supabase.from('approvals').select('*').eq('status', 'pending').order('created_at'),
    supabase.from('projects').select('*').order('name'),
    supabase.from('runner_heartbeats').select('*'),
    supabase.from('v_provider_spend_mtd').select('*'),
    supabase.from('outcomes').select('model,usd,project,tests_passed,integrated,created_at,slug').order('created_at').limit(500),
    supabase.from('controls').select('*'),
    supabase.from('capabilities').select('*'),
  ])
  tasks.value = t.data || []
  approvals.value = a.data || []
  projects.value = sortProjects(p.data || [])
  runners.value = r.data || []
  providerSpend.value = ps.data || []
  outcomes.value = o.data || []
  controls.value = ctrl.data || []
  capabilities.value = cap.data || []
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
  <!-- Sign-in gate -->
  <div v-if="!user" class="flex items-center justify-center min-h-screen bg-white">
    <div class="text-center space-y-8 p-10 max-w-sm">
      <div>
        <div class="text-2xl tracking-[0.3em] uppercase text-gray-900 mb-2" style="font-family: 'Fraunces', serif;">ORCHESTRATOR</div>
        <p class="text-sm text-gray-500 tracking-wide">AI Control Platform</p>
      </div>
      <button @click="signInWithGoogle" :disabled="signingIn"
        class="w-full px-6 py-3 bg-emerald-600 hover:bg-emerald-700 text-white font-medium rounded-lg transition-colors disabled:opacity-50 text-sm tracking-wide">
        {{ signingIn ? 'Signing in...' : 'Sign in with Google' }}
      </button>
    </div>
  </div>

  <!-- Main interface -->
  <div v-else class="min-h-screen bg-white text-gray-900">

    <!-- Status bar -->
    <div class="border-b border-gray-200 bg-white px-6 py-2 sticky top-0 z-10">
      <div class="flex items-center gap-5 flex-wrap text-[11px]">
        <div class="flex items-center gap-1.5">
          <span
            class="w-1.5 h-1.5 rounded-full flex-shrink-0"
            :class="liveRunnerCount > 0 ? 'bg-emerald-600 dot-breathe' : 'bg-gray-300'"
          ></span>
          <span class="text-gray-500">{{ liveRunnerCount }} running</span>
        </div>
        <span class="text-gray-200">·</span>
        <span class="text-gray-500">{{ backlogCount.toLocaleString() }} queued</span>
        <span class="text-gray-200">·</span>
        <span class="text-gray-500">${{ cashMtd.toFixed(2) }} MtD</span>
        <span class="text-gray-200">·</span>
        <span class="text-gray-500">{{ mergeRate }}% merge</span>
        <span class="text-gray-200">·</span>
        <NuxtLink to="/sign-offs" class="flex items-center gap-1.5" :class="pendingSignOffsCount > 0 ? 'text-red-600' : 'text-gray-500'">
          {{ pendingSignOffsCount }} sign-off{{ pendingSignOffsCount !== 1 ? 's' : '' }}
        </NuxtLink>
        <div class="ml-auto flex items-center gap-3">
          <button
            @click="globalPaused ? resumeAll() : stopAll()"
            :disabled="stopLoading"
            class="px-2.5 py-1 rounded border text-[11px] transition-colors"
            :class="globalPaused ? 'border-emerald-700 text-emerald-600 hover:bg-emerald-50' : 'border-red-300 text-red-600 hover:bg-red-50'"
          >
            {{ stopLoading ? '...' : globalPaused ? '▶ Resume' : '■ Stop All' }}
          </button>
          <button @click="signOut" class="text-gray-400 hover:text-gray-500 transition-colors">Sign out</button>
        </div>
      </div>
    </div>

    <div class="max-w-6xl mx-auto px-6 py-6 space-y-6">

      <!-- Command Terminal -->
      <div class="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-200 flex items-center gap-3">
          <span class="text-emerald-600 text-xs">→</span>
          <span class="text-sm font-medium text-gray-900" style="font-family: 'Fraunces', serif;">Command Terminal</span>
          <span class="text-xs text-gray-400 ml-1">Route tasks into the orchestration pipeline</span>
        </div>
        <div class="p-5 space-y-3">
          <!-- Selectors -->
          <div class="flex gap-3 flex-wrap">
            <select
              v-model="newTask.project_id"
              class="bg-gray-50 border border-gray-300 text-gray-800 text-sm rounded px-3 py-2 focus:outline-none focus:border-emerald-700 cursor-pointer flex-1 min-w-32"
            >
              <option value="" disabled>Project</option>
              <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
            <select
              v-model="newTask.model"
              class="bg-gray-50 border border-gray-300 text-gray-800 text-sm rounded px-3 py-2 focus:outline-none focus:border-emerald-700 cursor-pointer flex-1 min-w-40"
            >
              <option v-for="m in MODEL_OPTIONS" :key="m.value" :value="m.value">{{ m.label }}</option>
            </select>
            <select
              v-model="newTask.kind"
              class="bg-gray-50 border border-gray-300 text-gray-800 text-sm rounded px-3 py-2 focus:outline-none focus:border-emerald-700 cursor-pointer w-32"
            >
              <option v-for="k in KIND_OPTIONS" :key="k" :value="k">{{ k }}</option>
            </select>
            <select
              v-model="newTask.mode"
              class="bg-gray-50 border border-gray-300 text-gray-800 text-sm rounded px-3 py-2 focus:outline-none focus:border-emerald-700 cursor-pointer w-36"
            >
              <option v-for="m in MODE_OPTIONS" :key="m.value" :value="m.value">{{ m.label }}</option>
            </select>
          </div>
          <!-- Prompt -->
          <textarea
            v-model="newTask.prompt"
            rows="4"
            placeholder="Describe what to build, fix, or improve..."
            class="w-full bg-gray-50 border border-gray-300 text-gray-800 text-sm rounded px-4 py-3 placeholder-gray-400 resize-none focus:outline-none focus:border-emerald-700"
            style="font-family: 'JetBrains Mono', monospace;"
          ></textarea>
          <!-- Slug -->
          <input
            v-model="newTask.slug"
            type="text"
            placeholder="Slug (auto-generated if blank)"
            class="w-full bg-gray-50 border border-gray-200 text-gray-600 text-sm rounded px-4 py-2 placeholder-gray-400 focus:outline-none focus:border-gray-300"
          />
          <!-- Actions -->
          <div class="flex gap-3">
            <button
              @click="queueTask(false)"
              :disabled="queueLoading || !newTask.prompt.trim() || !newTask.project_id"
              class="px-5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {{ queueLoading ? 'Queuing...' : '→ Route & Execute' }}
            </button>
            <button
              @click="queueTask(true)"
              :disabled="queueLoading || !newTask.prompt.trim() || !newTask.project_id"
              class="px-5 py-2 border border-gray-300 text-gray-500 hover:text-gray-800 hover:border-emerald-700 text-sm rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Research First
            </button>
          </div>
        </div>
      </div>

      <!-- Capabilities -->
      <div v-if="capabilities.length > 0">
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-xs uppercase tracking-[0.15em] text-gray-400" style="font-family: 'Fraunces', serif;">Capabilities</h2>
          <NuxtLink to="/orchestrators" class="text-xs text-gray-500 hover:text-emerald-600 transition-colors">View all →</NuxtLink>
        </div>
        <div class="flex gap-3 overflow-x-auto pb-2 -mx-1 px-1">
          <NuxtLink
            v-for="cap in capabilities"
            :key="cap.id"
            :to="`/orchestrators?cap=${cap.id}`"
            class="flex-shrink-0 w-44 bg-white border border-gray-200 rounded-lg p-3 hover:border-emerald-700 transition-colors cursor-pointer"
          >
            <div class="flex items-start justify-between mb-2">
              <span class="text-xs font-medium text-gray-800 leading-tight">{{ cap.name }}</span>
              <span class="w-1.5 h-1.5 rounded-full flex-shrink-0 mt-0.5 ml-2" :class="capStatusDot(cap.status || cap.maturity_status || 'draft')"></span>
            </div>
            <div v-if="cap.domain" class="mb-2">
              <span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-50 text-gray-500 border border-gray-200">{{ cap.domain }}</span>
            </div>
            <div class="w-full h-0.5 bg-gray-200 rounded-full overflow-hidden">
              <div
                class="h-full rounded-full transition-all"
                :class="capMaturityColor(cap.maturity || 0)"
                :style="{ width: (cap.maturity || 0) + '%' }"
              ></div>
            </div>
          </NuxtLink>
        </div>
      </div>

      <!-- Pending Sign-offs -->
      <div v-if="operatorApprovals.length > 0" class="bg-white border border-red-200 rounded-lg overflow-hidden">
        <div class="px-5 py-3 border-b border-red-200 flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="text-red-600 text-xs">○</span>
            <span class="text-sm font-medium text-gray-900" style="font-family: 'Fraunces', serif;">Pending Sign-offs</span>
            <span class="text-[10px] bg-red-100 text-red-600 px-2 py-0.5 rounded-full">{{ pendingSignOffsCount }}</span>
          </div>
          <div class="flex items-center gap-3">
            <button
              @click="approveAll"
              :disabled="bulkApproving"
              class="px-3 py-1 bg-emerald-50 hover:bg-emerald-600 text-emerald-600 hover:text-white text-xs rounded border border-emerald-300 transition-colors disabled:opacity-50"
            >
              {{ bulkApproving ? 'Approving...' : `Approve All (${operatorApprovals.length})` }}
            </button>
            <NuxtLink to="/sign-offs" class="text-xs text-gray-500 hover:text-emerald-600 transition-colors">View all →</NuxtLink>
          </div>
        </div>
        <div class="divide-y divide-gray-200">
          <div v-for="a in operatorApprovals" :key="a.id" class="px-5 py-4">
            <!-- CADE mini brief -->
            <div class="flex items-start justify-between gap-4 mb-3">
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 flex-wrap mb-1.5">
                  <span class="text-[10px] px-2 py-0.5 rounded border font-medium"
                    :class="a.kind === 'legal' ? 'bg-red-50 text-red-600 border-red-300' : a.kind === 'deploy' ? 'bg-blue-50 text-blue-600 border-blue-300' : 'bg-emerald-50 text-emerald-600 border-emerald-300'">
                    {{ a.kind }}
                  </span>
                  <span v-if="a.project" class="text-[10px] text-gray-400 bg-gray-100 px-2 py-0.5 rounded border border-gray-200">{{ a.project }}</span>
                  <span class="text-[10px] text-gray-400 ml-auto">{{ a.created_at ? ago(a.created_at) : '' }}</span>
                </div>
                <div class="text-sm font-medium text-gray-800 mb-2">{{ a.title }}</div>
                <div class="space-y-1 text-xs">
                  <div><span class="text-gray-400 font-medium mr-2">C</span><span class="text-gray-600">{{ a.why || 'Authorization required for this action.' }}</span></div>
                  <div><span class="text-gray-400 font-medium mr-2">D</span>
                    <span class="text-emerald-600">Approve = {{ a.value || 'proceed' }}</span>
                    <span class="text-gray-400 mx-1">·</span>
                    <span class="text-red-600">Deny = {{ a.risk || 'blocks dependent tasks' }}</span>
                  </div>
                </div>
              </div>
              <div class="flex flex-col gap-2 flex-shrink-0">
                <button @click="decide(a.id, 'approved')" class="px-3 py-1.5 bg-emerald-50 hover:bg-emerald-600 text-emerald-600 hover:text-white text-xs rounded border border-emerald-300 transition-colors">Approve</button>
                <button @click="decide(a.id, 'denied')" class="px-3 py-1.5 bg-red-50 hover:bg-red-100 text-red-600 text-xs rounded border border-red-300 transition-colors">Deny</button>
              </div>
            </div>
          </div>
        </div>
        <div v-if="approvalError" class="px-5 py-2 text-xs text-red-600 bg-red-50 border-t border-red-200">{{ approvalError }}</div>
      </div>

      <!-- Live Activity -->
      <div class="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-200 flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-600 dot-breathe"></span>
            <span class="text-sm font-medium text-gray-900" style="font-family: 'Fraunces', serif;">Live Activity</span>
            <span class="text-xs text-gray-400">last 20 tasks</span>
          </div>
          <NuxtLink to="/queue" class="text-xs text-gray-500 hover:text-emerald-600 transition-colors">Full queue →</NuxtLink>
        </div>
        <div class="divide-y divide-gray-50">
          <div v-if="recentTasks.length === 0" class="px-5 py-10 text-center text-gray-400 text-sm">No tasks yet</div>
          <div
            v-for="t in recentTasks"
            :key="t.id"
            class="px-5 py-2.5 hover:bg-gray-50 transition-colors cursor-pointer"
            @click="expandedTask = expandedTask === t.id ? null : t.id"
          >
            <div class="flex items-center gap-3">
              <span
                class="text-[10px] px-2 py-0.5 rounded font-mono font-medium flex-shrink-0"
                :class="stateColor(t.state)"
              >{{ t.state }}</span>
              <span class="text-xs text-gray-600 truncate flex-1 font-mono">{{ t.slug }}</span>
              <span v-if="t.project_id" class="text-[10px] text-gray-400 hidden sm:block">{{ projects.find(p => p.id === t.project_id)?.name }}</span>
              <span class="text-[10px] text-gray-400 flex-shrink-0">{{ t.created_at ? ago(t.created_at) : '' }}</span>
              <span class="text-[10px]" :class="t.state === 'RUNNING' ? 'text-emerald-600' : 'text-gray-200'">▼</span>
            </div>
            <div v-if="expandedTask === t.id" class="mt-2 p-3 bg-gray-50 rounded border border-gray-200">
              <div class="text-xs text-gray-500 mb-2 font-mono">{{ t.prompt?.slice(0, 200) }}{{ t.prompt?.length > 200 ? '...' : '' }}</div>
              <pre v-if="t.log_tail" class="text-xs text-emerald-600 font-mono whitespace-pre-wrap overflow-x-auto max-h-40 overflow-y-auto">{{ t.log_tail }}</pre>
              <div v-else class="text-xs text-gray-400 italic">No log output yet</div>
            </div>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>
