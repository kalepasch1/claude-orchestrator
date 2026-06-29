<script setup lang="ts">
// One approval card. Used by index.vue for both groups:
//  - operator sign-offs (secrets / deploys / OAuth / legal) — accent "sky"
//  - code-merge approvals (material / proposal / self) — accent "amber"
// Emits `decide(id, 'approved'|'denied')` so the parent owns the two-key logic.
const props = withDefaults(defineProps<{
  a: any
  userEmail?: string | null
  accent?: 'amber' | 'sky'
}>(), { accent: 'amber', userEmail: null })

defineEmits<{ (e: 'decide', id: string, status: 'approved' | 'denied'): void }>()

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
    <p v-if="a.why" class="text-sm mt-2"><span class="text-xs font-semibold uppercase mr-2" :class="tone.label">Why</span>{{ a.why }}</p>
    <p v-if="a.value" class="text-sm mt-1"><span class="text-xs font-semibold uppercase mr-2" :class="tone.label">Value</span>{{ a.value }}</p>
    <p v-if="a.risk" class="text-sm mt-1"><span class="text-xs font-semibold uppercase mr-2" :class="tone.label">Risk</span>{{ a.risk }}</p>
    <pre v-if="a.detail" class="bg-black/40 border border-slate-700 rounded-md p-2 mt-2 text-xs text-slate-300 overflow-auto max-h-44 whitespace-pre-wrap font-mono">{{ a.detail }}</pre>
    <p v-if="a.approvals_required >= 2 && a.decided_by" class="text-xs text-green-400 mt-2">
      ✓ First approval: {{ a.decided_by }} — one more needed from a different user
    </p>
    <div class="flex gap-2 mt-3">
      <button @click="$emit('decide', a.id, 'approved')"
              class="bg-green-600 hover:bg-green-500 rounded-lg px-4 py-1.5 font-semibold text-sm">
        {{ a.approvals_required >= 2 && !a.decided_by ? 'Approve (1st)' : a.approvals_required >= 2 && a.decided_by !== userEmail ? 'Approve (2nd)' : 'Approve' }}
      </button>
      <button @click="$emit('decide', a.id, 'denied')" class="bg-red-600 hover:bg-red-500 rounded-lg px-4 py-1.5 font-semibold text-sm">Deny</button>
    </div>
  </div>
</template>
