<script setup lang="ts">
import type { FleetHealth } from '~/types/fleet-health'

const props = defineProps<{ health: FleetHealth | null }>()

const status = computed(() => props.health?.status ?? null)
const label = computed(() => status.value === null
  ? '…'
  : status.value === 'healthy'
    ? `Fleet healthy · ${props.health?.machines_live ?? 0} Mac${props.health?.machines_live === 1 ? '' : 's'}`
    : status.value === 'degraded'
      ? 'Fleet degraded · runner mismatch'
      : status.value === 'unknown' ? 'Fleet unknown' : 'Fleet down')
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium"
    :class="status === null
      ? 'border-slate-700 bg-slate-800/70 text-slate-400'
      : status === 'healthy'
        ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
        : status === 'degraded' || status === 'unknown'
          ? 'border-amber-500/30 bg-amber-500/10 text-amber-300'
          : 'border-red-500/30 bg-red-500/10 text-red-300'"
    role="status"
    aria-live="polite"
  >
    <span
      aria-hidden="true"
      class="h-1.5 w-1.5 rounded-full"
      :class="status === null ? 'bg-slate-500' : status === 'healthy' ? 'bg-emerald-400' : status === 'degraded' || status === 'unknown' ? 'bg-amber-400' : 'bg-red-400'"
    />
    {{ label }}
  </span>
</template>
