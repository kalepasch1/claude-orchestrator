<script setup lang="ts">
definePageMeta({ layout: 'default' })
const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()

const providerSpend = ref<any[]>([])
const outcomes = ref<any[]>([])
const budgets = ref<any[]>([])
const projects = ref<any[]>([])
const loading = ref(false)
let chart: any = null
const CHART_LINE = '#58a6ff'
const CHART_AXIS = '#8b98ad'

const isNotional = (p: any) => String(p ?? '').includes('notional')
const cashMtd = computed(() => providerSpend.value.filter(s => !isNotional(s.provider)).reduce((n, s) => n + Number(s.spent || 0), 0))
const coveredMtd = computed(() => providerSpend.value.filter(s => isNotional(s.provider)).reduce((n, s) => n + Number(s.spent || 0), 0))

const mergeRate = computed(() => {
  const valid = outcomes.value.filter(o => o.tests_passed || o.integrated)
  const merged = valid.filter(o => o.integrated)
  return valid.length ? Math.round((merged.length / valid.length) * 100) : 0
})
const usdPerMerge = computed(() => {
  const merged = outcomes.value.filter(o => o.integrated)
  const spend = merged.reduce((n, o) => n + Number(o.usd || 0), 0)
  return merged.length ? (spend / merged.length).toFixed(2) : null
})

const roiByProject = computed(() => {
  const m: Record<string, { spend: number; merged: number; tasks: number }> = {}
  for (const o of outcomes.value) {
    const p = o.project || '(none)'
    ;(m[p] ??= { spend: 0, merged: 0, tasks: 0 })
    m[p].spend += Number(o.usd || 0)
    m[p].tasks++
    if (o.integrated) m[p].merged++
  }
  return Object.entries(m).map(([project, v]) => ({
    project, spend: v.spend.toFixed(2), merged: v.merged,
    costPerMerge: v.merged ? (v.spend / v.merged).toFixed(2) : null,
    passRate: v.tasks ? Math.round(100 * v.merged / v.tasks) : 0,
  })).sort((a, b) => Number(a.costPerMerge ?? 9999) - Number(b.costPerMerge ?? 9999))
})

const byModel = computed(() => {
  const m: Record<string, number> = {}
  for (const o of outcomes.value) m[o.model] = (m[o.model] || 0) + Number(o.usd || 0)
  return Object.entries(m).sort((a, b) => b[1] - a[1])
})

function budgetFor(project: string) {
  const b = budgets.value.find(x => x.project === project)
  const spent = outcomes.value.filter(o => o.project === project).reduce((s, o) => s + Number(o.usd || 0), 0)
  return { cap: b ? Number(b.monthly_usd_cap) : null, spent, hard: b?.hard_pause }
}

async function loadAll() {
  loading.value = true
  const [ps, o, b, p] = await Promise.all([
    supabase.from('v_provider_spend_mtd').select('*'),
    supabase.from('outcomes').select('model,usd,project,tests_passed,integrated,created_at,slug').order('created_at').limit(2000),
    supabase.from('budgets').select('*'),
    supabase.from('projects').select('*').order('name'),
  ])
  providerSpend.value = ps.data || []
  outcomes.value = o.data || []
  budgets.value = b.data || []
  projects.value = p.data || []
  loading.value = false
  await nextTick()
  renderChart()
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
    data: { datasets: [{ label: 'Cumulative spend ($)', data: pts, borderColor: CHART_LINE, backgroundColor: 'rgba(56,139,253,.15)', fill: true, tension: .25, pointRadius: 0 }] },
    options: { responsive: true, plugins: { legend: { labels: { color: CHART_AXIS } } },
      scales: { x: { type: 'linear', ticks: { color: CHART_AXIS, callback: (v: any) => new Date(v).toLocaleDateString() } }, y: { ticks: { color: CHART_AXIS } } } },
  })
}

onMounted(() => { if (user.value) loadAll() })
onUnmounted(() => { if (chart) chart.destroy() })
watch(user, u => { if (u) loadAll() })
</script>

<template>
  <div class="min-h-screen bg-[#0d1117] text-slate-300">
    <div class="max-w-6xl mx-auto px-6 py-6 space-y-6">

      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-bold text-white">Spend &amp; ROI</h1>
          <p class="text-sm text-slate-500 mt-0.5">AI cost breakdown, budgets, and return on investment</p>
        </div>
        <button @click="loadAll" class="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-400 text-sm rounded-lg">↻ Refresh</button>
      </div>

      <!-- Summary KPIs -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <div class="text-2xl font-bold text-white font-mono">${{ cashMtd.toFixed(2) }}</div>
          <div class="text-xs text-slate-500 mt-1">Cash spend MtD</div>
        </div>
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <div class="text-2xl font-bold text-blue-300 font-mono">${{ coveredMtd.toFixed(2) }}</div>
          <div class="text-xs text-slate-500 mt-1">Max-covered MtD</div>
        </div>
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <div class="text-2xl font-bold text-green-300 font-mono">{{ mergeRate }}%</div>
          <div class="text-xs text-slate-500 mt-1">Merge rate</div>
        </div>
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <div class="text-2xl font-bold text-amber-300 font-mono">{{ usdPerMerge ? `$${usdPerMerge}` : '—' }}</div>
          <div class="text-xs text-slate-500 mt-1">$/merge</div>
        </div>
      </div>

      <!-- Burn-down Chart -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <div class="text-sm font-semibold text-white mb-3">Cumulative Spend</div>
        <canvas id="spendChart" height="120"></canvas>
      </div>

      <!-- Provider Spend -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <div class="px-5 py-3 border-b border-slate-800">
          <span class="text-sm font-semibold text-white">Provider Spend MtD</span>
        </div>
        <div v-if="providerSpend.length === 0" class="px-5 py-6 text-slate-600 text-sm">No spend data</div>
        <table v-else class="w-full text-sm">
          <thead class="border-b border-slate-800">
            <tr class="text-xs text-slate-500 uppercase tracking-wide">
              <th class="px-5 py-2 text-left">Provider</th>
              <th class="px-5 py-2 text-left">Project</th>
              <th class="px-5 py-2 text-right">Spent</th>
              <th class="px-5 py-2 text-right">Type</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800">
            <tr v-for="s in providerSpend" :key="`${s.provider}-${s.project}`" class="hover:bg-slate-800/30">
              <td class="px-5 py-2.5 font-mono text-slate-300 text-xs">{{ s.provider }}</td>
              <td class="px-5 py-2.5 text-xs text-slate-500">{{ s.project || '—' }}</td>
              <td class="px-5 py-2.5 text-right font-mono text-xs" :class="isNotional(s.provider) ? 'text-blue-300' : 'text-white'">${{ Number(s.spent || 0).toFixed(4) }}</td>
              <td class="px-5 py-2.5 text-right">
                <span class="text-xs px-1.5 py-0.5 rounded" :class="isNotional(s.provider) ? 'bg-blue-500/10 text-blue-400' : 'bg-slate-800 text-slate-400'">
                  {{ isNotional(s.provider) ? 'covered' : 'cash' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Budget Bars -->
      <div v-if="projects.length > 0" class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <div class="px-5 py-3 border-b border-slate-800">
          <span class="text-sm font-semibold text-white">Budget Usage</span>
        </div>
        <div class="p-5 space-y-4">
          <div v-for="p in projects" :key="p.id">
            <div v-if="budgetFor(p.name).cap !== null" class="space-y-1">
              <div class="flex justify-between text-xs">
                <span class="text-slate-300">{{ p.name }}</span>
                <span class="font-mono text-slate-400">${{ budgetFor(p.name).spent.toFixed(2) }} / ${{ budgetFor(p.name).cap }}</span>
              </div>
              <div class="h-2 bg-slate-800 rounded-full overflow-hidden">
                <div class="h-full rounded-full transition-all"
                  :style="`width: ${Math.min(100, (budgetFor(p.name).spent / (budgetFor(p.name).cap || 1)) * 100)}%`"
                  :class="budgetFor(p.name).spent / (budgetFor(p.name).cap || 1) > 0.9 ? 'bg-red-500' : budgetFor(p.name).spent / (budgetFor(p.name).cap || 1) > 0.7 ? 'bg-amber-500' : 'bg-blue-500'">
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ROI Table -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <div class="px-5 py-3 border-b border-slate-800">
          <span class="text-sm font-semibold text-white">ROI by Project</span>
        </div>
        <table class="w-full text-sm">
          <thead class="border-b border-slate-800">
            <tr class="text-xs text-slate-500 uppercase tracking-wide">
              <th class="px-5 py-2 text-left">Project</th>
              <th class="px-5 py-2 text-right">Spend</th>
              <th class="px-5 py-2 text-right">Merged</th>
              <th class="px-5 py-2 text-right">$/merge</th>
              <th class="px-5 py-2 text-right">Pass rate</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800">
            <tr v-for="r in roiByProject" :key="r.project" class="hover:bg-slate-800/30">
              <td class="px-5 py-2.5 text-slate-300">{{ r.project }}</td>
              <td class="px-5 py-2.5 text-right font-mono text-xs text-slate-400">${{ r.spend }}</td>
              <td class="px-5 py-2.5 text-right font-mono text-xs text-green-300">{{ r.merged }}</td>
              <td class="px-5 py-2.5 text-right font-mono text-xs text-amber-300">{{ r.costPerMerge ? `$${r.costPerMerge}` : '—' }}</td>
              <td class="px-5 py-2.5 text-right text-xs" :class="r.passRate >= 70 ? 'text-green-300' : r.passRate >= 40 ? 'text-amber-300' : 'text-red-300'">{{ r.passRate }}%</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Model Breakdown -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <div class="px-5 py-3 border-b border-slate-800">
          <span class="text-sm font-semibold text-white">Spend by Model</span>
        </div>
        <div class="p-5 space-y-3">
          <div v-for="[model, spend] in byModel" :key="model" class="flex items-center gap-3">
            <span class="text-xs font-mono text-slate-400 w-48 truncate">{{ model }}</span>
            <div class="flex-1 h-2 bg-slate-800 rounded-full overflow-hidden">
              <div class="h-full bg-blue-500 rounded-full" :style="`width: ${byModel.length ? (spend / (byModel[0]?.[1] || 1)) * 100 : 0}%`"></div>
            </div>
            <span class="text-xs font-mono text-slate-400 w-16 text-right">${{ spend.toFixed(3) }}</span>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>
