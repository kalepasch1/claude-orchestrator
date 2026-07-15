<script setup lang="ts">
import { deriveDecisionBrief } from '~/utils/decisionBrief'

const props = defineProps<{ approval: Record<string, any>; compact?: boolean }>()
const brief = computed(() => deriveDecisionBrief(props.approval))
const severityTone: Record<string, string> = { low: 'bg-gray-100 text-gray-600', medium: 'bg-amber-50 text-amber-700', high: 'bg-orange-50 text-orange-700', critical: 'bg-red-50 text-red-700' }
const recommendationTone: Record<string, string> = { 'APPROVE WITH CONDITIONS': 'border-emerald-200 bg-emerald-50 text-emerald-800', 'HOLD FOR EVIDENCE': 'border-amber-200 bg-amber-50 text-amber-800', ESCALATE: 'border-red-200 bg-red-50 text-red-800', ACKNOWLEDGE: 'border-blue-200 bg-blue-50 text-blue-800' }
</script>

<template>
  <section class="space-y-3" aria-label="Decision brief">
    <div class="rounded-lg border border-slate-200 bg-slate-50 p-4">
      <div class="flex flex-wrap items-center gap-2"><span class="text-[9px] font-semibold uppercase tracking-[.14em] text-slate-500">What is actually happening</span><span class="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[9px] text-slate-500">{{ brief.classification }}</span></div>
      <p class="mt-2 text-xs leading-5 text-slate-700">{{ brief.plainLanguage }}</p>
      <ol v-if="!compact" class="mt-3 space-y-1 text-xs text-slate-600"><li v-for="(change, index) in brief.proposedChanges" :key="change" class="flex gap-2"><b class="text-slate-400">{{ index + 1 }}.</b><span>{{ change }}</span></li></ol>
    </div>

    <div class="rounded-lg border p-3" :class="recommendationTone[brief.recommendation]">
      <div class="flex items-center gap-3"><strong class="text-[10px] tracking-wide">{{ brief.recommendation }}</strong><div class="h-1.5 flex-1 rounded-full bg-white/70"><div class="h-1.5 rounded-full bg-current opacity-50" :style="`width:${brief.confidence}%`" /></div><span class="font-mono text-[10px]">{{ brief.confidence }}%</span></div>
      <p class="mt-2 text-[11px] leading-4">Confidence measures evidence completeness, not probability that approval is legally correct.</p>
    </div>

    <div class="grid gap-3 md:grid-cols-2">
      <div class="rounded-lg border border-emerald-200 p-3"><h4 class="text-[9px] font-semibold uppercase tracking-wide text-emerald-700">Expected value</h4><ul class="mt-2 space-y-1 text-xs text-slate-600"><li v-for="reward in brief.rewards" :key="reward">+ {{ reward }}</li></ul></div>
      <div class="rounded-lg border border-slate-200 p-3"><h4 class="text-[9px] font-semibold uppercase tracking-wide text-slate-500">Scope and reversibility</h4><p class="mt-2 text-xs text-slate-600"><b>Blast radius:</b> {{ brief.blastRadius }}</p><p class="mt-1 text-xs text-slate-600"><b>Reversibility:</b> {{ brief.reversibility.replaceAll('_', ' ') }}</p><p class="mt-1 text-xs text-slate-600"><b>Rollback:</b> {{ brief.rollback }}</p></div>
    </div>

    <div class="rounded-lg border border-orange-200 overflow-hidden"><div class="bg-orange-50 px-3 py-1.5 text-[9px] font-semibold uppercase tracking-wide text-orange-700">Risks, consequences, and mitigations</div><div class="divide-y divide-orange-100"><div v-for="risk in brief.risks" :key="`${risk.category}:${risk.statement}`" class="p-3"><div class="flex items-center gap-2"><span class="text-xs font-medium text-slate-800">{{ risk.category }}</span><span class="rounded px-1.5 py-0.5 text-[9px] uppercase" :class="severityTone[risk.severity]">{{ risk.severity }}</span></div><p class="mt-1 text-xs text-slate-600">{{ risk.statement }}</p><p class="mt-1 text-[11px] text-slate-500"><b>Control:</b> {{ risk.mitigation }}</p></div></div></div>

    <div v-if="!compact" class="grid gap-3 md:grid-cols-2">
      <div class="rounded-lg border border-amber-200 bg-amber-50/40 p-3"><h4 class="text-[9px] font-semibold uppercase tracking-wide text-amber-700">Required before execution</h4><ul class="mt-2 space-y-1 text-xs text-slate-600"><li v-for="item in brief.prerequisites" :key="item">□ {{ item }}</li></ul><template v-if="brief.missingEvidence.length"><h4 class="mt-3 text-[9px] font-semibold uppercase tracking-wide text-red-600">Missing evidence</h4><ul class="mt-2 space-y-1 text-xs text-slate-600"><li v-for="item in brief.missingEvidence" :key="item">! {{ item }}</li></ul></template></div>
      <div class="rounded-lg border border-blue-200 bg-blue-50/30 p-3"><h4 class="text-[9px] font-semibold uppercase tracking-wide text-blue-700">Proof required to call this complete</h4><ul class="mt-2 space-y-1 text-xs text-slate-600"><li v-for="item in brief.verification" :key="item">✓ {{ item }}</li></ul></div>
    </div>

    <div class="rounded-lg border border-purple-200 bg-purple-50/30 p-3 text-xs leading-5 text-slate-700"><p><b>Approval means:</b> {{ brief.authorizationMeaning }}</p><p class="mt-1"><b>Completion means:</b> {{ brief.completionMeaning }}</p><p class="mt-1"><b>Hold/deny means:</b> {{ brief.denyMeaning }}</p></div>
  </section>
</template>
