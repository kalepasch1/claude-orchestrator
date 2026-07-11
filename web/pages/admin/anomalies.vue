<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-xl font-semibold">Anomaly Radar</h2>
        <p class="text-sm text-gray-500 mt-1">
          Statistical anomaly detection across all connected apps. Z-score analysis on event volume, error rate, and rejection rate.
        </p>
      </div>
      <div class="flex items-center gap-3">
        <span v-if="lastScan" class="text-xs text-gray-600">
          Last scan: {{ timeAgo(lastScan) }}
        </span>
        <button
          class="px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors disabled:opacity-50"
          :disabled="scanning"
          @click="runScan"
        >
          {{ scanning ? 'Scanning...' : 'Run Scan' }}
        </button>
      </div>
    </div>

    <!-- Summary cards -->
    <div class="grid grid-cols-4 gap-4 mb-6">
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="text-xs text-gray-500 uppercase tracking-wider">Total Alerts</div>
        <div class="text-2xl font-semibold mt-1">{{ alerts.length }}</div>
      </div>
      <div class="bg-gray-900 border border-red-900/40 rounded-lg p-4">
        <div class="text-xs text-red-400 uppercase tracking-wider">Critical</div>
        <div class="text-2xl font-semibold text-red-400 mt-1">{{ criticalCount }}</div>
      </div>
      <div class="bg-gray-900 border border-yellow-900/40 rounded-lg p-4">
        <div class="text-xs text-yellow-400 uppercase tracking-wider">Warning</div>
        <div class="text-2xl font-semibold text-yellow-400 mt-1">{{ warningCount }}</div>
      </div>
      <div class="bg-gray-900 border border-blue-900/40 rounded-lg p-4">
        <div class="text-xs text-blue-400 uppercase tracking-wider">Info</div>
        <div class="text-2xl font-semibold text-blue-400 mt-1">{{ infoCount }}</div>
      </div>
    </div>

    <!-- Loading state -->
    <div v-if="scanning && alerts.length === 0" class="bg-gray-900 border border-gray-800 rounded-lg p-12 text-center">
      <div class="text-gray-500">Scanning all apps for anomalies...</div>
    </div>

    <!-- Error state -->
    <div v-if="error" class="bg-red-950/30 border border-red-800/40 rounded-lg p-4 mb-4">
      <div class="text-sm text-red-400">{{ error }}</div>
    </div>

    <!-- Alert list -->
    <div v-if="alerts.length > 0" class="space-y-3">
      <div
        v-for="alert in alerts"
        :key="alert.id"
        class="bg-gray-900 border rounded-lg p-4"
        :class="{
          'border-red-800/50': alert.severity === 'critical',
          'border-yellow-800/50': alert.severity === 'warning',
          'border-blue-800/40': alert.severity === 'info',
        }"
      >
        <div class="flex items-start justify-between">
          <div class="flex items-center gap-2 mb-2">
            <span
              class="text-xs px-2 py-0.5 rounded font-medium uppercase tracking-wider"
              :class="{
                'bg-red-900/50 text-red-300': alert.severity === 'critical',
                'bg-yellow-900/50 text-yellow-300': alert.severity === 'warning',
                'bg-blue-900/40 text-blue-300': alert.severity === 'info',
              }"
            >
              {{ alert.severity }}
            </span>
            <span class="text-sm font-medium text-gray-200">{{ alert.app }}</span>
            <span class="text-xs text-gray-600">|</span>
            <span class="text-sm text-gray-400">{{ alert.metric }}</span>
          </div>
          <span class="text-xs text-gray-600">{{ timeAgo(alert.detected_at) }}</span>
        </div>

        <p class="text-sm text-gray-300 mb-3">{{ alert.message }}</p>

        <div class="flex gap-6 text-xs text-gray-500">
          <span>Current: <span class="text-gray-300 font-mono">{{ alert.current }}</span></span>
          <span>Baseline: <span class="text-gray-300 font-mono">{{ alert.baseline }}</span></span>
          <span>Std Dev: <span class="text-gray-300 font-mono">{{ alert.stddev }}</span></span>
          <span>Z-Score: <span class="font-mono" :class="{
            'text-red-400': Math.abs(alert.zscore) >= 3.5,
            'text-yellow-400': Math.abs(alert.zscore) >= 2.5 && Math.abs(alert.zscore) < 3.5,
            'text-blue-400': Math.abs(alert.zscore) < 2.5,
          }">{{ alert.zscore }}</span></span>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!scanning && alerts.length === 0 && !error" class="bg-gray-900 border border-gray-800 rounded-lg p-12 text-center">
      <div class="text-gray-500 mb-2">No anomalies detected</div>
      <div class="text-xs text-gray-600">All metrics are within normal ranges. Click "Run Scan" to check now.</div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

interface AnomalyAlert {
  id: string
  app: string
  metric: string
  current: number
  baseline: number
  stddev: number
  zscore: number
  severity: 'info' | 'warning' | 'critical'
  detected_at: string
  message: string
}

const alerts = ref<AnomalyAlert[]>([])
const scanning = ref(false)
const lastScan = ref<string | null>(null)
const error = ref<string | null>(null)

const criticalCount = computed(() => alerts.value.filter(a => a.severity === 'critical').length)
const warningCount = computed(() => alerts.value.filter(a => a.severity === 'warning').length)
const infoCount = computed(() => alerts.value.filter(a => a.severity === 'info').length)

function timeAgo(dateStr: string): string {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

async function fetchAlerts(cached = true) {
  try {
    error.value = null
    const data = await $fetch<{ alerts: AnomalyAlert[]; lastScan: string | null }>('/api/admin/anomalies', {
      params: { cached: cached ? 'true' : 'false' },
    })
    alerts.value = data.alerts
    lastScan.value = data.lastScan
  } catch (e: any) {
    error.value = e.data?.message || e.message || 'Failed to fetch alerts'
  }
}

async function runScan() {
  scanning.value = true
  error.value = null
  try {
    const data = await $fetch<{ alerts: AnomalyAlert[]; lastScan: string }>('/api/admin/anomalies/scan', {
      method: 'POST',
    })
    alerts.value = data.alerts
    lastScan.value = data.lastScan
  } catch (e: any) {
    error.value = e.data?.message || e.message || 'Scan failed'
  } finally {
    scanning.value = false
  }
}

// Initial load from cache
onMounted(() => {
  fetchAlerts(true)
})

// Auto-refresh every 60 seconds
let refreshInterval: ReturnType<typeof setInterval>
onMounted(() => {
  refreshInterval = setInterval(() => fetchAlerts(true), 60_000)
})
onUnmounted(() => {
  clearInterval(refreshInterval)
})
</script>
