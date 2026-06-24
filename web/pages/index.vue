<script setup lang="ts">
const supabase = useSupabaseClient()
const user = useSupabaseUser()

const email = ref('')
const sent = ref(false)
const tasks = ref<any[]>([])
const approvals = ref<any[]>([])
const outcomes = ref<any[]>([])
const runners = ref<any[]>([])
const projects = ref<any[]>([])
const budgets = ref<any[]>([])
const newTask = reactive({ project_id: '', slug: '', prompt: '', kind: 'build' })
let chart: any = null

async function signIn() {
  await supabase.auth.signInWithOtp({ email: email.value })
  sent.value = true
}
async function signOut() { await supabase.auth.signOut() }

async function loadAll() {
  const [t, a, o, r, p, b] = await Promise.all([
    supabase.from('tasks').select('*').order('created_at', { ascending: false }).limit(200),
    supabase.from('approvals').select('*').eq('status', 'pending').order('created_at'),
    supabase.from('outcomes').select('model,usd,project,tests_passed,created_at').order('created_at').limit(2000),
    supabase.from('runner_heartbeats').select('*'),
    supabase.from('projects').select('*').order('name'),
    supabase.from('budgets').select('*')
  ])
  tasks.value = t.data || []; approvals.value = a.data || []
  outcomes.value = o.data || []; runners.value = r.data || []; projects.value = p.data || []
  budgets.value = b.data || []
  if (!newTask.project_id && projects.value[0]) newTask.project_id = projects.value[0].id
  renderChart()
}

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
  const Chart = (await import('https://cdn.jsdelivr.net/npm/chart.js@4.4.3/+esm')).default
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
        y: { ticks: { color: '#8b98ad' } } } }
  })
}

async function decide(id: string, status: 'approved' | 'denied') {
  await supabase.from('approvals').update({
    status, decided_at: new Date().toISOString(), decided_by: user.value?.email
  }).eq('id', id)
  approvals.value = approvals.value.filter(a => a.id !== id)
}

async function queueTask() {
  if (!newTask.project_id || !newTask.prompt) return
  await supabase.from('tasks').insert({
    project_id: newTask.project_id, slug: newTask.slug || 'task-' + Date.now(),
    prompt: newTask.prompt, kind: newTask.kind, state: 'QUEUED'
  })
  newTask.slug = ''; newTask.prompt = ''
  loadAll()
}

const spend = computed(() => outcomes.value.reduce((s, o) => s + Number(o.usd || 0), 0))
const byModel = computed(() => {
  const m: Record<string, number> = {}
  for (const o of outcomes.value) m[o.model] = (m[o.model] || 0) + Number(o.usd || 0)
  return Object.entries(m).sort((a, b) => b[1] - a[1])
})
function alive(r: any) { return (Date.now() - new Date(r.last_seen).getTime()) < 60000 }
const stateColor: Record<string, string> = {
  RUNNING: 'bg-blue-500/20 text-blue-300', DONE: 'bg-green-500/20 text-green-300',
  MERGED: 'bg-green-500/20 text-green-300', QUEUED: 'bg-slate-500/20 text-slate-300',
  WAITING: 'bg-slate-500/20 text-slate-300', RETRY: 'bg-amber-500/20 text-amber-300',
  BLOCKED: 'bg-red-500/20 text-red-300', CONFLICT: 'bg-red-500/20 text-red-300',
  TESTFAIL: 'bg-red-500/20 text-red-300'
}

onMounted(() => {
  if (user.value) {
    loadAll()
    supabase.channel('orch')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'tasks' }, loadAll)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'approvals' }, loadAll)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'runner_heartbeats' }, loadAll)
      .subscribe()
  }
})
watch(user, (u) => { if (u) loadAll() })
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
      <header class="flex items-center gap-3 mb-6">
        <span class="w-2 h-2 rounded-full" :class="runners.some(alive) ? 'bg-green-400' : 'bg-red-400'"></span>
        <h1 class="text-lg font-semibold">Claude Orchestrator</h1>
        <span class="text-slate-500 text-sm">
          {{ runners.filter(alive).length }} runner(s) online · {{ approvals.length }} awaiting · ${{ spend.toFixed(2) }} spent
        </span>
        <span class="flex-1"></span>
        <button @click="signOut" class="text-slate-400 text-sm hover:text-white">Sign out</button>
      </header>

      <!-- approvals -->
      <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-2">Needs your approval</h2>
      <div v-if="!approvals.length" class="text-slate-600 italic text-sm mb-6">Nothing waiting. The swarm is flowing.</div>
      <div v-for="a in approvals" :key="a.id" class="bg-slate-900 border border-amber-600/60 rounded-xl p-4 mb-3">
        <div class="flex items-center gap-2">
          <span class="text-[10px] uppercase font-bold text-amber-400">{{ a.kind }}</span>
          <b>{{ a.title }}</b>
          <span class="flex-1"></span>
          <span class="text-slate-500 text-xs">{{ a.project }}</span>
        </div>
        <p v-if="a.why" class="text-sm mt-2"><span class="text-amber-400 text-xs font-semibold uppercase mr-2">Why</span>{{ a.why }}</p>
        <p v-if="a.value" class="text-sm mt-1"><span class="text-amber-400 text-xs font-semibold uppercase mr-2">Value</span>{{ a.value }}</p>
        <p v-if="a.risk" class="text-sm mt-1"><span class="text-amber-400 text-xs font-semibold uppercase mr-2">Risk</span>{{ a.risk }}</p>
        <ul v-if="a.alternatives?.length" class="text-slate-400 text-sm mt-1 list-disc ml-6">
          <li v-for="(alt, i) in a.alternatives" :key="i">{{ alt }}</li>
        </ul>
        <pre v-if="a.command" class="bg-black/40 border border-slate-700 rounded-md p-2 mt-2 text-xs text-orange-300 overflow-auto">{{ a.command }}</pre>
        <pre v-if="a.detail" class="bg-black/40 border border-slate-700 rounded-md p-2 mt-2 text-xs text-slate-300 overflow-auto max-h-44 whitespace-pre-wrap">{{ a.detail }}</pre>
        <div class="flex gap-2 mt-3">
          <button @click="decide(a.id, 'approved')" class="bg-green-600 hover:bg-green-500 rounded-lg px-4 py-1.5 font-semibold text-sm">Approve</button>
          <button @click="decide(a.id, 'denied')" class="bg-red-600 hover:bg-red-500 rounded-lg px-4 py-1.5 font-semibold text-sm">Deny</button>
        </div>
      </div>

      <!-- new task -->
      <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">Queue a task</h2>
      <div class="bg-slate-900 border border-slate-700 rounded-xl p-4 mb-6 grid sm:grid-cols-[1fr_1fr_auto] gap-2">
        <select v-model="newTask.project_id" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm">
          <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
        <input v-model="newTask.slug" placeholder="slug (optional)" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm" />
        <select v-model="newTask.kind" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm">
          <option>build</option><option>research</option><option>efficiency</option>
        </select>
        <textarea v-model="newTask.prompt" placeholder="scoped task prompt..." rows="2"
                  class="sm:col-span-3 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"></textarea>
        <button @click="queueTask" class="sm:col-span-3 bg-blue-600 hover:bg-blue-500 rounded-lg py-2 font-semibold text-sm">Queue</button>
      </div>

      <!-- tasks -->
      <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-2">Tasks</h2>
      <div v-for="t in tasks" :key="t.id" class="bg-slate-900 border border-slate-800 rounded-xl p-3 mb-2">
        <div class="flex items-center gap-2">
          <span class="text-[10px] px-2 py-0.5 rounded-full font-semibold" :class="stateColor[t.state] || 'bg-slate-700'">{{ t.state }}</span>
          <b class="text-sm">{{ t.slug }}</b>
          <span class="text-slate-500 text-xs">{{ t.model }}</span>
          <span class="flex-1"></span>
          <span v-if="t.note" class="text-slate-500 text-xs">{{ t.note }}</span>
        </div>
        <pre v-if="t.log_tail" class="bg-black/40 border border-slate-800 rounded-md p-2 mt-2 text-[11px] text-slate-400 overflow-auto max-h-32 whitespace-pre-wrap">{{ t.log_tail }}</pre>
      </div>

      <!-- runners / fleet -->
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

      <!-- budgets -->
      <h2 class="text-xs uppercase tracking-wider text-slate-500 mb-2 mt-8">Budgets (month-to-date)</h2>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 text-sm mb-2">
        <div v-for="p in projects" :key="p.id" class="mb-3 last:mb-0">
          <div class="flex justify-between mb-1">
            <span class="text-slate-300">{{ p.name }}</span>
            <span class="text-slate-400">${{ budgetFor(p.name).spent.toFixed(2) }}<template v-if="budgetFor(p.name).cap"> / ${{ budgetFor(p.name).cap }}</template></span>
          </div>
          <div v-if="budgetFor(p.name).cap" class="h-2 bg-slate-800 rounded-full overflow-hidden">
            <div class="h-full rounded-full" :class="budgetFor(p.name).spent >= budgetFor(p.name).cap ? 'bg-red-500' : budgetFor(p.name).spent / budgetFor(p.name).cap > 0.8 ? 'bg-amber-500' : 'bg-green-500'"
                 :style="{ width: Math.min(100, 100 * budgetFor(p.name).spent / budgetFor(p.name).cap) + '%' }"></div>
          </div>
          <div v-else class="text-slate-600 text-xs">no cap set</div>
        </div>
      </div>

      <!-- cost -->
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
