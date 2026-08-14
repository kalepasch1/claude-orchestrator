<script setup lang="ts">
const props = defineProps<{ dbUp: boolean | null }>()

const label = computed(() => props.dbUp === null
  ? '…'
  : props.dbUp ? 'Fleet healthy' : 'Fleet down')
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium"
    :class="dbUp === null
      ? 'border-slate-700 bg-slate-800/70 text-slate-400'
      : dbUp
        ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
        : 'border-red-500/30 bg-red-500/10 text-red-300'"
    role="status"
    aria-live="polite"
  >
    <span
      aria-hidden="true"
      class="h-1.5 w-1.5 rounded-full"
      :class="dbUp === null ? 'bg-slate-500' : dbUp ? 'bg-emerald-400' : 'bg-red-400'"
    />
    {{ label }}
  </span>
</template>
