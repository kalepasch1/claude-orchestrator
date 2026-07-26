<template>
  <div class="log-stream flex flex-col h-full">
    <!-- Filter Bar -->
    <div class="flex items-center gap-2 px-3 py-2 bg-slate-900/60 border-b border-slate-800">
      <input
        type="text"
        :value="filter"
        @input="$emit('update:filter', ($event.target as HTMLInputElement).value)"
        placeholder="Filter logs..."
        class="flex-1 bg-slate-800/50 border border-slate-700 rounded px-2 py-1 text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-emerald-600"
      />
      <button
        v-for="level in levels"
        :key="level"
        class="px-2 py-1 text-[10px] rounded font-medium uppercase tracking-wider transition-colors"
        :class="activeLevel === level ? activeLevelClass(level) : 'text-slate-500 hover:text-slate-400'"
        @click="activeLevel = activeLevel === level ? null : level"
      >
        {{ level }}
      </button>
    </div>

    <!-- Log Entries -->
    <div ref="logContainer" class="flex-1 overflow-y-auto p-3 space-y-0.5">
      <div
        v-for="entry in filteredEntries"
        :key="entry.id"
        class="log-entry flex items-start gap-2 py-0.5 font-mono text-xs leading-relaxed hover:bg-slate-900/40 px-1 rounded"
      >
        <span class="text-slate-600 shrink-0 w-20">{{ formatTime(entry.timestamp) }}</span>
        <span
          class="shrink-0 w-12 uppercase font-semibold"
          :class="levelColor(entry.level)"
        >{{ entry.level }}</span>
        <span class="text-slate-500 shrink-0">[{{ entry.source }}]</span>
        <span class="text-slate-300">{{ entry.message }}</span>
      </div>

      <div v-if="filteredEntries.length === 0" class="text-slate-600 text-xs py-8 text-center">
        No log entries{{ filter ? ' matching filter' : '' }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'

export interface LogEntry {
  id: string
  timestamp: string
  level: 'info' | 'warn' | 'error' | 'debug'
  source: string
  message: string
}

const props = defineProps<{
  entries: LogEntry[]
  filter: string
}>()

defineEmits<{
  'update:filter': [value: string]
}>()

const levels = ['info', 'warn', 'error', 'debug'] as const
const activeLevel = ref<string | null>(null)
const logContainer = ref<HTMLElement>()

const filteredEntries = computed(() => {
  return props.entries.filter(e => {
    if (activeLevel.value && e.level !== activeLevel.value) return false
    if (props.filter && !e.message.toLowerCase().includes(props.filter.toLowerCase())) return false
    return true
  })
})

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString('en-US', { hour12: false })
  } catch {
    return ts.slice(11, 19)
  }
}

function levelColor(level: string): string {
  const map: Record<string, string> = {
    info: 'text-blue-400',
    warn: 'text-amber-400',
    error: 'text-red-400',
    debug: 'text-slate-500'
  }
  return map[level] || 'text-slate-500'
}

function activeLevelClass(level: string): string {
  const map: Record<string, string> = {
    info: 'bg-blue-500/20 text-blue-400',
    warn: 'bg-amber-500/20 text-amber-400',
    error: 'bg-red-500/20 text-red-400',
    debug: 'bg-slate-500/20 text-slate-400'
  }
  return map[level] || 'bg-slate-500/20 text-slate-400'
}

// Auto-scroll to bottom on new entries
watch(() => props.entries.length, async () => {
  await nextTick()
  if (logContainer.value) {
    logContainer.value.scrollTop = logContainer.value.scrollHeight
  }
})
</script>
