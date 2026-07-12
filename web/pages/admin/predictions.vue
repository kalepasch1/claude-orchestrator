<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-xl font-semibold">Predictive Incident Detection</h2>
        <p class="text-sm text-gray-500 mt-1">
          Analyzes telemetry trends to forecast incidents before they happen. Linear regression on sliding windows with projected threshold crossings.
        </p>
      </div>
      <div class="flex items-center gap-3">
        <label class="flex items-center gap-2 text-xs text-gray-500">
          <input type="checkbox" v-model="autoRefresh" class="rounded border-gray-700 bg-gray-800" />
          Auto-refresh (5m)
        </label>
        <span v-if="lastScan" class="text-xs text-gray-600">
          Last scan: {{ timeAgo(lastScan) }}
        </span>
        <button
          class="px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors disabled:opacity-50"
          :disabled="scanning"
          @click="runScan"
        >
          {{ scanning ? 'Scanning...' : 'Refresh Predictions' }}
        </button>
      </div>
    </div>

    <!-- Status banner -->
    <div
      class="mb-6 rounded-lg p-4 border"
      :class="statusBannerClass"
    >
      <div class="flex items-center gap-2">
        <span class="text-lg">{{ statusIcon }}</span>
        <span class="font-medium">{{ statusMessage }}</span>
      </div>
    </div>

    <!-- Summary cards -->
    <div class="grid grid-cols-4 gap-4 mb-6">
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="text-xs text-gray-500 uppercase tracking-wider">Active Predictions</div>
        <div class="text-2xl font-semibold mt-1">{{ predictions.length }}</div>
      </div>
      <div class="bg-gray-900 border border-red-900/40 rounded-lg p-4">
        <div class="text-xs text-red-400 uppercase tracking-wider">Critical</div>
        <div class="text-2xl font-semibold text-red-400 mt-1">{{ criticalCount }}</div>
      </div>
      <div class="bg-gray-900 border border-yellow-900/40 rounded-lg p-4">
        <div class="text-xs text-yellow-400 uppercase tracking-wider">Warnings</div>
        <div class="text-2xl font-semibold text-yellow-400 mt-1">{{ warningCount }}</div>
      </div>
      <div class="bg-gray-900 border border-blue-900/40 rounded-lg p-4">
        <div class="text-xs text-blue-400 uppercase tracking-wider">Trends Tracked</div>
        <div class="text-2xl font-semibold text-blue-400 mt-1">{{ trends.length }}</div>
      </div>
    </div>

    <!-- Error state -->
    <div v-if="error" class="bg-red-950/30 border border-red-800/40 rounded-lg p-4 mb-4">
      <div class="text-sm text-red-400">{{ error }}</div>
    </div>

    <!-- Loading state -->
    <div v-if="scanning && predictions.length === 0 && trends.length === 0" class="bg-gray-900 border border-gray-800 rounded-lg p-12 text-center">
      <div class="text-gray-500">Analyzing telemetry trends across all apps...</div>
    </div>

    <!-- Prediction cards -->
    <div v-if="predictions.length > 0" class="mb-8">
      <h3 class="text-sm font-medium text-gray-400 uppercase tracking-wider mb-3">Active Predictions</h3>
      <div class="space-y-3">
        <div
          v-for="pred in predictions"
          :key="pred.id"
          class="bg-gray-900 border rounded-lg p-4"
          :class="{
            'border-red-800/50': pred.severity === 'critical',
            'border-yellow-800/50': pred.severity === 'warning',
            'border-blue-800/40': pred.severity === 'info',
          }"
        >
          <div class="flex items-start justify-between">
            <div class="flex-1">
              <div class="flex items-center gap-2 mb-2">
                <span
                  class="text-xs px-2 py-0.5 rounded font-medium uppercase tracking-wider"
                  :class="severityBadgeClass(pred.severity)"
                >
                  {{ pred.severity }}
                </span>
                <span
                  class="text-xs px-2 py-0.5 rounded font-medium"
                  :class="typeBadgeClass(pred.type)"
                >
                  {{ typeLabel(pred.type) }}
                </span>
                <span class="text-sm font-medium text-gray-200">{{ pred.app }}</span>
                <span class="text-xs text-gray-600">|</span>
                <span class="text-sm text-gray-400">{{ pred.metric }}</span>
              </div>

              <p class="text-sm text-gray-300 mb-3">{{ pred.message }}</p>

              <!-- Confidence meter -->
              <div class="flex items-center gap-2 mb-3">
                <span class="text-xs text-gray-500">Confidence:</span>
                <div class="w-32 h-2 bg-gray-800 rounded-full overflow-hidden">
                  <div
                    class="h-full rounded-full transition-all"
                    :class="confidenceBarClass(pred.confidence)"
                    :style="{ width: `${Math.round(pred.confidence * 100)}%` }"
                  />
                </div>
                <span class="text-xs text-gray-400">{{ Math.round(pred.confidence * 100) }}%</span>
              </div>

              <!-- Trend sparkline -->
              <div class="mb-3">
                <svg
                  :width="sparklineWidth"
                  height="40"
                  class="bg-gray-800/50 rounded"
                >
                  <!-- Historical line (solid) -->
                  <polyline
                    v-if="getSparklineData(pred).historical.length > 1"
                    :points="getSparklinePoints(getSparklineData(pred).historical, sparklineWidth * 0.6, 40)"
                    fill="none"
                    :stroke="sparklineColor(pred.severity)"
                    stroke-width="1.5"
                    stroke-linejoin="round"
                  />
                  <!-- Projected line (dashed) -->
                  <polyline
                    v-if="getSparklineData(pred).projected.length > 1"
                    :points="getSparklinePoints(getSparklineData(pred).projected, sparklineWidth * 0.4, 40, sparklineWidth * 0.6)"
                    fill="none"
                    :stroke="sparklineColor(pred.severity)"
                    stroke-width="1.5"
                    stroke-dasharray="4,3"
                    stroke-linejoin="round"
                    opacity="0.6"
                  />
                  <!-- Threshold line -->
                  <line
                    x1="0"
                    :y1="getThresholdY(pred, 40)"
                    :x2="sparklineWidth"
                    :y2="getThresholdY(pred, 40)"
                    stroke="#ef4444"
                    stroke-width="1"
                    stroke-dasharray="2,2"
                    opacity="0.4"
                  />
                </svg>
              </div>

              <!-- Predicted time -->
              <div class="flex items-center gap-4 text-xs text-gray-500">
                <span>Predicted: {{ formatTime(pred.predictedTime) }}</span>
                <span>Made: {{ timeAgo(pred.predictedAt) }}</span>
              </div>
            </div>

            <div class="flex flex-col gap-2 ml-4">
              <button
                v-if="pred.suggestedPlaybook"
                class="px-3 py-1.5 text-xs bg-indigo-600/30 hover:bg-indigo-600/50 text-indigo-300 rounded border border-indigo-700/40 transition-colors"
                @click="preemptPlaybook(pred)"
              >
                Preempt
              </button>
              <button
                v-if="!pred.acknowledged"
                class="px-3 py-1.5 text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 rounded border border-gray-700 transition-colors"
                @click="acknowledge(pred.id)"
              >
                Acknowledge
              </button>
              <span v-else class="text-xs text-gray-600 text-center">Ack'd</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Trend overview table -->
    <div v-if="trends.length > 0">
      <h3 class="text-sm font-medium text-gray-400 uppercase tracking-wider mb-3">Trend Overview</h3>
      <div class="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-gray-800">
              <th class="text-left px-4 py-3 text-xs text-gray-500 font-medium uppercase tracking-wider">App</th>
              <th class="text-left px-4 py-3 text-xs text-gray-500 font-medium uppercase tracking-wider">Metric</th>
              <th class="text-left px-4 py-3 text-xs text-gray-500 font-medium uppercase tracking-wider">Status</th>
              <th class="text-right px-4 py-3 text-xs text-gray-500 font-medium uppercase tracking-wider">Current</th>
              <th class="text-right px-4 py-3 text-xs text-gray-500 font-medium uppercase tracking-wider">Slope/hr</th>
              <th class="text-right px-4 py-3 text-xs text-gray-500 font-medium uppercase tracking-wider">R&sup2;</th>
              <th class="text-right px-4 py-3 text-xs text-gray-500 font-medium uppercase tracking-wider">Confidence</th>
              <th class="text-right px-4 py-3 text-xs text-gray-500 font-medium uppercase tracking-wider">Hrs to Threshold</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="trend in trends"
              :key="`${trend.app}:${trend.metric}`"
              class="border-b border-gray-800/50 hover:bg-gray-800/30"
            >
              <td class="px-4 py-3 text-gray-300">{{ trend.app }}</td>
              <td class="px-4 py-3 text-gray-400">{{ trend.metric }}</td>
              <td class="px-4 py-3">
                <span
                  class="text-xs px-2 py-0.5 rounded font-medium"
                  :class="statusBadgeClass(trend.status)"
                >
                  {{ statusLabel(trend.status) }}
                </span>
              </td>
              <td class="px-4 py-3 text-right text-gray-300 font-mono text-xs">{{ trend.currentValue.toFixed(2) }}</td>
              <td class="px-4 py-3 text-right font-mono text-xs" :class="trend.slope > 0 ? 'text-red-400' : trend.slope < 0 ? 'text-green-400' : 'text-gray-500'">
                {{ trend.slope > 0 ? '+' : '' }}{{ trend.slope.toFixed(3) }}
              </td>
              <td class="px-4 py-3 text-right text-gray-400 font-mono text-xs">{{ trend.r2.toFixed(3) }}</td>
              <td class="px-4 py-3 text-right">
                <span class="text-xs" :class="confidenceTextClass(trend.confidence)">{{ trend.confidence }}</span>
              </td>
              <td class="px-4 py-3 text-right font-mono text-xs" :class="hoursColor(trend.hoursToThreshold)">
                {{ trend.hoursToThreshold != null ? trend.hoursToThreshold.toFixed(1) : '--' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!scanning && predictions.length === 0 && trends.length === 0" class="bg-gray-900 border border-gray-800 rounded-lg p-12 text-center">
      <div class="text-gray-500">No trend data available. Click "Refresh Predictions" to scan telemetry.</div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

interface Prediction {
  id: string
  app: string
  metric: string
  type: 'incident_predicted' | 'capacity_warning' | 'degradation_detected' | 'recovery_expected'
  severity: 'info' | 'warning' | 'critical'
  message: string
  predictedAt: string
  predictedEvent: string
  predictedTime: string
  confidence: number
  suggestedPlaybook?: string
  acknowledged: boolean
  resolvedAt?: string
}

interface TrendAnalysis {
  app: string
  metric: string
  currentValue: number
  slope: number
  r2: number
  projectedThreshold: number
  projectedCrossing?: string
  hoursToThreshold?: number
  confidence: 'high' | 'medium' | 'low'
  status: 'stable' | 'trending_up' | 'trending_down' | 'approaching_threshold' | 'critical_trajectory'
}

const predictions = ref<Prediction[]>([])
const trends = ref<TrendAnalysis[]>([])
const scanning = ref(false)
const error = ref('')
const lastScan = ref<string | null>(null)
const autoRefresh = ref(false)
const sparklineWidth = 280

let refreshInterval: ReturnType<typeof setInterval> | null = null

const criticalCount = computed(() => predictions.value.filter(p => p.severity === 'critical').length)
const warningCount = computed(() => predictions.value.filter(p => p.severity === 'warning').length)

const statusBannerClass = computed(() => {
  if (criticalCount.value > 0) return 'bg-red-950/30 border-red-800/50 text-red-300'
  if (warningCount.value > 0) return 'bg-yellow-950/30 border-yellow-800/50 text-yellow-300'
  return 'bg-green-950/30 border-green-800/50 text-green-300'
})

const statusIcon = computed(() => {
  if (criticalCount.value > 0) return '\u{1F6A8}'
  if (warningCount.value > 0) return '⚠️'
  return '✅'
})

const statusMessage = computed(() => {
  const total = predictions.value.length
  if (total === 0) return 'All clear -- no incident predictions active'
  const parts = []
  if (criticalCount.value > 0) parts.push(`${criticalCount.value} critical`)
  if (warningCount.value > 0) parts.push(`${warningCount.value} warning`)
  const infoCount = total - criticalCount.value - warningCount.value
  if (infoCount > 0) parts.push(`${infoCount} info`)
  return `${total} prediction${total === 1 ? '' : 's'} active: ${parts.join(', ')}`
})

function severityBadgeClass(severity: string) {
  if (severity === 'critical') return 'bg-red-900/50 text-red-300'
  if (severity === 'warning') return 'bg-yellow-900/50 text-yellow-300'
  return 'bg-blue-900/40 text-blue-300'
}

function typeBadgeClass(type: string) {
  if (type === 'incident_predicted') return 'bg-red-900/30 text-red-400 border border-red-800/30'
  if (type === 'capacity_warning') return 'bg-yellow-900/30 text-yellow-400 border border-yellow-800/30'
  if (type === 'recovery_expected') return 'bg-green-900/30 text-green-400 border border-green-800/30'
  return 'bg-gray-800 text-gray-400 border border-gray-700'
}

function typeLabel(type: string) {
  const labels: Record<string, string> = {
    incident_predicted: 'Incident',
    capacity_warning: 'Capacity',
    degradation_detected: 'Degradation',
    recovery_expected: 'Recovery',
  }
  return labels[type] || type
}

function confidenceBarClass(confidence: number) {
  if (confidence >= 0.8) return 'bg-red-500'
  if (confidence >= 0.5) return 'bg-yellow-500'
  return 'bg-blue-500'
}

function confidenceTextClass(confidence: string) {
  if (confidence === 'high') return 'text-red-400'
  if (confidence === 'medium') return 'text-yellow-400'
  return 'text-gray-500'
}

function statusBadgeClass(status: string) {
  const map: Record<string, string> = {
    critical_trajectory: 'bg-red-900/50 text-red-300',
    approaching_threshold: 'bg-yellow-900/50 text-yellow-300',
    trending_up: 'bg-orange-900/40 text-orange-300',
    trending_down: 'bg-green-900/40 text-green-300',
    stable: 'bg-gray-800 text-gray-400',
  }
  return map[status] || 'bg-gray-800 text-gray-400'
}

function statusLabel(status: string) {
  const map: Record<string, string> = {
    critical_trajectory: 'Critical',
    approaching_threshold: 'Approaching',
    trending_up: 'Rising',
    trending_down: 'Falling',
    stable: 'Stable',
  }
  return map[status] || status
}

function hoursColor(hours: number | undefined) {
  if (hours == null) return 'text-gray-600'
  if (hours <= 2) return 'text-red-400'
  if (hours <= 12) return 'text-yellow-400'
  return 'text-gray-400'
}

// Sparkline helpers
function getSparklineData(pred: Prediction) {
  // Generate synthetic sparkline from prediction data
  const historical = generateTrendPoints(8, pred.confidence, pred.severity === 'critical' ? 0.8 : 0.4)
  const lastVal = historical[historical.length - 1]
  const projected = [lastVal]
  const step = pred.severity === 'critical' ? 0.15 : 0.08
  for (let i = 1; i <= 4; i++) {
    projected.push(Math.min(1, lastVal + step * i))
  }
  return { historical, projected }
}

function generateTrendPoints(count: number, trend: number, base: number): number[] {
  const points = []
  for (let i = 0; i < count; i++) {
    const noise = (Math.sin(i * 2.7 + trend * 5) * 0.05)
    points.push(Math.max(0, Math.min(1, base + (trend * i * 0.05) + noise)))
  }
  return points
}

function getSparklinePoints(values: number[], width: number, height: number, offsetX: number = 0): string {
  if (values.length < 2) return ''
  const padding = 4
  const h = height - padding * 2
  const step = width / (values.length - 1)
  return values.map((v, i) => `${offsetX + i * step},${padding + h * (1 - v)}`).join(' ')
}

function sparklineColor(severity: string) {
  if (severity === 'critical') return '#ef4444'
  if (severity === 'warning') return '#eab308'
  return '#60a5fa'
}

function getThresholdY(pred: Prediction, height: number) {
  const padding = 4
  return padding + (height - padding * 2) * 0.15 // threshold near top
}

function formatTime(iso: string) {
  try {
    const d = new Date(iso)
    return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

async function runScan() {
  scanning.value = true
  error.value = ''
  try {
    const [predResult, trendResult] = await Promise.all([
      $fetch('/api/admin/predictions', { params: { scan: 'true' } }),
      $fetch('/api/admin/predictions/trends', { params: { fresh: 'true' } }),
    ])
    predictions.value = (predResult as any).predictions || []
    lastScan.value = (predResult as any).lastScan
    trends.value = (trendResult as any).trends || []
  } catch (e: any) {
    error.value = e.data?.message || e.message || 'Scan failed'
  } finally {
    scanning.value = false
  }
}

async function loadCached() {
  try {
    const [predResult, trendResult] = await Promise.all([
      $fetch('/api/admin/predictions'),
      $fetch('/api/admin/predictions/trends'),
    ])
    predictions.value = (predResult as any).predictions || []
    lastScan.value = (predResult as any).lastScan
    trends.value = (trendResult as any).trends || []
  } catch {
    // Silent fail on initial load
  }
}

async function acknowledge(id: string) {
  try {
    await $fetch('/api/admin/predictions/acknowledge', {
      method: 'POST',
      body: { id },
    })
    const pred = predictions.value.find(p => p.id === id)
    if (pred) pred.acknowledged = true
  } catch (e: any) {
    error.value = e.data?.message || 'Failed to acknowledge'
  }
}

async function preemptPlaybook(pred: Prediction) {
  if (!pred.suggestedPlaybook) return
  // Navigate to playbooks page with execution request
  await navigateTo(`/admin/playbooks?execute=${pred.suggestedPlaybook}&trigger=${pred.id}`)
}

watch(autoRefresh, (enabled) => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
    refreshInterval = null
  }
  if (enabled) {
    refreshInterval = setInterval(runScan, 5 * 60 * 1000)
  }
})

onMounted(() => {
  loadCached()
})

onUnmounted(() => {
  if (refreshInterval) clearInterval(refreshInterval)
})
</script>
