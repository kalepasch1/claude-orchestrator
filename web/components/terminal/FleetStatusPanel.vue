<template>
  <div class="fleet-status p-3">
    <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
      Fleet Status
    </h3>

    <!-- Deployment Section -->
    <div class="mb-4">
      <h4 class="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
        Deployments
      </h4>
      <div
        v-for="dep in deployments"
        :key="dep.project"
        class="flex items-center justify-between py-1.5 px-2 rounded hover:bg-slate-800/40"
      >
        <div class="flex items-center gap-2">
          <span
            class="w-1.5 h-1.5 rounded-full"
            :class="deployStatusColor(dep.status)"
          />
          <span class="text-xs text-slate-300">{{ dep.project }}</span>
        </div>
        <span class="text-[10px] text-slate-500">{{ dep.version }}</span>
      </div>
      <div v-if="deployments.length === 0" class="text-slate-600 text-xs py-2 text-center">
        No deployments
      </div>
    </div>

    <!-- Active Agents -->
    <div>
      <h4 class="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
        Active Agents ({{ agents.length }})
      </h4>
      <div
        v-for="agent in agents"
        :key="agent.id"
        class="mb-2 p-2 rounded-lg bg-slate-900/50 border border-slate-800"
      >
        <div class="flex items-center justify-between mb-1">
          <span class="text-xs text-slate-300 font-medium truncate">{{ agent.name }}</span>
          <span
            class="text-[10px] px-1.5 py-0.5 rounded font-medium"
            :class="agentStatusClass(agent.status)"
          >{{ agent.status }}</span>
        </div>
        <div class="text-[10px] text-slate-500 truncate">{{ agent.currentTask }}</div>
        <div class="mt-1 flex items-center gap-2 text-[10px] text-slate-600">
          <span>CPU: {{ agent.cpuPct }}%</span>
          <span>MEM: {{ agent.memMb }}MB</span>
        </div>
      </div>
      <div v-if="agents.length === 0" class="text-slate-600 text-xs py-2 text-center">
        No active agents
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
export interface Agent {
  id: string
  name: string
  status: 'active' | 'idle' | 'error' | 'stopping'
  currentTask: string
  cpuPct: number
  memMb: number
}

export interface Deployment {
  project: string
  status: 'live' | 'deploying' | 'failed' | 'queued'
  version: string
}

defineProps<{
  agents: Agent[]
  deployments: Deployment[]
}>()

function deployStatusColor(status: string): string {
  const map: Record<string, string> = {
    live: 'bg-emerald-400',
    deploying: 'bg-amber-400 animate-pulse',
    failed: 'bg-red-400',
    queued: 'bg-slate-500'
  }
  return map[status] || 'bg-slate-500'
}

function agentStatusClass(status: string): string {
  const map: Record<string, string> = {
    active: 'bg-emerald-500/20 text-emerald-400',
    idle: 'bg-slate-500/20 text-slate-400',
    error: 'bg-red-500/20 text-red-400',
    stopping: 'bg-amber-500/20 text-amber-400'
  }
  return map[status] || 'bg-slate-500/20 text-slate-400'
}
</script>
