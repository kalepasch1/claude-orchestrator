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
    supabase.from('runner_heartbeats').select('*'),
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
onUnmounted(() => { if (refreshTimer) clearInterval(refreshTimer); if (realtimeSub) supabase.removeChannel(realtimeSub); if (logSub) supabase.removeChannel(logSub) })
watch(user, async value => { if (value) await loadAll() })
</script>

<template>
  <div class="command-page">
    <header class="command-topbar">
      <div class="system-state"><span class="live-dot" :class="{ muted: !liveRunnerCount }" />{{ liveRunnerCount ? 'Systems operating normally' : 'Execution fleet offline' }}</div>
      <div class="topbar-metrics"><span>{{ backlogCount }} queued</span><span>{{ mergeRate }}% shipped successfully</span><span>${{ cashMtd.toFixed(2) }} this month</span></div>
      <button class="quiet-button" :class="{ danger: !globalPaused }" :disabled="stopLoading" @click="togglePause">{{ stopLoading ? 'Updating…' : globalPaused ? 'Resume fleet' : 'Pause fleet' }}</button>
    </header>

    <main class="command-content">
      <section class="intent-hero">
        <div class="eyebrow">Madeus Orchestrator</div>
        <h1>What should we accomplish?</h1>
        <p>Describe the outcome. Madeus chooses the project context, research depth, specialists, models, worktrees, verification, and release path.</p>
        <form class="intent-console" @submit.prevent="submitIntent">
          <div class="intent-context-row">
            <label for="intent-project">Project</label>
            <select id="intent-project" v-model="selectedProject">
              <option value="">Let Madeus detect it</option>
              <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option>
            </select>
            <span>Optional — you can choose now or Madeus will ask only when the prompt is ambiguous.</span>
          </div>
          <textarea v-model="intent" rows="4" autofocus aria-label="Describe your objective" placeholder="Build, fix, research, or improve anything…" @keydown.meta.enter.prevent="submitIntent" @keydown.ctrl.enter.prevent="submitIntent" />
          <div class="intent-footer">
            <div class="autopilot-note"><span>✦</span><strong>Autopilot</strong> routes through triage, Colosseum, independent QA, and release verification</div>
            <button class="primary-button" :disabled="queueLoading || !intent.trim()">{{ queueLoading ? 'Routing…' : 'Start' }} <span>↗</span></button>
          </div>
        </form>
        <div v-if="projectChoice" class="project-choice" role="dialog" aria-label="Choose a project">
          <div><span class="project-choice-icon">⌘</span><div><strong>{{ projectChoice.message }}</strong><p>Your objective is preserved. Choose the primary workspace; Madeus will still coordinate any dependent applications automatically.</p></div></div>
          <div class="project-choice-options"><button v-for="project in projectChoice.projects" :key="project.id" type="button" :disabled="queueLoading" @click="selectedProject = project.id; submitIntent(project.id)">{{ project.name }} <span>↗</span></button></div>
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
      </section>

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
