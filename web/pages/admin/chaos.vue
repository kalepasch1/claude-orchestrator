<template>
  <div class="p-6">
    <div class="mb-6">
      <h2 class="text-xl font-semibold">Chaos Monkey</h2>
      <p class="text-sm text-gray-400 mt-1">Controlled failure injection for fleet resilience testing. Dry-run mode — simulates failures without breaking apps.</p>
    </div>

    <!-- Chaos Status Strip -->
    <div class="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
      <h3 class="text-sm font-medium text-gray-300 mb-3">Fleet Chaos Status</h3>
      <div class="flex flex-wrap gap-3">
        <div
          v-for="status in chaosStatus"
          :key="status.app"
          class="flex items-center gap-2 bg-gray-800/50 rounded px-3 py-2"
        >
          <span
            class="w-2.5 h-2.5 rounded-full"
            :class="status.inChaos ? 'bg-red-500 animate-pulse' : 'bg-green-500'"
          />
          <span class="text-sm text-gray-300">{{ status.app }}</span>
          <span v-if="status.inChaos" class="text-xs text-red-400">{{ status.failureType }}</span>
        </div>
      </div>
    </div>

    <!-- Experiment Templates -->
    <div class="mb-6">
      <h3 class="text-sm font-medium text-gray-300 mb-3">Experiment Templates</h3>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div
          v-for="template in templates"
          :key="template.name"
          class="bg-gray-900 border border-gray-800 rounded-lg p-4"
        >
          <div class="flex items-center gap-2 mb-2">
            <span class="text-sm font-medium text-gray-200">{{ template.name }}</span>
            <span
              class="text-xs px-2 py-0.5 rounded font-medium"
              :class="failureTypeClass(template.failureType)"
            >
              {{ template.failureType }}
            </span>
          </div>
          <p class="text-xs text-gray-400 mb-3">{{ template.description }}</p>
          <div class="flex items-center gap-3">
            <select
              v-model="templateTargets[template.name]"
              class="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="">Select target app...</option>
              <option v-for="app in allApps" :key="app" :value="app">{{ app }}</option>
            </select>
            <button
              class="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-800 disabled:text-gray-600 text-sm font-medium rounded transition-colors"
              :disabled="!templateTargets[template.name] || launching"
              @click="launchTemplate(template)"
            >
              Launch
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Active Experiments -->
    <div v-if="activeExperiments.length > 0" class="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
      <h3 class="text-sm font-medium text-gray-300 mb-3">Active Experiments</h3>
      <div class="space-y-3">
        <div
          v-for="exp in activeExperiments"
          :key="exp.id"
          class="bg-gray-800/50 border border-gray-700 rounded-lg p-4"
        >
          <div class="flex items-center justify-between mb-2">
            <div class="flex items-center gap-3">
              <span
                class="text-xs px-2 py-0.5 rounded font-medium bg-yellow-900/50 text-yellow-300 animate-pulse"
              >
                running
              </span>
              <span class="text-sm text-gray-200">{{ exp.name }}</span>
              <span class="text-xs text-gray-400">{{ exp.targetApp }}</span>
              <span
                class="text-xs px-2 py-0.5 rounded font-medium"
                :class="failureTypeClass(exp.failureType)"
              >
                {{ exp.failureType }}
              </span>
            </div>
            <button
              class="px-3 py-1.5 bg-red-700 hover:bg-red-600 text-sm font-bold rounded transition-colors"
              @click="abortExp(exp.id)"
            >
              ABORT
            </button>
          </div>
          <!-- Progress bar -->
          <div class="w-full bg-gray-700 rounded-full h-2 mt-2">
            <div
              class="h-2 rounded-full transition-all duration-1000 bg-yellow-500"
              :style="{ width: experimentProgress(exp) + '%' }"
            />
          </div>
          <div class="flex items-center justify-between mt-1">
            <span class="text-xs text-gray-500">{{ timeAgo(exp.startedAt) }}</span>
            <span class="text-xs text-gray-500">{{ formatDuration(exp.config.durationMs || 30000) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Experiment History -->
    <div class="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
      <div class="px-4 py-3 border-b border-gray-800">
        <h3 class="text-sm font-medium text-gray-300">Experiment History</h3>
      </div>
      <div v-if="finishedExperiments.length === 0" class="p-8 text-center text-gray-500">
        No completed experiments yet. Launch one above.
      </div>
      <div class="overflow-x-auto">
        <table v-if="finishedExperiments.length > 0" class="w-full text-sm">
          <thead>
            <tr class="text-left text-xs text-gray-500 border-b border-gray-800">
              <th class="px-4 py-2">Name</th>
              <th class="px-4 py-2">Target</th>
              <th class="px-4 py-2">Type</th>
              <th class="px-4 py-2">Status</th>
              <th class="px-4 py-2">Duration</th>
              <th class="px-4 py-2">Cascade?</th>
              <th class="px-4 py-2">Alerts</th>
              <th class="px-4 py-2">Recovery</th>
              <th class="px-4 py-2">Health</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="exp in finishedExperiments"
              :key="exp.id"
              class="border-b border-gray-800 last:border-0 hover:bg-gray-800/30 cursor-pointer"
              @click="toggleDetail(exp.id)"
            >
              <td class="px-4 py-3 text-gray-200">{{ exp.name }}</td>
              <td class="px-4 py-3 text-gray-300">{{ exp.targetApp }}</td>
              <td class="px-4 py-3">
                <span
                  class="text-xs px-2 py-0.5 rounded font-medium"
                  :class="failureTypeClass(exp.failureType)"
                >
                  {{ exp.failureType }}
                </span>
              </td>
              <td class="px-4 py-3">
                <span
                  class="text-xs px-2 py-0.5 rounded font-medium"
                  :class="statusClass(exp.status)"
                >
                  {{ exp.status }}
                </span>
              </td>
              <td class="px-4 py-3 text-gray-400">
                {{ exp.results ? formatDuration(exp.results.recoveryTimeMs) : '-' }}
              </td>
              <td class="px-4 py-3">
                <span v-if="exp.results" :class="exp.results.cascadeTriggered ? 'text-yellow-400' : 'text-gray-500'">
                  {{ exp.results.cascadeTriggered ? 'Yes' : 'No' }}
                </span>
              </td>
              <td class="px-4 py-3 text-gray-400">{{ exp.results?.alertsGenerated ?? '-' }}</td>
              <td class="px-4 py-3 text-gray-400">
                {{ exp.results ? formatDuration(exp.results.recoveryTimeMs) : '-' }}
              </td>
              <td class="px-4 py-3">
                <span v-if="exp.results" :class="exp.results.healthChecksPassed ? 'text-green-400' : 'text-red-400'">
                  {{ exp.results.healthChecksPassed ? 'Pass' : 'Fail' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Expanded Detail -->
      <div
        v-if="expandedId && expandedExperiment?.results"
        class="border-t border-gray-800 bg-gray-800/30 px-4 py-4"
      >
        <h4 class="text-sm font-medium text-gray-300 mb-3">Experiment Detail: {{ expandedExperiment.name }}</h4>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-3">
          <div>
            <div class="text-xs text-gray-500">Cascade Triggered</div>
            <div
              class="text-sm font-medium"
              :class="expandedExperiment.results.cascadeTriggered ? 'text-yellow-400' : 'text-gray-400'"
            >
              {{ expandedExperiment.results.cascadeTriggered ? 'Yes' : 'No' }}
            </div>
          </div>
          <div>
            <div class="text-xs text-gray-500">Alerts Generated</div>
            <div class="text-sm font-medium text-gray-200">{{ expandedExperiment.results.alertsGenerated }}</div>
          </div>
          <div>
            <div class="text-xs text-gray-500">Recovery Time</div>
            <div class="text-sm font-medium text-gray-200">{{ formatDuration(expandedExperiment.results.recoveryTimeMs) }}</div>
          </div>
          <div>
            <div class="text-xs text-gray-500">Health Checks</div>
            <div
              class="text-sm font-medium"
              :class="expandedExperiment.results.healthChecksPassed ? 'text-green-400' : 'text-red-400'"
            >
              {{ expandedExperiment.results.healthChecksPassed ? 'Passed' : 'Failed' }}
            </div>
          </div>
        </div>
        <div v-if="expandedExperiment.results.impactedApps.length > 0" class="mb-3">
          <div class="text-xs text-gray-500 mb-1">Impacted Apps</div>
          <div class="flex flex-wrap gap-2">
            <span
              v-for="app in expandedExperiment.results.impactedApps"
              :key="app"
              class="text-xs px-2 py-1 bg-yellow-900/30 text-yellow-300 rounded"
            >
              {{ app }}
            </span>
          </div>
        </div>
        <div>
          <div class="text-xs text-gray-500 mb-1">Notes</div>
          <p class="text-sm text-gray-300">{{ expandedExperiment.results.notes }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const allApps = ['apparently', 'tomorrow', 'smarter', 'galop', 'hisanta', 'pareto', 'orchestrator']

const templates = ref<any[]>([])
const experiments = ref<any[]>([])
const chaosStatus = ref<any[]>([])
const launching = ref(false)
const expandedId = ref<string | null>(null)
const templateTargets = ref<Record<string, string>>({})
let refreshTimer: ReturnType<typeof setInterval> | null = null

const activeExperiments = computed(() =>
  experiments.value.filter(e => e.status === 'running')
)

const finishedExperiments = computed(() =>
  experiments.value.filter(e => e.status === 'completed' || e.status === 'aborted')
)

const expandedExperiment = computed(() =>
  experiments.value.find(e => e.id === expandedId.value)
)

async function loadData() {
  try {
    const data = await $fetch('/api/admin/chaos')
    templates.value = (data as any).templates || []
    experiments.value = (data as any).experiments || []
    chaosStatus.value = (data as any).chaosStatus || []
  } catch {}
}

async function launchTemplate(template: any) {
  const targetApp = templateTargets.value[template.name]
  if (!targetApp) return
  launching.value = true
  try {
    await $fetch('/api/admin/chaos/run', {
      method: 'POST',
      body: {
        name: template.name,
        targetApp,
        failureType: template.failureType,
        config: template.config,
      },
    })
    templateTargets.value[template.name] = ''
    await loadData()
    startAutoRefresh()
  } catch {}
  launching.value = false
}

async function abortExp(id: string) {
  try {
    await $fetch('/api/admin/chaos/abort', {
      method: 'POST',
      body: { id },
    })
    await loadData()
  } catch {}
}

function toggleDetail(id: string) {
  expandedId.value = expandedId.value === id ? null : id
}

function experimentProgress(exp: any): number {
  if (!exp.startedAt || !exp.config.durationMs) return 0
  const elapsed = Date.now() - new Date(exp.startedAt).getTime()
  return Math.min(100, Math.round((elapsed / exp.config.durationMs) * 100))
}

function startAutoRefresh() {
  if (refreshTimer) return
  refreshTimer = setInterval(async () => {
    await loadData()
    if (activeExperiments.value.length === 0 && refreshTimer) {
      clearInterval(refreshTimer)
      refreshTimer = null
    }
  }, 3000)
}

function failureTypeClass(type: string): string {
  switch (type) {
    case 'offline': return 'bg-red-900/50 text-red-300'
    case 'slow': return 'bg-yellow-900/50 text-yellow-300'
    case 'error_rate': return 'bg-orange-900/50 text-orange-300'
    case 'data_stale': return 'bg-blue-900/50 text-blue-300'
    default: return 'bg-gray-800 text-gray-400'
  }
}

function statusClass(status: string): string {
  switch (status) {
    case 'pending': return 'bg-gray-800 text-gray-400'
    case 'running': return 'bg-yellow-900/50 text-yellow-300'
    case 'completed': return 'bg-green-900/50 text-green-300'
    case 'aborted': return 'bg-red-900/50 text-red-300'
    default: return 'bg-gray-800 text-gray-400'
  }
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  const secs = Math.round(ms / 1000)
  if (secs < 60) return `${secs}s`
  return `${Math.floor(secs / 60)}m ${secs % 60}s`
}

function timeAgo(iso: string | undefined): string {
  if (!iso) return '-'
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  return `${Math.floor(secs / 3600)}h ago`
}

onMounted(() => {
  loadData()
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>
