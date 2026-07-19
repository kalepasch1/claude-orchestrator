<script setup lang="ts">
const props = defineProps<{ title: string; recommendation: string; confidence: number }>()
const emit = defineEmits<{ adjust: [prompt: string]; implement: [] }>()
const reach = ref(50)
const intensity = ref(50)
const certainty = computed(() => Math.max(10, Math.min(99, Math.round(props.confidence * .7 + intensity.value * .3))))
const predictedLift = computed(() => Math.max(1, Math.round((props.confidence / 100) * (reach.value / 100) * (8 + intensity.value / 4))))
const risk = computed(() => intensity.value > 75 ? 'Elevated' : intensity.value > 40 ? 'Moderate' : 'Low')
function adjust() { emit('adjust', `${props.recommendation}\n\nSimulation controls: ${reach.value}% eligible reach, ${intensity.value}% change intensity. Target at least ${predictedLift.value}% task-completion lift with ${risk.value.toLowerCase()} implementation risk.`) }
</script>

<template>
  <section class="recommendation-sandbox">
    <header><div><span>Interactive outcome sandbox</span><h4>See the likely effect before implementation</h4></div><b>{{ certainty }}% modeled confidence</b></header>
    <div class="sandbox-grid"><label>Eligible reach <strong>{{ reach }}%</strong><input v-model.number="reach" type="range" min="10" max="100"></label><label>Change intensity <strong>{{ intensity }}%</strong><input v-model.number="intensity" type="range" min="10" max="100"></label><article><span>Predicted completion lift</span><strong>+{{ predictedLift }}%</strong></article><article><span>Implementation risk</span><strong>{{ risk }}</strong></article></div>
    <p><b>{{ title }}:</b> {{ recommendation }} The model is directional until preview telemetry and independent QA replace assumptions with observed evidence.</p>
    <footer><button type="button" @click="adjust">Adjust with this scenario</button><button type="button" @click="emit('implement')">Implement and measure</button></footer>
  </section>
</template>

<style scoped>
.recommendation-sandbox{margin-top:14px;padding:15px;border:1px solid #bfd2c4;border-radius:14px;background:#f3f7f3}.recommendation-sandbox header{display:flex;justify-content:space-between;gap:20px}.recommendation-sandbox header span{font-size:8px;font-weight:750;letter-spacing:.13em;text-transform:uppercase;color:#194c36}.recommendation-sandbox h4{margin-top:4px;font-size:12px}.recommendation-sandbox header>b{align-self:start;border-radius:99px;padding:5px 8px;background:#fff;color:#194c36;font-size:8px}.sandbox-grid{display:grid;grid-template-columns:1fr 1fr 140px 140px;gap:10px;margin-top:13px}.sandbox-grid label,.sandbox-grid article{padding:10px;border:1px solid #d9e2db;border-radius:9px;background:#fff;font-size:8px;color:#657068}.sandbox-grid label strong{float:right;color:#222}.sandbox-grid input{display:block;width:100%;margin-top:9px;accent-color:#194c36}.sandbox-grid article span,.sandbox-grid article strong{display:block}.sandbox-grid article strong{margin-top:6px;font-size:18px;color:#194c36}.recommendation-sandbox>p{margin-top:11px;font-size:9px;line-height:1.55;color:#667068}.recommendation-sandbox footer{display:flex;justify-content:flex-end;gap:7px;margin-top:12px}.recommendation-sandbox footer button{border:1px solid #cbd5ce;border-radius:8px;padding:8px 10px;background:#fff;font-size:9px}.recommendation-sandbox footer button:last-child{border-color:#194c36;background:#194c36;color:#fff}@media(max-width:800px){.sandbox-grid{grid-template-columns:1fr 1fr}.recommendation-sandbox header{flex-direction:column}}
</style>
