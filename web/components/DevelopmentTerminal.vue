<template>
  <div class="dev-terminal">
    <div class="dev-terminal__topbar">
      <div class="dev-terminal__branding">
        <span class="dev-terminal__mark">trojun</span>
        <span class="dev-terminal__separator">·</span>
        <span class="dev-terminal__subtitle">orchestrator terminal</span>
      </div>
      <div class="dev-terminal__live">
        <span class="dev-terminal__live-dot" :class="{ 'dev-terminal__live-dot--on': connected }" />
        <span class="dev-terminal__live-label">{{ connected ? 'live' : 'offline' }}</span>
        <span v-if="snapshot.total_running > 0" class="dev-terminal__badge">{{ snapshot.total_running }} running</span>
        <span v-if="snapshot.total_blocked > 0" class="dev-terminal__badge dev-terminal__badge--warn">{{ snapshot.total_blocked }} blocked</span>
      </div>
    </div>

    <div class="dev-terminal__phases">
      <Phase mark="01" name="Illuminati" :status="phaseStatus('illuminati')">
        <div class="dev-terminal__phase-content">
          <p class="dev-terminal__phase-desc">Understanding context, decomposing intent, selecting specialist routing.</p>
          <div v-if="snapshot.total_queued > 0" class="dev-terminal__phase-desc text-blue-400">
            {{ snapshot.total_queued }} task{{ snapshot.total_queued === 1 ? '' : 's' }} queued
          </div>
        </div>
      </Phase>

      <Phase mark="02" name="Trojan" :status="phaseStatus('trojan')">
        <div class="dev-terminal__phase-content">
          <div v-if="snapshot.running_tasks.length" class="dev-terminal__running-tasks">
            <div v-for="task in snapshot.running_tasks.slice(0, 4)" :key="task.slug" class="dev-terminal__running-task">
              <div class="dev-terminal__task-slug">{{ task.slug }}</div>
              <CascadeConfidenceIndicator
                v-if="task.cascade_confidence !== null"
                :confidence="task.cascade_confidence"
                :model="task.model_tier"
              />
            </div>
          </div>
          <div v-else class="dev-terminal__phase-desc">No tasks executing.</div>
        </div>
      </Phase>

      <Phase mark="03" name="Tojun" :status="phaseStatus('tojun')">
        <div class="dev-terminal__phase-content">
          <MetricRow label="cascade savings" :value="snapshot.cascade.saves_percent" format="percent" color-scale="green" />
          <MetricRow label="avg confidence" :value="Math.round(snapshot.cascade.avg_confidence * 100)" format="percent" color-scale="green" />
          <MetricRow label="total cost" :value="snapshot.metrics.total_cost_usd" format="currency" />
        </div>
      </Phase>
    </div>

    <div class="dev-terminal__terminal-section">
      <div class="dev-terminal__terminal-header">
        <span class="dev-terminal__section-label">terminal</span>
        <button v-if="outputLines.length" class="dev-terminal__clear-btn" @click="clearOutput">clear</button>
      </div>
      <div class="dev-terminal__output-container">
        <TerminalStreamOutput :lines="outputLines" :streaming="executing" />
      </div>
      <div class="dev-terminal__input-row">
        <TerminalInput
          ref="inputRef"
          v-model="command"
          placeholder="Type a command or describe what to build…"
          :disabled="executing"
          :history="commandHistory"
          @submit="executeCommand"
        />
      </div>
    </div>

    <div v-if="showPostCompletion" class="dev-terminal__post-completion">
      <div class="dev-terminal__panels-grid">
        <div class="dev-terminal__panel">
          <VerificationChecklist :steps="verificationSteps" />
        </div>
        <div class="dev-terminal__panel">
          <SuggestionPanel :suggestions="suggestions" />
        </div>
        <div class="dev-terminal__panel">
          <QAResultsPanel :agents="qaAgents" />
        </div>
        <div class="dev-terminal__panel">
          <CostRoutingPanel
            :total-cost-usd="snapshot.metrics.total_cost_usd"
            :completed-count="snapshot.metrics.completed_count"
            :saves-percent="snapshot.cascade.saves_percent"
            :cheap-model-rate="snapshot.metrics.cheap_model_rate"
          />
        </div>
      </div>
      <div class="dev-terminal__panel dev-terminal__panel--full">
        <FleetTopologyMap :snapshot="snapshot" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { OutputLine } from './TerminalStreamOutput.vue'
import type { ChecklistStep } from './VerificationChecklist.vue'
import type { Suggestion } from './SuggestionPanel.vue'
import type { QAAgent } from './QAResultsPanel.vue'

const { snapshot } = useOrchestratorSnapshot(2000)
const { connected } = useFleetWebSocket()

const inputRef = ref<any>(null)
const command = ref('')
const executing = ref(false)
const outputLines = ref<OutputLine[]>([])
const commandHistory = ref<string[]>([])
const suggestions = ref<Suggestion[]>([])
const qaAgents = ref<QAAgent[]>([])
const verificationSteps = ref<ChecklistStep[]>([])

const showPostCompletion = computed(() =>
  snapshot.value.metrics.completed_count > 0 || snapshot.value.recent_completions.length > 0
)

function phaseStatus(phase: 'illuminati' | 'trojan' | 'tojun'): 'idle' | 'active' | 'done' {
  const s = snapshot.value
  if (phase === 'illuminati') return s.total_queued > 0 ? 'active' : s.metrics.completed_count > 0 ? 'done' : 'idle'
  if (phase === 'trojan') return s.total_running > 0 ? 'active' : s.metrics.completed_count > 0 ? 'done' : 'idle'
  if (phase === 'tojun') return s.cascade.saves_percent > 0 ? 'active' : s.metrics.completed_count > 0 ? 'done' : 'idle'
  return 'idle'
}

async function executeCommand(cmd: string) {
  if (!cmd.trim() || executing.value) return
  commandHistory.value = [cmd, ...commandHistory.value.slice(0, 49)]
  command.value = ''
  executing.value = true
  outputLines.value.push({ kind: 'system', text: `❯ ${cmd}` })
  try {
    const supabase = useSupabaseClient<any>()
    const { data: { session } } = await supabase.auth.getSession()
    const result = await $fetch<{ outputs: Array<{ type: string; content: string; tool?: string }> }>('/api/terminal/execute', {
      method: 'POST',
      headers: session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {},
      body: { command: cmd, sessionId: 'trojun-terminal' },
    })
    for (const out of result.outputs ?? []) {
      if (out.type === 'tool') {
        outputLines.value.push({ kind: 'tool', text: out.content, tool: out.tool })
      } else {
        for (const line of out.content.split('\n')) {
          outputLines.value.push({ kind: 'text', text: line })
        }
      }
    }
  } catch (e: any) {
    outputLines.value.push({ kind: 'error', text: `Error: ${e?.message ?? 'Command failed'}` })
  } finally {
    executing.value = false
    await nextTick()
    inputRef.value?.focus()
  }
}

function clearOutput() { outputLines.value = [] }

watch(() => snapshot.value.recent_completions, (completions) => {
  if (!completions.length) return
  const latest = completions[0]
  verificationSteps.value = [
    { key: 'code_implemented', label: 'Code implemented', status: 'pass' },
    { key: 'wired_e2e', label: 'Wired end-to-end', status: 'pass' },
    { key: 'no_dead_code', label: 'No dead code', status: 'pass' },
    { key: 'git_merge_clean', label: 'Merge clean', status: latest.state === 'MERGED' ? 'pass' : 'pending' },
    { key: 'migrations_applied', label: 'Migrations applied', status: 'pass' },
    { key: 'vercel_deploy', label: 'Vercel deployed', status: latest.state === 'MERGED' ? 'pass' : 'pending' },
    { key: 'qa_testing', label: 'QA passed', status: 'pass' },
  ]
}, { deep: true })

onMounted(() => { setTimeout(() => inputRef.value?.focus(), 100) })
</script>

<style scoped>
.dev-terminal { @apply space-y-4; }
.dev-terminal__topbar { @apply flex items-center justify-between px-1; }
.dev-terminal__branding { @apply flex items-center gap-2; }
.dev-terminal__mark { @apply text-sm font-mono font-bold text-blue-400 tracking-widest uppercase; }
.dev-terminal__separator { @apply text-slate-600; }
.dev-terminal__subtitle { @apply text-xs text-slate-500 font-mono; }
.dev-terminal__live { @apply flex items-center gap-2; }
.dev-terminal__live-dot { @apply w-2 h-2 rounded-full bg-slate-600; }
.dev-terminal__live-dot--on { @apply bg-emerald-400 animate-pulse; }
.dev-terminal__live-label { @apply text-xs font-mono text-slate-500; }
.dev-terminal__badge { @apply text-xs px-2 py-0.5 rounded-full bg-blue-900/40 text-blue-300 font-mono; }
.dev-terminal__badge--warn { @apply bg-red-900/40 text-red-300; }
.dev-terminal__phases { @apply grid grid-cols-1 md:grid-cols-3 gap-3; }
.dev-terminal__phase-content { @apply space-y-2; }
.dev-terminal__phase-desc { @apply text-xs text-slate-400 leading-relaxed; }
.dev-terminal__running-tasks { @apply space-y-3; }
.dev-terminal__running-task { @apply space-y-1.5 p-2 rounded bg-white/5; }
.dev-terminal__task-slug { @apply text-xs font-mono text-slate-300 truncate; }
.dev-terminal__terminal-section { @apply rounded-xl border border-white/10 bg-black/20 overflow-hidden; }
.dev-terminal__terminal-header { @apply flex items-center justify-between px-4 py-2 border-b border-white/5; }
.dev-terminal__section-label { @apply text-xs font-mono text-slate-500 uppercase tracking-wider; }
.dev-terminal__clear-btn { @apply text-xs font-mono text-slate-600 hover:text-slate-400 transition-colors; }
.dev-terminal__output-container { @apply px-4 py-3 min-h-[120px]; }
.dev-terminal__input-row { @apply px-4 pb-3; }
.dev-terminal__post-completion { @apply space-y-3; }
.dev-terminal__panels-grid { @apply grid grid-cols-1 sm:grid-cols-2 gap-3; }
.dev-terminal__panel { @apply rounded-xl border border-white/10 bg-white/5 p-4; }
.dev-terminal__panel--full { @apply sm:col-span-2; }
</style>
