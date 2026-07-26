<template>
  <div class="cascade-indicator">
    <div class="cascade-indicator__header">
      <span class="cascade-indicator__label">Cascade Confidence</span>
      <span class="cascade-indicator__value" :class="valueClass">{{ displayValue }}%</span>
    </div>
    <div class="cascade-indicator__bar-track">
      <div class="cascade-indicator__bar-fill" :class="fillClass" :style="{ width: `${clampedValue}%` }" />
    </div>
    <div v-if="model" class="cascade-indicator__model">
      <span class="cascade-indicator__model-label">routing via</span>
      <span class="cascade-indicator__model-value">{{ model }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{
  confidence: number
  model?: string | null
}>()

const clampedValue = computed(() => Math.min(100, Math.max(0, Math.round((props.confidence ?? 0) * 100))))
const displayValue = computed(() => clampedValue.value)
const valueClass = computed(() => clampedValue.value >= 80 ? 'text-emerald-400' : clampedValue.value >= 60 ? 'text-yellow-400' : 'text-red-400')
const fillClass = computed(() => clampedValue.value >= 80 ? 'bg-emerald-500' : clampedValue.value >= 60 ? 'bg-yellow-500' : 'bg-red-500')
</script>

<style scoped>
.cascade-indicator { @apply space-y-1.5; }
.cascade-indicator__header { @apply flex items-center justify-between; }
.cascade-indicator__label { @apply text-xs text-slate-400 uppercase tracking-wide font-mono; }
.cascade-indicator__value { @apply text-sm font-mono font-bold tabular-nums; }
.cascade-indicator__bar-track { @apply w-full h-1.5 rounded-full bg-white/10 overflow-hidden; }
.cascade-indicator__bar-fill { @apply h-full rounded-full transition-all duration-500 ease-out; }
.cascade-indicator__model { @apply flex items-center gap-1.5 text-xs; }
.cascade-indicator__model-label { @apply text-slate-500; }
.cascade-indicator__model-value { @apply text-slate-300 font-mono; }
</style>
