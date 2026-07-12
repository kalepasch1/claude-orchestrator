<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-xl font-semibold">Fleet Cost Optimizer</h2>
        <p class="text-sm text-gray-500 mt-1">
          Monitor and optimize costs across Supabase, Vercel, and Anthropic API usage for all fleet apps.
        </p>
      </div>
      <div class="flex items-center gap-3">
        <select v-model="period" class="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200">
          <option value="3">Last 3 months</option>
          <option value="6">Last 6 months</option>
          <option value="12">Last 12 months</option>
        </select>
        <button
          class="px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors disabled:opacity-50"
          :disabled="loading"
          @click="refreshData"
        >
          {{ loading ? 'Loading...' : 'Refresh' }}
        </button>
      </div>
    </div>

    <!-- Error -->
    <div v-if="error" class="bg-red-950/30 border border-red-800/40 rounded-lg p-4 mb-4">
      <div class="text-sm text-red-400">{{ error }}</div>
    </div>

    <!-- Total fleet cost -->
    <div class="grid grid-cols-4 gap-4 mb-6">
      <div class="bg-gray-900 border border-indigo-900/40 rounded-lg p-4">
        <div class="text-xs text-indigo-400 uppercase tracking-wider">Total Monthly</div>
        <div class="text-3xl font-semibold text-indigo-400 mt-1">${{ formatCost(summary?.totalMonthly || 0) }}</div>
      </div>
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="text-xs text-gray-500 uppercase tracking-wider">Supabase</div>
        <div class="text-2xl font-semibold mt-1">${{ formatCost(summary?.byCategory.supabase || 0) }}</div>
      </div>
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="text-xs text-gray-500 uppercase tracking-wider">Vercel</div>
        <div class="text-2xl font-semibold mt-1">${{ formatCost(summary?.byCategory.vercel || 0) }}</div>
      </div>
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="text-xs text-gray-500 uppercase tracking-wider">Anthropic API</div>
        <div class="text-2xl font-semibold mt-1">${{ formatCost(summary?.byCategory.anthropic || 0) }}</div>
      </div>
    </div>

    <!-- Cost by app (horizontal bars) -->
    <div class="grid grid-cols-2 gap-4 mb-6">
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <h3 class="text-sm font-semibold text-gray-400 mb-4">Cost by App</h3>
        <div v-if="summary?.byApp.length" class="space-y-3">
          <div v-for="item in summary.byApp" :key="item.app" class="space-y-1">
            <div class="flex justify-between text-xs">
              <span class="text-gray-300">{{ item.app }}</span>
              <span class="text-gray-400 font-mono">${{ formatCost(item.total) }}</span>
            </div>
            <div class="w-full bg-gray-800 rounded-full h-2">
              <div
                class="bg-indigo-500 h-2 rounded-full transition-all duration-300"
                :style="{ width: `${maxAppCost > 0 ? (item.total / maxAppCost) * 100 : 0}%` }"
              />
            </div>
          </div>
        </div>
        <div v-else class="text-sm text-gray-600 text-center py-8">No cost data available</div>
      </div>

      <!-- Cost breakdown stacked bars -->
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <h3 class="text-sm font-semibold text-gray-400 mb-4">Cost Breakdown by Category</h3>
        <div v-if="costs.length" class="space-y-3">
          <div v-for="cost in costs" :key="cost.app" class="space-y-1">
            <div class="flex justify-between text-xs">
              <span class="text-gray-300">{{ cost.app }}</span>
              <span class="text-gray-400 font-mono">${{ formatCost(cost.total) }}</span>
            </div>
            <div class="flex w-full h-2 rounded-full overflow-hidden bg-gray-800">
              <div
                class="bg-emerald-500 h-full"
                :style="{ width: `${cost.total > 0 ? (cost.supabase.estimatedCost / cost.total) * 100 : 0}%` }"
                :title="`Supabase: $${formatCost(cost.supabase.estimatedCost)}`"
              />
              <div
                class="bg-blue-500 h-full"
                :style="{ width: `${cost.total > 0 ? (cost.vercel.estimatedCost / cost.total) * 100 : 0}%` }"
                :title="`Vercel: $${formatCost(cost.vercel.estimatedCost)}`"
              />
              <div
                class="bg-purple-500 h-full"
                :style="{ width: `${cost.total > 0 ? (cost.anthropic.estimatedCost / cost.total) * 100 : 0}%` }"
                :title="`Anthropic: $${formatCost(cost.anthropic.estimatedCost)}`"
              />
            </div>
          </div>
          <div class="flex gap-4 text-xs text-gray-500 mt-2 pt-2 border-t border-gray-800">
            <span class="flex items-center gap-1"><span class="w-2 h-2 bg-emerald-500 rounded-full inline-block" /> Supabase</span>
            <span class="flex items-center gap-1"><span class="w-2 h-2 bg-blue-500 rounded-full inline-block" /> Vercel</span>
            <span class="flex items-center gap-1"><span class="w-2 h-2 bg-purple-500 rounded-full inline-block" /> Anthropic</span>
          </div>
        </div>
        <div v-else class="text-sm text-gray-600 text-center py-8">No cost data available</div>
      </div>
    </div>

    <!-- Cost Trend -->
    <div v-if="summary?.trend.length" class="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
      <h3 class="text-sm font-semibold text-gray-400 mb-4">Monthly Cost Trend</h3>
      <div class="flex items-end gap-2 h-32">
        <div
          v-for="point in summary.trend"
          :key="point.period"
          class="flex-1 flex flex-col items-center gap-1"
        >
          <span class="text-xs text-gray-400 font-mono">${{ formatCost(point.total) }}</span>
          <div
            class="w-full bg-indigo-500/60 rounded-t transition-all duration-300"
            :style="{ height: `${maxTrend > 0 ? (point.total / maxTrend) * 80 : 0}px` }"
          />
          <span class="text-xs text-gray-600">{{ point.period.slice(5) }}</span>
        </div>
      </div>
    </div>

    <!-- Cost Anomalies -->
    <div v-if="anomalies.length > 0" class="mb-6">
      <h3 class="text-sm font-semibold text-gray-400 mb-3">Cost Anomalies</h3>
      <div class="space-y-2">
        <div
          v-for="(anomaly, i) in anomalies"
          :key="i"
          class="bg-gray-900 border rounded-lg p-4"
          :class="anomaly.severity === 'critical' ? 'border-red-800/50' : 'border-yellow-800/50'"
        >
          <div class="flex items-center gap-2 mb-1">
            <span
              class="text-xs px-2 py-0.5 rounded font-medium uppercase tracking-wider"
              :class="anomaly.severity === 'critical' ? 'bg-red-900/50 text-red-300' : 'bg-yellow-900/50 text-yellow-300'"
            >
              {{ anomaly.severity }}
            </span>
            <span class="text-sm font-medium text-gray-200">{{ anomaly.app }}</span>
            <span class="text-xs text-gray-600">|</span>
            <span class="text-sm text-gray-400">{{ anomaly.resource }}</span>
          </div>
          <p class="text-sm text-gray-300">{{ anomaly.message }}</p>
          <div class="flex gap-4 text-xs text-gray-500 mt-2">
            <span>Current: <span class="text-gray-300 font-mono">${{ formatCost(anomaly.current) }}</span></span>
            <span>Baseline: <span class="text-gray-300 font-mono">${{ formatCost(anomaly.baseline) }}</span></span>
            <span>Change: <span class="font-mono" :class="anomaly.percentChange > 0 ? 'text-red-400' : 'text-green-400'">{{ anomaly.percentChange > 0 ? '+' : '' }}{{ anomaly.percentChange }}%</span></span>
          </div>
        </div>
      </div>
    </div>

    <!-- Optimization Suggestions -->
    <div v-if="suggestions.length > 0">
      <h3 class="text-sm font-semibold text-gray-400 mb-3">Optimization Suggestions</h3>
      <div class="space-y-2">
        <div
          v-for="sug in suggestions"
          :key="sug.id"
          class="bg-gray-900 border border-gray-800 rounded-lg p-4"
        >
          <div class="flex items-start justify-between">
            <div class="flex-1">
              <div class="flex items-center gap-2 mb-1">
                <span class="text-xs px-2 py-0.5 rounded bg-gray-800 text-gray-400 uppercase tracking-wider">{{ sug.category }}</span>
                <span class="text-sm font-medium text-gray-200">{{ sug.app }}</span>
              </div>
              <p class="text-sm text-gray-300">{{ sug.description }}</p>
            </div>
            <div class="text-right ml-4 flex-shrink-0">
              <div class="text-sm font-semibold text-green-400">~${{ formatCost(sug.estimatedSavings) }}/mo</div>
              <div class="text-xs mt-0.5" :class="{
                'text-green-500': sug.effort === 'low',
                'text-yellow-500': sug.effort === 'medium',
                'text-red-500': sug.effort === 'high',
              }">
                {{ sug.effort }} effort
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!loading && costs.length === 0 && !error" class="bg-gray-900 border border-gray-800 rounded-lg p-12 text-center">
      <div class="text-gray-500 mb-2">No cost data available</div>
      <div class="text-xs text-gray-600">Click "Refresh" to fetch cost data from all fleet apps.</div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

interface AppCost {
  app: string
  appId: string
  period: string
  supabase: { dbSize: number; bandwidth: number; storage: number; estimatedCost: number }
  vercel: { builds: number; functions: number; bandwidth: number; estimatedCost: number }
  anthropic: { inputTokens: number; outputTokens: number; estimatedCost: number }
  total: number
}

interface CostAnomaly {
  app: string
  resource: string
  current: number
  baseline: number
  percentChange: number
  message: string
  severity: 'warning' | 'critical'
}

interface OptimizationSuggestion {
  id: string
  app: string
  category: string
  description: string
  estimatedSavings: number
  effort: 'low' | 'medium' | 'high'
  priority: number
}

interface FleetCostSummary {
  totalMonthly: number
  byCategory: { supabase: number; vercel: number; anthropic: number }
  byApp: { app: string; total: number }[]
  trend: { period: string; total: number }[]
  generatedAt: string
}

const period = ref('3')
const loading = ref(false)
const error = ref<string | null>(null)
const costs = ref<AppCost[]>([])
const summary = ref<FleetCostSummary | null>(null)
const anomalies = ref<CostAnomaly[]>([])
const suggestions = ref<OptimizationSuggestion[]>([])

const maxAppCost = computed(() => {
  if (!summary.value?.byApp.length) return 0
  return Math.max(...summary.value.byApp.map(a => a.total))
})

const maxTrend = computed(() => {
  if (!summary.value?.trend.length) return 0
  return Math.max(...summary.value.trend.map(t => t.total))
})

function formatCost(value: number): string {
  if (value >= 1000) return value.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
  return value.toFixed(2)
}

async function fetchCosts() {
  try {
    error.value = null
    const data = await $fetch<{ summary: FleetCostSummary; costs: AppCost[] }>('/api/admin/costs', {
      params: { months: period.value },
    })
    summary.value = data.summary
    costs.value = data.costs
  } catch (e: any) {
    error.value = e.data?.message || e.message || 'Failed to fetch costs'
  }
}

async function fetchAnomalies() {
  try {
    const data = await $fetch<{ anomalies: CostAnomaly[] }>('/api/admin/costs/anomalies')
    anomalies.value = data.anomalies
  } catch {}
}

async function fetchOptimizations() {
  try {
    const data = await $fetch<{ suggestions: OptimizationSuggestion[] }>('/api/admin/costs/optimizations')
    suggestions.value = data.suggestions
  } catch {}
}

async function refreshData() {
  loading.value = true
  try {
    await fetchCosts()
    await Promise.all([fetchAnomalies(), fetchOptimizations()])
  } finally {
    loading.value = false
  }
}

onMounted(() => refreshData())

let refreshInterval: ReturnType<typeof setInterval>
onMounted(() => {
  refreshInterval = setInterval(() => fetchCosts(), 60_000)
})
onUnmounted(() => {
  clearInterval(refreshInterval)
})
</script>
