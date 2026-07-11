<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-6">
      <h2 class="text-xl font-semibold">Revenue Fabric</h2>
      <div class="flex gap-1 bg-gray-900 rounded-lg p-0.5">
        <button v-for="p in periods" :key="p.value"
                class="px-3 py-1 text-xs rounded-md transition-colors"
                :class="selectedMonths === p.value ? 'bg-indigo-600 text-white' : 'text-gray-400 hover:text-gray-200'"
                @click="selectedMonths = p.value; load()">
          {{ p.label }}
        </button>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex items-center justify-center py-20">
      <div class="text-gray-500 text-sm">Loading revenue data...</div>
    </div>

    <template v-else>
      <!-- KPI Cards -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Total MRR</div>
          <div class="text-2xl font-semibold text-green-400">{{ formatCurrency(summary.totalMRR) }}</div>
          <div class="text-xs text-gray-600 mt-1">Latest month</div>
        </div>
        <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Net Revenue</div>
          <div class="text-2xl font-semibold text-indigo-400">{{ formatCurrency(summary.totalNetRevenue) }}</div>
          <div class="text-xs text-gray-600 mt-1">{{ selectedMonths }}mo period</div>
        </div>
        <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Refund Rate</div>
          <div class="text-2xl font-semibold" :class="refundRate > 5 ? 'text-red-400' : 'text-gray-300'">
            {{ refundRate.toFixed(1) }}%
          </div>
          <div class="text-xs text-gray-600 mt-1">{{ formatCurrency(summary.totalRefunds) }} total</div>
        </div>
        <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Active Apps</div>
          <div class="text-2xl font-semibold text-gray-300">{{ activeApps }} / {{ totalApps }}</div>
          <div class="text-xs text-gray-600 mt-1">{{ summary.totalTransactions }} transactions</div>
        </div>
      </div>

      <!-- Revenue by App (bar chart) -->
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-5 mb-6">
        <h3 class="text-sm font-medium text-gray-400 mb-4">Revenue by App</h3>
        <div v-if="appTotals.length === 0" class="text-center text-gray-600 py-8 text-sm">
          No revenue data available for this period.
        </div>
        <div v-else class="space-y-3">
          <div v-for="app in appTotals" :key="app.name" class="flex items-center gap-3">
            <div class="w-24 text-xs text-gray-400 truncate">{{ app.name }}</div>
            <div class="flex-1 h-6 bg-gray-800 rounded overflow-hidden relative">
              <div class="h-full rounded transition-all duration-500"
                   :style="{ width: barWidth(app.revenue) + '%' }"
                   :class="APP_COLORS[app.id] ?? 'bg-indigo-600'" />
              <span class="absolute inset-0 flex items-center px-2 text-xs font-medium text-white mix-blend-difference">
                {{ formatCurrency(app.revenue) }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Monthly Trend -->
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-5 mb-6">
        <h3 class="text-sm font-medium text-gray-400 mb-4">Monthly Revenue Trend</h3>
        <div v-if="summary.trend.length === 0" class="text-center text-gray-600 py-8 text-sm">
          No trend data available.
        </div>
        <div v-else>
          <svg :viewBox="`0 0 ${trendWidth} ${trendHeight + 30}`" class="w-full" style="max-height: 200px;">
            <!-- Grid lines -->
            <line v-for="i in 4" :key="'grid-' + i"
                  :x1="40" :x2="trendWidth - 10"
                  :y1="trendHeight - (i * trendHeight / 4)" :y2="trendHeight - (i * trendHeight / 4)"
                  stroke="#1f2937" stroke-width="1" />
            <!-- Y-axis labels -->
            <text v-for="i in 4" :key="'label-' + i"
                  :x="36" :y="trendHeight - (i * trendHeight / 4) + 4"
                  fill="#6b7280" font-size="9" text-anchor="end">
              {{ formatCompact((i / 4) * maxTrend) }}
            </text>
            <!-- Area fill -->
            <path :d="trendAreaPath" fill="url(#trendGradient)" opacity="0.3" />
            <!-- Line -->
            <polyline :points="trendPoints" fill="none" stroke="#818cf8" stroke-width="2" stroke-linejoin="round" />
            <!-- Dots -->
            <circle v-for="(pt, idx) in trendCoords" :key="'dot-' + idx"
                    :cx="pt.x" :cy="pt.y" r="3" fill="#818cf8" />
            <!-- X-axis labels -->
            <text v-for="(pt, idx) in trendCoords" :key="'xlabel-' + idx"
                  :x="pt.x" :y="trendHeight + 15"
                  fill="#6b7280" font-size="9" text-anchor="middle">
              {{ summary.trend[idx]?.period?.slice(5) }}
            </text>
            <defs>
              <linearGradient id="trendGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#818cf8" />
                <stop offset="100%" stop-color="#818cf8" stop-opacity="0" />
              </linearGradient>
            </defs>
          </svg>
        </div>
      </div>

      <!-- Per-App Breakdown Table -->
      <div class="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <h3 class="text-sm font-medium text-gray-400 px-5 pt-4 pb-2">Per-App Breakdown</h3>
        <table class="w-full text-sm">
          <thead>
            <tr class="text-xs text-gray-500 uppercase border-b border-gray-800">
              <th class="text-left px-5 py-2">App</th>
              <th class="text-right px-3 py-2">Net Revenue</th>
              <th class="text-right px-3 py-2">Transactions</th>
              <th class="text-right px-3 py-2">Refunds</th>
              <th class="text-right px-3 py-2">Refund %</th>
              <th class="px-3 py-2 w-32">Trend</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="app in appTotals" :key="app.id"
                class="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
              <td class="px-5 py-2.5">
                <span class="inline-block w-2 h-2 rounded-full mr-2" :class="APP_COLORS[app.id] ?? 'bg-indigo-600'" />
                {{ app.name }}
              </td>
              <td class="text-right px-3 py-2.5 font-medium text-gray-300">{{ formatCurrency(app.revenue) }}</td>
              <td class="text-right px-3 py-2.5 text-gray-400">{{ app.transactions }}</td>
              <td class="text-right px-3 py-2.5 text-gray-400">{{ formatCurrency(app.refunds) }}</td>
              <td class="text-right px-3 py-2.5" :class="app.refundPct > 5 ? 'text-red-400' : 'text-gray-400'">
                {{ app.refundPct.toFixed(1) }}%
              </td>
              <td class="px-3 py-2.5">
                <svg viewBox="0 0 100 24" class="w-full h-6" preserveAspectRatio="none">
                  <polyline :points="sparkline(app.id)" fill="none" stroke="#818cf8" stroke-width="1.5" stroke-linejoin="round" />
                </svg>
              </td>
            </tr>
            <tr v-if="appTotals.length === 0">
              <td colspan="6" class="text-center text-gray-600 py-6">No revenue data found for any app.</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Gaps / Notes -->
      <div v-if="summary.gaps.length > 0" class="mt-4 bg-yellow-950/20 border border-yellow-800/30 rounded-lg p-4">
        <h4 class="text-xs font-medium text-yellow-500 mb-2">Data Gaps</h4>
        <ul class="text-xs text-yellow-600 space-y-1">
          <li v-for="(gap, i) in summary.gaps" :key="i">{{ gap }}</li>
        </ul>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const periods = [
  { label: '3m', value: 3 },
  { label: '6m', value: 6 },
  { label: '12m', value: 12 },
]

const selectedMonths = ref(6)
const loading = ref(true)

interface AppRevenueItem {
  app: string
  appName: string
  period: string
  mrr: number
  transactions: number
  refunds: number
  netRevenue: number
}

interface Summary {
  totalMRR: number
  totalTransactions: number
  totalRefunds: number
  totalNetRevenue: number
  byApp: AppRevenueItem[]
  trend: { period: string; revenue: number }[]
  gaps: string[]
}

const summary = ref<Summary>({
  totalMRR: 0,
  totalTransactions: 0,
  totalRefunds: 0,
  totalNetRevenue: 0,
  byApp: [],
  trend: [],
  gaps: [],
})

const APP_COLORS: Record<string, string> = {
  apparently: 'bg-indigo-500',
  tomorrow: 'bg-emerald-500',
  smarter: 'bg-blue-500',
  galop: 'bg-amber-500',
  hisanta: 'bg-red-500',
  pareto: 'bg-purple-500',
}

// Computed
const refundRate = computed(() => {
  const gross = summary.value.totalNetRevenue + summary.value.totalRefunds
  return gross > 0 ? (summary.value.totalRefunds / gross) * 100 : 0
})

const appTotals = computed(() => {
  const map = new Map<string, { id: string; name: string; revenue: number; transactions: number; refunds: number; periods: { period: string; revenue: number }[] }>()
  for (const r of summary.value.byApp) {
    if (!map.has(r.app)) {
      map.set(r.app, { id: r.app, name: r.appName, revenue: 0, transactions: 0, refunds: 0, periods: [] })
    }
    const bucket = map.get(r.app)!
    bucket.revenue += r.netRevenue
    bucket.transactions += r.transactions
    bucket.refunds += r.refunds
    bucket.periods.push({ period: r.period, revenue: r.netRevenue })
  }

  return [...map.values()]
    .map((a) => ({
      ...a,
      refundPct: a.revenue + a.refunds > 0 ? (a.refunds / (a.revenue + a.refunds)) * 100 : 0,
      periods: a.periods.sort((x, y) => x.period.localeCompare(y.period)),
    }))
    .sort((a, b) => b.revenue - a.revenue)
})

const activeApps = computed(() => new Set(summary.value.byApp.map((r) => r.app)).size)
const totalApps = 6 // excluding orchestrator

const maxAppRevenue = computed(() => Math.max(...appTotals.value.map((a) => a.revenue), 1))
function barWidth(revenue: number) {
  return Math.max((revenue / maxAppRevenue.value) * 100, 1)
}

// Trend chart
const trendWidth = 600
const trendHeight = 140
const maxTrend = computed(() => Math.max(...summary.value.trend.map((t) => t.revenue), 1))

const trendCoords = computed(() => {
  const pts = summary.value.trend
  if (pts.length === 0) return []
  const step = (trendWidth - 60) / Math.max(pts.length - 1, 1)
  return pts.map((t, i) => ({
    x: 45 + i * step,
    y: trendHeight - (t.revenue / maxTrend.value) * (trendHeight - 10),
  }))
})

const trendPoints = computed(() => trendCoords.value.map((p) => `${p.x},${p.y}`).join(' '))

const trendAreaPath = computed(() => {
  if (trendCoords.value.length === 0) return ''
  const first = trendCoords.value[0]
  const last = trendCoords.value[trendCoords.value.length - 1]
  return `M${first.x},${trendHeight} L${trendPoints.value} L${last.x},${trendHeight} Z`
})

// Sparklines
function sparkline(appId: string): string {
  const app = appTotals.value.find((a) => a.id === appId)
  if (!app || app.periods.length === 0) return '0,12 100,12'
  const max = Math.max(...app.periods.map((p) => p.revenue), 1)
  const step = 100 / Math.max(app.periods.length - 1, 1)
  return app.periods.map((p, i) => `${i * step},${24 - (p.revenue / max) * 20}`).join(' ')
}

// Formatting
function formatCurrency(val: number): string {
  if (Math.abs(val) >= 1_000_000) return '$' + (val / 1_000_000).toFixed(1) + 'M'
  if (Math.abs(val) >= 1_000) return '$' + (val / 1_000).toFixed(1) + 'K'
  return '$' + val.toFixed(2)
}

function formatCompact(val: number): string {
  if (val >= 1_000_000) return (val / 1_000_000).toFixed(0) + 'M'
  if (val >= 1_000) return (val / 1_000).toFixed(0) + 'K'
  return val.toFixed(0)
}

// Data loading
async function load() {
  loading.value = true
  try {
    const data = await $fetch<Summary>('/api/admin/revenue', {
      params: { months: selectedMonths.value },
    })
    summary.value = data
  } catch (err) {
    console.error('Revenue load failed:', err)
    summary.value = { totalMRR: 0, totalTransactions: 0, totalRefunds: 0, totalNetRevenue: 0, byApp: [], trend: [], gaps: ['Failed to load revenue data'] }
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
