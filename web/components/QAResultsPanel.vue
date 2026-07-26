<template>
  <div class="qa-panel">
    <div class="qa-panel__header">
      <span class="qa-panel__title">QA Agents</span>
      <div class="qa-panel__summary">
        <span class="qa-panel__pass">{{ passCount }}P</span>
        <span class="qa-panel__sep">/</span>
        <span class="qa-panel__fail">{{ failCount }}F</span>
      </div>
    </div>
    <div class="qa-panel__agents">
      <div v-for="agent in resolvedAgents" :key="agent.id" class="qa-agent" :class="agentClass(agent.verdict)">
        <div class="qa-agent__header">
          <span class="qa-agent__name">{{ agent.name }}</span>
          <span class="qa-agent__verdict" :class="verdictClass(agent.verdict)">{{ agent.verdict ?? '—' }}</span>
        </div>
        <div v-if="agent.issues?.length" class="qa-agent__issues">
          <div v-for="(issue, i) in agent.issues.slice(0, 2)" :key="i" class="qa-agent__issue">{{ issue }}</div>
        </div>
        <div v-if="agent.running" class="qa-agent__running">
          <span class="qa-agent__dot" /><span class="qa-agent__dot qa-agent__dot--delay-1" /><span class="qa-agent__dot qa-agent__dot--delay-2" />
          <span class="qa-agent__running-label">analyzing</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
export interface QAAgent {
  id: string
  name: string
  verdict: 'PASS' | 'FAIL' | 'WARN' | null
  issues?: string[]
  running?: boolean
}

const DEFAULT_AGENTS: QAAgent[] = [
  { id: 'unit', name: 'Unit Tests', verdict: null },
  { id: 'security', name: 'Security', verdict: null },
  { id: 'dead_code', name: 'Dead Code', verdict: null },
  { id: 'performance', name: 'Performance', verdict: null },
]

const props = defineProps<{ agents?: QAAgent[] }>()
const resolvedAgents = computed(() => props.agents?.length ? props.agents : DEFAULT_AGENTS)
const passCount = computed(() => resolvedAgents.value.filter(a => a.verdict === 'PASS').length)
const failCount = computed(() => resolvedAgents.value.filter(a => a.verdict === 'FAIL').length)

function agentClass(verdict: string | null) {
  return { 'qa-agent--pass': verdict === 'PASS', 'qa-agent--fail': verdict === 'FAIL', 'qa-agent--warn': verdict === 'WARN', 'qa-agent--pending': !verdict }
}
function verdictClass(verdict: string | null) {
  return verdict === 'PASS' ? 'text-emerald-400' : verdict === 'FAIL' ? 'text-red-400' : verdict === 'WARN' ? 'text-yellow-400' : 'text-slate-500'
}
</script>

<style scoped>
.qa-panel { @apply space-y-3; }
.qa-panel__header { @apply flex items-center justify-between; }
.qa-panel__title { @apply text-xs font-mono uppercase tracking-widest text-slate-400; }
.qa-panel__summary { @apply flex items-center gap-1 text-xs font-mono; }
.qa-panel__pass { @apply text-emerald-400; }
.qa-panel__sep { @apply text-slate-600; }
.qa-panel__fail { @apply text-red-400; }
.qa-panel__agents { @apply grid grid-cols-2 gap-2; }
.qa-agent { @apply p-2.5 rounded-lg border border-white/5 space-y-1.5; }
.qa-agent--pass { @apply border-emerald-500/20 bg-emerald-500/5; }
.qa-agent--fail { @apply border-red-500/20 bg-red-500/5; }
.qa-agent--warn { @apply border-yellow-500/20 bg-yellow-500/5; }
.qa-agent--pending { @apply opacity-50; }
.qa-agent__header { @apply flex items-center justify-between; }
.qa-agent__name { @apply text-xs text-slate-300 font-mono; }
.qa-agent__verdict { @apply text-xs font-mono font-semibold; }
.qa-agent__issues { @apply space-y-0.5; }
.qa-agent__issue { @apply text-xs text-slate-400 truncate; }
.qa-agent__running { @apply flex items-center gap-1; }
.qa-agent__dot { @apply w-1 h-1 rounded-full bg-blue-400 inline-block animate-bounce; }
.qa-agent__dot--delay-1 { animation-delay: 0.15s; }
.qa-agent__dot--delay-2 { animation-delay: 0.3s; }
.qa-agent__running-label { @apply text-xs text-blue-400 font-mono ml-1; }
</style>
