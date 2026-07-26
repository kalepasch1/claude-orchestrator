<template>
  <div class="suggestions">
    <div class="suggestions__header">
      <span class="suggestions__title">Suggestions</span>
      <span v-if="suggestions.length" class="suggestions__count">{{ suggestions.length }}</span>
    </div>
    <div v-if="!suggestions.length" class="suggestions__empty">Suggestions appear after tasks complete</div>
    <div v-else class="suggestions__list">
      <div v-for="(s, i) in suggestions" :key="s.id ?? i" class="suggestion" :class="impactClass(s.impact)">
        <div class="suggestion__rank">#{{ i + 1 }}</div>
        <div class="suggestion__body">
          <div class="suggestion__title">{{ s.title }}</div>
          <div v-if="s.description" class="suggestion__desc">{{ s.description }}</div>
          <div class="suggestion__meta">
            <span class="suggestion__tag" :class="impactTagClass(s.impact)">{{ s.impact }}</span>
            <span v-if="s.effort" class="suggestion__tag suggestion__tag--neutral">{{ s.effort }}</span>
            <span v-if="s.category" class="suggestion__tag suggestion__tag--dim">{{ s.category }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
export interface Suggestion {
  id?: string
  title: string
  description?: string
  impact: 'HIGH' | 'MEDIUM' | 'LOW' | string
  effort?: string
  category?: string
}

defineProps<{ suggestions: Suggestion[] }>()

function impactClass(impact: string) {
  const i = impact?.toUpperCase()
  return i === 'HIGH' ? 'suggestion--high' : i === 'MEDIUM' ? 'suggestion--medium' : 'suggestion--low'
}
function impactTagClass(impact: string) {
  const i = impact?.toUpperCase()
  return i === 'HIGH' ? 'suggestion__tag--high' : i === 'MEDIUM' ? 'suggestion__tag--medium' : 'suggestion__tag--low'
}
</script>

<style scoped>
.suggestions { @apply space-y-3; }
.suggestions__header { @apply flex items-center gap-2; }
.suggestions__title { @apply text-xs font-mono uppercase tracking-widest text-slate-400; }
.suggestions__count { @apply text-xs font-mono bg-white/10 text-slate-300 px-1.5 py-0.5 rounded-full; }
.suggestions__empty { @apply text-sm text-slate-600 italic; }
.suggestions__list { @apply space-y-2; }
.suggestion { @apply flex gap-3 p-3 rounded-lg border border-white/5 bg-white/3; }
.suggestion--high { @apply border-emerald-500/20 bg-emerald-500/5; }
.suggestion--medium { @apply border-yellow-500/20 bg-yellow-500/5; }
.suggestion__rank { @apply text-xs font-mono text-slate-500 pt-0.5 shrink-0; }
.suggestion__body { @apply flex-1 space-y-1.5; }
.suggestion__title { @apply text-sm text-slate-200; }
.suggestion__desc { @apply text-xs text-slate-400 leading-relaxed; }
.suggestion__meta { @apply flex items-center gap-1.5 flex-wrap; }
.suggestion__tag { @apply text-xs px-1.5 py-0.5 rounded font-mono; }
.suggestion__tag--high { @apply bg-emerald-900/60 text-emerald-300; }
.suggestion__tag--medium { @apply bg-yellow-900/60 text-yellow-300; }
.suggestion__tag--low { @apply bg-slate-800 text-slate-400; }
.suggestion__tag--neutral { @apply bg-blue-900/40 text-blue-300; }
.suggestion__tag--dim { @apply bg-white/5 text-slate-500; }
</style>
