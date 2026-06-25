<script setup lang="ts">
const supabase = useSupabaseClient()
const user = useSupabaseUser()

// ── auth ──────────────────────────────────────────────────────────────────
const email = ref('')
const sent = ref(false)
async function signIn() { await supabase.auth.signInWithOtp({ email: email.value }); sent.value = true }
async function signOut() { await supabase.auth.signOut() }

// ── data ──────────────────────────────────────────────────────────────────
const tasks = ref<any[]>([])
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
let chart: any = null

const newTask = reactive({ project_id: '', slug: '', prompt: '', kind: 'build' })
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
async function loadAll() {
  const [t, a, o, r, p, b, r2, h, g, i, tx] = await Promise.all([
    supabase.from('tasks').select('*').order('created_at', { ascending: false }).limit(200),
    supabase.from('approvals').select('*').eq('status', 'pending').order('created_at'),
    supabase.from('outcomes').select('model,usd,project,tests_passed,integrated,created_at').order('created_at').limit(2000),
    supabase.from('runner_heartbeats').select('*'),
    supabase.from('projects').select('*').order('name'),
    supabase.from('budgets').select('*'),
    supabase.from('runs').select('*').order('created_at', { ascending: false }).limit(100),
    supabase.from('v_project_health').select('*'),
    supabase.from('goals').select('*').eq('status', 'active').order('priority'),
    supabase.from('v_action_inbox').select('*').limit(20),
    supabase.from('txns').select('*').order('created_at', { ascending: false }).limit(50),
  ])
  tasks.value = t.data || []; approvals.value = a.data || []
  outcomes.value = o.data || []; runners.value = r.data || []; projects.value = p.data || []
  budgets.value = b.data || []; runs.value = r2.data || []; health.value = h.data || []
  goals.value = g.data || []; inbox.value = i.data || []; txns.value = tx.data || []
  if (!newTask.project_id && projects.value[0]) newTask.project_id = projects.value[0].id
  renderChart()
}

// ── approvals ─────────────────────────────────────────────────────────────
async function decide(id: string, status: 'approved' | 'denied') {
  const a = approvals.value.find(x => x.id === id)
  if (!a) return

  if (status === 'approved' && a.approvals_required >= 2) {
    if (!a.decided_by) {
      // First approval: record approver, leave status pending
      await supabase.from('approvals').update({ decided_by: user.value?.email }).eq('id', id)
      a.decided_by = user.value?.email   // update local copy to re-render
      return
    }
    if (a.decided_by === user.value?.email) {
      alert('You already approved this. A different team member must provide the second approval.')
      return
    }
    // Second approval from a different user → flip to approved
    await supabase.from('approvals').update({
      status: 'approved',
      second_approver: user.value?.email,
      decided_at: new Date().toISOString(),
    }).eq('id', id)
  } else {
    await supabase.from('approvals').update({
      status, decided_at: new Date().toISOString(), decided_by: user.value?.email,
    }).eq('id', id)
  }
  approvals.value = approvals.value.filter(x => x.id !== id)
}

// ── tasks ─────────────────────────────────────────────────────────────────
async function queueTask() {
  if (!newTask.project_id || !newTask.prompt) return
  await supabase.from('tasks').insert({
    project_id: newTask.project_id, slug: newTask.slug || 'task-' + Date.now(),
    prompt: newTask.prompt, kind: newTask.kind, state: 'QUEUED',
  })
  newTask.slug = ''; newTask.prompt = ''; loadAll()
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
    data: { datasets: [{ label: 'Cumulative spend ($)', data: pts, borderColor: '#58a6ff',
      backgroundColor: 'rgba(56,139,253,.15)', fill: true, tension: .25, pointRadius: 0 }] },
    options: { responsive: true, plugins: { legend: { labels: { color: '#8b98ad' } } },
      scales: { x: { type: 'linear', ticks: { color: '#8b98ad',
        callback: (v: any) => new Date(v).toLocaleDateString() } },
        y: { ticks: { color: '#8b98ad' } } } },
  })
}

function alive(r: any) { return (Date.now() - new Date(r.last_seen).getTime()) < 60000 }
function fmtConf(c: any) { return c != null ? Math.round(Number(c) * 100) + '%' : '' }
function ago(ts: string) {
  const d = Math.round((Date.now() - new Date(ts).getTime()) / 60000)
  return d < 60 ? `${d}m ago` : d < 1440 ? `${Math.round(d/60)}h ago` : `${Math.round(d/1440)}d ago`
}

const spend = computed(() => outcomes.value.reduce((s, o) => s + Number(o.usd || 0), 0))
const byModel = computed(() => {
  const m: Record<string, number> = {}
  for (const o of outcomes.value) m[o.model] = (m[o.model] || 0) + Number(o.usd || 0)
  return Object.entries(m).sort((a, b) => b[1] - a[1])
})

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

onMounted(() => {
  if (user.value) {
    loadAll()
    supabase.channel('orch')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'tasks' }, loadAll)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'approvals' }, loadAll)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'runner_heartbeats' }, loadAll)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'runs' }, loadAll)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'txns' }, loadAll)
      .subscribe()
  }
})
watch(user, u => { if (u) loadAll() })
</script>

<template>
  <div class="min-h-screen">

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
      <header class="flex items-center gap-3 mb-6">
        <span class="w-2 h-2 rounded-full" :class="runners.some(alive) ? 'bg-green-400' : 'bg-red-400'"></span>
        <h1 class="text-lg font-semibold">Claude Orchestrator</h1>
        <span class="text-slate-500 text-sm">
          {{ runners.filter(alive).length }} runner(s) · {{ approvals.length }} pending · ${{ spend.toFixed(2) }} spent
        </span>
        <span class="flex-1"></span>
        <button @click="signOut" class="text-slate-400 text-sm hover:text-white">Sign out</button>
      </header>

      <!-- ── NL analytics search ── -->
      <div class="bg-slate-900 border border-slate-700 rounded-xl p-4 mb-6">
        <div class="flex gap-2">
          <input v-model="nlQuery" @keydown.enter="askNL" placeholder="Ask a question: 'which projects are blocked?' or 'where is money going?'"
                 class="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm" />
          <button @click="askNL" :disabled="nlLoading"
                  class="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 rounded-lg px-4 py-2 text-sm font-semibold">
            {{ nlLoading ? '…' : 'Ask' }}</button>
        </div>
        <p v-if="nlAnswer" class="mt-3 text-sm text-slate-300 whitespace-pre-wrap border-t border-slate-800 pt-3">{{ nlAnswer }}</p>
      </div>

      <!-- ── Health & Goals ── -->
      <div v-if="health.length || goals.length" class="grid sm:grid-cols-2 gap-4 mb-6">
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
      <div v-if="inbox.length" class="mb-6">
        <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-2">Action inbox</h2>
        <div v-for="item in inbox" :key="item.id ?? item.title"
             class="bg-slate-900 border border-slate-700 rounded-xl px-4 py-2 mb-2 flex items-center gap-3">
          <span class="text-[10px] uppercase font-bold text-slate-400">{{ item.kind ?? item.type }}</span>
          <span class="text-sm text-slate-300 flex-1">{{ item.title ?? item.message }}</span>
          <span class="text-xs text-slate-500">{{ item.project }}</span>
        </div>
      </div>

      <!-- ── Approvals (with two-key enforcement) ── -->
      <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-2">Needs your approval</h2>
      <div v-if="!approvals.length" class="text-slate-600 italic text-sm mb-6">Nothing waiting. The swarm is flowing.</div>
      <div v-for="a in approvals" :key="a.id" class="bg-slate-900 border border-amber-600/60 rounded-xl p-4 mb-3">
        <div class="flex items-center gap-2">
          <span class="text-[10px] uppercase font-bold text-amber-400">{{ a.kind }}</span>
          <b>{{ a.title }}</b>
          <span v-if="a.approvals_required >= 2"
                class="text-[10px] bg-red-900/60 text-red-300 rounded px-1.5 py-0.5 font-bold">2-KEY</span>
          <span class="flex-1"></span>
          <span class="text-slate-500 text-xs">{{ a.project }}</span>
        </div>
        <p v-if="a.why" class="text-sm mt-2"><span class="text-amber-400 text-xs font-semibold uppercase mr-2">Why</span>{{ a.why }}</p>
        <p v-if="a.value" class="text-sm mt-1"><span class="text-amber-400 text-xs font-semibold uppercase mr-2">Value</span>{{ a.value }}</p>
        <p v-if="a.risk" class="text-sm mt-1"><span class="text-amber-400 text-xs font-semibold uppercase mr-2">Risk</span>{{ a.risk }}</p>
        <pre v-if="a.detail" class="bg-black/40 border border-slate-700 rounded-md p-2 mt-2 text-xs text-slate-300 overflow-auto max-h-44 whitespace-pre-wrap">{{ a.detail }}</pre>
        <!-- two-key status indicator -->
        <p v-if="a.approvals_required >= 2 && a.decided_by" class="text-xs text-green-400 mt-2">
          ✓ First approval: {{ a.decided_by }} — one more needed from a different user
        </p>
        <div class="flex gap-2 mt-3">
          <button @click="decide(a.id, 'approved')"
                  class="bg-green-600 hover:bg-green-500 rounded-lg px-4 py-1.5 font-semibold text-sm">
            {{ a.approvals_required >= 2 && !a.decided_by ? 'Approve (1st)' : a.approvals_required >= 2 && a.decided_by !== user?.email ? 'Approve (2nd)' : 'Approve' }}
          </button>
          <button @click="decide(a.id, 'denied')" class="bg-red-600 hover:bg-red-500 rounded-lg px-4 py-1.5 font-semibold text-sm">Deny</button>
        </div>
      </div>

      <!-- ── Transactions ── -->
      <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">Cross-repo transactions</h2>
      <div class="bg-slate-900 border border-slate-700 rounded-xl p-4 mb-3 grid sm:grid-cols-[auto_1fr_1fr_auto] gap-2 items-center">
        <input v-model="newTxn.id" placeholder="txn-id (kebab)" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm" />
        <input v-model="newTxn.name" placeholder="Name" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm" />
        <input v-model="newTxn.description" placeholder="Description (optional)" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm" />
        <button @click="createTxn" class="bg-indigo-600 hover:bg-indigo-500 rounded-lg px-4 py-2 text-sm font-semibold">Create</button>
      </div>
      <div v-if="txns.length" class="bg-slate-900 border border-slate-800 rounded-xl p-4 mb-3 text-sm">
        <div v-for="tx in txns" :key="tx.id" class="flex items-center gap-2 py-1 border-b border-slate-800 last:border-0">
          <span class="text-[10px] px-2 py-0.5 rounded-full font-semibold" :class="txnColor[tx.status] || 'bg-slate-700'">{{ tx.status }}</span>
          <b class="text-slate-300">{{ tx.id }}</b>
          <span class="text-slate-400">{{ tx.name }}</span>
          <span class="flex-1"></span>
          <span class="text-slate-500 text-xs">{{ ago(tx.created_at) }}</span>
        </div>
      </div>
      <div v-else class="text-slate-600 italic text-sm mb-6">No transactions yet. Tag tasks with <code>txn:&lt;id&gt;</code> in their note to join one.</div>

      <!-- ── Queue a task ── -->
      <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">Queue a task</h2>
      <div class="bg-slate-900 border border-slate-700 rounded-xl p-4 mb-6 grid sm:grid-cols-[1fr_1fr_auto] gap-2">
        <select v-model="newTask.project_id" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm">
          <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
        <input v-model="newTask.slug" placeholder="slug (optional)" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm" />
        <select v-model="newTask.kind" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm">
          <option>build</option><option>research</option><option>efficiency</option><option>speculative</option>
        </select>
        <textarea v-model="newTask.prompt" placeholder="scoped task prompt…" rows="2"
                  class="sm:col-span-3 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"></textarea>
        <button @click="queueTask" class="sm:col-span-3 bg-blue-600 hover:bg-blue-500 rounded-lg py-2 font-semibold text-sm">Queue</button>
      </div>

      <!-- ── Tasks ── -->
      <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-2">Tasks</h2>
      <div v-for="t in tasks" :key="t.id" class="bg-slate-900 border border-slate-800 rounded-xl p-3 mb-2">
        <div class="flex items-center gap-2 flex-wrap">
          <span class="text-[10px] px-2 py-0.5 rounded-full font-semibold" :class="stateColor[t.state] || 'bg-slate-700'">{{ t.state }}</span>
          <b class="text-sm">{{ t.slug }}</b>
          <span class="text-slate-500 text-xs">{{ t.model }}</span>
          <span v-if="t.confidence != null" class="text-[10px] bg-slate-700 text-slate-300 rounded px-1.5 py-0.5">
            conf {{ fmtConf(t.confidence) }}</span>
          <span class="flex-1"></span>
          <span v-if="t.note" class="text-slate-500 text-xs">{{ t.note }}</span>
        </div>
        <pre v-if="t.log_tail" class="bg-black/40 border border-slate-800 rounded-md p-2 mt-2 text-[11px] text-slate-400 overflow-auto max-h-32 whitespace-pre-wrap">{{ t.log_tail }}</pre>
      </div>

      <!-- ── Runs history ── -->
      <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">Run history</h2>
      <div v-if="!runs.length" class="text-slate-600 italic text-sm mb-6">No runs captured yet.</div>
      <div v-else class="bg-slate-900 border border-slate-800 rounded-xl p-4 mb-3 text-sm overflow-x-auto">
        <table class="w-full text-xs">
          <thead>
            <tr class="text-slate-500 text-left border-b border-slate-800">
              <th class="pb-2 pr-3">Project</th><th class="pb-2 pr-3">Slug</th>
              <th class="pb-2 pr-3">Model</th><th class="pb-2 pr-3">Conf</th>
              <th class="pb-2 pr-3">When</th><th class="pb-2"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in runs" :key="r.id" class="border-b border-slate-800/60 last:border-0">
              <td class="py-1.5 pr-3 text-slate-300">{{ r.project }}</td>
              <td class="py-1.5 pr-3 text-slate-400">{{ r.slug }}</td>
              <td class="py-1.5 pr-3 text-slate-500">{{ r.model }}</td>
              <td class="py-1.5 pr-3">
                <span v-if="r.confidence != null" class="text-slate-400">{{ fmtConf(r.confidence) }}</span>
              </td>
              <td class="py-1.5 pr-3 text-slate-500">{{ ago(r.created_at) }}</td>
              <td class="py-1.5">
                <button @click="triggerReplay(r)"
                        class="text-[10px] bg-indigo-900/50 hover:bg-indigo-800/70 text-indigo-300 rounded px-2 py-0.5">
                  Replay
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- ── ROI panel ── -->
      <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">ROI by project</h2>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 mb-3 text-sm">
        <div v-if="!roiData.length" class="text-slate-600 italic">No outcome data yet.</div>
        <table v-else class="w-full text-xs">
          <thead>
            <tr class="text-slate-500 text-left border-b border-slate-800">
              <th class="pb-2 pr-3">Project</th><th class="pb-2 pr-3">Spend</th>
              <th class="pb-2 pr-3">Merged</th><th class="pb-2 pr-3">$/merge</th><th class="pb-2">Pass rate</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in roiData" :key="r.project" class="border-b border-slate-800/60 last:border-0">
              <td class="py-1.5 pr-3 text-slate-300 font-medium">{{ r.project }}</td>
              <td class="py-1.5 pr-3 text-slate-400">${{ r.spend }}</td>
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
      <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">Runner fleet</h2>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 text-sm mb-2">
        <div v-if="!runners.length" class="text-slate-600 italic">No runners registered. Start runner.py on a machine.</div>
        <div v-for="r in runners" :key="r.runner_id" class="flex items-center gap-2 border-b border-slate-800 py-1 last:border-0">
          <span class="w-2 h-2 rounded-full" :class="alive(r) ? 'bg-green-400' : 'bg-red-400'"></span>
          <b class="text-slate-300">{{ r.hostname }}</b>
          <span class="text-slate-500 text-xs">{{ r.runner_id }}</span>
          <span class="flex-1"></span>
          <span class="text-slate-400 text-xs">{{ r.active_tasks }} active</span>
        </div>
      </div>

      <!-- ── Budgets ── -->
      <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">Budgets (month-to-date)</h2>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 text-sm mb-2">
        <div v-for="p in projects" :key="p.id" class="mb-3 last:mb-0">
          <div class="flex justify-between mb-1">
            <span class="text-slate-300">{{ p.name }}</span>
            <span class="text-slate-400">${{ budgetFor(p.name).spent.toFixed(2) }}<template v-if="budgetFor(p.name).cap"> / ${{ budgetFor(p.name).cap }}</template></span>
          </div>
          <div v-if="budgetFor(p.name).cap" class="h-2 bg-slate-800 rounded-full overflow-hidden">
            <div class="h-full rounded-full"
                 :class="budgetFor(p.name).spent >= budgetFor(p.name).cap ? 'bg-red-500' : budgetFor(p.name).spent / budgetFor(p.name).cap > 0.8 ? 'bg-amber-500' : 'bg-green-500'"
                 :style="{ width: Math.min(100, 100 * budgetFor(p.name).spent / (budgetFor(p.name).cap ?? 1)) + '%' }"></div>
          </div>
          <div v-else class="text-slate-600 text-xs">no cap set</div>
        </div>
      </div>

      <!-- ── Spend burn-down ── -->
      <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">Spend burn-down</h2>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 text-sm">
        <canvas id="spendChart" height="110"></canvas>
        <div class="grid grid-cols-2 gap-x-6 mt-3">
          <div v-for="[m, v] in byModel" :key="m" class="flex justify-between border-b border-slate-800 py-1">
            <span class="text-slate-300">{{ m }}</span><span class="text-slate-400">${{ v.toFixed(2) }}</span>
          </div>
        </div>
        <div class="flex justify-between pt-2 font-semibold"><span>Total</span><span>${{ spend.toFixed(2) }}</span></div>
      </div>

    </div>
  </div>
</template>
