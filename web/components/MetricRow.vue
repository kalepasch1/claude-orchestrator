<template>
  <div class="metric-row" :class="{ 'metric-row--highlight': highlight }">
    <span class="metric-row__label">{{ label }}</span>
    <span class="metric-row__value" :class="valueClass">{{ formattedValue }}</span>
    <span v-if="unit" class="metric-row__unit">{{ unit }}</span>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{
  label: string
  value: number | string | null
  unit?: string
  format?: 'number' | 'percent' | 'currency' | 'ms' | 'raw'
  highlight?: boolean
  colorScale?: 'green' | 'red' | 'neutral'
}>()

const formattedValue = computed(() => {
  if (props.value === null || props.value === undefined) return '—'
  const v = props.value
  if (typeof v === 'string') return v
  switch (props.format) {
    case 'percent': return `${Math.round(v)}%`
    case 'currency': return `$${v.toFixed(4)}`
    case 'ms': return `${v}ms`
    case 'number': return v.toLocaleString()
    default: return String(v)
  }
})

const valueClass = computed(() => {
  if (!props.colorScale || props.value === null) return 'text-slate-200'
  const v = typeof props.value === 'number' ? props.value : 0
  if (props.colorScale === 'green') {
    if (v >= 80) return 'text-emerald-400'
    if (v >= 50) return 'text-yellow-400'
    return 'text-red-400'
  }
  if (props.colorScale === 'red') {
    if (v === 0) return 'text-emerald-400'
    if (v <= 2) return 'text-yellow-400'
    return 'text-red-400'
  }
  return 'text-slate-200'
})
</script>

<style scoped>
.metric-row {
  @apply flex items-center gap-2 py-1 px-2 rounded text-sm;
}
.metric-row--highlight {
  @apply bg-white/5;
}
.metric-row__label {
  @apply text-slate-400 flex-1 font-mono text-xs uppercase tracking-wide;
}
.metric-row__value {
  @apply font-mono font-semibold tabular-nums;
}
.metric-row__unit {
  @apply text-slate-500 text-xs;
}
</style>
