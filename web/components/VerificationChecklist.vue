<template>
  <div class="verification">
    <div class="verification__header">
      <span class="verification__title">Verification</span>
      <span class="verification__score">{{ passCount }}/{{ steps.length }}</span>
    </div>
    <div class="verification__steps">
      <div v-for="step in resolvedSteps" :key="step.key" class="verification__step" :class="stepClass(step.status)">
        <div class="verification__step-icon">
          <span v-if="step.status === 'pass'">✓</span>
          <span v-else-if="step.status === 'fail'">✗</span>
          <span v-else-if="step.status === 'running'" class="verification__running">◈</span>
          <span v-else>○</span>
        </div>
        <div class="verification__step-body">
          <span class="verification__step-name">{{ step.label }}</span>
          <span v-if="step.detail" class="verification__step-detail">{{ step.detail }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
export type StepStatus = 'pending' | 'running' | 'pass' | 'fail' | 'skip'

export interface ChecklistStep {
  key: string
  label: string
  status: StepStatus
  detail?: string
}

const STEP_LABELS: Record<string, string> = {
  code_implemented: 'Code implemented',
  wired_e2e: 'Wired end-to-end',
  no_dead_code: 'No dead code',
  git_merge_clean: 'Merge clean',
  migrations_applied: 'Migrations applied',
  vercel_deploy: 'Vercel deployed',
  qa_testing: 'QA passed',
}

const props = defineProps<{ steps?: ChecklistStep[] }>()

const resolvedSteps = computed<ChecklistStep[]>(() =>
  props.steps?.length
    ? props.steps
    : Object.entries(STEP_LABELS).map(([key, label]) => ({ key, label, status: 'pending' as StepStatus }))
)

const passCount = computed(() => resolvedSteps.value.filter(s => s.status === 'pass').length)

function stepClass(status: StepStatus) {
  return {
    'verification__step--pass': status === 'pass',
    'verification__step--fail': status === 'fail',
    'verification__step--running': status === 'running',
    'verification__step--skip': status === 'skip',
  }
}
</script>

<style scoped>
.verification { @apply space-y-3; }
.verification__header { @apply flex items-center justify-between; }
.verification__title { @apply text-xs font-mono uppercase tracking-widest text-slate-400; }
.verification__score { @apply text-xs font-mono text-slate-300; }
.verification__steps { @apply space-y-1.5; }
.verification__step { @apply flex items-start gap-2.5 text-sm; }
.verification__step-icon { @apply w-4 h-4 flex items-center justify-center text-slate-500 font-mono text-xs mt-0.5 shrink-0; }
.verification__step--pass .verification__step-icon { @apply text-emerald-400; }
.verification__step--fail .verification__step-icon { @apply text-red-400; }
.verification__step--running .verification__step-icon { @apply text-blue-400; }
.verification__step-body { @apply flex flex-col gap-0.5; }
.verification__step-name { @apply text-slate-300; }
.verification__step--pass .verification__step-name { @apply text-emerald-300; }
.verification__step--fail .verification__step-name { @apply text-red-300; }
.verification__step-detail { @apply text-xs text-slate-500 font-mono; }
.verification__running { @apply animate-pulse; }
</style>
