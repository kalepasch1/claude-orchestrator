<template>
  <header class="terminal-header flex items-center justify-between px-4 py-2 bg-slate-900 border-b border-slate-800">
    <div class="flex items-center gap-3">
      <div class="flex items-center gap-2">
        <span class="text-emerald-400 font-bold text-base tracking-wide">TROJUN</span>
        <span class="text-slate-500 text-xs">Development Terminal</span>
      </div>
      <span class="text-slate-600">|</span>
      <span class="text-xs text-slate-400">{{ orchestratorSlug }}</span>
    </div>

    <div class="flex items-center gap-4">
      <div class="flex items-center gap-1.5">
        <span
          class="w-2 h-2 rounded-full"
          :class="statusColor"
        />
        <span class="text-xs text-slate-400">{{ connectionStatus }}</span>
      </div>
      <span class="text-xs text-slate-500">
        Uptime: {{ formatUptime(uptime) }}
      </span>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  orchestratorSlug: string
  connectionStatus: string
  uptime: number
}>()

const statusColor = computed(() => ({
  'bg-emerald-400': props.connectionStatus === 'connected',
  'bg-amber-400': props.connectionStatus === 'connecting',
  'bg-red-400': props.connectionStatus === 'disconnected'
}))

function formatUptime(ms: number): string {
  const s = Math.floor(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return `${h}h ${m}m ${s % 60}s`
}
</script>
