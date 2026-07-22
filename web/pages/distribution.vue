<script setup lang="ts">
definePageMeta({ layout: 'default' })

const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()

// --- State ---
const loading = ref(false)
const safetyGate = ref<'blocked' | 'active'>('blocked')
const safetyLoading = ref(false)
const humanTasks = ref<any[]>([])
const apps = ref<any[]>([])
const budgetInput = ref<number>(0)
const allocations = ref<any[]>([])
const channelScoreboard = ref<any[]>([])
const projects = ref<any[]>([])

// --- Helpers ---
const money = (n: any) => '$' + Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })
const pct = (n: any) => Number(n || 0).toFixed(1) + '%'
function ago(ts: string) {
  const d = Math.round((Date.now() - new Date(ts).getTime()) / 60000)
  if (d < 1) return 'now'
  if (d < 60) return `${d}m ago`
  if (d < 1440) return `${Math.round(d / 60)}h ago`
  return `${Math.round(d / 1440)}d ago`
}
function evPerHour(task: any) {
  const impact = Number(task.impact || 0)
  const effort = Number(task.effort_hours || 1)
  return effort > 0 ? (impact / effort).toFixed(1) : '—'
}

const tasksByApp = computed(() => {
  const groups: Record<string, any[]> = {}
  for (const t of humanTasks.value) {
    const app = t.app || t.project || 'Unassigned'
    ;(groups[app] ??= []).push(t)
  }
  return groups
})

// --- Data loading ---
async function authedFetch<T = any>(url: string, opts: any = {}): Promise<T> {
  const { data: { session } } = await supabase.auth.getSession()
  return $fetch<T>(url, {
    ...opts,
    headers: { ...(opts.headers || {}), ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}) },
  })
}

async function loadAll() {
  loading.value = true
  try {
    const [ctrlRes, taskRes, projectRes] = await Promise.all([
      supabase.from('controls').select('*'),
      supabase.from('tasks').select('*').in('state', ['BLOCKED', 'WAITING']).order('created_at', { ascending: false }).limit(100),
      supabase.from('projects').select('*').order('name'),
    ])

    const controls = ctrlRes.data || []
    const sendingCtrl = controls.find((c: any) => c.scope === 'distribution_sending')
    safetyGate.value = sendingCtrl?.paused === false ? 'active' : 'blocked'
    humanTasks.value = (taskRes.data || []).map((t: any) => ({
      ...t,
      app: (projectRes.data || []).find((p: any) => p.id === t.project_id)?.name || 'Unknown',
      title: t.slug,
      why: t.note || 'Needs human review',
      effort_hours: t.effort_hours || 1,
      impact: t.impact || 50,
      deadline: t.deadline || null,
    }))
    projects.value = projectRes.data || []

    // Load app grid data
    try {
      const appData = await authedFetch('/api/distribution/apps')
      apps.value = appData?.apps || []
    } catch { apps.value = projects.value.map((p: any) => ({ name: p.name, id: p.id, active_runs: 0, open_tasks: 0, reach: 0, signups: 0, cac: 0 })) }

    // Load portfolio CMO allocations
    try {
      const cmoData = await authedFetch('/api/distribution/portfolio-cmo')
      allocations.value = cmoData?.allocations || []
      budgetInput.value = cmoData?.total_budget || 0
    } catch { allocations.value = [] }

    // Load channel scoreboard
    try {
      const scoreData = await authedFetch('/api/distribution/channels')
      channelScoreboard.value = scoreData?.channels || []
    } catch { channelScoreboard.value = [] }
  } finally { loading.value = false }
}

async function toggleSafetyGate() {
  safetyLoading.value = true
  try {
    const newPaused = safetyGate.value === 'active'
    await supabase.from('controls').upsert({
      scope: 'distribution_sending', project: null, paused: newPaused,
      reason: newPaused ? 'Manual pause from distribution page' : 'Activated from distribution page',
      updated_by: user.value?.email, updated_at: new Date().toISOString(),
    }, { onConflict: 'scope,project' })
    safetyGate.value = newPaused ? 'blocked' : 'active'
  } finally { safetyLoading.value = false }
}

async function completeTask(id: string) {
  await supabase.from('tasks').update({ state: 'DONE', note: 'Completed from distribution page' }).eq('id', id)
  await loadAll()
}
async function declineTask(id: string) {
  await supabase.from('tasks').update({ state: 'SHELVED', note: 'Declined from distribution page' }).eq('id', id)
  await loadAll()
}

async function recalcAllocations() {
  try {
    const result = await authedFetch('/api/distribution/portfolio-cmo', {
      method: 'POST', body: { total_budget: budgetInput.value },
    })
    allocations.value = result?.allocations || []
  } catch {}
}

let realtimeSub: any
onMounted(async () => {
  if (user.value) await loadAll()
  realtimeSub = supabase.channel('distribution-live')
    .on('postgres_changes', { event: '*', schema: 'public', table: 'tasks' }, loadAll)
    .on('postgres_changes', { event: '*', schema: 'public', table: 'controls' }, loadAll)
    .subscribe()
})
onUnmounted(() => { if (realtimeSub) supabase.removeChannel(realtimeSub) })
watch(user, u => { if (u) loadAll() })
</script>

<template>
  <div class="min-h-screen bg-white text-gray-900">
    <div class="max-w-6xl mx-auto px-6 py-6 space-y-6">

      <!-- Page header -->
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-bold text-gray-900">Distribution</h1>
          <p class="text-sm text-gray-500 mt-0.5">Portfolio-wide sending controls, human task queue, app grid, and channel performance</p>
        </div>
        <button @click="loadAll" class="px-3 py-2 bg-gray-100 hover:bg-gray-200 text-gray-500 text-sm rounded-lg">↻ Refresh</button>
      </div>

      <!-- 1. MASTER SAFETY GATE -->
      <div class="rounded-xl border-2 p-5" :class="safetyGate === 'active' ? 'border-amber-400 bg-amber-50' : 'border-gray-300 bg-gray-50'">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-3">
            <span class="text-2xl">{{ safetyGate === 'active' ? '⚡' : '🛑' }}</span>
            <div>
              <h2 class="text-base font-bold" :class="safetyGate === 'active' ? 'text-amber-800' : 'text-gray-700'">
                {{ safetyGate === 'active' ? 'Autonomous sending ON' : 'Autonomous sending OFF across all apps' }}
              </h2>
              <p class="text-sm" :class="safetyGate === 'active' ? 'text-amber-600' : 'text-gray-500'">
                {{ safetyGate === 'active' ? 'Distribution agents can send emails, social posts, and messages autonomously.' : 'No automated distribution is happening. Activate to allow agents to send on your behalf.' }}
              </p>
            </div>
          </div>
          <button @click="toggleSafetyGate" :disabled="safetyLoading"
            class="px-5 py-2.5 text-sm font-medium rounded-lg border transition-colors"
            :class="safetyGate === 'active'
              ? 'border-amber-500 text-amber-700 bg-white hover:bg-amber-100'
              : 'border-green-600 text-white bg-green-600 hover:bg-green-700'">
            {{ safetyLoading ? 'Updating...' : safetyGate === 'active' ? 'Pause sending' : 'Activate sending' }}
          </button>
        </div>
      </div>

      <!-- 2. YOUR QUEUE — human tasks grouped by app -->
      <div class="bg-gray-50 border border-gray-200 rounded-xl overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-200">
          <span class="text-sm font-semibold text-gray-900">Your Queue</span>
          <span class="text-xs text-gray-400 ml-2">{{ humanTasks.length }} tasks needing your attention</span>
        </div>
        <div v-if="loading" class="px-5 py-8 text-center text-gray-400 text-sm">Loading...</div>
        <div v-else-if="humanTasks.length === 0" class="px-5 py-8 text-center text-gray-400 text-sm">No tasks need your attention right now.</div>
        <template v-else>
          <div v-for="(taskList, appName) in tasksByApp" :key="appName" class="border-b border-gray-200 last:border-b-0">
            <div class="px-5 py-2 bg-gray-100 text-xs font-semibold text-gray-600 uppercase tracking-wide">{{ appName }}</div>
            <div class="divide-y divide-gray-100">
              <div v-for="task in taskList" :key="task.id" class="px-5 py-3 hover:bg-white transition-colors">
                <div class="flex items-start justify-between gap-4">
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                      <span class="text-sm font-medium text-gray-800 truncate">{{ task.title }}</span>
                      <span v-if="task.deadline" class="text-xs text-red-500 flex-shrink-0">Due {{ ago(task.deadline) }}</span>
                    </div>
                    <p class="text-xs text-gray-500 mt-0.5">{{ task.why }}</p>
                    <div class="flex items-center gap-4 mt-1.5 text-xs text-gray-400">
                      <span>Effort: {{ task.effort_hours }}h</span>
                      <span>Impact: {{ task.impact }}</span>
                      <span class="font-medium" :class="Number(evPerHour(task)) > 20 ? 'text-green-600' : 'text-gray-500'">EV/hr: {{ evPerHour(task) }}</span>
                    </div>
                  </div>
                  <div class="flex items-center gap-2 flex-shrink-0">
                    <button @click.stop="completeTask(task.id)"
                      class="px-3 py-1.5 text-xs font-medium text-green-700 bg-green-50 border border-green-200 rounded-lg hover:bg-green-100 transition-colors">Done</button>
                    <button @click.stop="declineTask(task.id)"
                      class="px-3 py-1.5 text-xs font-medium text-gray-500 bg-gray-100 border border-gray-200 rounded-lg hover:bg-gray-200 transition-colors">Decline</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- 3. PER-APP GRID -->
      <div class="bg-gray-50 border border-gray-200 rounded-xl overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-200">
          <span class="text-sm font-semibold text-gray-900">Per-App Grid</span>
          <span class="text-xs text-gray-400 ml-2">Distribution status across all apps</span>
        </div>
        <div v-if="apps.length === 0" class="px-5 py-8 text-center text-gray-400 text-sm">No app data available yet.</div>
        <table v-else class="w-full text-sm">
          <thead class="border-b border-gray-200">
            <tr class="text-xs text-gray-500 uppercase tracking-wide">
              <th class="px-5 py-2 text-left">App</th>
              <th class="px-5 py-2 text-right">Active runs</th>
              <th class="px-5 py-2 text-right">Open tasks</th>
              <th class="px-5 py-2 text-right">Reach</th>
              <th class="px-5 py-2 text-right">Signups</th>
              <th class="px-5 py-2 text-right">CAC</th>
              <th class="px-5 py-2 text-right">Launch play</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-200">
            <tr v-for="app in apps" :key="app.id || app.name" class="hover:bg-gray-50">
              <td class="px-5 py-2.5 font-medium text-gray-800">{{ app.name }}</td>
              <td class="px-5 py-2.5 text-right font-mono text-xs" :class="app.active_runs > 0 ? 'text-blue-600' : 'text-gray-400'">{{ app.active_runs }}</td>
              <td class="px-5 py-2.5 text-right font-mono text-xs" :class="app.open_tasks > 0 ? 'text-amber-600' : 'text-gray-400'">{{ app.open_tasks }}</td>
              <td class="px-5 py-2.5 text-right font-mono text-xs text-gray-600">{{ Number(app.reach || 0).toLocaleString() }}</td>
              <td class="px-5 py-2.5 text-right font-mono text-xs text-green-600">{{ Number(app.signups || 0).toLocaleString() }}</td>
              <td class="px-5 py-2.5 text-right font-mono text-xs" :class="Number(app.cac) > 50 ? 'text-red-600' : 'text-gray-600'">{{ app.cac ? money(app.cac) : '—' }}</td>
              <td class="px-5 py-2.5 text-right">
                <select class="text-xs bg-white border border-gray-200 rounded px-2 py-1 text-gray-600 cursor-pointer">
                  <option value="">Pick a play...</option>
                  <option value="cold_outreach">Cold outreach</option>
                  <option value="content_blitz">Content blitz</option>
                  <option value="referral_program">Referral program</option>
                  <option value="paid_ads">Paid ads</option>
                  <option value="partnership">Partnership</option>
                </select>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 4. PORTFOLIO CMO — budget + allocation -->
      <div class="bg-gray-50 border border-gray-200 rounded-xl overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-200 flex items-center justify-between">
          <div>
            <span class="text-sm font-semibold text-gray-900">Portfolio CMO</span>
            <span class="text-xs text-gray-400 ml-2">AI-suggested budget allocation based on ROI signals</span>
          </div>
        </div>
        <div class="p-5 space-y-4">
          <div class="flex items-center gap-3">
            <label class="text-sm text-gray-600 flex-shrink-0">Total budget</label>
            <div class="flex items-center gap-2">
              <span class="text-gray-400">$</span>
              <input v-model.number="budgetInput" type="number" min="0" step="100"
                class="w-36 bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono text-gray-800 focus:outline-none focus:border-blue-500" />
            </div>
            <button @click="recalcAllocations"
              class="px-4 py-2 text-sm font-medium text-blue-700 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 transition-colors">
              Recalculate
            </button>
          </div>
          <div v-if="allocations.length === 0" class="text-sm text-gray-400">Enter a budget and click Recalculate to see suggested allocations.</div>
          <table v-else class="w-full text-sm">
            <thead class="border-b border-gray-200">
              <tr class="text-xs text-gray-500 uppercase tracking-wide">
                <th class="px-4 py-2 text-left">App / Channel</th>
                <th class="px-4 py-2 text-right">ROI index</th>
                <th class="px-4 py-2 text-right">Suggested share</th>
                <th class="px-4 py-2 text-right">Suggested budget</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-200">
              <tr v-for="a in allocations" :key="a.name" class="hover:bg-gray-50">
                <td class="px-4 py-2.5 font-medium text-gray-800">{{ a.name }}</td>
                <td class="px-4 py-2.5 text-right font-mono text-xs" :class="Number(a.roi_index) > 1 ? 'text-green-600' : 'text-amber-600'">{{ Number(a.roi_index || 0).toFixed(2) }}</td>
                <td class="px-4 py-2.5 text-right font-mono text-xs text-gray-600">{{ pct(a.suggested_share * 100) }}</td>
                <td class="px-4 py-2.5 text-right font-mono text-xs text-gray-900 font-medium">{{ money(a.suggested_budget) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 5. CHANNEL SCOREBOARD -->
      <div class="bg-gray-50 border border-gray-200 rounded-xl overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-200">
          <span class="text-sm font-semibold text-gray-900">Channel Scoreboard</span>
          <span class="text-xs text-gray-400 ml-2">Distribution rollup across portfolio</span>
        </div>
        <div v-if="channelScoreboard.length === 0" class="px-5 py-8 text-center text-gray-400 text-sm">No channel data available yet.</div>
        <table v-else class="w-full text-sm">
          <thead class="border-b border-gray-200">
            <tr class="text-xs text-gray-500 uppercase tracking-wide">
              <th class="px-5 py-2 text-left">Channel</th>
              <th class="px-5 py-2 text-right">Sent</th>
              <th class="px-5 py-2 text-right">Delivered</th>
              <th class="px-5 py-2 text-right">Opened</th>
              <th class="px-5 py-2 text-right">Clicked</th>
              <th class="px-5 py-2 text-right">Converted</th>
              <th class="px-5 py-2 text-right">Cost</th>
              <th class="px-5 py-2 text-right">CPL</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-200">
            <tr v-for="ch in channelScoreboard" :key="ch.channel" class="hover:bg-gray-50">
              <td class="px-5 py-2.5 font-medium text-gray-800">{{ ch.channel }}</td>
              <td class="px-5 py-2.5 text-right font-mono text-xs text-gray-600">{{ Number(ch.sent || 0).toLocaleString() }}</td>
              <td class="px-5 py-2.5 text-right font-mono text-xs text-gray-600">{{ Number(ch.delivered || 0).toLocaleString() }}</td>
              <td class="px-5 py-2.5 text-right font-mono text-xs text-blue-600">{{ Number(ch.opened || 0).toLocaleString() }}</td>
              <td class="px-5 py-2.5 text-right font-mono text-xs text-indigo-600">{{ Number(ch.clicked || 0).toLocaleString() }}</td>
              <td class="px-5 py-2.5 text-right font-mono text-xs text-green-600">{{ Number(ch.converted || 0).toLocaleString() }}</td>
              <td class="px-5 py-2.5 text-right font-mono text-xs text-gray-600">{{ money(ch.cost) }}</td>
              <td class="px-5 py-2.5 text-right font-mono text-xs" :class="Number(ch.cpl) > 30 ? 'text-red-600' : 'text-gray-600'">{{ ch.cpl ? money(ch.cpl) : '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

    </div>
  </div>
</template>
