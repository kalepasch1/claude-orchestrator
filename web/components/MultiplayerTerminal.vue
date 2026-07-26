<template>
  <div class="multiplayer-terminal">
    <div class="terminal-header">
      MULTIPLAYER HIVEMIND
      <span class="status-dot" :class="connected ? 'connected' : 'disconnected'" />
      <span class="status-text">{{ connected ? 'LIVE' : 'OFFLINE' }}</span>
    </div>
    <div class="terminal-grid">
      <div class="grid-cell">
        <DiscoveryBusFeed :entries="discoveryEntries" :stats="discoveryStats" />
      </div>
      <div class="grid-cell">
        <HivemindMemoryPanel :patterns="hivemindPatterns" :stats="hivemindStats" />
      </div>
      <div class="grid-cell">
        <ComplianceRiskPanel :risks="complianceRisks" :stats="complianceStats" />
      </div>
      <div class="grid-cell">
        <ConflictMapViz :locks="conflictLocks" :stats="conflictStats" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import DiscoveryBusFeed from './DiscoveryBusFeed.vue'
import HivemindMemoryPanel from './HivemindMemoryPanel.vue'
import ComplianceRiskPanel from './ComplianceRiskPanel.vue'
import ConflictMapViz from './ConflictMapViz.vue'

const connected = ref(false)
const discoveryEntries = ref<any[]>([])
const discoveryStats = ref<Record<string, any>>({})
const hivemindPatterns = ref<any[]>([])
const hivemindStats = ref<Record<string, any>>({})
const complianceRisks = ref<any[]>([])
const complianceStats = ref<Record<string, any>>({})
const conflictLocks = ref<any[]>([])
const conflictStats = ref<Record<string, any>>({})

let pollInterval: ReturnType<typeof setInterval> | null = null
const CONSOLE_URL = 'http://127.0.0.1:8701'

async function fetchSnapshot() {
  try {
    const res = await fetch(`${CONSOLE_URL}/snapshot`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    connected.value = true

    // Discovery bus
    discoveryStats.value = data.discovery_bus || {}

    // Hivemind
    hivemindStats.value = data.hivemind || {}

    // Compliance
    const compliance = data.compliance || {}
    complianceStats.value = compliance.stats || {}
    complianceRisks.value = compliance.unacknowledged_risks || []

    // Conflicts
    const conflicts = data.conflicts || {}
    conflictStats.value = conflicts.stats || {}
    conflictLocks.value = conflicts.active_locks || []
  } catch {
    connected.value = false
  }
}

onMounted(() => {
  fetchSnapshot()
  pollInterval = setInterval(fetchSnapshot, 10000)
})

onUnmounted(() => {
  if (pollInterval) clearInterval(pollInterval)
})
</script>

<style scoped lang="postcss">
.multiplayer-terminal {
  @apply p-4 bg-slate-900 rounded-lg border border-slate-700;
}

.terminal-header {
  @apply font-bold text-lg text-slate-200 mb-4 flex items-center gap-2 tracking-wider;

  .status-dot {
    @apply inline-block w-2.5 h-2.5 rounded-full ml-auto;

    &.connected {
      @apply bg-emerald-500 animate-pulse;
    }

    &.disconnected {
      @apply bg-red-500;
    }
  }

  .status-text {
    @apply text-xs font-mono;
  }
}

.terminal-grid {
  @apply grid grid-cols-1 md:grid-cols-2 gap-4;

  .grid-cell {
    @apply p-3 bg-slate-850 rounded border border-slate-700;
  }
}
</style>
