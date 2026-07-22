<script setup lang="ts">
import { deriveDecisionBrief } from '~/utils/decisionBrief'
import type { LogLine } from '~/types/log'
definePageMeta({ layout: 'default', alias: ['/index'] })

const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()
const tasks = ref<any[]>([])
const approvals = ref<any[]>([])
const projects = ref<any[]>([])
const runners = ref<any[]>([])
const providerSpend = ref<any[]>([])
const outcomes = ref<any[]>([])
const capabilities = ref<any[]>([])
const expandedTask = ref<string | null>(null)
const intent = ref('')
const selectedProject = ref('')
const projectChoice = ref<{ message: string; projects: Array<{ id: string; name: string }> } | null>(null)
const queueLoading = ref(false)
const queueError = ref('')
const lastRoute = ref<any>(null)
const stopLoading = ref(false)
const globalPaused = ref(false)
const approvalError = ref('')

// ── run_logs realtime ring buffer ────────────────────────────────────────────
const LOG_RING_MAX = 500
const logLines = ref<LogLine[]>([])

function pushLogRow(row: { ts?: string; level?: string; source?: string; message?: string }) {
  const line: LogLine = {
    ts: row.ts ?? new Date().toISOString(),
    level: (['debug', 'info', 'warn', 'error'].includes(row.level ?? '') ? row.level : 'info') as LogLine['level'],
    source: row.source ?? undefined,
    message: row.message ?? '',
  }
  const buf = logLines.value
  buf.push(line)
  // trim to ring-buffer cap (slice from end to keep recent)
  if (buf.length > LOG_RING_MAX) logLines.value = buf.slice(buf.length - LOG_RING_MAX)
}
function signalOutcome(tone: 'success' | 'error', title: string, detail: string) { if (import.meta.client) window.dispatchEvent(new CustomEvent('madeus:outcome', { detail: { tone, title, detail } })) }

async function authedFetch<T = any>(url: string, opts: any = {}): Promise<T> {
  const { data: { session } } = await supabase.auth.getSession()
  return $fetch<T>(url, { ...opts, headers: { ...(opts.headers || {}), ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}) } })
}

function alive(r: any) { return Date.now() - new Date(r.last_seen).getTime() < 60_000 }
function ago(ts: string) {
  const minutes = Math.round((Date.now() - new Date(ts).getTime()) / 60_000)
  if (!Number.isFinite(minutes)) return ''
  if (minutes < -2) return 'Scheduled'
  if (minutes < 1) return 'now'
  if (minutes < 60) return `${minutes}m ago`
  if (minutes < 1440) return `${Math.round(minutes / 60)}h ago`
  return `${Math.round(minutes / 1440)}d ago`
}
const projectName = (id: string) => projects.value.find(project => project.id === id)?.name || 'Workspace'
const liveRunnerCount = computed(() => runners.value.filter(alive).length)
const backlogCount = computed(() => tasks.value.filter(t => ['QUEUED', 'RETRY', 'WAITING'].includes(t.state)).length)
const attentionCount = computed(() => tasks.value.filter(t => ['BLOCKED', 'CONFLICT', 'TESTFAIL'].includes(t.state)).length + approvals.value.length)
const cashMtd = computed(() => providerSpend.value.filter(s => !String(s.provider || '').includes('notional')).reduce((sum, s) => sum + Number(s.spent || 0), 0))
const mergeRate = computed(() => outcomes.value.length ? Math.round(outcomes.value.filter(o => o.integrated).length / outcomes.value.length * 100) : 0)
const recentTasks = computed(() => tasks.value.slice(0, 12))
const operatorApprovals = computed(() => approvals.value.filter(a => !a.slug && !/\bmerge of\b/i.test(String(a.title || ''))).slice(0, 3))
const capabilityGroups = computed(() => {
  const hasDesign = capabilities.value.some(c => /design|brand|ux|product/i.test(`${c.name} ${c.domain}`))
  return [
    { title: 'Build & ship', description: 'Plan, implement, test, merge, and release product changes.', icon: '↗', to: '/queue', meta: `${liveRunnerCount.value} agents active` },
    { title: 'Design systems', description: 'Apply brand, interface, accessibility, and content-direction expertise.', icon: '✦', to: '/orchestrators/design-orchestrator', meta: hasDesign ? 'Design capability ready' : 'Configure capability' },
    { title: 'Research & decide', description: 'Compare approaches, model outcomes, and turn evidence into action.', icon: '◌', to: '/digital-twin', meta: 'Digital twin + strategy' },
    { title: 'Connect & govern', description: 'Use delegated tools and keep sensitive actions inside policy.', icon: '⌘', to: '/connectors', meta: 'Scoped connections' },
  ]
})

function stateTone(state: string) {
  if (state === 'RUNNING') return 'tone-running'
  if (['DONE', 'MERGED'].includes(state)) return 'tone-success'
  if (['BLOCKED', 'CONFLICT', 'TESTFAIL'].includes(state)) return 'tone-danger'
  if (state === 'RETRY') return 'tone-warning'
  return 'tone-neutral'
}
function readableState(state: string) {
  return ({ QUEUED: 'Queued', RUNNING: 'In progress', MERGED: 'Shipped', DONE: 'Complete', TESTFAIL: 'Tests failed', BLOCKED: 'Needs input', CONFLICT: 'Merge conflict', RETRY: 'Retrying', WAITING: 'Waiting' } as any)[state] || state
}

async function loadAll() {
  const [taskRows, approvalRows, projectRows, runnerRows, spendRows, outcomeRows, controlRows, capabilityRows] = await Promise.all([
    supabase.from('tasks').select('*').order('created_at', { ascending: false }).limit(50),
    supabase.from('approvals').select('*').eq('status', 'pending').order('created_at'),
    supabase.from('projects').select('*').order('name'),
    supabase.from('budgets').select('*'),
    supabase.from('runs').select('*').order('created_at', { ascending: false }).limit(100),
    supabase.from('v_project_health').select('*'),
    supabase.from('goals').select('*').eq('status', 'active').order('priority'),
    supabase.from('v_action_inbox').select('*').limit(20),
    supabase.from('txns').select('*').order('created_at', { ascending: false }).limit(50),
    supabase.from('capabilities').select('*').order('maturity', { ascending: false }),
    supabase.from('capability_instances').select('*').eq('status', 'active'),
    supabase.from('capability_provenance').select('*'),
    supabase.from('approvals').select('*').eq('kind', 'proposal').eq('status', 'pending').order('created_at', { ascending: false }).limit(20),
    // autonomy layer
    supabase.from('loops').select('*').order('project'),
    supabase.from('session_actions').select('*').in('status', ['paused', 'finished']).order('created_at', { ascending: false }).limit(50),
    supabase.from('orchestrator_feedback').select('id,created_at,source,category,severity,observation,suggestion,status').order('created_at', { ascending: false }).limit(200),
    supabase.from('v_provider_spend_mtd').select('*'),
    supabase.from('outcomes').select('model,usd,project,tests_passed,integrated,created_at,slug').order('created_at', { ascending: false }).limit(500),
    supabase.from('controls').select('*'),
    supabase.from('capabilities').select('*'),
  ])
  tasks.value = taskRows.data || []; approvals.value = approvalRows.data || []; projects.value = projectRows.data || []
  runners.value = runnerRows.data || []; providerSpend.value = spendRows.data || []; outcomes.value = outcomeRows.data || []
  capabilities.value = capabilityRows.data || []; globalPaused.value = (controlRows.data || []).some((c: any) => c.scope === 'global' && c.paused)
}

async function submitIntent(projectId?: string) {
  if (!intent.value.trim()) return
  queueLoading.value = true; queueError.value = ''; lastRoute.value = null
  try {
    lastRoute.value = await authedFetch('/api/tasks/intake', { method: 'POST', body: { intent: intent.value, project_id: projectId || selectedProject.value || undefined } })
    intent.value = ''
    projectChoice.value = null
    await loadAll()
    signalOutcome('success', 'Objective accepted', 'Madeus selected the route and moved the objective into governed execution.')
  } catch (error: any) {
    const details = error?.data?.data || error?.data
    if (error?.statusCode === 409 || details?.code === 'project_required') {
      projectChoice.value = { message: details?.message || 'Which project should Madeus change?', projects: details?.projects || projects.value.map(project => ({ id: project.id, name: project.name })) }
    } else { queueError.value = details?.message || error?.message || 'The objective could not be queued.'; signalOutcome('error', 'Objective not queued', queueError.value) }
  }
  finally { queueLoading.value = false }
}

async function decide(id: string, status: 'approved' | 'denied') {
  approvalError.value = ''
  try { await authedFetch('/api/approvals/decide', { method: 'POST', body: { id, status, approver: user.value?.email || 'dashboard' } }); await loadAll(); signalOutcome('success', status === 'approved' ? 'Approved' : 'Declined', status === 'approved' ? 'Execution can continue within the reviewed boundary.' : 'Dependent execution has been stopped.') }
  catch (error: any) { approvalError.value = error?.data?.message || error?.message || 'The decision could not be saved.'; signalOutcome('error', 'Decision not saved', approvalError.value) }
}
async function togglePause() {
  stopLoading.value = true
  try {
    await supabase.from('controls').upsert({ scope: 'global', project: null, paused: !globalPaused.value, reason: globalPaused.value ? null : 'manual stop from command center', updated_by: user.value?.email, updated_at: new Date().toISOString() }, { onConflict: 'scope,project' })
    globalPaused.value = !globalPaused.value
  } finally { stopLoading.value = false }
}

let refreshTimer: any
let realtimeSub: any
let logSub: any
onMounted(async () => {
  if (user.value) await loadAll()
  refreshTimer = setInterval(() => { if (user.value) loadAll() }, 30_000)
  realtimeSub = supabase.channel('command-center-live').on('postgres_changes', { event: '*', schema: 'public', table: 'tasks' }, loadAll).on('postgres_changes', { event: '*', schema: 'public', table: 'approvals' }, loadAll).subscribe()

  // seed with recent log rows then subscribe to inserts
  if (user.value) {
    const { data: seed } = await supabase.from('run_logs').select('ts,level,source,message').order('ts', { ascending: false }).limit(LOG_RING_MAX)
    if (seed && seed.length) {
      // seed comes newest-first; reverse so oldest is at index 0
      seed.reverse().forEach((r: any) => pushLogRow(r))
    }
  }
  logSub = supabase.channel('run-logs-live')
    .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'run_logs' }, (payload: any) => {
      pushLogRow(payload.new)
    })
    .subscribe()
})

const deployableTasks = computed(() =>
  tasks.value.filter(t => !['BLOCKED', 'CONFLICT', 'TESTFAIL'].includes(String(t.state || '').toUpperCase()))
)
const exactState = (state: string) => Number(queueCounts.value.states?.[state] || 0)
const exactQueued = computed(() => exactState('QUEUED'))
const exactRunning = computed(() => exactState('RUNNING'))
const exactRetry = computed(() => exactState('RETRY'))
const exactBlockedLike = computed(() => BLOCKED_QUEUE_STATES.reduce((n, state) => n + exactState(state), 0))
const exactBacklogCount = computed(() =>
  ['QUEUED', 'RETRY', 'BLOCKED', 'CONFLICT', 'TESTFAIL', 'QUARANTINED', 'WAITING']
    .reduce((n, state) => n + exactState(state), 0)
)
const exactTotalTasks = computed(() => Number(queueCounts.value.totalTasks || 0))
const exactCountsLoaded = computed(() => Boolean(queueCounts.value.updatedAt && !queueCounts.value.error))
const repairingTaskCount = computed(() => exactCountsLoaded.value
  ? exactBlockedLike.value
  : tasks.value.filter(t => ['BLOCKED', 'CONFLICT', 'TESTFAIL'].includes(String(t.state || '').toUpperCase())).length
)
const liveRunnerCount = computed(() => runners.value.filter(alive).length)
const runnerFleetTarget = computed(() => Math.max(8, liveRunnerCount.value || 0))
const hiddenBacklog = computed(() => exactTotalTasks.value > tasks.value.length)
const queueCoveragePct = computed(() => exactTotalTasks.value
  ? Math.min(100, Math.round((tasks.value.length / exactTotalTasks.value) * 100))
  : 100
)
const queueSummaryTiles = computed(() => [
  { label: 'Queued', value: exactQueued.value, tone: exactQueued.value ? 'text-amber-300' : 'text-slate-300' },
  { label: 'Running', value: exactRunning.value, tone: exactRunning.value ? 'text-blue-300' : 'text-slate-300' },
  { label: 'Retry', value: exactRetry.value, tone: exactRetry.value ? 'text-amber-300' : 'text-slate-300' },
  { label: 'Blocked', value: exactBlockedLike.value, tone: exactBlockedLike.value ? 'text-red-300' : 'text-slate-300' },
  { label: 'Done', value: exactState('DONE'), tone: exactState('DONE') ? 'text-green-300' : 'text-slate-300' },
  { label: 'Merged', value: exactState('MERGED'), tone: exactState('MERGED') ? 'text-green-300' : 'text-slate-300' },
])
const priorityQueueTiles = computed(() => [
  { label: 'Recovery', value: queueCounts.value.recoveryQueued, tone: queueCounts.value.recoveryQueued ? 'text-cyan-300' : 'text-slate-300' },
  { label: 'Release fix', value: queueCounts.value.releaseFixQueued + queueCounts.value.releaseFixRunning, tone: (queueCounts.value.releaseFixQueued + queueCounts.value.releaseFixRunning) ? 'text-red-300' : 'text-slate-300' },
  { label: 'Improvement', value: queueCounts.value.improvementsQueued, tone: queueCounts.value.improvementsQueued ? 'text-indigo-300' : 'text-slate-300' },
  { label: 'Canary active', value: queueCounts.value.canariesActive, tone: queueCounts.value.canariesActive ? 'text-emerald-300' : 'text-slate-300' },
])
function fmtInt(n: any) {
  return Number(n || 0).toLocaleString()
}

const stateColor: Record<string, string> = {
  RUNNING: 'bg-blue-500/20 text-blue-300', DONE: 'bg-green-500/20 text-green-300',
  MERGED: 'bg-green-500/20 text-green-300', QUEUED: 'bg-slate-500/20 text-slate-300',
  WAITING: 'bg-slate-500/20 text-slate-300', RETRY: 'bg-amber-500/20 text-amber-300',
  BLOCKED: 'bg-red-500/20 text-red-300', CONFLICT: 'bg-red-500/20 text-red-300',
  TESTFAIL: 'bg-red-500/20 text-red-300',
}
const txnColor: Record<string, string> = {
  pending: 'bg-amber-500/20 text-amber-300', merged: 'bg-green-500/20 text-green-300',
  aborted: 'bg-red-500/20 text-red-300',
}
const capStatusColor: Record<string, string> = {
  experimental: 'bg-slate-500/20 text-slate-300',
  trusted: 'bg-blue-500/20 text-blue-300',
  productizable: 'bg-green-500/20 text-green-300',
  retired: 'bg-red-500/20 text-red-300',
}
function instancesFor(capId: string) {
  return capInstances.value.filter((i: any) => i.capability_id === capId)
}
function provFor(capId: string) {
  return capProvenance.value.find((p: any) => p.capability_id === capId)
}
// radar proposals keyed by capability slug parsed from detail JSON
const radarBySlug = computed(() => {
  const m: Record<string, any[]> = {}
  for (const p of radarProposals.value) {
    try {
      const d = p.detail ? JSON.parse(p.detail) : {}
      const key = d.capability || 'unknown'
      ;(m[key] ??= []).push({ ...p, _detail: d })
    } catch { /* ignore */ }
  }
  return m
})

// Wraps loadAll so every realtime event also stamps the Mission Control clock.
function onRealtime() { lastEventAt.value = Date.now(); loadAll() }

onMounted(() => {
  if (user.value) {
    loadAll()
    supabase.channel('orch')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'tasks' }, onRealtime)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'approvals' }, onRealtime)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'runner_heartbeats' }, onRealtime)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'runs' }, onRealtime)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'txns' }, onRealtime)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'orchestrator_feedback' }, onRealtime)
      .subscribe()
  }
})
watch(user, u => { if (u) loadAll() })
</script>

<template>
  <div class="command-page">
    <header class="command-topbar">
      <div class="system-state"><span class="live-dot" :class="{ muted: !liveRunnerCount }" />{{ liveRunnerCount ? 'Systems operating normally' : 'Execution fleet offline' }}</div>
      <div class="topbar-metrics"><span>{{ backlogCount }} queued</span><span>{{ mergeRate }}% shipped successfully</span><span>${{ cashMtd.toFixed(2) }} this month</span></div>
      <button class="quiet-button" :class="{ danger: !globalPaused }" :disabled="stopLoading" @click="togglePause">{{ stopLoading ? 'Updating…' : globalPaused ? 'Resume fleet' : 'Pause fleet' }}</button>
    </header>

    <!-- sign in -->
    <div v-if="!user" class="max-w-sm mx-auto pt-32 px-6">
      <h1 class="text-xl font-semibold mb-1">Claude Orchestrator</h1>
      <p class="text-slate-400 text-sm mb-6">Sign in to monitor builds and approve changes.</p>
      <div v-if="!sent" class="space-y-3">
        <input v-model="email" type="email" placeholder="you@team.com"
               class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2" />
        <button @click="signIn" class="w-full bg-blue-600 hover:bg-blue-500 rounded-lg py-2 font-semibold">
          Send magic link</button>
      </div>
      <p v-else class="text-green-400 text-sm">Check your email for the sign-in link.</p>
    </div>

    <!-- dashboard -->
    <div v-else class="max-w-5xl mx-auto px-5 py-6">

      <!-- header -->
      <header class="sticky top-0 z-30 -mx-5 px-5 py-3 mb-6 flex items-center gap-3
                     bg-canvas/80 backdrop-blur border-b border-border-subtle">
        <span class="relative flex w-2 h-2">
          <span v-if="runners.some(alive)"
                class="motion-safe:animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-60"></span>
          <span class="relative inline-flex w-2 h-2 rounded-full"
                :class="runners.some(alive) ? 'bg-green-400 dot-breathe' : 'bg-red-400'"></span>
        </span>
        <h1 class="text-lg font-semibold">Claude Orchestrator</h1>
        <span class="text-slate-500 text-sm">
          {{ liveRunnerCount }}/{{ runnerFleetTarget }} live lanes · <span class="font-mono" :class="exactBacklogCount ? 'text-amber-300' : 'text-emerald-400'" title="Exact full-table backlog count from SQL">{{ fmtInt(exactBacklogCount) }}</span> backlog · {{ approvals.length }} pending · <span class="font-mono text-slate-300" title="Token cost covered by your Claude Max plan — not cash">${{ coveredMtd.toFixed(2) }}</span> Max-covered · <span class="font-mono text-emerald-400" title="Real out-of-pocket API cash, month-to-date">${{ cashMtd.toFixed(2) }}</span> cash · <span class="font-mono text-cyan-300" title="Estimated prompt/result cache and patch-template savings from recent resource events">{{ Math.round(savingsKpi.tokens).toLocaleString() }}</span> tok avoided · <span class="font-mono" :class="integrateKpi.overall >= 1 ? 'text-emerald-400' : 'text-amber-400'" title="Post-QA merge-rate: passed/non-churn work that actually integrated. Target is 100%; failed drafting attempts are tracked separately as attempt yield.">{{ (integrateKpi.overall * 100).toFixed(0) }}%</span> merge-rate ({{ integrateKpi.integrated }}/{{ integrateKpi.completed }}) · <span class="font-mono" :class="(integrateKpi.usdPerMerge ?? 99) <= 2 ? 'text-emerald-400' : 'text-amber-400'" title="NORTH STAR: $ per merged change. Drive this DOWN.">{{ integrateKpi.usdPerMerge == null ? '—' : ('$' + integrateKpi.usdPerMerge.toFixed(2)) }}</span>/merge
        </span>
        <span class="flex-1"></span>
        <button @click="signOut" class="text-slate-400 text-sm hover:text-white">Sign out</button>
      </header>

      <!-- ── Mission Control live strip ── -->
      <MissionControl
        :tasks="deployableTasks"
        :runners="runners"
        :approvals="approvals"
        :outcomes="outcomes"
        :spend="spend"
        :last-event-at="lastEventAt" />

      <!-- ── Configuration Feedback Panel ── -->
      <ConfigurationFeedbackPanel :items="feedbackItems.slice(0, 20)" />

      <!-- Shared proof packs -->
      <section class="bg-slate-900 border border-slate-800 rounded-xl p-4 mb-6">
        <div class="flex items-center gap-2 mb-3">
          <h2 class="text-xs uppercase tracking-wider text-slate-500">Shared proof packs</h2>
          <span class="text-xs text-slate-500">Common Brain - CADE - receipts</span>
          <span class="flex-1"></span>
          <span v-if="proofPacks.error" class="text-xs text-red-300">{{ proofPacks.error }}</span>
          <span v-else class="text-xs text-slate-500">{{ commonBrainProofRows.length }} brain deployments - {{ recentProofReceipts.length }} receipts</span>
        </div>
        <p v-if="queueError" class="inline-error" role="alert">{{ queueError }}</p>
        <div v-if="lastRoute" class="route-receipt" role="status">
          <div><span class="receipt-check">✓</span><strong>Objective accepted for {{ lastRoute.project.name }}</strong><span>{{ lastRoute.task.slug }}</span></div>
          <p>{{ lastRoute.route.summary }}</p>
          <div class="stage-line"><span v-for="stage in lastRoute.route.stages" :key="stage">{{ stage }}</span></div>
        </div>
      </section>

      <section class="overview-grid" aria-label="Operational overview">
        <NuxtLink to="/queue" class="overview-card"><span class="overview-label">In motion</span><strong>{{ liveRunnerCount }}</strong><p>agents currently executing</p><span class="card-link">View live work ↗</span></NuxtLink>
        <NuxtLink to="/queue" class="overview-card"><span class="overview-label">Up next</span><strong>{{ backlogCount }}</strong><p>objectives ready for the fleet</p><span class="card-link">Open queue ↗</span></NuxtLink>
        <NuxtLink :to="approvals.length ? '/sign-offs' : '/health'" class="overview-card" :class="{ attention: attentionCount }"><span class="overview-label">Needs attention</span><strong>{{ attentionCount }}</strong><p>{{ attentionCount ? 'decisions or recoveries are waiting' : 'nothing requires you right now' }}</p><span class="card-link">{{ attentionCount ? 'Review now' : 'View health' }} ↗</span></NuxtLink>
      </section>

      <section class="section-block">
        <div class="section-heading"><div><span class="eyebrow">Capability layer</span><h2>One interface, specialized intelligence</h2></div><NuxtLink to="/orchestrators">Explore all {{ capabilities.length }} capabilities ↗</NuxtLink></div>
        <div class="capability-grid">
          <NuxtLink v-for="capability in capabilityGroups" :key="capability.title" :to="capability.to" class="capability-card"><div class="capability-icon">{{ capability.icon }}</div><div><h3>{{ capability.title }}</h3><p>{{ capability.description }}</p><span>{{ capability.meta }}</span></div><b>↗</b></NuxtLink>
        </div>
        <div class="divide-y divide-gray-200">
          <div v-for="a in operatorApprovals" :key="a.id" class="px-5 py-4">
            <!-- Decision mini brief -->
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

      <section v-if="operatorApprovals.length" class="section-block attention-block">
        <div class="section-heading"><div><span class="eyebrow">Your decision</span><h2>{{ operatorApprovals.length }} action{{ operatorApprovals.length === 1 ? '' : 's' }} only you can authorize</h2></div><NuxtLink to="/sign-offs">Review all ↗</NuxtLink></div>
        <div class="decision-list">
          <article v-for="approval in operatorApprovals" :key="approval.id" class="decision-row">
            <div><div class="decision-meta"><span>{{ approval.kind || 'Approval' }}</span><span>{{ approval.project || 'Portfolio' }}</span><time>{{ ago(approval.created_at) }}</time></div><h3>{{ approval.title }}</h3><p>{{ deriveDecisionBrief(approval).plainLanguage }}</p><p><b>{{ deriveDecisionBrief(approval).recommendation }}</b> · {{ deriveDecisionBrief(approval).confidence }}% evidence confidence · {{ deriveDecisionBrief(approval).reversibility.replaceAll('_', ' ') }}</p></div>
            <div class="decision-actions"><NuxtLink class="primary-button" to="/sign-offs">Review decision brief</NuxtLink></div>
          </article>
        </div>
        <p v-if="approvalError" class="inline-error">{{ approvalError }}</p>
      </section>

      <section class="section-block">
        <div class="section-heading"><div><span class="eyebrow">Live execution</span><h2>Recent objectives</h2></div><NuxtLink to="/queue">Full queue ↗</NuxtLink></div>
        <div class="activity-table">
          <div v-if="!recentTasks.length" class="empty-state">Your first objective will appear here.</div>
          <article v-for="task in recentTasks" :key="task.id" class="activity-row" @click="expandedTask = expandedTask === task.id ? null : task.id">
            <div class="activity-primary"><span class="state-pill" :class="stateTone(task.state)">{{ readableState(task.state) }}</span><div><h3>{{ task.slug }}</h3><p>{{ projectName(task.project_id) }}</p></div></div>
            <div class="activity-time">{{ ago(task.created_at) }}</div><button :aria-label="`Show details for ${task.slug}`">{{ expandedTask === task.id ? '−' : '+' }}</button>
            <div v-if="expandedTask === task.id" class="activity-detail"><p>{{ task.prompt?.replace(/# User objective\s*/i, '').slice(0, 360) }}</p><div><span>Routing</span>{{ task.model || 'Autopilot selecting the best available route' }}</div><div><span>Execution note</span>{{ task.note || 'Preparing execution context' }}</div></div>
          </article>
        </div>
      </section>

      <section class="section-block">
        <div class="section-heading"><div><span class="eyebrow">Fleet telemetry</span><h2>Live log stream</h2></div></div>
        <LogView :lines="logLines" title="Run logs" :max-lines="LOG_RING_MAX" height="24rem" />
      </section>
    </main>
  </div>
</template>
