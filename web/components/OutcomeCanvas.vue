<script setup lang="ts">
const props = defineProps<{ modelValue: string; appName: string; capability: string; busy?: boolean; successCriteria?: string; constraints?: string; advanced?: boolean }>()
const emit = defineEmits(['update:modelValue', 'update:successCriteria', 'update:constraints', 'update:advanced', 'submit'])
const expanded = ref(false)
const suggestions = computed(() => {
  const domain = props.capability.toLowerCase()
  if (domain.includes('design')) return ['Increase first-use completion', 'Create a production-ready visual system', 'Reduce cognitive load without losing power']
  if (domain.includes('legal')) return ['Reduce material risk', 'Produce an approval-ready redline', 'Create a defensible audit trail']
  if (domain.includes('growth')) return ['Improve qualified conversion', 'Validate positioning with evidence', 'Ship a measurable experiment']
  return ['Fix the root cause and prevent recurrence', 'Ship a verified improvement', 'Research and recommend the best path']
})
</script>

<template>
  <section class="outcome-canvas" :class="{ expanded }">
    <header>
      <div><span>Outcome canvas</span><b>What should change for {{ appName }}?</b></div>
      <button type="button" @click="expanded = !expanded">{{ expanded ? 'Compact' : 'Plan outcome' }}</button>
    </header>
    <textarea :value="modelValue" rows="expanded ? 4 : 2" placeholder="Describe the result—not the model, vendor, branch, or implementation…" @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)" @keydown.meta.enter.prevent="emit('submit')" @keydown.ctrl.enter.prevent="emit('submit')" />
    <div v-if="expanded" class="outcome-details">
      <label><span>Success looks like</span><textarea :value="successCriteria" rows="2" placeholder="Measurable acceptance criteria…" @input="emit('update:successCriteria', ($event.target as HTMLTextAreaElement).value)" /></label>
      <label><span>Constraints</span><textarea :value="constraints" rows="2" placeholder="Deadlines, audience, policy, brand, or non-negotiables…" @input="emit('update:constraints', ($event.target as HTMLTextAreaElement).value)" /></label>
    </div>
    <div class="suggestions"><button v-for="item in suggestions" :key="item" type="button" @click="emit('update:modelValue', item)">{{ item }}</button></div>
    <footer>
      <div><b>✦ Autopilot</b><span>Context → research → specialists → QA → release proof</span></div>
      <button type="button" :disabled="busy || !modelValue.trim()" @click="emit('submit')">{{ busy ? 'Routing…' : 'Start outcome' }} <span>↗</span></button>
    </footer>
    <button class="advanced-toggle" type="button" @click="emit('update:advanced', !advanced)"><span>{{ advanced ? '−' : '+' }}</span> {{ advanced ? 'Hide advanced controls' : 'Show advanced controls when needed' }}</button>
  </section>
</template>

<style scoped>
.outcome-canvas{padding:12px;background:#fff;border-top:1px solid #e5e7eb;box-shadow:0 -10px 28px rgba(15,23,42,.06)}.outcome-canvas>header{display:flex;align-items:center;justify-content:space-between;gap:12px}.outcome-canvas header div{display:flex;flex-direction:column}.outcome-canvas header span,.outcome-details label>span{font-size:8px;font-weight:750;letter-spacing:.13em;text-transform:uppercase;color:#6257c9}.outcome-canvas header b{margin-top:2px;font-size:11px;color:#111827}.outcome-canvas header button,.advanced-toggle{border:0;background:none;color:#6b7280;font-size:9px}.outcome-canvas>textarea,.outcome-details textarea{display:block;width:100%;resize:none;margin-top:9px;padding:9px 10px;border:1px solid #e5e7eb;border-radius:10px;background:#f9fafb;outline:none;font-size:11px;line-height:1.45}.outcome-canvas textarea:focus{border-color:#8b83de;background:#fff;box-shadow:0 0 0 3px #eeecff}.outcome-details{display:grid;grid-template-columns:1fr 1fr;gap:8px}.outcome-details label{display:block;margin-top:9px}.outcome-details textarea{margin-top:4px}.suggestions{display:flex;gap:5px;overflow-x:auto;margin-top:7px}.suggestions button{flex:none;border:1px solid #e5e7eb;border-radius:99px;background:#fff;padding:5px 7px;color:#6b7280;font-size:8px;white-space:nowrap}.outcome-canvas footer{display:flex;align-items:center;gap:10px;margin-top:9px}.outcome-canvas footer>div{display:flex;min-width:0;flex:1;flex-direction:column;font-size:8px;color:#9ca3af}.outcome-canvas footer b{color:#6257c9;font-size:9px}.outcome-canvas footer>button{border:0;border-radius:8px;background:#111827;padding:9px 11px;color:#fff;font-size:9px;font-weight:700}.outcome-canvas footer>button:disabled{opacity:.35}.advanced-toggle{display:flex;gap:5px;align-items:center;margin-top:8px;padding:0}.advanced-toggle span{display:grid;width:14px;height:14px;place-items:center;border-radius:50%;background:#f1f1f4;color:#555}@media(max-width:520px){.outcome-details{grid-template-columns:1fr}}
.outcome-canvas{border-color:#d7ddd8}.outcome-canvas__eyebrow{color:#194c36}.outcome-canvas :is(button.primary,.primary){background:#194c36}.outcome-canvas :is(input,textarea,select):focus{border-color:#57856b;box-shadow:0 0 0 3px #e5efe8}
</style>
