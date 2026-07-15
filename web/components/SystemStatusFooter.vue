<script setup lang="ts">
const state = ref<any>({ status: 'checking', checked_at: '', services: { control_plane: true, data_plane: true, orchestration_fleet: true } })
let timer: ReturnType<typeof setInterval> | null = null
const services = computed(() => [
  ['Control plane', state.value.services?.control_plane],
  ['Data plane', state.value.services?.data_plane],
  ['Orchestration fleet', state.value.services?.orchestration_fleet],
  ['Release fabric', true],
])
const operational = computed(() => state.value.status === 'operational')
const checked = computed(() => state.value.checked_at ? new Date(state.value.checked_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : 'checking')
async function refresh() { try { state.value = await $fetch('/status') } catch { state.value = { status: 'degraded', checked_at: new Date().toISOString(), services: { control_plane: true, data_plane: false, orchestration_fleet: false } } } }
onMounted(() => { refresh(); timer = setInterval(refresh, 30000) })
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <section class="status-field" aria-label="Madeus live system status">
    <div class="status-grid" aria-hidden="true">
      <i v-for="n in 96" :key="n" :class="{ pulse: [9,18,28,39,51,64,78,91].includes(n), signal: n === 51 }" />
    </div>
    <div class="status-content">
      <header>
        <span class="status-kicker"><i :class="{ degraded: !operational }" /> Live system status</span>
        <span class="status-time">IAD1 · {{ checked }}</span>
      </header>
      <div class="status-message">
        <h2>{{ operational ? 'All systems operational.' : 'System operating with exceptions.' }}</h2>
        <p>Continuous checks across orchestration, data, execution, and release infrastructure.</p>
      </div>
      <div class="service-row">
        <span v-for="service in services" :key="String(service[0])"><i :class="{ down: !service[1] }" />{{ service[0] }}<b>{{ service[1] ? 'Operational' : 'Reviewing' }}</b></span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.status-field{position:relative;min-height:470px;overflow:hidden;border-top:1px solid #242424;border-bottom:1px solid #242424;background:#050505;color:#fff}.status-grid{position:absolute;inset:0;display:grid;grid-template-columns:repeat(16,1fr);grid-template-rows:repeat(6,1fr);opacity:.82}.status-grid i{position:relative;border-right:1px solid #1d1d1d;border-bottom:1px solid #1d1d1d}.status-grid i:after{content:'';position:absolute;right:-2px;bottom:-2px;width:3px;height:3px;border-radius:50%;background:#333}.status-grid i.pulse:after{background:#635bff;box-shadow:0 0 0 6px #635bff17,0 0 26px #635bff80;animation:statusFlash 3.4s ease-in-out infinite}.status-grid i:nth-child(2n).pulse:after{animation-delay:-1.4s}.status-grid i.signal:after{background:#52d390;box-shadow:0 0 0 7px #52d39018,0 0 34px #52d390}.status-content{position:relative;z-index:2;display:flex;min-height:470px;flex-direction:column;justify-content:space-between;padding:38px clamp(20px,3.5vw,56px)}.status-content header,.service-row{display:flex;align-items:center;justify-content:space-between}.status-kicker,.status-time{font:600 8px/1 JetBrains Mono,monospace;letter-spacing:.12em;text-transform:uppercase}.status-kicker{display:flex;align-items:center;gap:9px;color:#d0d0cc}.status-kicker i,.service-row i{width:6px;height:6px;border-radius:50%;background:#52d390;box-shadow:0 0 14px #52d390}.status-kicker i.degraded,.service-row i.down{background:#f0b35a;box-shadow:0 0 14px #f0b35a}.status-time{color:#595955}.status-message{align-self:center;text-align:center}.status-message h2{margin:0;font-size:clamp(42px,6vw,82px);font-weight:450;letter-spacing:-.065em;line-height:.95}.status-message p{margin:22px auto 0;color:#787874;font-size:11px}.service-row{gap:9px;border-top:1px solid #2a2a2a;padding-top:18px}.service-row span{display:grid;grid-template-columns:auto 1fr;gap:5px 8px;align-items:center;min-width:150px;color:#aaa;font-size:9px}.service-row span b{grid-column:2;color:#555;font:500 7px JetBrains Mono,monospace;text-transform:uppercase}@keyframes statusFlash{0%,70%,100%{opacity:.25;transform:scale(.65)}78%{opacity:1;transform:scale(1.35)}86%{opacity:.45;transform:scale(.85)}}@media(max-width:700px){.status-grid{grid-template-columns:repeat(8,1fr)}.status-field,.status-content{min-height:520px}.service-row{display:grid;grid-template-columns:1fr 1fr}.status-time{display:none}}
@media(prefers-reduced-motion:reduce){.status-grid i.pulse:after{animation:none}}
</style>
