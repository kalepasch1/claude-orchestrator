<template>
  <div class="cascade-monitor p-3">
    <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
      Cascade Operations
    </h3>

    <div v-if="cascades.length === 0" class="text-slate-600 text-xs py-4 text-center">
      No active cascades
    </div>

    <div
      v-for="cascade in cascades"
      :key="cascade.id"
      class="cascade-card mb-2 p-2.5 rounded-lg border cursor-pointer transition-colors"
      :class="cascade.id === selectedCascade ? 'border-emerald-600 bg-slate-800/60' : 'border-slate-800 bg-slate-900/40 hover:border-slate-700'"
      @click="$emit('select', cascade.id)"
    >
      <div class="flex items-center justify-between mb-1.5">
        <span class="text-xs font-medium text-slate-200 truncate">{{ cascade.name }}</span>
        <CascadeStatusBadge :status="cascade.status" />
      </div>

      <div class="flex items-center gap-2 text-xs text-slate-500">
        <span>{{ cascade.completedSteps }}/{{ cascade.totalSteps }} steps</span>
        <span class="text-slate-700">|</span>
        <span>{{ cascade.activeAgents }} agents</span>
      </div>

      <!-- Progress bar -->
      <div class="mt-2 h-1 bg-slate-800 rounded-full overflow-hidden">
        <div
          class="h-full rounded-full transition-all duration-500"
          :class="progressColor(cascade.status)"
          :style="{ width: progressPct(cascade) + '%' }"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import CascadeStatusBadge from './CascadeStatusBadge.vue'

export interface Cascade {
  id: string
  name: string
  status: 'running' | 'paused' | 'completed' | 'failed' | 'queued'
  completedSteps: number
  totalSteps: number
  activeAgents: number
}

defineProps<{
  cascades: Cascade[]
  selectedCascade: string | null
}>()

defineEmits<{
  select: [id: string]
}>()

function progressPct(c: Cascade): number {
  return c.totalSteps > 0 ? Math.round((c.completedSteps / c.totalSteps) * 100) : 0
}

function progressColor(status: string): string {
  const map: Record<string, string> = {
    running: 'bg-emerald-500',
    paused: 'bg-amber-500',
    completed: 'bg-blue-500',
    failed: 'bg-red-500',
    queued: 'bg-slate-600'
  }
  return map[status] || 'bg-slate-600'
}
</script>
