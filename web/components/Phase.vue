<template>
  <div class="phase" :class="phaseClass">
    <div class="phase__header">
      <div class="phase__indicator">
        <div v-if="status === 'active'" class="phase__dot phase__dot--pulse" />
        <div v-else-if="status === 'done'" class="phase__dot phase__dot--done" />
        <div v-else class="phase__dot phase__dot--idle" />
      </div>
      <div class="phase__meta">
        <span class="phase__mark">{{ mark }}</span>
        <span class="phase__name">{{ name }}</span>
      </div>
      <span class="phase__status-label">{{ statusLabel }}</span>
    </div>
    <div v-if="$slots.default && status !== 'idle'" class="phase__body">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{
  mark: string
  name: string
  status: 'idle' | 'active' | 'done' | 'error'
}>()

const statusLabel = computed(() => {
  switch (props.status) {
    case 'active': return 'running'
    case 'done': return 'complete'
    case 'error': return 'error'
    default: return 'waiting'
  }
})

const phaseClass = computed(() => ({
  'phase--idle': props.status === 'idle',
  'phase--active': props.status === 'active',
  'phase--done': props.status === 'done',
  'phase--error': props.status === 'error',
}))
</script>

<style scoped>
.phase { @apply rounded-xl border border-white/10 p-4 space-y-3 transition-all duration-300; }
.phase--idle { @apply opacity-40; }
.phase--active { @apply border-blue-500/40 bg-blue-500/5; }
.phase--done { @apply border-emerald-500/30 bg-emerald-500/5; }
.phase--error { @apply border-red-500/30 bg-red-500/5; }
.phase__header { @apply flex items-center gap-3; }
.phase__indicator { @apply flex items-center justify-center w-6 h-6; }
.phase__dot { @apply w-2.5 h-2.5 rounded-full; }
.phase__dot--pulse { @apply bg-blue-400 animate-pulse; }
.phase__dot--done { @apply bg-emerald-400; }
.phase__dot--idle { @apply bg-slate-600; }
.phase__meta { @apply flex items-center gap-2 flex-1; }
.phase__mark { @apply text-xs font-mono text-slate-500; }
.phase__name { @apply text-sm font-semibold text-slate-200 tracking-wide; }
.phase__status-label { @apply text-xs font-mono text-slate-500 uppercase tracking-widest; }
.phase__body { @apply pl-9 space-y-2; }
</style>
