<script setup lang="ts">
const props = defineProps<{ tasks: any[]; deployments?: any[]; capability: string }>()
const steps = computed(() => {
  const task = props.tasks?.[0]
  const deployment = props.deployments?.[0]
  const state = String(task?.state || '').toUpperCase()
  return [
    { name: 'Outcome understood', detail: task ? task.slug : `Ready for a ${props.capability} outcome`, done: !!task, active: !task },
    { name: 'Best route selected', detail: task?.kind ? `${task.kind} route · policy governed` : 'Selected automatically after intake', done: !!task, active: state === 'QUEUED' },
    { name: 'Work executed', detail: state && !['QUEUED', 'BLOCKED'].includes(state) ? state.toLowerCase() : 'Specialists, tools, and worktrees coordinated', done: ['DONE', 'MERGED'].includes(state), active: ['RUNNING', 'VERIFYING'].includes(state) },
    { name: 'Independently verified', detail: state === 'MERGED' ? 'Tests and evidence accepted' : 'QA, accessibility, and regression proof required', done: state === 'MERGED', active: state === 'DONE' },
    { name: 'Durable release', detail: deployment?.external_url || deployment?.note || 'Release train promotes verified work only', done: deployment?.deploy_status === 'deployed', active: state === 'MERGED' },
  ]
})
</script>

<template>
  <details class="proof-timeline">
    <summary><span><b>Execution proof</b><small>Request → route → work → verification → durable release</small></span><i>{{ steps.filter(step => step.done).length }}/{{ steps.length }} proven</i></summary>
    <ol><li v-for="(step, index) in steps" :key="step.name" :class="{ done: step.done, active: step.active }"><span>{{ step.done ? '✓' : index + 1 }}</span><div><b>{{ step.name }}</b><small>{{ step.detail }}</small></div></li></ol>
  </details>
</template>

<style scoped>
.proof-timeline{overflow:hidden;border:1px solid #d8ded9;border-radius:14px;background:#fff}.proof-timeline summary{display:flex;justify-content:space-between;align-items:center;padding:15px 17px;cursor:pointer;list-style:none}.proof-timeline summary span,.proof-timeline summary b,.proof-timeline summary small{display:block}.proof-timeline summary b{font-size:11px}.proof-timeline summary small{margin-top:3px;color:#777;font-size:9px}.proof-timeline summary i{font-size:8px;font-style:normal;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#194c36}.proof-timeline ol{display:grid;grid-template-columns:repeat(5,1fr);margin:0;padding:0;border-top:1px solid #e4e7e3;list-style:none}.proof-timeline li{position:relative;display:grid;grid-template-columns:24px 1fr;gap:8px;padding:14px 12px;border-right:1px solid #e4e7e3}.proof-timeline li:last-child{border:0}.proof-timeline li>span{display:grid;width:22px;height:22px;place-items:center;border:1px solid #d9dedb;border-radius:50%;color:#999;font-size:8px}.proof-timeline li.done>span{border-color:#9ab6a3;background:#edf5ef;color:#194c36}.proof-timeline li.active>span{border-color:#194c36;box-shadow:0 0 0 4px #e8f0ea}.proof-timeline li b,.proof-timeline li small{display:block}.proof-timeline li b{font-size:9px}.proof-timeline li small{margin-top:4px;color:#858b87;font-size:8px;line-height:1.4}@media(max-width:900px){.proof-timeline ol{grid-template-columns:1fr}.proof-timeline li{border-right:0;border-bottom:1px solid #e4e7e3}}
</style>
