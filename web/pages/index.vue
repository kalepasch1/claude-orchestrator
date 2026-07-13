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
  if (status === 'trusted') return 'bg-[#6fcf8a]'
  if (status === 'experimental') return 'bg-yellow-400'
  return 'bg-[#3a5a3a]'
}
function capMaturityColor(n: number) {
  if (n >= 80) return 'bg-[#2d7a3a]'
  if (n >= 50) return 'bg-[#1e5228]'
  return 'bg-[#162016]'
}

// ── State color helpers ───────────────────────────────────────────────────
function stateColor(state: string) {
  const s = (state || '').toUpperCase()
  if (s === 'RUNNING') return 'text-[#6fcf8a] bg-[#0a1e0e]'
  if (s === 'DONE') return 'text-[#4ade80] bg-[#052e10]'
  if (s === 'MERGED') return 'text-[#60a5fa] bg-[#0c1e38]'
  if (s === 'QUEUED') return 'text-[#7a9a7a] bg-[#0a120a]'
  if (['BLOCKED', 'CONFLICT', 'TESTFAIL'].includes(s)) return 'text-[#f87171] bg-[#2a0808]'
  if (s === 'RETRY') return 'text-orange-400 bg-orange-400/10'
  return 'text-[#5a7a5a] bg-[#0a120a]'
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
  <div v-if="!user" class="flex items-center justify-center min-h-screen bg-[#07090a]">
    <div class="text-center space-y-8 p-10 max-w-sm">
      <div>
        <div class="text-2xl tracking-[0.3em] uppercase text-[#dde5dd] mb-2" style="font-family: 'Fraunces', serif;">ORCHESTRATOR</div>
        <p class="text-sm text-[#3a5a3a] tracking-wide">AI Control Platform</p>
      </div>
      <button
        @click="signInWithGoogle"
        :disabled="signingIn"
        class="w-full px-6 py-3 bg-[#1e5228] hover:bg-[#2d7a3a] text-white font-medium rounded-lg transition-colors disabled:opacity-50 text-sm tracking-wide"
      >
        {{ signingIn ? 'Signing in...' : 'Sign in with Google' }}
      </button>
    </div>
  </div>

  <!-- Main interface -->
  <div v-else class="min-h-screen bg-[#07090a] text-[#dde5dd]">

    <!-- Status bar -->
    <div class="border-b border-[#162016] bg-[#07090a] px-6 py-2 sticky top-0 z-10">
      <div class="flex items-center gap-5 flex-wrap text-[11px]">
        <div class="flex items-center gap-1.5">
          <span
            class="w-1.5 h-1.5 rounded-full flex-shrink-0"
            :class="liveRunnerCount > 0 ? 'bg-[#6fcf8a] dot-breathe' : 'bg-[#1e2e1e]'"
          ></span>
          <span class="text-[#5a7a5a]">{{ liveRunnerCount }} running</span>
        </div>
        <span class="text-[#162016]">·</span>
        <span class="text-[#5a7a5a]">{{ backlogCount.toLocaleString() }} queued</span>
        <span class="text-[#162016]">·</span>
        <span class="text-[#5a7a5a]">${{ cashMtd.toFixed(2) }} MtD</span>
        <span class="text-[#162016]">·</span>
        <span class="text-[#5a7a5a]">{{ mergeRate }}% merge</span>
        <span class="text-[#162016]">·</span>
        <NuxtLink to="/sign-offs" class="flex items-center gap-1.5" :class="pendingSignOffsCount > 0 ? 'text-red-400' : 'text-[#5a7a5a]'">
          {{ pendingSignOffsCount }} sign-off{{ pendingSignOffsCount !== 1 ? 's' : '' }}
        </NuxtLink>
        <div class="ml-auto flex items-center gap-3">
          <button
            @click="globalPaused ? resumeAll() : stopAll()"
            :disabled="stopLoading"
            class="px-2.5 py-1 rounded border text-[11px] transition-colors"
            :class="globalPaused ? 'border-[#2d7a3a] text-[#6fcf8a] hover:bg-[#0f2014]' : 'border-[#3a1010] text-[#f87171] hover:bg-[#1a0808]'"
          >
            {{ stopLoading ? '...' : globalPaused ? '▶ Resume' : '■ Stop All' }}
          </button>
          <button @click="signOut" class="text-[#3a5a3a] hover:text-[#5a7a5a] transition-colors">Sign out</button>
        </div>
      </div>
    </div>

    <div class="max-w-6xl mx-auto px-6 py-6 space-y-6">

      <!-- Command Terminal -->
      <div class="bg-[#0c110c] border border-[#162016] rounded-lg overflow-hidden">
        <div class="px-5 py-3 border-b border-[#162016] flex items-center gap-3">
          <span class="text-[#6fcf8a] text-xs">→</span>
          <span class="text-sm font-medium text-[#dde5dd]" style="font-family: 'Fraunces', serif;">Command Terminal</span>
          <span class="text-xs text-[#3a5a3a] ml-1">Route tasks into the orchestration pipeline</span>
        </div>
        <div class="p-5 space-y-3">
          <!-- Selectors -->
          <div class="flex gap-3 flex-wrap">
            <select
              v-model="newTask.project_id"
              class="bg-[#070c07] border border-[#1e2e1e] text-[#c8d8c8] text-sm rounded px-3 py-2 focus:outline-none focus:border-[#2d7a3a] cursor-pointer flex-1 min-w-32"
            >
              <option value="" disabled>Project</option>
              <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
            <select
              v-model="newTask.model"
              class="bg-[#070c07] border border-[#1e2e1e] text-[#c8d8c8] text-sm rounded px-3 py-2 focus:outline-none focus:border-[#2d7a3a] cursor-pointer flex-1 min-w-40"
            >
              <option v-for="m in MODEL_OPTIONS" :key="m.value" :value="m.value">{{ m.label }}</option>
            </select>
            <select
              v-model="newTask.kind"
              class="bg-[#070c07] border border-[#1e2e1e] text-[#c8d8c8] text-sm rounded px-3 py-2 focus:outline-none focus:border-[#2d7a3a] cursor-pointer w-32"
            >
              <option v-for="k in KIND_OPTIONS" :key="k" :value="k">{{ k }}</option>
            </select>
            <select
              v-model="newTask.mode"
              class="bg-[#070c07] border border-[#1e2e1e] text-[#c8d8c8] text-sm rounded px-3 py-2 focus:outline-none focus:border-[#2d7a3a] cursor-pointer w-36"
            >
              <option v-for="m in MODE_OPTIONS" :key="m.value" :value="m.value">{{ m.label }}</option>
            </select>
          </div>
          <!-- Prompt -->
          <textarea
            v-model="newTask.prompt"
            rows="4"
            placeholder="Describe what to build, fix, or improve..."
            class="w-full bg-[#070c07] border border-[#1e2e1e] text-[#c8d8c8] text-sm rounded px-4 py-3 placeholder-[#3a5a3a] resize-none focus:outline-none focus:border-[#2d7a3a]"
            style="font-family: 'JetBrains Mono', monospace;"
          ></textarea>
          <!-- Slug -->
          <input
            v-model="newTask.slug"
            type="text"
            placeholder="Slug (auto-generated if blank)"
            class="w-full bg-[#070c07] border border-[#162016] text-[#7a9a7a] text-sm rounded px-4 py-2 placeholder-[#3a5a3a] focus:outline-none focus:border-[#1e2e1e]"
          />
          <!-- Actions -->
          <div class="flex gap-3">
            <button
              @click="queueTask(false)"
              :disabled="queueLoading || !newTask.prompt.trim() || !newTask.project_id"
              class="px-5 py-2 bg-[#1e5228] hover:bg-[#2d7a3a] text-white text-sm font-medium rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {{ queueLoading ? 'Queuing...' : '→ Route & Execute' }}
            </button>
            <button
              @click="queueTask(true)"
              :disabled="queueLoading || !newTask.prompt.trim() || !newTask.project_id"
              class="px-5 py-2 border border-[#1e2e1e] text-[#5a7a5a] hover:text-[#c8d8c8] hover:border-[#2d7a3a] text-sm rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Research First
            </button>
          </div>
        </div>
      </div>

      <!-- Capabilities -->
      <div v-if="capabilities.length > 0">
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-xs uppercase tracking-[0.15em] text-[#3a5a3a]" style="font-family: 'Fraunces', serif;">Capabilities</h2>
          <NuxtLink to="/orchestrators" class="text-xs text-[#5a7a5a] hover:text-[#6fcf8a] transition-colors">View all →</NuxtLink>
        </div>
        <div class="flex gap-3 overflow-x-auto pb-2 -mx-1 px-1">
          <NuxtLink
            v-for="cap in capabilities"
            :key="cap.id"
            to="/orchestrators"
            class="flex-shrink-0 w-44 bg-[#0c110c] border border-[#162016] rounded-lg p-3 hover:border-[#2d7a3a] transition-colors cursor-pointer"
          >
            <div class="flex items-start justify-between mb-2">
              <span class="text-xs font-medium text-[#c8d8c8] leading-tight">{{ cap.name }}</span>
              <span class="w-1.5 h-1.5 rounded-full flex-shrink-0 mt-0.5 ml-2" :class="capStatusDot(cap.status || cap.maturity_status || 'draft')"></span>
            </div>
            <div v-if="cap.domain" class="mb-2">
              <span class="text-[10px] px-1.5 py-0.5 rounded bg-[#0f2014] text-[#5a7a5a] border border-[#162016]">{{ cap.domain }}</span>
            </div>
            <div class="w-full h-0.5 bg-[#162016] rounded-full overflow-hidden">
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
      <div v-if="operatorApprovals.length > 0" class="bg-[#0c110c] border border-[#2a1010] rounded-lg overflow-hidden">
        <div class="px-5 py-3 border-b border-[#1e1010] flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="text-[#f87171] text-xs">○</span>
            <span class="text-sm font-medium text-[#dde5dd]" style="font-family: 'Fraunces', serif;">Pending Sign-offs</span>
            <span class="text-[10px] bg-red-500/20 text-red-400 px-2 py-0.5 rounded-full">{{ pendingSignOffsCount }}</span>
          </div>
          <div class="flex items-center gap-3">
            <button
              @click="approveAll"
              :disabled="bulkApproving"
              class="px-3 py-1 bg-[#0f2014] hover:bg-[#1e5228] text-[#6fcf8a] text-xs rounded border border-[#1c3a1c] transition-colors disabled:opacity-50"
            >
              {{ bulkApproving ? 'Approving...' : `Approve All (${operatorApprovals.length})` }}
            </button>
            <NuxtLink to="/sign-offs" class="text-xs text-[#5a7a5a] hover:text-[#6fcf8a] transition-colors">View all →</NuxtLink>
          </div>
        </div>
        <div class="divide-y divide-[#162016]">
          <div v-for="a in operatorApprovals" :key="a.id" class="px-5 py-4">
            <!-- CADE mini brief -->
            <div class="flex items-start justify-between gap-4 mb-3">
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 flex-wrap mb-1.5">
                  <span class="text-[10px] px-2 py-0.5 rounded border font-medium"
                    :class="a.kind === 'legal' ? 'bg-red-500/10 text-red-400 border-red-800/40' : a.kind === 'deploy' ? 'bg-blue-500/10 text-blue-400 border-blue-800/40' : 'bg-[#0f2014] text-[#6fcf8a] border-[#1c3a1c]'">
                    {{ a.kind }}
                  </span>
                  <span v-if="a.project" class="text-[10px] text-[#3a5a3a] bg-[#0a120a] px-2 py-0.5 rounded border border-[#162016]">{{ a.project }}</span>
                  <span class="text-[10px] text-[#3a5a3a] ml-auto">{{ a.created_at ? ago(a.created_at) : '' }}</span>
                </div>
                <div class="text-sm font-medium text-[#c8d8c8] mb-2">{{ a.title }}</div>
                <div class="space-y-1 text-xs">
                  <div><span class="text-[#3a5a3a] font-medium mr-2">C</span><span class="text-[#7a9a7a]">{{ a.why || 'Authorization required for this action.' }}</span></div>
                  <div><span class="text-[#3a5a3a] font-medium mr-2">D</span>
                    <span class="text-[#6fcf8a]">Approve = {{ a.value || 'proceed' }}</span>
                    <span class="text-[#3a5a3a] mx-1">·</span>
                    <span class="text-[#f87171]">Deny = {{ a.risk || 'blocks dependent tasks' }}</span>
                  </div>
                </div>
              </div>
              <div class="flex flex-col gap-2 flex-shrink-0">
                <button @click="decide(a.id, 'approved')" class="px-3 py-1.5 bg-[#0f2014] hover:bg-[#1e5228] text-[#6fcf8a] text-xs rounded border border-[#1c3a1c] transition-colors">Approve</button>
                <button @click="decide(a.id, 'denied')" class="px-3 py-1.5 bg-[#1a0808] hover:bg-[#2a1010] text-[#f87171] text-xs rounded border border-[#3a1010] transition-colors">Deny</button>
              </div>
            </div>
          </div>
        </div>
        <div v-if="approvalError" class="px-5 py-2 text-xs text-red-400 bg-red-500/10 border-t border-red-800/30">{{ approvalError }}</div>
      </div>

      <!-- Live Activity -->
      <div class="bg-[#0c110c] border border-[#162016] rounded-lg overflow-hidden">
        <div class="px-5 py-3 border-b border-[#162016] flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="w-1.5 h-1.5 rounded-full bg-[#6fcf8a] dot-breathe"></span>
            <span class="text-sm font-medium text-[#dde5dd]" style="font-family: 'Fraunces', serif;">Live Activity</span>
            <span class="text-xs text-[#3a5a3a]">last 20 tasks</span>
          </div>
          <NuxtLink to="/queue" class="text-xs text-[#5a7a5a] hover:text-[#6fcf8a] transition-colors">Full queue →</NuxtLink>
        </div>
        <div class="divide-y divide-[#0f180f]">
          <div v-if="recentTasks.length === 0" class="px-5 py-10 text-center text-[#3a5a3a] text-sm">No tasks yet</div>
          <div
            v-for="t in recentTasks"
            :key="t.id"
            class="px-5 py-2.5 hover:bg-[#0f180f] transition-colors cursor-pointer"
            @click="expandedTask = expandedTask === t.id ? null : t.id"
          >
            <div class="flex items-center gap-3">
              <span
                class="text-[10px] px-2 py-0.5 rounded font-mono font-medium flex-shrink-0"
                :class="stateColor(t.state)"
              >{{ t.state }}</span>
              <span class="text-xs text-[#7a9a7a] truncate flex-1 font-mono">{{ t.slug }}</span>
              <span v-if="t.project_id" class="text-[10px] text-[#3a5a3a] hidden sm:block">{{ projects.find(p => p.id === t.project_id)?.name }}</span>
              <span class="text-[10px] text-[#3a5a3a] flex-shrink-0">{{ t.created_at ? ago(t.created_at) : '' }}</span>
              <span class="text-[10px]" :class="t.state === 'RUNNING' ? 'text-[#6fcf8a]' : 'text-[#162016]'">▼</span>
            </div>
            <div v-if="expandedTask === t.id" class="mt-2 p-3 bg-[#070c07] rounded border border-[#162016]">
              <div class="text-xs text-[#5a7a5a] mb-2 font-mono">{{ t.prompt?.slice(0, 200) }}{{ t.prompt?.length > 200 ? '...' : '' }}</div>
              <pre v-if="t.log_tail" class="text-xs text-[#6fcf8a] font-mono whitespace-pre-wrap overflow-x-auto max-h-40 overflow-y-auto">{{ t.log_tail }}</pre>
              <div v-else class="text-xs text-[#3a5a3a] italic">No log output yet</div>
            </div>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>
