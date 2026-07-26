import { ref } from 'vue'
import type { Cascade } from '~/components/terminal/CascadeMonitor.vue'
import type { LogEntry } from '~/components/terminal/LogStream.vue'
import type { Agent, Deployment } from '~/components/terminal/FleetStatusPanel.vue'

export function useTerminalState() {
  const cascades = ref<Cascade[]>([])
  const selectedCascade = ref<string | null>(null)
  const logEntries = ref<LogEntry[]>([])
  const logFilter = ref('')
  const agents = ref<Agent[]>([])
  const deployments = ref<Deployment[]>([])
  const commandHistory = ref<string[]>([])

  async function refreshState() {
    try {
      const [cascadeData, fleetData] = await Promise.all([
        $fetch<{ cascades: Cascade[] }>('/api/terminal/cascades'),
        $fetch<{ agents: Agent[]; deployments: Deployment[] }>('/api/terminal/fleet')
      ])

      cascades.value = cascadeData.cascades
      agents.value = fleetData.agents
      deployments.value = fleetData.deployments

      logEntries.value.push({
        id: crypto.randomUUID(),
        timestamp: new Date().toISOString(),
        level: 'info',
        source: 'system',
        message: `State refreshed: ${cascades.value.length} cascades, ${agents.value.length} agents, ${deployments.value.length} deployments`
      })
    } catch (e: any) {
      logEntries.value.push({
        id: crypto.randomUUID(),
        timestamp: new Date().toISOString(),
        level: 'warn',
        source: 'system',
        message: `State refresh failed: ${e.message}. Using offline mode.`
      })
      // Initialize with demo data for development
      loadDemoState()
    }
  }

  function loadDemoState() {
    cascades.value = [
      {
        id: 'cascade-1',
        name: 'Deploy Pipeline v15',
        status: 'running',
        completedSteps: 7,
        totalSteps: 12,
        activeAgents: 3
      },
      {
        id: 'cascade-2',
        name: 'Migration Batch 2026-07',
        status: 'queued',
        completedSteps: 0,
        totalSteps: 8,
        activeAgents: 0
      }
    ]

    deployments.value = [
      { project: 'trojun', status: 'live', version: 'v15.2.1' },
      { project: 'apparently', status: 'deploying', version: 'v8.4.0' },
      { project: 'smarter', status: 'live', version: 'v6.1.0' },
      { project: 'pareto', status: 'queued', version: 'v3.0.0' },
      { project: 'tomorrow', status: 'live', version: 'v2.8.0' }
    ]

    agents.value = [
      {
        id: 'agent-1',
        name: 'cascade-executor',
        status: 'active',
        currentTask: 'Running deploy pipeline step 8/12',
        cpuPct: 34,
        memMb: 256
      },
      {
        id: 'agent-2',
        name: 'health-monitor',
        status: 'idle',
        currentTask: 'Awaiting next health check cycle',
        cpuPct: 2,
        memMb: 64
      }
    ]
  }

  return {
    cascades,
    selectedCascade,
    logEntries,
    logFilter,
    agents,
    deployments,
    commandHistory,
    refreshState
  }
}
