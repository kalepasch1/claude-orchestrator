<template>
  <span
    class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wider"
    :class="badgeClass"
  >
    {{ status }}
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  status: string
}>()

const badgeClass = computed(() => {
  const map: Record<string, string> = {
    running: 'bg-emerald-500/20 text-emerald-400',
    paused: 'bg-amber-500/20 text-amber-400',
    completed: 'bg-blue-500/20 text-blue-400',
    failed: 'bg-red-500/20 text-red-400',
    queued: 'bg-slate-500/20 text-slate-400'
  }
  return map[props.status] || 'bg-slate-500/20 text-slate-400'
})
</script>
