<script setup lang="ts">
import type { LogLine } from '~/types/log'
definePageMeta({ alias: ['/index'] })

const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()

// ── auth ──────────────────────────────────────────────────────────────────
const signingIn = ref(false)
async function signInWithGoogle() {
  signingIn.value = true
  try {
    await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: typeof window !== 'undefined' ? window.location.origin : undefined },
    })
  } finally {
    signingIn.value = false
  }
}
async function signOut() { await supabase.auth.signOut() }

// ── data ──────────────────────────────────────────────────────────────────
const tasks = ref<any[]>([])
type QueueCounters = {
  states: Record<string, number>
  totalTasks: number
  unknownStateTotal: number
  recoveryQueued: number
  improvementsQueued: number
  canariesActive: number
  releaseFixQueued: number
  releaseFixRunning: number
  sampled: number
  updatedAt: string | null
  error: string | null
}
const QUEUE_COUNT_STATES = [
  'QUEUED', 'RUNNING', 'RETRY', 'DONE', 'MERGED', 'BLOCKED',
  'CONFLICT', 'TESTFAIL', 'QUARANTINED', 'DECOMPOSED', 'SHELVED', 'WAITING',
]
const BLOCKED_QUEUE_STATES = ['BLOCKED', 'CONFLICT', 'TESTFAIL']
const RELEASE_FIX_PREFIXES = ['relfix-', 'qafix-', 'deployfix-', 'buildfix-']
const emptyQueueCounters = (): QueueCounters => ({
  states: {},
  totalTasks: 0,
  unknownStateTotal: 0,
  recoveryQueued: 0,
  improvementsQueued: 0,
  canariesActive: 0,
  releaseFixQueued: 0,
  releaseFixRunning: 0,
  sampled: 0,
  updatedAt: null,
  error: null,
})
const queueCounts = ref<QueueCounters>(emptyQueueCounters())
const approvals = ref<any[]>([])
const outcomes = ref<any[]>([])
const runners = ref<any[]>([])
const projects = ref<any[]>([])
const budgets = ref<any[]>([])
const runs = ref<any[]>([])
const health = ref<any[]>([])
const goals = ref<any[]>([])
const inbox = ref<any[]>([])
const txns = ref<any[]>([])
const capabilities = ref<any[]>([])
const capInstances = ref<any[]>([])
const capProvenance = ref<any[]>([])
const radarProposals = ref<any[]>([])
const proofPacks = ref<any>({ commonBrain: [], receipts: [], error: null })
const resilience = ref<any>({ mesh: null, db: null, spoolDepth: 0 })
// Mission Control: epoch ms of the last realtime event observed (header live-strip).
const lastEventAt = ref<number | null>(null)
let chart: any = null
let refreshTimer: ReturnType<typeof setInterval> | null = null

// Chart accents — mirror the `chart-line` / `chart-axis` tailwind tokens
// (tailwind.config.js). Single source of truth for the canvas hexes.
const CHART_LINE = '#58a6ff'
const CHART_AXIS = '#8b98ad'

// ── Capabilities productize ────────────────────────────────────────────────
const gtmLoading = ref<Record<string, boolean>>({})
async function productize(proposal: any) {
  const detail = proposal.detail ? JSON.parse(proposal.detail) : {}
  const slug = detail.capability || ''
  const target = detail.target_app || proposal.project || ''
  const product = detail.product || slug
  if (!slug || !target) { alert('Missing capability slug or target app'); return }
  gtmLoading.value[proposal.id] = true
  try {
    await $fetch('/api/go-to-market', {
      method: 'POST',
      body: { slug, target_project: target, product_name: product },
    })
    await loadAll()
  } catch (e: any) {
    alert('go-to-market failed: ' + e.message)
  } finally {
    gtmLoading.value[proposal.id] = false
  }
}

// Operator sign-offs only. Code-merge approvals are intentionally hidden because code
// mergers are automatic after tests + verification + judge; production deploys are batch-gated.
const OPERATOR_KINDS = ['operator', 'legal', 'secret', 'deploy']
const PROJECT_PRIORITY_ALIASES: Record<string, number> = {
  orchestrator: 1,
  beethoven: 1,
  tomorrow: 2,
  apparently: 3,
  smarter: 4,
  'pareto-2080': 5,
  pareto: 5,
  '2080': 5,
  hisanta: 6,
  'santas-secret-workshop': 6,
  galop: 7,
  racefeed: 7,
  'sustainable-barks': 8,
  sustainablebarks: 8,
}
function projectPriorityRank(name: any) {
  const key = String(name || '').trim().toLowerCase()
  return PROJECT_PRIORITY_ALIASES[key] ?? 9
}
function projectNameSort(a: any, b: any) {
  const pa = projectPriorityRank(a)
  const pb = projectPriorityRank(b)
  return pa === pb ? String(a || '').localeCompare(String(b || '')) : pa - pb
}
function sortProjects(rows: any[]) {
  return [...rows].sort((a, b) => projectNameSort(a?.name, b?.name))
}
const isCodeMergeApproval = (a: any) =>
  Boolean(a.slug || /\bmerge of\b/i.test(String(a.title || '')))
const approvalText = (a: any) => `${a.title || ''} ${a.why || ''}`.toLowerCase()
const isOperatorApproval = (a: any) => {
  if (isCodeMergeApproval(a)) return false
  const text = approvalText(a)
  return OPERATOR_KINDS.includes(a.kind) ||
    (a.kind === 'material' && /\b(legal|regulatory|compliance|business[- ]model)\b/i.test(text)) ||
    (a.kind === 'self' && /\b(credential|secret|api key|token)\b/i.test(text))
}
const operatorApprovals = computed(() => approvals.value.filter(isOperatorApproval))

// Per-project filter for the operator section — clear one repo's gates without the others in the way.
const operatorProjectFilter = ref('all')
const operatorProjects = computed(() =>
  [...new Set(operatorApprovals.value.map(a => a.project).filter(Boolean))].sort(projectNameSort))
const filteredOperatorApprovals = computed(() => operatorProjectFilter.value === 'all'
  ? [...operatorApprovals.value].sort((a, b) => projectNameSort(a.project, b.project))
  : operatorApprovals.value.filter(a => a.project === operatorProjectFilter.value))
// If the selected project's gates all clear, fall back to "all" so the dropdown never sticks on an empty view.
watch(operatorProjects, projs => {
  if (operatorProjectFilter.value !== 'all' && !projs.includes(operatorProjectFilter.value)) {
    operatorProjectFilter.value = 'all'
  }
})

// One-click: approve every operator gate currently in view (respects the project filter).
// Two-key cards only record the caller's first approval — a second person still has to confirm.
const bulkApproving = ref(false)
const approvalError = ref('')
async function approveAllOperator() {
  const items = [...filteredOperatorApprovals.value]
  if (!items.length) return
  const scope = operatorProjectFilter.value === 'all' ? 'all projects' : operatorProjectFilter.value
  if (!confirm(`Approve ${items.length} operator sign-off(s) for ${scope}?\nTwo-key items will only record your first approval.`)) return
  bulkApproving.value = true
  approvalError.value = ''
  const failures: string[] = []
  try {
    for (const a of items) {
      try { await decide(a.id, 'approved', false) }
      catch (e: any) { failures.push(`${a.project || 'portfolio'}: ${e?.message || e}`) }
    }
    await loadAll()
    if (failures.length) {
      approvalError.value = `${failures.length} sign-off(s) failed: ${failures.slice(0, 3).join(' · ')}`
      alert(approvalError.value)
    }
  } finally {
    bulkApproving.value = false
  }
}

// ── autonomy layer ────────────────────────────────────────────────────────
const loops = ref<any[]>([])
const sessions = ref<any[]>([])
const resourceGauge = ref<any>({})
const recentPrunes = ref<any[]>([])
const savingsEvents = ref<any[]>([])
const feedbackItems = ref<any[]>([])
const newFeedback = reactive({ category: 'other', severity: 'med', observation: '', suggestion: '' })
const feedbackSaving = ref(false)
const providerSpend = ref<any[]>([])
const credRequests = ref<any[]>([])
const globalPaused = ref(false)
const stopLoading = ref(false)
const panicLoading = ref(false)
const rotateLoading = ref<Record<string, boolean>>({})
const sessionRunning = ref<Record<string, boolean>>({})

const newTask = reactive({ project_id: '', slug: '', prompt: '', kind: 'build', mode: 'improvement' })
const queueLoading = ref(false)
const newTxn = reactive({ id: '', name: '', description: '' })

// ── NL analytics ──────────────────────────────────────────────────────────
const nlQuery = ref('')
const nlAnswer = ref('')
const nlLoading = ref(false)
async function askNL() {
  if (!nlQuery.value.trim()) return
  nlLoading.value = true; nlAnswer.value = ''
  try {
    const { data, error } = await supabase.functions.invoke('ask', { body: { question: nlQuery.value } })
    nlAnswer.value = (data as any)?.answer ?? ((error as any)?.message ?? 'No answer returned.')
  } catch (e: any) { nlAnswer.value = 'Error: ' + e.message }
  nlLoading.value = false
}

// ── load ──────────────────────────────────────────────────────────────────
async function exactTaskCount(applyFilters?: (query: any) => any) {
  let query: any = supabase.from('tasks').select('id', { count: 'exact', head: true })
  if (applyFilters) query = applyFilters(query)
  const { count, error } = await query
  if (error) throw error
  return count || 0
}

async function exactPrefixCount(prefix: string, state?: string) {
  return exactTaskCount(q => {
    let next = q.like('slug', `${prefix}%`)
    if (state) next = next.eq('state', state)
    return next
  })
}

function countersFromRows(rows: any[]): QueueCounters | null {
  if (!rows?.length) return null
  const states: Record<string, number> = {}
  const totals: Record<string, number> = {}
  const prefixes: Record<string, number> = {}
  for (const row of rows) {
    const bucket = String(row.bucket || '')
    const name = String(row.name || '')
    const n = Number(row.n || 0)
    if (!bucket || !name) continue
    if (bucket === 'state') states[name] = n
    else if (bucket === 'total') totals[name] = n
    else if (bucket === 'prefix') prefixes[name] = n
  }
  if (!Object.keys(states).length && !totals.tasks) return null
  const knownStateTotal = Object.values(states).reduce((sum, n) => sum + Number(n || 0), 0)
  const totalTasks = totals.tasks || knownStateTotal
  return {
    ...emptyQueueCounters(),
    states,
    totalTasks,
    unknownStateTotal: Math.max(0, totalTasks - knownStateTotal),
    recoveryQueued: prefixes.recovery_queued || 0,
    improvementsQueued: prefixes.improvements_queued || 0,
    canariesActive: prefixes.canaries_active || 0,
    releaseFixQueued: prefixes.release_fix_queued || 0,
    releaseFixRunning: prefixes.release_fix_running || 0,
    updatedAt: new Date().toISOString(),
  }
}

async function loadQueueCounters(): Promise<QueueCounters> {
  try {
    const view = await supabase.from('v_task_queue_counters').select('bucket,name,n')
    if (!view.error) {
      const fromView = countersFromRows(view.data || [])
      if (fromView) return fromView
    }
    const statePairs = await Promise.all(
      QUEUE_COUNT_STATES.map(async state => [state, await exactTaskCount(q => q.eq('state', state))] as const),
    )
    const states = Object.fromEntries(statePairs)
    const totalTasks = await exactTaskCount()
    const [recoveryQueued, improvementsQueued, canariesActive, releaseQueuedParts, releaseRunningParts] = await Promise.all([
      exactPrefixCount('recover-missing-branch-', 'QUEUED'),
      exactPrefixCount('improve-', 'QUEUED'),
      exactTaskCount(q => q.like('slug', 'canary-%').in('state', ['QUEUED', 'RUNNING'])),
      Promise.all(RELEASE_FIX_PREFIXES.map(prefix => exactPrefixCount(prefix, 'QUEUED'))),
      Promise.all(RELEASE_FIX_PREFIXES.map(prefix => exactPrefixCount(prefix, 'RUNNING'))),
    ])
    const knownStateTotal = Object.values(states).reduce((n, v) => n + Number(v || 0), 0)
    return {
      ...emptyQueueCounters(),
      states,
      totalTasks,
      unknownStateTotal: Math.max(0, totalTasks - knownStateTotal),
      recoveryQueued,
      improvementsQueued,
      canariesActive,
      releaseFixQueued: releaseQueuedParts.reduce((n, v) => n + v, 0),
      releaseFixRunning: releaseRunningParts.reduce((n, v) => n + v, 0),
      updatedAt: new Date().toISOString(),
    }
  } catch (e: any) {
    return { ...emptyQueueCounters(), error: e?.message || String(e), updatedAt: new Date().toISOString() }
  }
}

async function loadAll() {
  const [t, a, o, r, p, b, r2, h, g, i, tx, caps, cinst, cprov, rprops,
         lps, sess, fb, pspend, creds, ctrl, prunes, savings, qcounts, proof, resilienceData] = await Promise.all([
    supabase.from('tasks').select('*').order('created_at', { ascending: false }).limit(200),
    supabase.from('approvals').select('*').eq('status', 'pending').order('created_at'),
    supabase.from('outcomes').select('model,usd,project,tests_passed,integrated,created_at,slug').order('created_at').limit(2000),
    supabase.from('runner_heartbeats').select('*'),
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
    supabase.from('orchestrator_feedback').select('category,severity,status').limit(500),
    supabase.from('v_provider_spend_mtd').select('*'),
    supabase.from('credential_requests').select('*').order('created_at', { ascending: false }).limit(20),
    supabase.from('controls').select('*'),
    supabase.from('resource_events').select('kind,detail,action,created_at').eq('kind', 'prune').order('created_at', { ascending: false }).limit(10),
    supabase.from('resource_events').select('value,detail,action,created_at').eq('kind', 'savings').order('created_at', { ascending: false }).limit(200),
    loadQueueCounters(),
    $fetch('/api/fleet/proof-packs').catch((e: any) => ({ commonBrain: [], receipts: [], error: e?.message || String(e) })),
    $fetch('/api/fleet/resilience').catch((e: any) => ({ mesh: null, db: null, spoolDepth: 0, error: e?.message || String(e) })),
  ])
  tasks.value = t.data || []; approvals.value = (a.data || []).filter(isOperatorApproval)
  outcomes.value = o.data || []; runners.value = r.data || []; projects.value = sortProjects(p.data || [])
  budgets.value = b.data || []; runs.value = r2.data || []; health.value = h.data || []
  goals.value = g.data || []; inbox.value = (i.data || []).filter(isActionInboxItem); txns.value = tx.data || []
  capabilities.value = caps.data || []
  capInstances.value = cinst.data || []
  capProvenance.value = cprov.data || []
  radarProposals.value = rprops.data || []
  loops.value = lps.data || []
  sessions.value = (sess.data || []).filter((s: any) => s.status !== 'paused')
  feedbackItems.value = fb.data || []
  providerSpend.value = pspend.data || []
  credRequests.value = creds.data || []
  recentPrunes.value = prunes.data || []
  savingsEvents.value = savings.data || []
  proofPacks.value = proof || { commonBrain: [], receipts: [], error: null }
  resilience.value = resilienceData || { mesh: null, db: null, spoolDepth: 0 }
  queueCounts.value = { ...(qcounts || emptyQueueCounters()), sampled: tasks.value.length }
  const ctrlRows = ctrl.data || []
  globalPaused.value = ctrlRows.some((c: any) => c.scope === 'global' && c.paused)
  // latest disk gauge from resource_events
  const diskRow = (await supabase.from('resource_events').select('value,detail,created_at')
    .eq('kind', 'disk').order('created_at', { ascending: false }).limit(1)).data?.[0]
  if (diskRow) {
    const freeGb = parseFloat((diskRow.detail || '').match(/([\d.]+)GB/)?.[1] || '0')
    resourceGauge.value = { disk_pct: diskRow.value, free_gb: freeGb, ts: diskRow.created_at }
  }
  if (!newTask.project_id && projects.value[0]) newTask.project_id = projects.value[0].id
  renderChart()
}

// ── approvals ─────────────────────────────────────────────────────────────
async function decide(id: string, status: 'approved' | 'denied', reload = true) {
  const a = approvals.value.find(x => x.id === id)
  if (!a) return
  approvalError.value = ''
  const approver = user.value?.email || 'dashboard'

  try {
    const res = await $fetch<any>('/api/approvals/decide', {
      method: 'POST',
      body: { id, status, approver },
    })
    const next = res?.approval
    if (next?.status === 'pending') Object.assign(a, next)
    else approvals.value = approvals.value.filter(x => x.id !== id)
    if (reload) await loadAll()
  } catch (e: any) {
    const message = e?.data?.message || e?.message || String(e)
    approvalError.value = message
    alert(`Approval update failed: ${message}`)
    throw e
  }
}

// ── tasks ─────────────────────────────────────────────────────────────────
async function queueTask() {
  if (!newTask.project_id || !newTask.prompt) return
  queueLoading.value = true
  try {
    const project = projects.value.find((p: any) => p.id === newTask.project_id)
    const slug = newTask.slug || makeSlug(newTask.prompt)
    await supabase.from('tasks').insert({
      project_id: newTask.project_id, slug,
      prompt: optimizedImprovementPrompt(newTask.prompt, project?.name || ''),
      kind: newTask.kind, state: 'QUEUED',
      note: 'pipeline:dashboard-user-driven; triage-plan-code-qa-devmerge-release',
    })
    newTask.slug = ''; newTask.prompt = ''; await loadAll()
  } finally {
    queueLoading.value = false
  }
}

// ── replay ────────────────────────────────────────────────────────────────
async function triggerReplay(run: any) {
  const proj = projects.value.find(p => p.name === run.project)
  if (!proj) { alert('Project not found in projects list'); return }
  await $fetch('/api/replay', { method: 'POST', body: { run_id: run.id, project_id: proj.id } })
  loadAll()
}

// ── transactions ──────────────────────────────────────────────────────────
async function createTxn() {
  if (!newTxn.id || !newTxn.name) return
  await supabase.from('txns').insert({ id: newTxn.id, name: newTxn.name, description: newTxn.description })
  newTxn.id = ''; newTxn.name = ''; newTxn.description = ''; loadAll()
}

// ── ROI ───────────────────────────────────────────────────────────────────
const roiData = computed(() => {
  const agg: Record<string, any> = {}
  for (const o of outcomes.value) {
    const a = agg[o.project] ??= { spend: 0, merged: 0, tasks: 0 }
    a.spend += Number(o.usd || 0); a.tasks++
    if (o.integrated) a.merged++
  }
  return Object.entries(agg).map(([project, a]: [string, any]) => ({
    project, spend: a.spend.toFixed(2), merged: a.merged,
    cost_per_merge: a.merged ? (a.spend / a.merged).toFixed(2) : null,
    pass_rate: a.tasks ? Math.round(100 * a.merged / a.tasks) : 0,
  })).sort((x, y) => Number(x.cost_per_merge ?? 9999) - Number(y.cost_per_merge ?? 9999))
})

// ── autonomy layer actions ─────────────────────────────────────────────────

async function toggleLoop(loop: any) {
  await supabase.from('loops').update({ enabled: !loop.enabled }).eq('id', loop.id)
  loop.enabled = !loop.enabled
}

async function runSession(sess: any) {
  if (!sess.next_action) return
  sessionRunning.value[sess.id] = true
  try {
    const proj = projects.value.find((p: any) => p.name === sess.project)
    if (!proj) { alert('Project not found'); return }
    await supabase.from('tasks').insert({
      project_id: proj.id, slug: `cont-${sess.session_id?.slice(0, 6) || 'sess'}`,
      prompt: sess.next_action, kind: 'build', state: 'QUEUED',
    })
    await supabase.from('session_actions').update({ status: 'queued' }).eq('id', sess.id)
    await loadAll()
  } finally { sessionRunning.value[sess.id] = false }
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

async function panicStopAndRevoke(providerName: string) {
  if (!confirm(`SECURITY PANIC: stop the runner and revoke ALL active ${providerName} keys? This cannot be undone automatically.`)) return
  panicLoading.value = true
  try {
    const proj = projects.value[0]
    if (!proj) { alert('No projects registered'); return }
    await supabase.from('tasks').insert({
      project_id: proj.id,
      slug: `panic-${providerName}-${Date.now()}`,
      prompt: `REVOKE_AND_STOP:${providerName}`,
      kind: 'build', state: 'QUEUED',
    })
    alert(`Panic task queued. The runner will revoke ${providerName} keys and pause immediately.`)
    await loadAll()
  } finally { panicLoading.value = false }
}

async function rotateKey(providerName: string, keyName: string, project: string | null) {
  const key = `${providerName}/${keyName}`
  rotateLoading.value[key] = true
  try {
    const proj = project ? projects.value.find((p: any) => p.name === project) : projects.value[0]
    if (!proj) { alert('Project not found for rotation'); return }
    await supabase.from('tasks').insert({
      project_id: proj.id,
      slug: `rotate-${providerName}-${Date.now()}`,
      prompt: `ROTATE_KEY:${providerName}:${keyName}`,
      kind: 'build', state: 'QUEUED',
    })
    alert(`Rotation enqueued for ${providerName}/${keyName}. The runner will execute it.`)
  } finally { rotateLoading.value[key] = false }
}

async function submitFeedback() {
  if (!newFeedback.observation.trim()) return
  feedbackSaving.value = true
  try {
    await supabase.from('orchestrator_feedback').insert({
      category: newFeedback.category, severity: newFeedback.severity,
      observation: newFeedback.observation, suggestion: newFeedback.suggestion,
      source: 'human', status: 'new',
    })
    newFeedback.observation = ''; newFeedback.suggestion = ''
    await loadAll()
  } finally { feedbackSaving.value = false }
}

// ── helpers ───────────────────────────────────────────────────────────────
function budgetFor(project: string) {
  const b = budgets.value.find(x => x.project === project)
  const spent = outcomes.value.filter(o => o.project === project)
    .reduce((s, o) => s + Number(o.usd || 0), 0)
  return { cap: b ? Number(b.monthly_usd_cap) : null, spent, hard: b?.hard_pause }
}

async function renderChart() {
  if (!process.client || !outcomes.value.length) return
  const el = document.getElementById('spendChart') as HTMLCanvasElement | null
  if (!el) return
  const { Chart } = await import('chart.js/auto')
  let cum = 0
  const pts = outcomes.value.map(o => ({ x: new Date(o.created_at).getTime(), y: (cum += Number(o.usd || 0)) }))
  if (chart) chart.destroy()
  chart = new Chart(el, {
    type: 'line',
    data: { datasets: [{ label: 'Cumulative spend ($)', data: pts, borderColor: CHART_LINE,
      backgroundColor: 'rgba(56,139,253,.15)', fill: true, tension: .25, pointRadius: 0 }] },
    options: { responsive: true, plugins: { legend: { labels: { color: CHART_AXIS } } },
      scales: { x: { type: 'linear', ticks: { color: CHART_AXIS,
        callback: (v: any) => new Date(v).toLocaleDateString() } },
        y: { ticks: { color: CHART_AXIS } } } },
  })
}

function alive(r: any) { return (Date.now() - new Date(r.last_seen).getTime()) < 60000 }

async function restartRunner(host: string) {
  try {
    await $fetch('/api/runners/restart', { method: 'POST', body: { host } })
    alert('Restart requested — ' + host + ' will respawn within ~1 min')
  } catch (e: any) {
    alert('Restart failed: ' + (e?.message || String(e)))
  }
}
function fmtConf(c: any) { return c != null ? Math.round(Number(c) * 100) + '%' : '' }
function confidenceLabel(c: any) {
  if (c == null) return 'not scored'
  const pct = Math.round(Number(c) * 100)
  if (pct >= 90) return `${pct}% ready`
  if (pct >= 75) return `${pct}% needs watch`
  return `${pct}% risky`
}
function ago(ts: string) {
  const d = Math.round((Date.now() - new Date(ts).getTime()) / 60000)
  return d < 60 ? `${d}m ago` : d < 1440 ? `${Math.round(d/60)}h ago` : `${Math.round(d/1440)}d ago`
}

function makeSlug(text: string) {
  const s = text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 48)
  return s || `task-${Date.now()}`
}

function optimizedImprovementPrompt(text: string, projectName: string) {
  return [
    `USER-DRIVEN IMPROVEMENT for ${projectName || 'selected app'}`,
    '',
    text.trim(),
    '',
    'Route this through the orchestration pipeline:',
    '1. Use the shared orchestration contract: cheap capable preflight, cross-provider strategy planning, best available coding agent, independent QA, automatic dev merge, and batch production release.',
    '2. Coordinate with continuous improvement loops already running for this app: reuse prior shipped solutions, avoid duplicate work, and do not delete or overwrite queued improvements from other bots.',
    '3. Pick fixed-price/subscription capacity first; fall back to configured paid API routes only when that is the highest-value available path for the task.',
    '4. Use cross-model/cross-bot review before merge: one model plans, one coder implements, another model family checks the diff and legal/regulatory posture.',
    '5. Do not create manual approval, blocked_task, or paused-session interruptions unless the work would force a licensing/registration/custody/transmission/advice posture change or needs a missing secret.',
  ].join('\n')
}

function isActionInboxItem(item: any) {
  const kind = String(item.kind ?? item.type ?? '').toLowerCase()
  if (kind === 'blocked_task') return false
  const text = `${item.title || ''} ${item.message || ''}`.toLowerCase()
  return !/\bblocked_task\b/.test(text)
}

const feedbackStats = computed(() => {
  const cats: Record<string, number> = {}
  const sevs: Record<string, number> = {}
  let newCount = 0
  for (const f of feedbackItems.value) {
    cats[f.category] = (cats[f.category] || 0) + 1
    sevs[f.severity] = (sevs[f.severity] || 0) + 1
    if (f.status === 'new') newCount++
  }
  return { cats, sevs, newCount, total: feedbackItems.value.length }
})

const loopHealth = computed(() => {
  const m: Record<string, Record<string, any>> = {}
  for (const l of loops.value) {
    if (!m[l.project]) m[l.project] = {}
    m[l.project][l.type] = l
  }
  return m
})

const spend = computed(() => outcomes.value.reduce((s, o) => s + Number(o.usd || 0), 0))
const savingsKpi = computed(() => {
  let tokens = 0
  let minutes = 0
  for (const e of savingsEvents.value) {
    tokens += Number(e.value || 0)
    const m = String(e.action || '').match(/minutes=([\d.]+)/)
    if (m) minutes += Number(m[1] || 0)
  }
  return { tokens, minutes }
})
// Cost split: `*-notional` providers are token cost COVERED by the fixed Claude Max plan
// (no cash). Everything else is REAL out-of-pocket API cash. Sourced from v_provider_spend_mtd.
const isNotional = (p: any) => String(p ?? '').includes('notional')
const coveredMtd = computed(() => providerSpend.value.filter(s => isNotional(s.provider)).reduce((n, s) => n + Number(s.spent || 0), 0))
const cashMtd = computed(() => providerSpend.value.filter(s => !isNotional(s.provider)).reduce((n, s) => n + Number(s.spent || 0), 0))
const spendSplitByProject = computed(() => {
  const m: Record<string, { covered: number; cash: number }> = {}
  for (const s of providerSpend.value) {
    const p = s.project || '(none)'
    ;(m[p] ??= { covered: 0, cash: 0 })
    if (isNotional(s.provider)) m[p].covered += Number(s.spent || 0)
    else m[p].cash += Number(s.spent || 0)
  }
  return m
})
// MERGE-RATE KPI: after work reaches a passing QA/build state, it should merge 100%.
// Raw failed attempts are tracked separately as attemptYield; they should not make the production
// merge-rate read as 2% when the real control problem is passed work waiting for integration.
const isChurn = (slug: any) => { const s = String(slug ?? ''); return s.startsWith('cont-') || s.startsWith('batch-mech') }
const integrateKpi = computed(() => {
  const m: Record<string, { completed: number; integrated: number; attempts: number; usd: number }> = {}
  let c = 0, i = 0, attempts = 0, attemptIntegrated = 0, usd = 0
  for (const o of outcomes.value) {
    if (isChurn(o.slug)) continue
    const p = o.project || '(none)'
    ;(m[p] ??= { completed: 0, integrated: 0, attempts: 0, usd: 0 })
    m[p].attempts++; attempts++; m[p].usd += Number(o.usd || 0); usd += Number(o.usd || 0)
    if (o.integrated) attemptIntegrated++
    if (!(o.tests_passed || o.integrated)) continue
    m[p].completed++; c++
    if (o.integrated) { m[p].integrated++; i++ }
  }
  const byProject = Object.entries(m)
    .map(([project, v]) => ({ project, ...v, rate: v.completed ? v.integrated / v.completed : 0,
                              usdPerMerge: v.integrated ? v.usd / v.integrated : null }))
    .sort((a, b) => b.completed - a.completed)
  // $/merged-change is the north-star: drive it DOWN.
  return {
    overall: c ? i / c : 1,
    completed: c,
    integrated: i,
    attempts,
    attemptYield: attempts ? attemptIntegrated / attempts : 0,
    usd,
    usdPerMerge: i ? usd / i : null,
    byProject,
  }
})
const byModel = computed(() => {
  const m: Record<string, number> = {}
  for (const o of outcomes.value) m[o.model] = (m[o.model] || 0) + Number(o.usd || 0)
  return Object.entries(m).sort((a, b) => b[1] - a[1])
})
const commonBrainProofRows = computed(() => proofPacks.value?.commonBrain || [])
const recentProofReceipts = computed(() => proofPacks.value?.receipts || [])

// ── live log lines for LogView ──────────────────────────────────────────────
// Flattens the most recent tasks' `log_tail` text blobs into typed LogLine[].
// Level is inferred from a leading token (ERROR/WARN/DEBUG); default info.
// TODO(bind-stream): replace with a dedicated run_logs table + realtime channel
// for true per-line streaming instead of polling the task log_tail snapshot.
const logLines = computed(() => {
  const out: LogLine[] = []
  const recent = [...tasks.value]
    .filter(t => t.log_tail)
    .slice(0, 12)
    .reverse() // oldest first so the tail reads top→bottom
  for (const t of recent) {
    const base = t.updated_at || t.created_at
    const baseMs = base ? new Date(base).getTime() : undefined
    for (const raw of String(t.log_tail).split('\n')) {
      const line = raw.trimEnd()
      if (!line) continue
      const m = line.match(/^\s*(ERROR|ERR|WARN|WARNING|DEBUG|DBG|INFO)\b[:\s-]*/i)
      let level: LogLine['level'] = 'info'
      let message = line
      if (m) {
        const tok = m[1].toUpperCase()
        level = tok.startsWith('ERR') ? 'error'
              : tok.startsWith('WARN') ? 'warn'
              : (tok === 'DEBUG' || tok === 'DBG') ? 'debug' : 'info'
        message = line.slice(m[0].length) || line
      } else if (/\b(fail|failed|exception|traceback|429|rate.?limit)\b/i.test(line)) {
        level = 'error'
      }
      out.push({ ts: baseMs, level, message, source: t.slug })
    }
  }
  return out
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
const resilienceMesh = computed(() => resilience.value?.mesh || {})
const resilienceDb = computed(() => resilience.value?.db || resilienceMesh.value?.db || {})
const resilienceOffline = computed(() => resilienceMesh.value?.mode === 'offline-continuity' || resilienceDb.value?.ok === false)
const resilienceVendors = computed(() => {
  const v = resilienceMesh.value?.vendors || {}
  return [...new Set([...(v.available_providers || []), ...(v.agentic_coders || [])])].filter(Boolean)
})
const resiliencePrewarm = computed(() => resilienceMesh.value?.actions?.prewarm || {})
const resilienceSupervisor = computed(() => resilienceMesh.value?.supervisor || {})
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
      .subscribe()
    refreshTimer = setInterval(loadAll, 30000)
  }
})
watch(user, u => {
  if (u) {
    loadAll()
    if (!refreshTimer) refreshTimer = setInterval(loadAll, 30000)
  } else if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})
onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<template>
  <div class="min-h-screen">

    <!-- sign in -->
    <div v-if="!user" class="max-w-sm mx-auto pt-32 px-6">
      <div class="bg-surface border border-border-subtle rounded-2xl p-8">
        <h1 class="font-serif text-2xl text-ink mb-1">Claude Orchestrator</h1>
        <p class="text-slate-500 text-sm mb-7">Sign in to monitor builds and approve changes.</p>
        <button @click="signInWithGoogle" :disabled="signingIn"
                class="w-full flex items-center justify-center gap-2.5 bg-[#fdfbf6] hover:bg-[#f6f3ec]
                       disabled:opacity-50 border border-[#d9d3c1] rounded-lg py-2.5 font-medium text-sm text-ink transition-colors">
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z"/>
            <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.81.54-1.85.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z"/>
            <path fill="#FBBC05" d="M3.97 10.72A5.4 5.4 0 0 1 3.68 9c0-.6.1-1.18.29-1.72V4.95H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.05l3.01-2.33z"/>
            <path fill="#EA4335" d="M9 3.58c1.32 0 2.51.46 3.44 1.35l2.59-2.59C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z"/>
          </svg>
          {{ signingIn ? 'Redirecting…' : 'Continue with Google' }}
        </button>
      </div>
    </div>

    <!-- dashboard -->
    <div v-else class="flex min-h-screen">

      <!-- ── Left sidebar ── -->
      <aside class="w-56 flex-shrink-0 sticky top-0 h-screen flex flex-col bg-[#0d1117] border-r border-slate-800 overflow-y-auto">
        <!-- App name -->
        <div class="px-4 pt-5 pb-3 border-b border-slate-800">
          <span class="text-xs font-semibold text-slate-400 tracking-wide">Claude Orchestrator</span>
        </div>

        <!-- Action To-Do panel -->
        <div class="px-4 py-3 border-b border-slate-800">
          <p class="text-[10px] uppercase tracking-wider text-slate-600 mb-2">Action queue</p>
          <div class="space-y-1.5">
            <div class="flex items-center justify-between text-xs">
              <span class="text-slate-400">Sign-offs pending</span>
              <span class="font-mono font-bold px-1.5 py-0.5 rounded text-[11px]"
                    :class="operatorApprovals.length ? 'bg-red-900/60 text-red-300' : 'text-slate-600'">
                {{ operatorApprovals.length }}
              </span>
            </div>
            <div class="flex items-center justify-between text-xs">
              <span class="text-slate-400">Inbox items</span>
              <span class="font-mono font-bold px-1.5 py-0.5 rounded text-[11px]"
                    :class="inbox.length ? 'bg-amber-900/60 text-amber-300' : 'text-slate-600'">
                {{ inbox.length }}
              </span>
            </div>
            <div class="flex items-center justify-between text-xs">
              <span class="text-slate-400">Cred requests</span>
              <span class="font-mono font-bold px-1.5 py-0.5 rounded text-[11px]"
                    :class="credRequests.length ? 'bg-amber-900/60 text-amber-300' : 'text-slate-600'">
                {{ credRequests.length }}
              </span>
            </div>
            <div class="flex items-center justify-between text-xs">
              <span class="text-slate-400">Blocked tasks</span>
              <span class="font-mono font-bold px-1.5 py-0.5 rounded text-[11px]"
                    :class="exactBlockedLike ? 'bg-red-900/60 text-red-300' : 'text-slate-600'">
                {{ exactBlockedLike }}
              </span>
            </div>
          </div>
        </div>

        <!-- Nav links -->
        <nav class="flex-1 px-3 py-3">
          <p class="text-[10px] uppercase tracking-wider text-slate-600 mb-2 px-1">Navigate</p>
          <ul class="space-y-0.5 text-xs">
            <li><a href="#mission-control" class="block px-2 py-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 transition-colors">Mission Control</a></li>
            <li><a href="#queue-status" class="block px-2 py-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 transition-colors">Queue Status</a></li>
            <li><a href="#improvement-queue" class="block px-2 py-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 transition-colors">Queue Improvement</a></li>
            <li><a href="#nl-search" class="block px-2 py-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 transition-colors">NL Search</a></li>
            <li><a href="#health-goals" class="block px-2 py-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 transition-colors">Goals &amp; Health</a></li>
            <li><a href="#inbox" class="block px-2 py-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 transition-colors">Action Inbox</a></li>
            <li>
              <a href="#sign-offs" class="flex items-center justify-between px-2 py-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 transition-colors">
                <span>Sign-offs</span>
                <span v-if="operatorApprovals.length"
                      class="text-[10px] bg-red-900/60 text-red-300 rounded-full px-1.5 py-0.5 font-bold leading-none">
                  {{ operatorApprovals.length }}
                </span>
              </a>
            </li>
            <li><a href="#capabilities" class="block px-2 py-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 transition-colors">Capabilities</a></li>
            <li><a href="#activity" class="block px-2 py-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 transition-colors">Activity Log</a></li>
            <li><a href="#tasks" class="block px-2 py-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 transition-colors">Task Flow</a></li>
            <li><a href="#roi" class="block px-2 py-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 transition-colors">ROI</a></li>
            <li><a href="#runners" class="block px-2 py-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 transition-colors">Runner Fleet</a></li>
            <li><a href="#budgets" class="block px-2 py-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 transition-colors">Budgets</a></li>
            <li><a href="#loops" class="block px-2 py-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 transition-colors">Loops</a></li>
            <li><a href="#sessions" class="block px-2 py-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 transition-colors">Sessions</a></li>
            <li><a href="#resources" class="block px-2 py-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 transition-colors">Resources</a></li>
            <li><a href="#feedback" class="block px-2 py-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 transition-colors">Feedback</a></li>
            <li><a href="#spend-keys" class="block px-2 py-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 transition-colors">Spend &amp; Keys</a></li>
          </ul>
        </nav>

        <!-- Sign out -->
        <div class="px-4 py-4 border-t border-slate-800">
          <button @click="signOut" class="w-full text-left text-xs text-slate-500 hover:text-slate-200 transition-colors">Sign out</button>
        </div>
      </aside>

      <!-- ── Main content area ── -->
      <div class="flex-1 overflow-y-auto">

      <!-- header -->
      <header class="sticky top-0 z-30 px-5 py-3 mb-6 flex items-center gap-3
                     bg-canvas/80 backdrop-blur border-b border-border-subtle">
        <span class="relative flex w-2 h-2">
          <span v-if="runners.some(alive)"
                class="motion-safe:animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-60"></span>
          <span class="relative inline-flex w-2 h-2 rounded-full"
                :class="runners.some(alive) ? 'bg-green-400 dot-breathe' : 'bg-red-400'"></span>
        </span>
        <h1 class="font-serif text-lg text-ink">Claude Orchestrator</h1>
        <span class="text-slate-500 text-sm">
          {{ liveRunnerCount }}/{{ runnerFleetTarget }} live lanes · <span class="font-mono" :class="exactBacklogCount ? 'text-amber-300' : 'text-emerald-400'" title="Exact full-table backlog count from SQL">{{ fmtInt(exactBacklogCount) }}</span> backlog · {{ approvals.length }} pending · <span class="font-mono text-slate-300" title="Token cost covered by your Claude Max plan — not cash">${{ coveredMtd.toFixed(2) }}</span> Max-covered · <span class="font-mono text-emerald-400" title="Real out-of-pocket API cash, month-to-date">${{ cashMtd.toFixed(2) }}</span> cash · <span class="font-mono text-cyan-300" title="Estimated prompt/result cache and patch-template savings from recent resource events">{{ Math.round(savingsKpi.tokens).toLocaleString() }}</span> tok avoided · <span class="font-mono" :class="integrateKpi.overall >= 1 ? 'text-emerald-400' : 'text-amber-400'" title="Post-QA merge-rate: passed/non-churn work that actually integrated. Target is 100%; failed drafting attempts are tracked separately as attempt yield.">{{ (integrateKpi.overall * 100).toFixed(0) }}%</span> merge-rate ({{ integrateKpi.integrated }}/{{ integrateKpi.completed }}) · <span class="font-mono" :class="(integrateKpi.usdPerMerge ?? 99) <= 2 ? 'text-emerald-400' : 'text-amber-400'" title="NORTH STAR: $ per merged change. Drive this DOWN.">{{ integrateKpi.usdPerMerge == null ? '—' : ('$' + integrateKpi.usdPerMerge.toFixed(2)) }}</span>/merge
        </span>
        <span class="flex-1"></span>
      </header>

      <div class="max-w-5xl mx-auto px-5 py-6">

      <!-- ── Mission Control live strip ── -->
      <div id="mission-control">
        <MissionControl
          :tasks="deployableTasks"
          :runners="runners"
          :approvals="approvals"
          :outcomes="outcomes"
          :spend="spend"
          :last-event-at="lastEventAt" />
      </div>

      <!-- ── Queue Status ── -->
      <div id="queue-status">

      <!-- Resilience continuity -->
      <section class="bg-slate-900 border rounded-xl p-4 mb-6"
               :class="resilienceOffline ? 'border-amber-600/60' : 'border-slate-800'">
        <div class="flex items-center gap-2 mb-3 flex-wrap">
          <h2 class="text-xs uppercase tracking-wider text-slate-500">Resilience mesh</h2>
          <span class="text-xs font-mono"
                :class="resilienceOffline ? 'text-amber-300' : 'text-emerald-300'">
            {{ resilienceMesh.mode || 'warming' }}
          </span>
          <span class="text-xs text-slate-500">updated {{ resilienceMesh.updated_at ? ago(resilienceMesh.updated_at) : 'pending' }}</span>
          <span class="flex-1"></span>
          <span class="text-xs" :class="resilienceDb.ok === false ? 'text-amber-300' : 'text-emerald-300'">
            DB {{ resilienceDb.ok === false ? 'deferred' : 'available' }}
          </span>
        </div>
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <div class="border border-slate-800 rounded-lg px-3 py-2">
            <div class="text-[10px] uppercase tracking-wider text-slate-500">Spool</div>
            <div class="font-mono tabular-nums text-lg leading-tight" :class="Number(resilience.spoolDepth || 0) ? 'text-amber-300' : 'text-slate-300'">
              {{ fmtInt(resilience.spoolDepth || resilienceMesh.spool_depth || 0) }}
            </div>
          </div>
          <div class="border border-slate-800 rounded-lg px-3 py-2">
            <div class="text-[10px] uppercase tracking-wider text-slate-500">Vendors</div>
            <div class="font-mono tabular-nums text-lg leading-tight text-cyan-300">
              {{ fmtInt(resilienceVendors.length) }}
            </div>
          </div>
          <div class="border border-slate-800 rounded-lg px-3 py-2">
            <div class="text-[10px] uppercase tracking-wider text-slate-500">Repos warmed</div>
            <div class="font-mono tabular-nums text-lg leading-tight" :class="resiliencePrewarm.ok === false ? 'text-amber-300' : 'text-emerald-300'">
              {{ fmtInt((resiliencePrewarm.results || []).length) }}
            </div>
          </div>
          <div class="border border-slate-800 rounded-lg px-3 py-2">
            <div class="text-[10px] uppercase tracking-wider text-slate-500">Duplicate lanes</div>
            <div class="font-mono tabular-nums text-lg leading-tight" :class="(resilienceSupervisor.duplicate_runner_pids || []).length ? 'text-red-300' : 'text-slate-300'">
              {{ fmtInt((resilienceSupervisor.duplicate_runner_pids || []).length + (resilienceSupervisor.duplicate_keepalive_pids || []).length) }}
            </div>
          </div>
        </div>
        <div v-if="resilienceDb.error" class="mt-2 text-xs text-amber-300 truncate" :title="resilienceDb.error">
          {{ resilienceDb.error }}
        </div>
      </section>

      <!-- Shared proof packs -->
      <section class="bg-slate-900 border border-slate-800 rounded-xl p-4 mb-6">
        <div class="flex items-center gap-2 mb-3">
          <h2 class="text-xs uppercase tracking-wider text-slate-500">Shared proof packs</h2>
          <span class="text-xs text-slate-500">Common Brain - CADE - receipts</span>
          <span class="flex-1"></span>
          <span v-if="proofPacks.error" class="text-xs text-red-300">{{ proofPacks.error }}</span>
          <span v-else class="text-xs text-slate-500">{{ commonBrainProofRows.length }} brain deployments - {{ recentProofReceipts.length }} receipts</span>
        </div>
        <div v-if="commonBrainProofRows.length" class="overflow-x-auto">
          <table class="w-full text-xs">
            <thead>
              <tr class="text-slate-500 text-left border-b border-slate-800">
                <th class="pb-2 pr-3">App</th>
                <th class="pb-2 pr-3">Task</th>
                <th class="pb-2 pr-3">Status</th>
                <th class="pb-2 pr-3">Outcome</th>
                <th class="pb-2 pr-3">Avoided</th>
                <th class="pb-2 pr-3">Review fails</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in commonBrainProofRows.slice(0, 8)" :key="row.task_slug"
                  class="border-b border-slate-800/60 last:border-0">
                <td class="py-1.5 pr-3 text-slate-300 font-medium">{{ row.product }}</td>
                <td class="py-1.5 pr-3 text-slate-400 font-mono">{{ row.task_slug }}</td>
                <td class="py-1.5 pr-3">
                  <span class="px-2 py-0.5 rounded-full text-[10px] font-bold"
                        :class="row.status === 'merged' ? 'bg-green-900/60 text-green-300' : row.status === 'failed' ? 'bg-red-900/60 text-red-300' : 'bg-slate-800 text-slate-300'">
                    {{ row.status }}
                  </span>
                </td>
                <td class="py-1.5 pr-3 text-slate-400">{{ row.outcome || 'pending' }}</td>
                <td class="py-1.5 pr-3 text-cyan-300">{{ Number(row.tokens_avoided || 0).toLocaleString() }} tok - {{ Number(row.minutes_avoided || 0).toFixed(1) }}m</td>
                <td class="py-1.5 pr-3" :class="Number(row.review_failures || 0) ? 'text-amber-300' : 'text-slate-500'">{{ row.review_failures || 0 }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="text-slate-600 italic text-sm">No Common Brain proof-pack deployments recorded yet.</div>
        <div v-if="recentProofReceipts.length" class="mt-3 flex flex-wrap gap-2">
          <span v-for="r in recentProofReceipts.slice(0, 5)" :key="r.id"
                class="text-[10px] bg-slate-800 text-slate-400 rounded-full px-2 py-0.5 font-mono"
                :title="r.reason">
            {{ String(r.digest || r.id).slice(0, 18) }} - {{ r.decision }}
          </span>
        </div>
      </section>

      <!-- ── Exact full-queue counters ── -->
      <section class="bg-slate-900 border border-slate-800 rounded-xl p-4 mb-6">
        <div class="flex items-center gap-2 mb-3 flex-wrap">
          <h2 class="text-xs uppercase tracking-wider text-slate-500">Full queue SQL counters</h2>
          <span class="text-xs font-mono" :class="hiddenBacklog ? 'text-amber-300' : 'text-slate-500'">
            sample {{ fmtInt(tasks.length) }}/{{ fmtInt(exactTotalTasks || tasks.length) }} · {{ queueCoveragePct }}%
          </span>
          <span v-if="queueCounts.unknownStateTotal" class="text-xs text-amber-300">
            {{ fmtInt(queueCounts.unknownStateTotal) }} unknown-state
          </span>
          <span class="flex-1"></span>
          <span v-if="queueCounts.error" class="text-xs text-red-300">{{ queueCounts.error }}</span>
          <span v-else class="text-xs text-slate-500">updated {{ queueCounts.updatedAt ? ago(queueCounts.updatedAt) : '—' }}</span>
        </div>
        <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 mb-3">
          <div v-for="item in queueSummaryTiles" :key="item.label" class="border border-slate-800 rounded-lg px-3 py-2">
            <div class="text-[10px] uppercase tracking-wider text-slate-500">{{ item.label }}</div>
            <div class="font-mono tabular-nums text-lg leading-tight" :class="item.tone">{{ fmtInt(item.value) }}</div>
          </div>
        </div>
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <div v-for="item in priorityQueueTiles" :key="item.label" class="border border-slate-800 rounded-lg px-3 py-2">
            <div class="text-[10px] uppercase tracking-wider text-slate-500">{{ item.label }}</div>
            <div class="font-mono tabular-nums text-lg leading-tight" :class="item.tone">{{ fmtInt(item.value) }}</div>
          </div>
        </div>
      </section>

      </div><!-- /#queue-status -->

      <!-- ── Improvement command center ── -->
      <div id="improvement-queue">
      <section class="bg-slate-900 border border-slate-700 rounded-xl p-4 mb-6">
        <div class="flex items-center gap-2 mb-3">
          <h2 class="text-xs uppercase tracking-wider text-slate-500">Queue an improvement</h2>
          <span class="text-xs text-slate-500">triage → code → QA → dev merge → batch release</span>
          <span class="flex-1"></span>
          <span v-if="repairingTaskCount" class="text-xs text-amber-300">{{ repairingTaskCount }} auto-repairing internally</span>
        </div>
        <div class="grid md:grid-cols-[1fr_1fr_auto] gap-2">
          <select v-model="newTask.project_id" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm">
            <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
          <input v-model="newTask.slug" placeholder="slug (optional)" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm" />
          <select v-model="newTask.kind" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm">
            <option value="build">Code change</option>
            <option value="research">Research then implement</option>
            <option value="efficiency">Efficiency / cost</option>
            <option value="speculative">Experiment</option>
          </select>
          <textarea v-model="newTask.prompt" placeholder="Describe the improvement, product change, bug fix, or new concept to generate and implement…" rows="3"
                    class="md:col-span-3 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"></textarea>
          <button @click="queueTask" :disabled="queueLoading || !newTask.prompt.trim()"
                  class="md:col-span-3 bg-[#20201c] hover:bg-[#33322c] disabled:opacity-40 text-[#f6f3ec] rounded-lg py-2 font-semibold text-sm">
            {{ queueLoading ? 'Routing…' : 'Route, implement, QA, and merge' }}
          </button>
        </div>
      </section>

      </div><!-- /#improvement-queue -->

      <!-- ── NL analytics search ── -->
      <div id="nl-search" class="bg-slate-900 border border-slate-700 rounded-xl p-4 mb-6">
        <div class="flex gap-2">
          <input v-model="nlQuery" @keydown.enter="askNL" placeholder="Ask a question: 'which projects are shipping today?' or 'where is money going?'"
                 class="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm" />
          <button @click="askNL" :disabled="nlLoading"
                  class="bg-[#3d3a6b] hover:bg-[#4a4680] disabled:opacity-40 text-white rounded-lg px-4 py-2 text-sm font-semibold">
            {{ nlLoading ? '…' : 'Ask' }}</button>
        </div>
        <p v-if="nlAnswer" class="mt-3 text-sm text-slate-300 whitespace-pre-wrap border-t border-slate-800 pt-3">{{ nlAnswer }}</p>
      </div>

      <!-- ── Health & Goals ── -->
      <div id="health-goals" v-if="health.length || goals.length" class="grid sm:grid-cols-2 gap-4 mb-6">
        <div v-if="health.length" class="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-3">Project health</h2>
          <div v-for="h in health" :key="h.project" class="flex items-center gap-2 py-1 border-b border-slate-800 last:border-0">
            <span class="w-2 h-2 rounded-full flex-shrink-0"
                  :class="h.health_score >= 80 ? 'bg-green-400' : h.health_score >= 50 ? 'bg-amber-400' : 'bg-red-400'"></span>
            <span class="text-sm text-slate-300 flex-1">{{ h.project }}</span>
            <span class="text-xs text-slate-500">score {{ h.health_score }}</span>
          </div>
        </div>
        <div v-if="goals.length" class="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-3">Active goals</h2>
          <div v-for="g in goals" :key="g.id" class="py-1 border-b border-slate-800 last:border-0">
            <div class="flex gap-2 items-start">
              <span class="text-xs text-slate-500 mt-0.5">#{{ g.priority }}</span>
              <div>
                <p class="text-sm text-slate-300">{{ g.objective }}</p>
                <p v-if="g.metric" class="text-xs text-slate-500">{{ g.metric }} → {{ g.target }}</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ── Action inbox (v_action_inbox) ── -->
      <div id="inbox" v-if="inbox.length" class="mb-6">
        <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-2">Action inbox</h2>
        <div v-for="item in inbox" :key="item.id ?? item.title"
             class="bg-slate-900 border border-slate-700 rounded-xl px-4 py-2 mb-2 flex items-center gap-3">
          <span class="text-xs uppercase font-bold text-slate-400">{{ item.kind ?? item.type }}</span>
          <span class="text-sm text-slate-300 flex-1">{{ item.title ?? item.message }}</span>
          <span class="text-xs text-slate-500">{{ item.project }}</span>
        </div>
      </div>

      <!-- ── Operator sign-offs (secrets / deploys / OAuth / legal) ── -->
      <h2 id="sign-offs" class="text-xs uppercase tracking-wider text-slate-500 mb-2 flex items-center gap-2 flex-wrap">
        Operator sign-offs
        <span class="text-slate-400 normal-case tracking-normal">secrets · deploys · OAuth · legal</span>
        <span v-if="operatorApprovals.length"
              class="text-[10px] bg-sky-900/60 text-sky-300 rounded-full px-2 py-0.5 font-bold">{{ filteredOperatorApprovals.length }}/{{ operatorApprovals.length }}</span>
        <span v-if="approvalError" class="text-[10px] text-red-300 normal-case tracking-normal">{{ approvalError }}</span>
        <span class="flex-1"></span>
        <select v-if="operatorProjects.length > 1" v-model="operatorProjectFilter"
                class="bg-slate-800 border border-slate-700 rounded-lg px-2 py-1 text-xs text-slate-200 normal-case tracking-normal">
          <option value="all">All projects</option>
          <option v-for="p in operatorProjects" :key="p" :value="p">{{ p }}</option>
        </select>
        <button v-if="filteredOperatorApprovals.length" @click="approveAllOperator" :disabled="bulkApproving"
                class="bg-[#1f5c56] hover:bg-[#276f68] disabled:opacity-50 rounded-lg px-3 py-1 text-xs font-semibold text-white normal-case tracking-normal">
          {{ bulkApproving ? 'Approving…' : `Approve all${operatorProjectFilter === 'all' ? '' : ' (' + operatorProjectFilter + ')'} · ${filteredOperatorApprovals.length}` }}
        </button>
      </h2>
      <div v-if="!operatorApprovals.length" class="text-slate-500 italic text-sm mb-6">No operator gates waiting.</div>
      <div v-else-if="!filteredOperatorApprovals.length" class="text-slate-500 italic text-sm mb-6">No operator gates for {{ operatorProjectFilter }}.</div>
      <ApprovalCard v-for="a in filteredOperatorApprovals" :key="a.id" :a="a" :user-email="user?.email" accent="sky"
                    @decide="decide" />

      <!-- ── Transactions ── -->
      <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">Cross-repo transactions</h2>
      <div class="bg-slate-900 border border-slate-700 rounded-xl p-4 mb-3 grid sm:grid-cols-[auto_1fr_1fr_auto] gap-2 items-center">
        <input v-model="newTxn.id" placeholder="txn-id (kebab)" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm" />
        <input v-model="newTxn.name" placeholder="Name" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm" />
        <input v-model="newTxn.description" placeholder="Description (optional)" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm" />
        <button @click="createTxn" class="bg-[#3d3a6b] hover:bg-[#4a4680] text-white rounded-lg px-4 py-2 text-sm font-semibold">Create</button>
      </div>
      <div v-if="txns.length" class="bg-slate-900 border border-slate-800 rounded-xl p-4 mb-3 text-sm">
        <div v-for="tx in txns" :key="tx.id" class="flex items-center gap-2 py-1 border-b border-slate-800 last:border-0">
          <StatusPill :label="tx.status" :tone="txnColor[tx.status] || 'bg-slate-700'" />
          <b class="text-slate-300 font-mono">{{ tx.id }}</b>
          <span class="text-slate-400">{{ tx.name }}</span>
          <span class="flex-1"></span>
          <span class="text-slate-500 text-xs">{{ ago(tx.created_at) }}</span>
        </div>
      </div>
      <div v-else class="text-slate-500 italic text-sm mb-6">No transactions yet. Tag tasks with <code class="font-mono not-italic">txn:&lt;id&gt;</code> in their note to join one.</div>

      <!-- ── Capabilities ── -->
      <h2 id="capabilities" class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">Capabilities</h2>
      <div v-if="!capabilities.length" class="text-slate-500 italic text-sm mb-6">No capabilities published yet. Run distill.py to extract one.</div>
      <div v-else class="bg-slate-900 border border-slate-800 rounded-xl p-4 mb-3 text-sm overflow-x-auto">
        <table class="w-full text-xs">
          <thead>
            <tr class="text-slate-500 text-left border-b border-slate-800">
              <th class="pb-2 pr-3">Capability</th>
              <th class="pb-2 pr-3">Status</th>
              <th class="pb-2 pr-3">Maturity</th>
              <th class="pb-2 pr-3">Domain</th>
              <th class="pb-2 pr-3">Source / consent</th>
              <th class="pb-2">Instances</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in capabilities" :key="c.id" class="border-b border-slate-800/60 last:border-0">
              <td class="py-1.5 pr-3">
                <span class="text-slate-300 font-medium">{{ c.name }}</span>
                <span class="text-slate-500 ml-1 text-xs font-mono">{{ c.slug }}</span>
              </td>
              <td class="py-1.5 pr-3">
                <StatusPill :label="c.status" :tone="capStatusColor[c.status] || 'bg-slate-700'" />
              </td>
              <td class="py-1.5 pr-3">
                <span :class="Number(c.maturity) >= 80 ? 'text-green-400' : Number(c.maturity) >= 40 ? 'text-amber-400' : 'text-slate-400'">
                  {{ c.maturity }}
                </span>
              </td>
              <td class="py-1.5 pr-3 text-slate-400">{{ c.domain }}</td>
              <td class="py-1.5 pr-3">
                <template v-if="provFor(c.id)">
                  <span class="text-slate-400">{{ provFor(c.id).source_project }}</span>
                  <span :class="provFor(c.id).consent ? 'text-green-400 ml-1' : 'text-red-400 ml-1'" class="text-xs">
                    {{ provFor(c.id).consent ? '✓ consent' : '✗ no consent' }}
                  </span>
                </template>
                <span v-else class="text-slate-600">—</span>
              </td>
              <td class="py-1.5">
                <span v-if="instancesFor(c.id).length" class="text-slate-400">
                  {{ instancesFor(c.id).map((i: any) => i.project).join(', ') }}
                </span>
                <span v-else class="text-slate-600">none</span>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="capabilities.length" class="text-slate-500 text-xs mt-2">
          Maturity score = eval_pass_rate × 60 + active_instances × 20. Recomputed daily by <span class="font-mono">maturity.py</span>.
        </p>
      </div>

      <!-- ── Capability Radar ── -->
      <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">Capability radar</h2>
      <div v-if="!Object.keys(radarBySlug).length" class="text-slate-500 italic text-sm mb-6">
        No cross-app proposals yet. Radar runs weekly once capabilities reach trusted/productizable status.
      </div>
      <div v-else class="mb-6">
        <div v-for="(proposals, slug) in radarBySlug" :key="slug"
             class="bg-slate-900 border border-slate-700 rounded-xl p-4 mb-3">
          <h3 class="text-sm font-semibold text-slate-200 mb-2">
            <span class="text-indigo-400 font-mono">{{ slug }}</span>
            <span class="text-slate-500 font-normal ml-2">capability proposals</span>
          </h3>
          <div v-for="p in proposals" :key="p.id"
               class="border border-slate-800 rounded-lg px-3 py-2 mb-2 last:mb-0">
            <div class="flex items-start gap-2">
              <div class="flex-1">
                <p class="text-sm text-slate-300">{{ p.title }}</p>
                <p v-if="p.why" class="text-xs text-slate-500 mt-0.5">{{ p.why }}</p>
                <div v-if="p._detail" class="flex gap-3 mt-1 text-xs text-slate-500 font-mono">
                  <span>reach {{ p._detail.reach }}</span>
                  <span>impact {{ p._detail.impact }}</span>
                  <span>readiness {{ Math.round(Number(p._detail.confidence || 0) * 100) }}%</span>
                  <span>{{ p._detail.effort_days }}d</span>
                  <span class="text-indigo-400 font-semibold">→ {{ p._detail.target_app }}</span>
                </div>
              </div>
              <button @click="productize(p)"
                      :disabled="gtmLoading[p.id]"
                      class="text-xs bg-green-900/50 hover:bg-green-800/70 disabled:opacity-40 text-green-300 rounded px-2 py-1 font-semibold whitespace-nowrap">
                {{ gtmLoading[p.id] ? '…' : 'Productize' }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- ── Live activity log ── -->
      <h2 id="activity" class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">Live activity</h2>
      <div class="mb-6">
        <LogView title="Runner activity" :lines="logLines" height="18rem" />
      </div>

      <!-- ── Proof-Pack Portfolio ── -->
      <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">Proof-pack portfolio</h2>
      <div class="mb-6">
        <ProofPackViewer />
      </div>

      <!-- ── Tasks ── -->
      <h2 id="tasks" class="text-xs uppercase tracking-wider text-slate-500 mb-2">Deployable task flow</h2>
      <div v-if="!deployableTasks.length" class="text-slate-500 italic text-sm mb-6">No deployable tasks visible yet; repair work is handled internally.</div>
      <div v-for="t in deployableTasks" :key="t.id" class="bg-slate-900 border border-slate-800 rounded-xl p-3 mb-2">
        <div class="flex items-center gap-2 flex-wrap">
          <StatusPill :label="t.state" :tone="stateColor[t.state] || 'bg-slate-700'" />
          <b class="text-sm font-mono">{{ t.slug }}</b>
          <span class="text-slate-500 text-xs font-mono">{{ t.model }}</span>
          <span v-if="t.confidence != null" class="text-xs bg-slate-700 text-slate-300 rounded px-1.5 py-0.5 font-mono">
            {{ confidenceLabel(t.confidence) }}</span>
          <span class="flex-1"></span>
          <span v-if="t.note" class="text-slate-500 text-xs">{{ t.note }}</span>
        </div>
        <pre v-if="t.log_tail" class="bg-slate-800/50 border border-slate-800 rounded-md p-2 mt-2 text-xs text-slate-400 overflow-auto max-h-32 whitespace-pre-wrap font-mono">{{ t.log_tail }}</pre>
      </div>

      <!-- ── Runs history ── -->
      <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">Run history</h2>
      <div v-if="!runs.length" class="text-slate-500 italic text-sm mb-6">No runs captured yet.</div>
      <div v-else class="bg-slate-900 border border-slate-800 rounded-xl p-4 mb-3 text-sm overflow-x-auto">
        <table class="w-full text-xs">
          <thead>
            <tr class="text-slate-500 text-left border-b border-slate-800">
              <th class="pb-2 pr-3">Project</th><th class="pb-2 pr-3">Slug</th>
              <th class="pb-2 pr-3">Model</th><th class="pb-2 pr-3">Merge readiness</th>
              <th class="pb-2 pr-3">When</th><th class="pb-2"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in runs" :key="r.id" class="border-b border-slate-800/60 last:border-0">
              <td class="py-1.5 pr-3 text-slate-300">{{ r.project }}</td>
              <td class="py-1.5 pr-3 text-slate-400 font-mono">{{ r.slug }}</td>
              <td class="py-1.5 pr-3 text-slate-500 font-mono">{{ r.model }}</td>
              <td class="py-1.5 pr-3">
                <span v-if="r.confidence != null" class="text-slate-400 font-mono">{{ confidenceLabel(r.confidence) }}</span>
              </td>
              <td class="py-1.5 pr-3 text-slate-500">{{ ago(r.created_at) }}</td>
              <td class="py-1.5">
                <button @click="triggerReplay(r)"
                        class="text-xs bg-indigo-900/50 hover:bg-indigo-800/70 text-indigo-300 rounded px-2 py-0.5">
                  Replay
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- ── ROI panel ── -->
      <h2 id="roi" class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">ROI by project</h2>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 mb-3 text-sm">
        <div v-if="!roiData.length" class="text-slate-500 italic">No outcome data yet.</div>
        <table v-else class="w-full text-xs">
          <thead>
            <tr class="text-slate-500 text-left border-b border-slate-800">
              <th class="pb-2 pr-3">Project</th><th class="pb-2 pr-3">Max-covered</th><th class="pb-2 pr-3">Cash</th>
              <th class="pb-2 pr-3">Merged</th><th class="pb-2 pr-3">$/merge</th><th class="pb-2">Pass rate</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in roiData" :key="r.project" class="border-b border-slate-800/60 last:border-0">
              <td class="py-1.5 pr-3 text-slate-300 font-medium">{{ r.project }}</td>
              <td class="py-1.5 pr-3 text-slate-400" title="Token cost covered by your Claude Max plan — not cash">${{ r.spend }}</td>
              <td class="py-1.5 pr-3 text-emerald-400" title="Real out-of-pocket API cash (month-to-date)">${{ (spendSplitByProject[r.project]?.cash ?? 0).toFixed(2) }}</td>
              <td class="py-1.5 pr-3 text-slate-400">{{ r.merged }}</td>
              <td class="py-1.5 pr-3">
                <span :class="r.cost_per_merge ? 'text-slate-300' : 'text-slate-600'">
                  {{ r.cost_per_merge ? '$' + r.cost_per_merge : '—' }}
                </span>
              </td>
              <td class="py-1.5">
                <span :class="r.pass_rate >= 70 ? 'text-green-400' : r.pass_rate >= 40 ? 'text-amber-400' : 'text-red-400'">
                  {{ r.pass_rate }}%
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- ── Runner fleet ── -->
      <h2 id="runners" class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">Runner fleet</h2>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 text-sm mb-2">
        <div v-if="!runners.length" class="text-slate-500 italic">No runners registered. Start runner.py on a machine.</div>
        <div v-for="r in runners" :key="r.runner_id" class="flex items-center gap-2 border-b border-slate-800 py-1 last:border-0">
          <span class="w-2 h-2 rounded-full" :class="alive(r) ? 'bg-green-400 dot-breathe' : 'bg-red-400'"></span>
          <b class="text-slate-300">{{ r.hostname }}</b>
          <span class="text-slate-500 text-xs font-mono">{{ r.runner_id }}</span>
          <span class="flex-1"></span>
          <span class="text-slate-400 text-xs">{{ r.active_tasks }} active</span>
          <button
            class="ml-2 px-2 py-0.5 text-[10px] rounded bg-slate-700 hover:bg-slate-600 text-slate-300 transition-colors"
            title="Request runner restart"
            @click="restartRunner(r.hostname)"
          >Restart</button>
        </div>
      </div>

      <!-- ── Budgets ── -->
      <h2 id="budgets" class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">Budgets (month-to-date)</h2>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 text-sm mb-2">
        <div v-for="p in projects" :key="p.id" class="mb-3 last:mb-0">
          <div class="flex justify-between mb-1">
            <span class="text-slate-300">{{ p.name }}</span>
            <span class="text-slate-400">${{ budgetFor(p.name).spent.toFixed(2) }}<template v-if="budgetFor(p.name).cap"> / ${{ budgetFor(p.name).cap }}</template></span>
          </div>
          <div v-if="budgetFor(p.name).cap" class="h-2 bg-slate-800 rounded-full overflow-hidden">
            <div class="h-full rounded-full"
                 :class="budgetFor(p.name).spent >= (budgetFor(p.name).cap ?? 0) ? 'bg-red-500' : budgetFor(p.name).spent / (budgetFor(p.name).cap ?? 1) > 0.8 ? 'bg-amber-500' : 'bg-green-500'"
                 :style="{ width: Math.min(100, 100 * budgetFor(p.name).spent / (budgetFor(p.name).cap ?? 1)) + '%' }"></div>
          </div>
          <div v-else class="text-slate-600 text-xs">no cap set</div>
        </div>
      </div>

      <!-- ═══ Loops ════════════════════════════════════════════════════════ -->
      <h2 id="loops" class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-10">Loops</h2>
      <div v-if="!loops.length" class="text-slate-500 italic text-sm mb-6">No loops yet. Loops are auto-created once projects exist.</div>
      <div v-else class="bg-slate-900 border border-slate-800 rounded-xl p-4 mb-6 overflow-x-auto">
        <table class="w-full text-xs">
          <thead>
            <tr class="text-slate-500 text-left border-b border-slate-800">
              <th class="pb-2 pr-3">Project</th>
              <th class="pb-2 pr-3">Type</th>
              <th class="pb-2 pr-3">Health</th>
              <th class="pb-2 pr-3">Cadence</th>
              <th class="pb-2 pr-3">Last run</th>
              <th class="pb-2">Enabled</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="l in loops" :key="l.id" class="border-b border-slate-800/60 last:border-0">
              <td class="py-1.5 pr-3 text-slate-300">{{ l.project }}</td>
              <td class="py-1.5 pr-3">
                <StatusPill :label="l.type"
                      :tone="l.type === 'remediate' ? 'bg-red-900/50 text-red-300' :
                             l.type === 'optimize' ? 'bg-blue-900/50 text-blue-300' :
                             l.type === 'learn' ? 'bg-indigo-900/50 text-indigo-300' :
                             'bg-slate-700 text-slate-300'" />
              </td>
              <td class="py-1.5 pr-3">
                <span :class="Number(l.health) >= 80 ? 'text-green-400' : Number(l.health) >= 50 ? 'text-amber-400' : 'text-red-400'">
                  {{ l.health }}
                </span>
              </td>
              <td class="py-1.5 pr-3 text-slate-400">
                {{ l.cadence_seconds >= 86400 ? Math.round(l.cadence_seconds/86400) + 'd' :
                   l.cadence_seconds >= 3600 ? Math.round(l.cadence_seconds/3600) + 'h' :
                   Math.round(l.cadence_seconds/60) + 'm' }}
              </td>
              <td class="py-1.5 pr-3 text-slate-500">{{ l.last_run ? ago(l.last_run) : 'never' }}</td>
              <td class="py-1.5">
                <button @click="toggleLoop(l)"
                        class="text-xs rounded px-2 py-0.5 font-semibold transition-colors"
                        :class="l.enabled ? 'bg-green-900/50 text-green-300 hover:bg-red-900/50 hover:text-red-300'
                                          : 'bg-slate-700 text-slate-400 hover:bg-green-900/50 hover:text-green-300'">
                  {{ l.enabled ? 'On' : 'Off' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- ═══ Sessions ══════════════════════════════════════════════════════ -->
      <h2 id="sessions" class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">Sessions</h2>
      <div v-if="!sessions.length" class="text-slate-500 italic text-sm mb-6">No paused/finished sessions detected yet.</div>
      <div v-else class="mb-6 space-y-2">
        <div v-for="s in sessions" :key="s.id"
             class="bg-slate-900 border rounded-xl p-3"
             :class="s.status === 'finished' ? 'border-green-700/40' : 'border-amber-600/40'">
          <div class="flex items-center gap-2 flex-wrap">
            <StatusPill :label="s.status"
                        :tone="s.status === 'finished' ? 'bg-green-900/50 text-green-300' : 'bg-amber-900/50 text-amber-300'" />
            <span class="text-sm text-slate-300 font-medium">{{ s.project }}</span>
            <span class="text-xs text-slate-500 font-mono">{{ s.session_id?.slice(0, 12) }}</span>
            <span class="flex-1"></span>
            <span class="text-xs text-slate-500">{{ ago(s.created_at) }}</span>
          </div>
          <p v-if="s.next_action" class="text-sm text-slate-400 mt-1.5">
            <span class="text-slate-500 text-xs font-semibold uppercase mr-1">Next</span>{{ s.next_action }}
          </p>
          <div class="mt-2 flex gap-2">
            <button v-if="s.status === 'paused' && s.next_action"
                    @click="runSession(s)" :disabled="sessionRunning[s.id]"
                    class="text-xs bg-[#1f5c56] hover:bg-[#276f68] disabled:opacity-40 text-white rounded px-3 py-1 font-semibold">
              {{ sessionRunning[s.id] ? 'Queuing…' : 'Run it' }}
            </button>
          </div>
        </div>
      </div>

      <!-- ═══ Resources ══════════════════════════════════════════════════════ -->
      <h2 id="resources" class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">Resources</h2>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 mb-6">
        <div v-if="resourceGauge.disk_pct != null" class="mb-4">
          <div class="flex justify-between text-xs text-slate-400 mb-1">
            <span>Disk used</span>
            <span>{{ resourceGauge.disk_pct }}% · {{ resourceGauge.free_gb?.toFixed(1) }} GB free</span>
          </div>
          <div class="h-3 bg-slate-800 rounded-full overflow-hidden">
            <div class="h-full rounded-full transition-all"
                 :class="resourceGauge.disk_pct >= 90 ? 'bg-red-500' : resourceGauge.disk_pct >= 80 ? 'bg-amber-500' : 'bg-green-500'"
                 :style="{ width: resourceGauge.disk_pct + '%' }"></div>
          </div>
          <p class="text-xs text-slate-500 mt-1">Last checked {{ resourceGauge.ts ? ago(resourceGauge.ts) : '–' }}</p>
        </div>
        <div v-else class="text-slate-600 italic text-sm mb-4">No disk readings yet. resource_governor runs every 3 min.</div>
        <div class="grid grid-cols-3 gap-3 text-center mb-4">
          <div class="bg-slate-800 rounded-lg p-3">
            <div class="text-lg font-semibold" :class="resourceGauge.disk_pct >= 90 ? 'text-red-400' : 'text-slate-200'">
              {{ resourceGauge.disk_pct != null ? resourceGauge.disk_pct + '%' : '–' }}
            </div>
            <div class="text-xs text-slate-500 mt-0.5">Disk used</div>
          </div>
          <div class="bg-slate-800 rounded-lg p-3">
            <div class="text-lg font-semibold text-slate-200">
              {{ resourceGauge.free_gb != null ? resourceGauge.free_gb?.toFixed(1) + ' GB' : '–' }}
            </div>
            <div class="text-xs text-slate-500 mt-0.5">Free space</div>
          </div>
          <div class="bg-slate-800 rounded-lg p-3">
            <div class="text-lg font-semibold text-slate-200">Current throttle</div>
            <div class="text-xs text-slate-500 mt-0.5">see runner env</div>
          </div>
        </div>
        <div class="grid grid-cols-2 gap-3 text-center mb-4">
          <div class="bg-slate-800 rounded-lg p-3">
            <div class="text-lg font-semibold text-cyan-300">{{ Math.round(savingsKpi.tokens).toLocaleString() }}</div>
            <div class="text-xs text-slate-500 mt-0.5">Tokens avoided</div>
          </div>
          <div class="bg-slate-800 rounded-lg p-3">
            <div class="text-lg font-semibold text-cyan-300">{{ savingsKpi.minutes.toFixed(1) }}</div>
            <div class="text-xs text-slate-500 mt-0.5">Minutes avoided</div>
          </div>
        </div>
        <div v-if="recentPrunes.length">
          <h3 class="text-xs uppercase text-slate-500 mb-1">Recent prunes</h3>
          <div v-for="p in recentPrunes" :key="p.created_at"
               class="text-xs text-slate-500 border-b border-slate-800 py-1 last:border-0 flex justify-between">
            <span class="font-mono">{{ p.detail }}</span>
            <span class="text-slate-500">{{ ago(p.created_at) }}</span>
          </div>
        </div>
      </div>

      <!-- ═══ Feedback ══════════════════════════════════════════════════════ -->
      <h2 id="feedback" class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">Feedback</h2>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 mb-6">
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          <div class="bg-slate-800 rounded-lg p-3 text-center">
            <div class="text-xl font-semibold text-blue-400">{{ feedbackStats.newCount }}</div>
            <div class="text-xs text-slate-500 mt-0.5">New / unread</div>
          </div>
          <div class="bg-slate-800 rounded-lg p-3 text-center">
            <div class="text-xl font-semibold text-slate-200">{{ feedbackStats.total }}</div>
            <div class="text-xs text-slate-500 mt-0.5">Total items</div>
          </div>
          <div class="bg-slate-800 rounded-lg p-3 col-span-2">
            <div class="text-xs text-slate-500 mb-1">By severity</div>
            <div class="flex gap-3 text-xs">
              <span class="text-red-400 font-semibold">{{ feedbackStats.sevs['high'] || 0 }} high</span>
              <span class="text-amber-400">{{ feedbackStats.sevs['med'] || 0 }} med</span>
              <span class="text-slate-400">{{ feedbackStats.sevs['low'] || 0 }} low</span>
            </div>
          </div>
        </div>
        <div v-if="Object.keys(feedbackStats.cats).length" class="flex flex-wrap gap-2 mb-4">
          <span v-for="(cnt, cat) in feedbackStats.cats" :key="cat"
                class="text-xs bg-slate-700 text-slate-300 rounded-full px-2 py-0.5">
            {{ cat }}: {{ cnt }}
          </span>
        </div>
        <div class="border-t border-slate-800 pt-4">
          <h3 class="text-xs text-slate-400 font-semibold mb-2">Add human feedback</h3>
          <div class="grid grid-cols-2 gap-2 mb-2">
            <select v-model="newFeedback.category" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm">
              <option v-for="c in ['context','model','prompt','tooling','guardrail','strategy','rate_limit','other']" :key="c">{{ c }}</option>
            </select>
            <select v-model="newFeedback.severity" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm">
              <option>low</option><option>med</option><option>high</option>
            </select>
          </div>
          <textarea v-model="newFeedback.observation" placeholder="Observation — what went wrong or what could be better?"
                    rows="2" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm mb-2"></textarea>
          <textarea v-model="newFeedback.suggestion" placeholder="Suggestion (optional)"
                    rows="1" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm mb-2"></textarea>
          <button @click="submitFeedback" :disabled="feedbackSaving"
                  class="bg-[#3d3a6b] hover:bg-[#4a4680] disabled:opacity-40 text-white rounded-lg px-4 py-2 text-sm font-semibold">
            {{ feedbackSaving ? 'Saving…' : 'Submit feedback' }}
          </button>
        </div>
      </div>

      <!-- ═══ Spend & Keys ══════════════════════════════════════════════════ -->
      <div id="spend-keys" class="flex items-center gap-3 mt-10 mb-2 flex-wrap">
        <h2 class="text-xs uppercase tracking-wider text-slate-500">Spend &amp; Keys</h2>
        <span class="flex-1"></span>
        <button v-if="!globalPaused" @click="stopAll" :disabled="stopLoading"
                class="bg-[#a83a2a] hover:bg-[#bf4632] disabled:opacity-40 text-white rounded-lg px-4 py-1.5 text-sm font-bold transition-colors">
          {{ stopLoading ? 'Stopping…' : '⏹ STOP ALL' }}
        </button>
        <button v-else @click="resumeAll" :disabled="stopLoading"
                class="bg-[#2f6b46] hover:bg-[#3a7d54] disabled:opacity-40 text-white rounded-lg px-4 py-1.5 text-sm font-bold transition-colors">
          {{ stopLoading ? 'Resuming…' : '▶ Resume' }}
        </button>
      </div>
      <div v-if="globalPaused" class="bg-red-950/60 border border-red-700/60 rounded-xl px-4 py-2 mb-4 text-red-300 text-sm font-semibold">
        ⛔ Runner is GLOBALLY PAUSED. No tasks will be claimed until you resume.
      </div>

      <!-- Provider spend table -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 mb-4 overflow-x-auto">
        <h3 class="text-xs text-slate-500 uppercase mb-3">Provider spend (month-to-date)</h3>
        <div v-if="!providerSpend.length" class="text-slate-600 italic text-sm">No external provider spend recorded yet.</div>
        <table v-else class="w-full text-xs">
          <thead>
            <tr class="text-slate-500 text-left border-b border-slate-800">
              <th class="pb-2 pr-3">Provider</th>
              <th class="pb-2 pr-3">Project</th>
              <th class="pb-2 pr-3">Spent MTD</th>
              <th class="pb-2 pr-8">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in providerSpend" :key="`${s.provider}-${s.project}`"
                class="border-b border-slate-800/60 last:border-0">
              <td class="py-1.5 pr-3 text-slate-300 font-medium">
                {{ s.provider }}
                <span :class="isNotional(s.provider) ? 'bg-slate-700 text-slate-400' : 'bg-emerald-900/60 text-emerald-300'"
                      class="ml-1 text-[9px] px-1 py-0.5 rounded uppercase tracking-wide">{{ isNotional(s.provider) ? 'Max-covered' : 'cash' }}</span>
              </td>
              <td class="py-1.5 pr-3 text-slate-400">{{ s.project || '—' }}</td>
              <td class="py-1.5 pr-3">
                <span v-if="isNotional(s.provider)" class="text-slate-500" title="Covered by Claude Max plan — not cash">${{ Number(s.spent).toFixed(2) }}</span>
                <span v-else :class="Number(s.spent) > 20 ? 'text-amber-400' : 'text-emerald-300'">${{ Number(s.spent).toFixed(2) }}</span>
              </td>
              <td class="py-1.5">
                <div class="flex items-center gap-2">
                  <button @click="rotateKey(s.provider, s.provider.toUpperCase() + '_API_KEY', s.project)"
                          :disabled="rotateLoading[`${s.provider}/${s.provider.toUpperCase()}_API_KEY`]"
                          class="text-[10px] bg-slate-700 hover:bg-amber-900/60 disabled:opacity-40 text-slate-300 hover:text-amber-300 rounded px-2 py-0.5 whitespace-nowrap">
                    Rotate key
                  </button>
                  <button @click="panicStopAndRevoke(s.provider)"
                          :disabled="panicLoading"
                          class="text-[10px] bg-red-950/80 hover:bg-red-900/80 border border-red-800/60 disabled:opacity-40 text-red-400 hover:text-red-300 rounded px-2 py-0.5 whitespace-nowrap"
                          title="Security panic: stop runner + revoke all active keys for this provider">
                    ☠ Revoke
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Credential requests -->
      <div v-if="credRequests.length" class="bg-slate-900 border border-slate-700 rounded-xl p-4 mb-6">
        <h3 class="text-xs text-slate-500 uppercase mb-3">Credential requests</h3>
        <div v-for="cr in credRequests" :key="cr.id"
             class="border-b border-slate-800 py-2 last:border-0 flex items-start gap-3">
          <span class="text-xs px-2 py-0.5 rounded-full font-bold whitespace-nowrap"
                :class="cr.status === 'payment_required' ? 'bg-red-900/60 text-red-300' : 'bg-amber-900/60 text-amber-300'">
            {{ cr.status === 'payment_required' ? '💳 payment required' : cr.status }}
          </span>
          <div class="flex-1">
            <p class="text-sm text-slate-300"><b>{{ cr.provider }}</b><span v-if="cr.project" class="text-slate-500 ml-2">{{ cr.project }}</span></p>
            <p v-if="cr.reason" class="text-xs text-slate-500 mt-0.5">{{ cr.reason }}</p>
          </div>
          <span class="text-xs text-slate-500 whitespace-nowrap">{{ ago(cr.created_at) }}</span>
        </div>
      </div>

      <!-- ── Spend burn-down ── -->
      <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">Spend burn-down</h2>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 text-sm">
        <canvas id="spendChart" height="110"></canvas>
        <div class="grid grid-cols-2 gap-x-6 mt-3">
          <div v-for="[m, v] in byModel" :key="m" class="flex justify-between border-b border-slate-800 py-1">
            <span class="text-slate-300 font-mono">{{ m }}</span><span class="text-slate-400 font-mono">${{ v.toFixed(2) }}</span>
          </div>
        </div>
        <div class="flex justify-between pt-2 font-semibold"><span>Total</span><span class="font-mono">${{ spend.toFixed(2) }}</span></div>
      </div>

      </div><!-- /.max-w-5xl -->
      </div><!-- /.flex-1 main content -->
    </div><!-- /.flex dashboard -->
  </div><!-- /.min-h-screen -->
</template>
