<template>
  <div class="fleet-map">
    <div class="fleet-map__header">
      <span class="fleet-map__title">Fleet</span>
      <div class="fleet-map__status">
        <span class="fleet-map__dot" :class="healthClass" />
        <span class="fleet-map__health-label">{{ healthLabel }}</span>
      </div>
    </div>
    <div class="fleet-map__nodes">
      <div v-for="node in nodes" :key="node.id" class="fleet-node" :class="nodeClass(node)">
        <div class="fleet-node__header">
          <span class="fleet-node__name">{{ node.label }}</span>
          <span class="fleet-node__state" :class="stateClass(node.state)">{{ node.state }}</span>
        </div>
        <div v-if="node.running !== undefined" class="fleet-node__metrics">
          <MetricRow label="running" :value="node.running" format="number" />
          <MetricRow v-if="node.queued !== undefined" label="queued" :value="node.queued" format="number" />
        </div>
      </div>
    </div>
    <div v-if="!nodes.length" class="fleet-map__empty">No fleet nodes discovered</div>
  </div>
</template>

<script setup lang="ts">
export interface FleetNode {
  id: string
  label: string
  state: string
  running?: number
  queued?: number
}

const props = defineProps<{
  nodes?: FleetNode[]
  snapshot?: { total_running: number; total_queued: number; total_blocked: number; queue_states: Record<string, number> }
}>()

const nodes = computed<FleetNode[]>(() => {
  if (props.nodes?.length) return props.nodes
  if (!props.snapshot) return []
  const s = props.snapshot
  return [{ id: 'orchestrator', label: 'Orchestrator', state: s.total_running > 0 ? 'healthy' : 'idle', running: s.total_running, queued: s.total_queued }]
})

const overallHealth = computed(() => {
  if (!nodes.value.length) return 'unknown'
  return nodes.value.some(n => n.state === 'down') ? 'down' : nodes.value.some(n => n.state === 'degraded') ? 'degraded' : 'healthy'
})

const healthClass = computed(() => ({
  'bg-emerald-400': overallHealth.value === 'healthy',
  'bg-yellow-400': overallHealth.value === 'degraded',
  'bg-red-400': overallHealth.value === 'down',
  'bg-slate-500': overallHealth.value === 'unknown',
}))
const healthLabel = computed(() => overallHealth.value)

function nodeClass(node: FleetNode) {
  return { 'fleet-node--healthy': node.state === 'healthy', 'fleet-node--idle': node.state === 'idle', 'fleet-node--down': node.state === 'down' }
}
function stateClass(state: string) {
  return state === 'healthy' ? 'text-emerald-400' : state === 'degraded' ? 'text-yellow-400' : state === 'down' ? 'text-red-400' : 'text-slate-500'
}
</script>

<style scoped>
.fleet-map { @apply space-y-3; }
.fleet-map__header { @apply flex items-center justify-between; }
.fleet-map__title { @apply text-xs font-mono uppercase tracking-widest text-slate-400; }
.fleet-map__status { @apply flex items-center gap-1.5; }
.fleet-map__dot { @apply w-2 h-2 rounded-full; }
.fleet-map__health-label { @apply text-xs font-mono text-slate-400; }
.fleet-map__nodes { @apply grid grid-cols-2 gap-2; }
.fleet-map__empty { @apply text-sm text-slate-600 italic; }
.fleet-node { @apply p-2.5 rounded-lg border border-white/5 space-y-2; }
.fleet-node--healthy { @apply border-emerald-500/20; }
.fleet-node--idle { @apply opacity-60; }
.fleet-node--down { @apply border-red-500/20; }
.fleet-node__header { @apply flex items-center justify-between; }
.fleet-node__name { @apply text-xs font-mono text-slate-300; }
.fleet-node__state { @apply text-xs font-mono; }
.fleet-node__metrics { @apply space-y-0.5; }
</style>
