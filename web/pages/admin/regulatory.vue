<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-6">
      <h2 class="text-xl font-semibold">Regulatory Snapshot</h2>
      <div class="flex gap-2">
        <button v-if="currentSnapshot"
                class="px-3 py-1.5 text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg transition-colors"
                @click="exportReport">
          &#128196; Export HTML Report
        </button>
        <button class="px-4 py-1.5 text-sm bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors"
                :disabled="generating"
                @click="generate">
          {{ generating ? 'Generating...' : 'Generate Snapshot' }}
        </button>
      </div>
    </div>

    <!-- Date Range Picker -->
    <div class="flex gap-3 items-center mb-6">
      <label class="text-xs text-gray-500">Period:</label>
      <input type="date" v-model="dateFrom"
             class="bg-gray-900 border border-gray-700 text-gray-300 text-xs rounded px-2 py-1 focus:border-indigo-500 focus:outline-none" />
      <span class="text-gray-600 text-xs">to</span>
      <input type="date" v-model="dateTo"
             class="bg-gray-900 border border-gray-700 text-gray-300 text-xs rounded px-2 py-1 focus:border-indigo-500 focus:outline-none" />
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex items-center justify-center py-20">
      <div class="text-gray-500 text-sm">Loading regulatory data...</div>
    </div>

    <template v-else>
      <!-- Overall Status Banner -->
      <div v-if="currentSnapshot" class="mb-6 rounded-lg p-4 border"
           :class="statusBannerClass">
        <div class="flex items-center justify-between">
          <div>
            <div class="text-lg font-semibold" :class="statusTextClass">{{ statusLabel }}</div>
            <div class="text-xs mt-1 opacity-70" :class="statusTextClass">
              Generated {{ formatDate(currentSnapshot.generatedAt) }} &mdash;
              Period: {{ formatDate(currentSnapshot.period.from) }} to {{ formatDate(currentSnapshot.period.to) }}
            </div>
          </div>
          <div class="text-3xl font-bold" :class="statusTextClass">
            {{ statusIcon }}
          </div>
        </div>
      </div>

      <!-- Summary KPI Cards -->
      <div v-if="currentSnapshot" class="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Apps Scanned</div>
          <div class="text-2xl font-semibold text-gray-300">{{ currentSnapshot.summary.totalApps }}</div>
        </div>
        <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Apps with Issues</div>
          <div class="text-2xl font-semibold" :class="currentSnapshot.summary.appsWithIssues > 0 ? 'text-yellow-400' : 'text-green-400'">
            {{ currentSnapshot.summary.appsWithIssues }}
          </div>
        </div>
        <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Critical Items</div>
          <div class="text-2xl font-semibold" :class="currentSnapshot.summary.criticalItems > 0 ? 'text-red-400' : 'text-gray-300'">
            {{ currentSnapshot.summary.criticalItems }}
          </div>
        </div>
        <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <div class="text-xs text-gray-500 uppercase tracking-wider mb-1">Warning Items</div>
          <div class="text-2xl font-semibold" :class="currentSnapshot.summary.warningItems > 0 ? 'text-yellow-400' : 'text-gray-300'">
            {{ currentSnapshot.summary.warningItems }}
          </div>
        </div>
      </div>

      <!-- Per-App Sections -->
      <div v-if="currentSnapshot" class="space-y-4 mb-8">
        <div v-for="section in currentSnapshot.sections" :key="section.app"
             class="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
          <!-- Section Header (clickable to toggle) -->
          <button class="w-full flex items-center justify-between px-5 py-3 hover:bg-gray-800/50 transition-colors text-left"
                  @click="toggleSection(section.app)">
            <div class="flex items-center gap-3">
              <span class="w-2 h-2 rounded-full"
                    :class="sectionDotColor(section.status)" />
              <span class="text-sm font-medium text-gray-200">{{ section.title }}</span>
              <span class="text-xs px-2 py-0.5 rounded-full font-medium"
                    :class="sectionBadgeClass(section.status)">
                {{ sectionStatusLabel(section.status) }}
              </span>
              <span v-if="section.items.length > 0" class="text-xs text-gray-500">
                {{ section.items.length }} item(s)
              </span>
            </div>
            <span class="text-gray-500 text-xs transition-transform"
                  :class="expandedSections.has(section.app) ? 'rotate-180' : ''">
              &#9660;
            </span>
          </button>

          <!-- Section Body (collapsible) -->
          <div v-if="expandedSections.has(section.app)" class="border-t border-gray-800">
            <div v-if="section.items.length === 0" class="px-5 py-4 text-sm text-gray-500">
              No compliance issues found.
            </div>
            <table v-else class="w-full text-sm">
              <thead>
                <tr class="text-xs text-gray-500 uppercase border-b border-gray-800">
                  <th class="text-left px-5 py-2 w-20">Severity</th>
                  <th class="text-left px-3 py-2 w-32">Type</th>
                  <th class="text-left px-3 py-2">Description</th>
                  <th class="text-left px-3 py-2 w-40">Timestamp</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(item, idx) in section.items" :key="idx"
                    class="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                  <td class="px-5 py-2">
                    <span class="text-xs font-semibold uppercase"
                          :class="severityColor(item.severity)">
                      {{ item.severity }}
                    </span>
                  </td>
                  <td class="px-3 py-2 text-gray-400 text-xs">{{ item.type }}</td>
                  <td class="px-3 py-2 text-gray-300 text-xs">{{ item.description }}</td>
                  <td class="px-3 py-2 text-gray-500 text-xs">{{ formatDate(item.timestamp) }}</td>
                </tr>
              </tbody>
            </table>
            <div class="px-5 py-3 text-xs text-gray-500 border-t border-gray-800">
              {{ section.summary }}
            </div>
          </div>
        </div>
      </div>

      <!-- No snapshot yet -->
      <div v-if="!currentSnapshot && history.length === 0" class="text-center py-20">
        <div class="text-gray-600 text-sm mb-4">No regulatory snapshots generated yet.</div>
        <button class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded-lg transition-colors"
                @click="generate">
          Generate First Snapshot
        </button>
      </div>

      <!-- Snapshot History -->
      <div v-if="history.length > 0" class="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <h3 class="text-sm font-medium text-gray-400 px-5 pt-4 pb-2">Snapshot History</h3>
        <table class="w-full text-sm">
          <thead>
            <tr class="text-xs text-gray-500 uppercase border-b border-gray-800">
              <th class="text-left px-5 py-2">ID</th>
              <th class="text-left px-3 py-2">Generated</th>
              <th class="text-left px-3 py-2">Period</th>
              <th class="text-left px-3 py-2">Status</th>
              <th class="text-right px-3 py-2">Critical</th>
              <th class="text-right px-3 py-2">Warnings</th>
              <th class="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="snap in history" :key="snap.id"
                class="border-b border-gray-800/50 hover:bg-gray-800/30 cursor-pointer transition-colors"
                @click="loadSnapshot(snap.id)">
              <td class="px-5 py-2.5 font-mono text-xs text-gray-400">{{ snap.id.slice(0, 16) }}</td>
              <td class="px-3 py-2.5 text-gray-300 text-xs">{{ formatDate(snap.generatedAt) }}</td>
              <td class="px-3 py-2.5 text-gray-500 text-xs">
                {{ formatDate(snap.period.from) }} &mdash; {{ formatDate(snap.period.to) }}
              </td>
              <td class="px-3 py-2.5">
                <span class="text-xs font-semibold"
                      :class="overallStatusColor(snap.summary.overallStatus)">
                  {{ snap.summary.overallStatus.replace('_', ' ').toUpperCase() }}
                </span>
              </td>
              <td class="text-right px-3 py-2.5 text-xs"
                  :class="snap.summary.criticalItems > 0 ? 'text-red-400' : 'text-gray-500'">
                {{ snap.summary.criticalItems }}
              </td>
              <td class="text-right px-3 py-2.5 text-xs"
                  :class="snap.summary.warningItems > 0 ? 'text-yellow-400' : 'text-gray-500'">
                {{ snap.summary.warningItems }}
              </td>
              <td class="px-3 py-2.5 text-right">
                <span class="text-indigo-400 text-xs hover:underline">View</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

interface SnapshotItem {
  type: string
  severity: 'info' | 'warning' | 'critical'
  description: string
  details: any
  timestamp: string
}

interface SnapshotSection {
  title: string
  app: string
  status: 'clean' | 'issues_found' | 'data_unavailable'
  items: SnapshotItem[]
  summary: string
}

interface RegulatorySnapshot {
  id: string
  generatedAt: string
  generatedBy: string
  period: { from: string; to: string }
  sections: SnapshotSection[]
  summary: {
    totalApps: number
    appsWithIssues: number
    criticalItems: number
    warningItems: number
    overallStatus: 'compliant' | 'issues_detected' | 'action_required'
  }
}

type SnapshotMeta = Pick<RegulatorySnapshot, 'id' | 'generatedAt' | 'summary' | 'period'>

const loading = ref(true)
const generating = ref(false)
const currentSnapshot = ref<RegulatorySnapshot | null>(null)
const history = ref<SnapshotMeta[]>([])
const expandedSections = ref(new Set<string>())

// Default period: last 30 days
const now = new Date()
const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000)
const dateFrom = ref(thirtyDaysAgo.toISOString().slice(0, 10))
const dateTo = ref(now.toISOString().slice(0, 10))

// Status banner styling
const statusBannerClass = computed(() => {
  if (!currentSnapshot.value) return ''
  switch (currentSnapshot.value.summary.overallStatus) {
    case 'compliant': return 'bg-green-950/30 border-green-800/50'
    case 'issues_detected': return 'bg-yellow-950/30 border-yellow-800/50'
    case 'action_required': return 'bg-red-950/30 border-red-800/50'
  }
})

const statusTextClass = computed(() => {
  if (!currentSnapshot.value) return ''
  switch (currentSnapshot.value.summary.overallStatus) {
    case 'compliant': return 'text-green-400'
    case 'issues_detected': return 'text-yellow-400'
    case 'action_required': return 'text-red-400'
  }
})

const statusLabel = computed(() => {
  if (!currentSnapshot.value) return ''
  switch (currentSnapshot.value.summary.overallStatus) {
    case 'compliant': return 'Compliant'
    case 'issues_detected': return 'Issues Detected'
    case 'action_required': return 'Action Required'
  }
})

const statusIcon = computed(() => {
  if (!currentSnapshot.value) return ''
  switch (currentSnapshot.value.summary.overallStatus) {
    case 'compliant': return '✓'
    case 'issues_detected': return '⚠'
    case 'action_required': return '✗'
  }
})

function sectionDotColor(status: string) {
  switch (status) {
    case 'clean': return 'bg-green-500'
    case 'issues_found': return 'bg-yellow-500'
    case 'data_unavailable': return 'bg-gray-500'
    default: return 'bg-gray-500'
  }
}

function sectionBadgeClass(status: string) {
  switch (status) {
    case 'clean': return 'bg-green-900/50 text-green-400'
    case 'issues_found': return 'bg-yellow-900/50 text-yellow-400'
    case 'data_unavailable': return 'bg-gray-800 text-gray-500'
    default: return 'bg-gray-800 text-gray-500'
  }
}

function sectionStatusLabel(status: string) {
  switch (status) {
    case 'clean': return 'Clean'
    case 'issues_found': return 'Issues Found'
    case 'data_unavailable': return 'Unavailable'
    default: return status
  }
}

function severityColor(severity: string) {
  switch (severity) {
    case 'critical': return 'text-red-400'
    case 'warning': return 'text-yellow-400'
    case 'info': return 'text-gray-400'
    default: return 'text-gray-400'
  }
}

function overallStatusColor(status: string) {
  switch (status) {
    case 'compliant': return 'text-green-400'
    case 'issues_detected': return 'text-yellow-400'
    case 'action_required': return 'text-red-400'
    default: return 'text-gray-400'
  }
}

function toggleSection(app: string) {
  if (expandedSections.value.has(app)) {
    expandedSections.value.delete(app)
  } else {
    expandedSections.value.add(app)
  }
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

// Data loading
async function loadHistory() {
  try {
    const data = await $fetch<{ snapshots: SnapshotMeta[] }>('/api/admin/regulatory')
    history.value = data.snapshots || []
  } catch {
    history.value = []
  }
}

async function generate() {
  generating.value = true
  try {
    const snapshot = await $fetch<RegulatorySnapshot>('/api/admin/regulatory/generate', {
      method: 'POST',
      body: { from: dateFrom.value, to: dateTo.value },
    })
    currentSnapshot.value = snapshot
    // Expand sections with issues by default
    expandedSections.value = new Set(
      snapshot.sections.filter(s => s.status === 'issues_found').map(s => s.app)
    )
    await loadHistory()
  } catch (err) {
    console.error('Snapshot generation failed:', err)
  } finally {
    generating.value = false
  }
}

async function loadSnapshot(id: string) {
  loading.value = true
  try {
    const snapshot = await $fetch<RegulatorySnapshot>(`/api/admin/regulatory/${id}`)
    currentSnapshot.value = snapshot
    expandedSections.value = new Set(
      snapshot.sections.filter(s => s.status === 'issues_found').map(s => s.app)
    )
  } catch (err) {
    console.error('Failed to load snapshot:', err)
  } finally {
    loading.value = false
  }
}

function exportReport() {
  if (!currentSnapshot.value) return
  window.open(`/api/admin/regulatory/export?id=${currentSnapshot.value.id}`, '_blank')
}

onMounted(async () => {
  await loadHistory()
  loading.value = false
})
</script>
