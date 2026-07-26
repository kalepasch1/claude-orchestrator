<template>
  <div class="dev-terminal flex flex-col h-full">
    <!-- Header Bar -->
    <TerminalHeader
      :orchestrator-slug="orchestratorSlug"
      :connection-status="connectionStatus"
      :uptime="uptime"
    />

    <!-- Main Content Area -->
    <div class="flex-1 flex overflow-hidden">
      <!-- Left Panel: Cascade Monitor -->
      <div class="w-1/3 border-r border-slate-800 overflow-y-auto">
        <CascadeMonitor
          :cascades="cascades"
          :selected-cascade="selectedCascade"
          @select="selectedCascade = $event"
        />
      </div>

      <!-- Center Panel: Log Stream -->
      <div class="flex-1 flex flex-col overflow-hidden">
        <LogStream
          :entries="logEntries"
          :filter="logFilter"
          @update:filter="logFilter = $event"
        />
      </div>

      <!-- Right Panel: Fleet Status -->
      <div class="w-1/4 border-l border-slate-800 overflow-y-auto">
        <FleetStatusPanel
          :agents="agents"
          :deployments="deployments"
        />
      </div>
    </div>

    <!-- Bottom Bar: Command Input -->
    <TerminalCommandBar
      @execute="handleCommand"
      :history="commandHistory"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useTerminalConnection } from '~/composables/useTerminalConnection'
import { useTerminalState } from '~/composables/useTerminalState'
import TerminalHeader from '~/components/terminal/TerminalHeader.vue'
import CascadeMonitor from '~/components/terminal/CascadeMonitor.vue'
import LogStream from '~/components/terminal/LogStream.vue'
import FleetStatusPanel from '~/components/terminal/FleetStatusPanel.vue'
import TerminalCommandBar from '~/components/terminal/TerminalCommandBar.vue'

interface Props {
  orchestratorSlug?: string
}

const props = withDefaults(defineProps<Props>(), {
  orchestratorSlug: 'trojun'
})

const {
  connectionStatus,
  uptime,
  connect,
  disconnect,
  sendCommand
} = useTerminalConnection(props.orchestratorSlug)

const {
  cascades,
  selectedCascade,
  logEntries,
  logFilter,
  agents,
  deployments,
  commandHistory,
  refreshState
} = useTerminalState()

async function handleCommand(cmd: string) {
  commandHistory.value.unshift(cmd)
  if (commandHistory.value.length > 100) commandHistory.value.pop()

  const builtins: Record<string, () => void> = {
    clear: () => { logEntries.value = [] },
    refresh: () => refreshState(),
    status: () => addSystemLog('Connection: ' + connectionStatus.value + ' | Uptime: ' + formatUptime(uptime.value)),
    help: () => addSystemLog('Commands: clear, refresh, status, deploy <target>, cascade <id>, help')
  }

  const [base, ...rest] = cmd.trim().split(/\s+/)
  if (builtins[base]) {
    builtins[base]()
  } else {
    try {
      const result = await sendCommand(cmd)
      addSystemLog(result || `Executed: ${cmd}`)
    } catch (e: any) {
      addSystemLog(`Error: ${e.message}`, 'error')
    }
  }
}

function addSystemLog(message: string, level: 'info' | 'warn' | 'error' = 'info') {
  logEntries.value.push({
    id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
    level,
    source: 'terminal',
    message
  })
}

function formatUptime(ms: number): string {
  const s = Math.floor(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return `${h}h ${m}m`
}

onMounted(() => {
  connect()
  refreshState()
})

onUnmounted(() => {
  disconnect()
})
</script>

<style scoped lang="postcss">
.dev-terminal {
  @apply bg-slate-950 text-slate-200 font-mono text-sm;
}
</style>
