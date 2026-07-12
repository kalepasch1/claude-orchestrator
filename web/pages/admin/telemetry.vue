<template>
  <div class="p-6">
    <div class="mb-6">
      <h2 class="text-xl font-semibold">Fleet Telemetry Lake</h2>
      <p class="text-sm text-gray-400 mt-1">Time-series analysis of fleet events. Query historical data beyond the 7-day anomaly window.</p>
    </div>

    <!-- Controls -->
    <div class="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
      <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
        <!-- Date Range Presets -->
        <div>
          <label class="text-xs text-gray-500 block mb-2">Time Range</label>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="preset in rangePresets"
              :key="preset.label"
              class="px-3 py-1.5 text-xs rounded font-medium transition-colors"
              :class="activePreset === preset.label ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-gray-200'"
              @click="applyPreset(preset)"
            >
              {{ preset.label }}
            </button>
          </div>
          <div class="flex gap-2 mt-2">
            <input
              v-model="fromDate"
              type="date"
              class="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200 focus:outline-none focus:border-indigo-500"
            />
            <input
              v-model="toDate"
              type="date"
              class="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200 focus:outline-none focus:border-indigo-500"
            />
          </div>
        </div>

        <!-- Bucket Size -->
        <div>
          <label class="text-xs text-gray-500 block mb-2">Bucket Size</label>
          <select
            v-model="bucket"
            class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
          >
            <option value="1h">Hourly</option>
            <option value="1d">Daily</option>
            <option value="1w">Weekly</option>
            <option value="1M">Monthly</option>
          </select>
        </div>

        <!-- Metrics -->
        <div>
          <label class="text-xs text-gray-500 block mb-2">Metrics</label>
          <div class="space-y-1 max-h-32 overflow-y-auto">
            <label
              v-for="metric in availableMetrics"
              :key="metric"
              class="flex items-center gap-2 text-xs text-gray-300 cursor-pointer"
            >
              <input
                type="checkbox"
                :value="metric"
                v-model="selectedMetrics"
                class="rounded bg-gray-800 border-gray-600 text-indigo-500 focus:ring-indigo-500 focus:ring-offset-0"
              />
              {{ metric }}
            </label>
            <p v-if="availableMetrics.length === 0" class="text-xs text-gray-600">No metrics found</p>
          </div>
        </div>

        <!-- Apps -->
        <div>
          <label class="text-xs text-gray-500 block mb-2">Apps</label>
          <div class="space-y-1 max-h-32 overflow-y-auto">
            <label
              v-for="app in allApps"
              :key="app"
              class="flex items-center gap-2 text-xs text-gray-300 cursor-pointer"
            >
              <input
                type="checkbox"
                :value="app"
                v-model="selectedApps"
                class="rounded bg-gray-800 border-gray-600 text-indigo-500 focus:ring-indigo-500 focus:ring-offset-0"
              />
              {{ app }}
            </label>
          </div>
        </div>
      </div>

      <div class="mt-4 flex items-center gap-3">
        <button
          class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-sm font-medium rounded transition-colors"
          :disabled="loading"
          @click="fetchData"
        >
          {{ loading ? 'Querying...' : 'Query' }}
        </button>
        <span v-if="lastQueryTime" class="text-xs text-gray-500">Last query: {{ lastQueryTime }}</span>
      </div>
    </div>

    <!-- Chart -->
    <div class="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
      <h3 class="text-sm font-medium text-gray-300 mb-4">Time Series</h3>
      <div v-if="!chartData.length" class="h-64 flex items-center justify-center text-gray-600 text-sm">
        {{ loading ? 'Loading telemetry data...' : 'No data for the selected range. Try adjusting filters.' }}
      </div>
      <div v-else class="relative">
        <svg :viewBox="`0 0 ${chartWidth} ${chartHeight}`" class="w-full" style="max-height: 400px;">
          <!-- Grid lines -->
          <line
            v-for="i in 5"
            :key="'grid-' + i"
            :x1="chartPadding.left"
            :y1="chartPadding.top + ((i - 1) / 4) * plotHeight"
            :x2="chartWidth - chartPadding.right"
            :y2="chartPadding.top + ((i - 1) / 4) * plotHeight"
            stroke="#1f2937"
            stroke-width="1"
          />

          <!-- Y-axis labels -->
          <text
            v-for="i in 5"
            :key="'ylabel-' + i"
            :x="chartPadding.left - 8"
            :y="chartPadding.top + ((i - 1) / 4) * plotHeight + 4"
            text-anchor="end"
            class="fill-gray-600"
            font-size="10"
          >
            {{ formatAxisValue(maxChartValue - ((i - 1) / 4) * maxChartValue) }}
          </text>

          <!-- X-axis labels -->
          <text
            v-for="(label, idx) in xLabels"
            :key="'xlabel-' + idx"
            :x="chartPadding.left + (idx / Math.max(xLabels.length - 1, 1)) * plotWidth"
            :y="chartHeight - 4"
            text-anchor="middle"
            class="fill-gray-600"
            font-size="10"
          >
            {{ label }}
          </text>

          <!-- Data lines -->
          <polyline
            v-for="(series, idx) in chartSeries"
            :key="series.key"
            :points="series.points"
            fill="none"
            :stroke="seriesColors[idx % seriesColors.length]"
            stroke-width="2"
            stroke-linejoin="round"
          />

          <!-- Data point dots -->
          <template v-for="(series, idx) in chartSeries" :key="'dots-' + series.key">
            <circle
              v-for="(pt, pi) in series.pointsArray"
              :key="series.key + '-' + pi"
              :cx="pt.x"
              :cy="pt.y"
              r="3"
              :fill="seriesColors[idx % seriesColors.length]"
              class="opacity-70"
            />
          </template>
        </svg>

        <!-- Legend -->
        <div class="flex flex-wrap gap-3 mt-3">
          <div
            v-for="(series, idx) in chartSeries"
            :key="'legend-' + series.key"
            class="flex items-center gap-1.5 text-xs text-gray-400"
          >
            <span
              class="w-3 h-1 rounded"
              :style="{ backgroundColor: seriesColors[idx % seriesColors.length] }"
            />
            {{ series.key }}
          </div>
        </div>
      </div>
    </div>

    <!-- Summary Stats -->
    <div v-if="summary" class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="text-xs text-gray-500">Min</div>
        <div class="text-lg font-semibold text-gray-200 mt-1">{{ formatNumber(summary.min) }}</div>
      </div>
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="text-xs text-gray-500">Max</div>
        <div class="text-lg font-semibold text-gray-200 mt-1">{{ formatNumber(summary.max) }}</div>
      </div>
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="text-xs text-gray-500">Average</div>
        <div class="text-lg font-semibold text-gray-200 mt-1">{{ formatNumber(summary.avg) }}</div>
      </div>
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="text-xs text-gray-500">Total</div>
        <div class="text-lg font-semibold text-gray-200 mt-1">{{ formatNumber(summary.total) }}</div>
      </div>
    </div>

    <!-- Retention Info -->
    <div v-if="retentionStats" class="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <h3 class="text-sm font-medium text-gray-300 mb-3">Data Retention</h3>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
        <div>
          <span class="text-xs text-gray-500 block">Total Points</span>
          <span class="text-gray-200">{{ formatNumber(retentionStats.totalPoints) }}</span>
        </div>
        <div>
          <span class="text-xs text-gray-500 block">Oldest Data</span>
          <span class="text-gray-200">{{ retentionStats.oldestPoint ? formatDate(retentionStats.oldestPoint) : 'N/A' }}</span>
        </div>
        <div>
          <span class="text-xs text-gray-500 block">Newest Data</span>
          <span class="text-gray-200">{{ retentionStats.newestPoint ? formatDate(retentionStats.newestPoint) : 'N/A' }}</span>
        </div>
        <div>
          <span class="text-xs text-gray-500 block">Est. Size</span>
          <span class="text-gray-200">{{ retentionStats.sizeEstimate }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const allApps = ['apparently', 'tomorrow', 'smarter', 'galop', 'hisanta', 'pareto', 'orchestrator']

const seriesColors = ['#818cf8', '#34d399', '#fbbf24', '#f87171', '#a78bfa', '#38bdf8', '#fb923c', '#e879f9']

const chartWidth = 800
const chartHeight = 320
const chartPadding = { top: 20, right: 20, bottom: 30, left: 60 }
const plotWidth = chartWidth - chartPadding.left - chartPadding.right
const plotHeight = chartHeight - chartPadding.top - chartPadding.bottom

// State
const loading = ref(false)
const fromDate = ref('')
const toDate = ref('')
const bucket = ref<string>('1d')
const selectedMetrics = ref<string[]>([])
const selectedApps = ref<string[]>([])
const availableMetrics = ref<string[]>([])
const activePreset = ref('7d')
const lastQueryTime = ref('')

const chartData = ref<any[]>([])
const summary = ref<{ min: number; max: number; avg: number; total: number } | null>(null)
const retentionStats = ref<any>(null)

const rangePresets = [
  { label: '24h', ms: 86400000 },
  { label: '7d', ms: 7 * 86400000 },
  { label: '30d', ms: 30 * 86400000 },
  { label: '90d', ms: 90 * 86400000 },
]

function applyPreset(preset: { label: string; ms: number }) {
  activePreset.value = preset.label
  const now = new Date()
  const from = new Date(now.getTime() - preset.ms)
  fromDate.value = from.toISOString().slice(0, 10)
  toDate.value = now.toISOString().slice(0, 10)

  // Auto-select bucket based on range
  if (preset.ms <= 86400000) bucket.value = '1h'
  else if (preset.ms <= 7 * 86400000) bucket.value = '1h'
  else if (preset.ms <= 30 * 86400000) bucket.value = '1d'
  else bucket.value = '1w'

  fetchData()
}

// Computed chart data
const maxChartValue = computed(() => {
  let max = 0
  for (const b of chartData.value) {
    for (const v of Object.values(b.values)) {
      if ((v as number) > max) max = v as number
    }
  }
  return max || 1
})

const xLabels = computed(() => {
  const data = chartData.value
  if (!data.length) return []
  const step = Math.max(1, Math.floor(data.length / 8))
  const labels: string[] = []
  for (let i = 0; i < data.length; i += step) {
    labels.push(formatDateShort(data[i].timestamp))
  }
  return labels
})

interface ChartPoint { x: number; y: number }
interface ChartSeries { key: string; points: string; pointsArray: ChartPoint[] }

const chartSeries = computed((): ChartSeries[] => {
  const data = chartData.value
  if (!data.length) return []

  // Collect all unique keys across all buckets
  const allKeys = new Set<string>()
  for (const b of data) {
    for (const k of Object.keys(b.values)) allKeys.add(k)
  }

  return Array.from(allKeys).map((key) => {
    const pointsArray: ChartPoint[] = data.map((b: any, i: number) => ({
      x: chartPadding.left + (i / Math.max(data.length - 1, 1)) * plotWidth,
      y: chartPadding.top + plotHeight - ((b.values[key] || 0) / maxChartValue.value) * plotHeight,
    }))
    const points = pointsArray.map(p => `${p.x},${p.y}`).join(' ')
    return { key, points, pointsArray }
  })
})

async function fetchData() {
  loading.value = true
  try {
    const params: Record<string, string> = {
      from: fromDate.value ? new Date(fromDate.value).toISOString() : new Date(Date.now() - 7 * 86400000).toISOString(),
      to: toDate.value ? new Date(toDate.value + 'T23:59:59').toISOString() : new Date().toISOString(),
      bucket: bucket.value,
    }
    if (selectedApps.value.length) params.apps = selectedApps.value.join(',')
    if (selectedMetrics.value.length) params.metrics = selectedMetrics.value.join(',')

    const data = await $fetch('/api/admin/telemetry', { params })
    chartData.value = (data as any).buckets || []
    summary.value = (data as any).summary || null
    availableMetrics.value = (data as any).metricNames || []
    lastQueryTime.value = new Date().toLocaleTimeString()
  } catch (e) {
    console.error('Telemetry query failed:', e)
  }
  loading.value = false
}

async function fetchStats() {
  try {
    const data = await $fetch('/api/admin/telemetry/stats')
    retentionStats.value = data
    if ((data as any).metricNames?.length && !availableMetrics.value.length) {
      availableMetrics.value = (data as any).metricNames
    }
  } catch {}
}

function formatNumber(n: number): string {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
  return String(Math.round(n * 100) / 100)
}

function formatAxisValue(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(0)}K`
  return String(Math.round(n))
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function formatDateShort(iso: string): string {
  const d = new Date(iso)
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`
}

onMounted(() => {
  // Default to 7-day view
  const now = new Date()
  fromDate.value = new Date(now.getTime() - 7 * 86400000).toISOString().slice(0, 10)
  toDate.value = now.toISOString().slice(0, 10)
  fetchData()
  fetchStats()
})
</script>
