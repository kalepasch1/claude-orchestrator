<script setup lang="ts">
const props = defineProps<{ connectors: any[] }>()
const groups = computed(() => {
  const definitions = [
    { name: 'Create', keys: ['image-generation','video-generation','graphic-design','motion-design','voice-generation','3d-generation'] },
    { name: 'Build', keys: ['repositories','design-to-code','web-design','site-publish','preview-deploy'] },
    { name: 'Research', keys: ['search','whiteboards','research-synthesis','docs','pages'] },
    { name: 'Publish', keys: ['publishing','cms','assets','delivery','localization'] },
    { name: 'Verify', keys: ['visual-regression','accessibility-qa','ui-testing','deployment-status','actions'] },
  ]
  return definitions.map(group => {
    const matches = props.connectors.filter(c => c.capabilities?.some((cap: string) => group.keys.includes(cap)))
    const connected = matches.filter(c => c.connected_accounts?.length || (c.kind === 'internal' && c.configured)).length
    return { ...group, total: matches.length, connected, providers: matches.slice(0, 5).map(c => c.name) }
  })
})
</script>
<template>
  <section class="unlock-graph">
    <header><div><span>Capability graph</span><h2>What your connections unlock</h2></div><p>Madeus combines providers into outcomes. Connecting one specialist can strengthen several command centers automatically.</p></header>
    <div class="graph-flow"><div class="origin"><b>Connected tools</b><span>Least-privilege accounts</span></div><i>→</i><div class="nodes"><article v-for="group in groups" :key="group.name"><div><b>{{ group.name }}</b><span>{{ group.connected }}/{{ group.total }} providers ready</span></div><progress :value="group.connected" :max="Math.max(group.total,1)"/><small>{{ group.providers.join(' · ') || 'No matching providers' }}</small></article></div><i>→</i><div class="origin outcome"><b>Verified outcomes</b><span>Routed only when useful</span></div></div>
  </section>
</template>
<style scoped>
.unlock-graph{margin:0 0 28px;padding:24px;border:1px solid #dedede;border-radius:15px;background:#111;color:#fff}.unlock-graph header{display:flex;justify-content:space-between;gap:30px}.unlock-graph header span{font-size:8px;font-weight:750;letter-spacing:.14em;text-transform:uppercase;color:#9d95ff}.unlock-graph h2{margin-top:6px;font-size:19px}.unlock-graph header p{max-width:480px;color:#8e8e8e;font-size:10px;line-height:1.55}.graph-flow{display:grid;grid-template-columns:135px 20px 1fr 20px 135px;gap:11px;align-items:center;margin-top:20px}.origin{display:flex;min-height:86px;flex-direction:column;justify-content:center;padding:12px;border:1px solid #333;border-radius:10px;background:#181818}.origin b{font-size:10px}.origin span{margin-top:4px;color:#777;font-size:8px}.origin.outcome{border-color:#315841;background:#122219}.graph-flow>i{text-align:center;color:#555}.nodes{display:grid;grid-template-columns:repeat(5,1fr);gap:6px}.nodes article{padding:9px;border:1px solid #2e2e2e;border-radius:8px;background:#171717}.nodes article div{display:flex;justify-content:space-between;gap:4px}.nodes b{font-size:9px}.nodes span,.nodes small{color:#777;font-size:6px}.nodes small{display:block;overflow:hidden;margin-top:5px;text-overflow:ellipsis;white-space:nowrap}.nodes progress{width:100%;height:3px;margin-top:8px;accent-color:#8074ee}@media(max-width:900px){.graph-flow{grid-template-columns:1fr}.graph-flow>i{transform:rotate(90deg)}.nodes{grid-template-columns:repeat(2,1fr)}}
</style>
