<script setup lang="ts">
import { deriveDecisionBrief } from '~/utils/decisionBrief'
// One approval card for operator sign-offs (secrets / deploys / OAuth / legal).
// Emits `decide(id, 'approved'|'denied')` so the parent owns the two-key logic.
const props = withDefaults(defineProps<{
  a: any
  userEmail?: string | null
  accent?: 'amber' | 'sky'
}>(), { accent: 'amber', userEmail: null })

const emit = defineEmits<{ (e: 'decide', id: string, status: 'approved' | 'denied'): void }>()
const brief = computed(() => deriveDecisionBrief(props.a))

function requestDecision(status: 'approved' | 'denied') {
  const message = status === 'approved'
    ? `Authorize this bounded action? Approval is permission to attempt it, not proof of completion.\n\n${brief.value.authorizationMeaning}`
    : `Hold or deny this request?\n\n${brief.value.denyMeaning}`
  if (confirm(message)) emit('decide', props.a.id, status)
}

const tone = computed(() => props.accent === 'sky'
  ? { border: 'border-sky-600/60', label: 'text-sky-400' }
  : { border: 'border-amber-600/60', label: 'text-amber-400' })
</script>

<template>
  <div class="bg-slate-900 border rounded-xl p-4 mb-3" :class="tone.border">
    <div class="flex items-center gap-2">
      <span class="text-xs uppercase font-bold" :class="tone.label">{{ a.kind }}</span>
      <b>{{ a.title }}</b>
      <span v-if="a.approvals_required >= 2"
            class="text-xs bg-red-900/60 text-red-300 rounded px-1.5 py-0.5 font-bold">2-KEY</span>
      <span class="flex-1"></span>
      <span class="text-slate-500 text-xs">{{ a.project }}</span>
    </div>
    <div class="mt-3 rounded-lg bg-white p-3 text-slate-900"><DecisionBrief :approval="a" compact /></div>
    <p v-if="a.approvals_required >= 2 && a.decided_by" class="text-xs text-green-400 mt-2">
      ✓ First approval: {{ a.decided_by }} — one more needed from a different user
    </p>
    <div class="flex gap-2 mt-3">
      <button @click="requestDecision('approved')"
              class="bg-[#2f6b46] hover:bg-[#3a7d54] text-white rounded-lg px-4 py-1.5 font-semibold text-sm">
        {{ a.approvals_required >= 2 && !a.decided_by ? 'Authorize (1st)' : a.approvals_required >= 2 && a.decided_by !== userEmail ? 'Authorize (2nd)' : 'Authorize with conditions' }}
      </button>
      <button @click="requestDecision('denied')" class="bg-[#a83a2a] hover:bg-[#bf4632] text-white rounded-lg px-4 py-1.5 font-semibold text-sm">Hold / deny</button>
    </div>
  </div>
</template>
