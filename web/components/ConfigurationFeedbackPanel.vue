<script setup lang="ts">
interface FeedbackItem {
  id?: string
  created_at: string
  source?: string
  category?: string
  severity?: string
  observation?: string
  suggestion?: string
  status?: string
}

defineProps<{ items: FeedbackItem[] }>()

function ago(ts: string) {
  const d = Math.round((Date.now() - new Date(ts).getTime()) / 60000)
  return d < 1 ? 'just now' : d < 60 ? `${d}m ago` : d < 1440 ? `${Math.round(d / 60)}h ago` : `${Math.round(d / 1440)}d ago`
}

const severityDot: Record<string, string> = {
  high: 'bg-red-400',
  med: 'bg-amber-400',
  low: 'bg-slate-500',
}
</script>

<template>
  <section class="bg-slate-900 border border-slate-800 rounded-xl p-4 mb-6">
    <div class="flex items-center gap-2 mb-3">
      <h2 class="text-xs uppercase tracking-wider text-slate-500">Configuration feedback — live</h2>
      <span class="relative flex w-2 h-2">
        <span class="motion-safe:animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-50"></span>
        <span class="relative inline-flex w-2 h-2 rounded-full bg-blue-400"></span>
      </span>
      <span class="flex-1"></span>
      <span class="text-xs text-slate-500">{{ items.length }} recent</span>
    </div>

    <div v-if="!items.length" class="text-slate-600 italic text-sm py-2">
      No configuration feedback yet. Submit feedback below or wait for the system to report changes.
    </div>

    <ul v-else class="space-y-2 max-h-72 overflow-y-auto pr-1">
      <li v-for="item in items" :key="item.id || item.created_at"
          class="border border-slate-800 rounded-lg px-3 py-2 hover:border-slate-700 transition-colors">
        <div class="flex items-center gap-2 mb-1 flex-wrap">
          <span class="w-1.5 h-1.5 rounded-full flex-shrink-0"
                :class="severityDot[item.severity || ''] || 'bg-slate-500'"></span>
          <time class="text-[10px] font-mono text-slate-500" :title="item.created_at">
            {{ ago(item.created_at) }}
          </time>
          <span class="text-[10px] font-semibold text-slate-300 bg-slate-800 rounded px-1.5 py-0.5">
            {{ item.source || 'system' }}
          </span>
          <span v-if="item.category"
                class="text-[10px] text-slate-400 bg-slate-800/60 rounded px-1.5 py-0.5">
            {{ item.category }}
          </span>
        </div>
        <p class="text-sm text-slate-300 leading-snug">{{ item.observation || '—' }}</p>
        <p v-if="item.suggestion" class="text-xs text-slate-500 mt-0.5 italic">
          → {{ item.suggestion }}
        </p>
      </li>
    </ul>
  </section>
</template>
