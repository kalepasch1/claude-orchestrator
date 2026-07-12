<template>
  <div class="p-6">
    <div class="mb-6">
      <h2 class="text-xl font-semibold">Cross-App Session Replay</h2>
      <p class="text-sm text-gray-400 mt-1">Trace user activity across all fleet apps. Unified timeline of events, approvals, and actions.</p>
    </div>

    <!-- Search -->
    <div class="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
      <div class="flex gap-3">
        <input
          v-model="searchEmail"
          type="email"
          placeholder="Enter email to trace (e.g. user@example.com)"
          class="flex-1 bg-gray-800 border border-gray-700 rounded px-4 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500"
          @keyup.enter="traceUser"
        />
        <button
          class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-800 disabled:text-gray-600 text-sm font-medium rounded transition-colors"
          :disabled="!searchEmail || tracing"
          @click="traceUser"
        >
          {{ tracing ? 'Tracing...' : 'Trace' }}
        </button>
      </div>
    </div>

    <!-- Recently Active Users -->
    <div v-if="!session && recentUsers.length > 0" class="mb-6">
      <h3 class="text-sm font-medium text-gray-300 mb-3">Recently Active Users</h3>
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        <div
          v-for="user in recentUsers"
          :key="user.email"
          class="bg-gray-900 border border-gray-800 rounded-lg p-4 cursor-pointer hover:border-gray-700 transition-colors"
          @click="searchEmail = user.email; traceUser()"
        >
          <div class="flex items-center gap-2 mb-1">
            <span class="text-sm font-medium text-gray-200">{{ user.email }}</span>
          </div>
          <div class="flex items-center gap-2 text-xs text-gray-500">
            <span
              class="px-1.5 py-0.5 rounded text-xs font-medium"
              :class="appColor(user.app)"
            >
              {{ user.app }}
            </span>
            <span>{{ user.eventType }}</span>
            <span>{{ timeAgo(user.lastSeen) }}</span>
          </div>
          <p class="text-xs text-gray-400 mt-1 truncate">{{ user.description }}</p>
        </div>
      </div>
    </div>

    <!-- Session Detail -->
    <div v-if="session">
      <!-- Session Header -->
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
        <div class="flex items-center justify-between mb-3">
          <div>
            <h3 class="text-lg font-medium text-gray-200">{{ session.email }}</h3>
            <p v-if="session.userId" class="text-xs text-gray-500 mt-0.5">ID: {{ session.userId }}</p>
          </div>
          <button
            class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-sm text-gray-400 rounded transition-colors"
            @click="session = null"
          >
            Clear
          </button>
        </div>

        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <span class="text-xs text-gray-500 block">Apps</span>
            <div class="flex flex-wrap gap-1 mt-1">
              <span
                v-for="app in session.apps"
                :key="app"
                class="px-1.5 py-0.5 rounded text-xs font-medium"
                :class="appColor(app)"
              >
                {{ app }}
              </span>
            </div>
          </div>
          <div>
            <span class="text-xs text-gray-500 block">First Seen</span>
            <span class="text-sm text-gray-200">{{ session.firstSeen ? formatDate(session.firstSeen) : 'N/A' }}</span>
          </div>
          <div>
            <span class="text-xs text-gray-500 block">Last Seen</span>
            <span class="text-sm text-gray-200">{{ session.lastSeen ? formatDate(session.lastSeen) : 'N/A' }}</span>
          </div>
          <div>
            <span class="text-xs text-gray-500 block">Total Events</span>
            <span class="text-sm font-semibold text-gray-200">{{ session.totalEvents }}</span>
          </div>
        </div>
      </div>

      <!-- Filters -->
      <div class="flex flex-wrap gap-3 mb-4">
        <div class="flex items-center gap-2">
          <span class="text-xs text-gray-500">App:</span>
          <button
            v-for="app in ['all', ...session.apps]"
            :key="app"
            class="px-2 py-1 text-xs rounded transition-colors"
            :class="filterApp === app ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-gray-200'"
            @click="filterApp = app"
          >
            {{ app }}
          </button>
        </div>
        <div class="flex items-center gap-2">
          <span class="text-xs text-gray-500">Severity:</span>
          <button
            v-for="sev in ['all', 'info', 'warning', 'critical']"
            :key="sev"
            class="px-2 py-1 text-xs rounded transition-colors"
            :class="filterSeverity === sev ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-gray-200'"
            @click="filterSeverity = sev"
          >
            {{ sev }}
          </button>
        </div>
      </div>

      <!-- Timeline -->
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <h3 class="text-sm font-medium text-gray-300 mb-4">
          Timeline ({{ filteredTimeline.length }} events)
        </h3>

        <div v-if="filteredTimeline.length === 0" class="py-8 text-center text-gray-600 text-sm">
          No events match the current filters.
        </div>

        <div class="relative ml-4">
          <!-- Vertical line -->
          <div class="absolute left-2 top-0 bottom-0 w-px bg-gray-800" />

          <div
            v-for="(event, idx) in filteredTimeline"
            :key="idx"
            class="relative pl-8 pb-6 last:pb-0"
          >
            <!-- Timeline dot -->
            <div
              class="absolute left-0 top-1 w-4 h-4 rounded-full border-2 border-gray-900"
              :class="dotColor(event)"
            />

            <!-- Event content -->
            <div class="flex items-start gap-2">
              <span
                class="px-1.5 py-0.5 rounded text-xs font-medium shrink-0"
                :class="appColor(event.app)"
              >
                {{ event.app }}
              </span>
              <span
                class="px-1.5 py-0.5 rounded text-xs font-medium shrink-0"
                :class="typeColor(event.type)"
              >
                {{ event.type }}
              </span>
              <span
                v-if="event.severity !== 'info'"
                class="px-1.5 py-0.5 rounded text-xs font-medium shrink-0"
                :class="severityColor(event.severity)"
              >
                {{ event.severity }}
              </span>
            </div>
            <p class="text-sm text-gray-200 mt-1">{{ event.description }}</p>
            <span class="text-xs text-gray-600 mt-0.5 block">{{ formatDateTime(event.timestamp) }}</span>
            <div
              v-if="event.details && Object.keys(event.details).length"
              class="mt-1 text-xs text-gray-500 bg-gray-800/50 rounded px-2 py-1 font-mono"
            >
              {{ JSON.stringify(event.details, null, 0).slice(0, 200) }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Loading state -->
    <div v-if="tracing" class="flex items-center justify-center py-12">
      <div class="text-sm text-gray-500">Tracing user across {{ allApps.length }} apps...</div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const allApps = ['apparently', 'tomorrow', 'smarter', 'galop', 'hisanta', 'pareto', 'orchestrator']

const searchEmail = ref('')
const tracing = ref(false)
const session = ref<any>(null)
const recentUsers = ref<any[]>([])
const filterApp = ref('all')
const filterSeverity = ref('all')

const APP_COLORS: Record<string, string> = {
  apparently: 'bg-blue-900/50 text-blue-300',
  tomorrow: 'bg-purple-900/50 text-purple-300',
  smarter: 'bg-indigo-900/50 text-indigo-300',
  galop: 'bg-green-900/50 text-green-300',
  hisanta: 'bg-red-900/50 text-red-300',
  pareto: 'bg-yellow-900/50 text-yellow-300',
  orchestrator: 'bg-cyan-900/50 text-cyan-300',
}

const APP_DOT_COLORS: Record<string, string> = {
  apparently: 'bg-blue-500',
  tomorrow: 'bg-purple-500',
  smarter: 'bg-indigo-500',
  galop: 'bg-green-500',
  hisanta: 'bg-red-500',
  pareto: 'bg-yellow-500',
  orchestrator: 'bg-cyan-500',
}

const filteredTimeline = computed(() => {
  if (!session.value?.timeline) return []
  return session.value.timeline.filter((e: any) => {
    if (filterApp.value !== 'all' && e.app !== filterApp.value) return false
    if (filterSeverity.value !== 'all' && e.severity !== filterSeverity.value) return false
    return true
  })
})

async function traceUser() {
  if (!searchEmail.value) return
  tracing.value = true
  session.value = null
  try {
    const data = await $fetch('/api/admin/session-replay', {
      params: { email: searchEmail.value.trim() },
    })
    session.value = (data as any).session || (data as any).sessions?.[0] || null
  } catch (e) {
    console.error('Session replay failed:', e)
  }
  tracing.value = false
}

async function loadRecent() {
  try {
    const data = await $fetch('/api/admin/session-replay/recent')
    recentUsers.value = (data as any).users || []
  } catch {}
}

function appColor(app: string): string {
  return APP_COLORS[app] || 'bg-gray-800 text-gray-400'
}

function dotColor(event: any): string {
  if (event.severity === 'critical') return 'bg-red-500'
  if (event.severity === 'warning') return 'bg-yellow-500'
  return APP_DOT_COLORS[event.app] || 'bg-gray-500'
}

function typeColor(type: string): string {
  switch (type) {
    case 'login': return 'bg-green-900/50 text-green-300'
    case 'action': return 'bg-blue-900/50 text-blue-300'
    case 'error': return 'bg-red-900/50 text-red-300'
    case 'fleet_event': return 'bg-purple-900/50 text-purple-300'
    case 'approval': return 'bg-indigo-900/50 text-indigo-300'
    default: return 'bg-gray-800 text-gray-400'
  }
}

function severityColor(severity: string): string {
  switch (severity) {
    case 'critical': return 'bg-red-900/50 text-red-300'
    case 'warning': return 'bg-yellow-900/50 text-yellow-300'
    default: return 'bg-gray-800 text-gray-400'
  }
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function formatDateTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function timeAgo(iso: string): string {
  if (!iso) return ''
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

onMounted(() => {
  loadRecent()
})
</script>
