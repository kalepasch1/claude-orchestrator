<template>
  <div class="cost-panel">
    <div class="cost-panel__header">
      <span class="cost-panel__title">Cost Analysis</span>
      <span class="cost-panel__total">${{ totalFormatted }}</span>
    </div>
    <div class="cost-panel__metrics">
      <MetricRow label="Cascade savings" :value="savesPercent" format="percent" color-scale="green" />
      <MetricRow label="Completed tasks" :value="completedCount" format="number" />
      <MetricRow label="Avg cost/task" :value="avgCost" format="currency" />
      <MetricRow label="Cheap model rate" :value="cheapModelRate" format="percent" color-scale="green" />
    </div>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{
  totalCostUsd: number
  completedCount: number
  savesPercent: number
  cheapModelRate: number
}>()

const totalFormatted = computed(() => {
  const v = props.totalCostUsd ?? 0
  return v < 0.01 ? v.toFixed(6) : v.toFixed(4)
})

const avgCost = computed(() => {
  if (!props.completedCount) return 0
  return (props.totalCostUsd ?? 0) / props.completedCount
})
</script>

<style scoped>
.cost-panel { @apply space-y-3; }
.cost-panel__header { @apply flex items-center justify-between; }
.cost-panel__title { @apply text-xs font-mono uppercase tracking-widest text-slate-400; }
.cost-panel__total { @apply text-sm font-mono font-semibold text-slate-200 tabular-nums; }
.cost-panel__metrics { @apply space-y-1; }
</style>
