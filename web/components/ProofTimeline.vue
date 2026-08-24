<script setup lang="ts">
const props = defineProps<{
  tasks: any[]
  deployments?: any[]
  capability: string
  projectId?: string
  projectName?: string
}>()
const steps = computed(() => {
  const task = props.tasks?.find(item => !props.projectId || item.project_id === props.projectId)
  const deployment = props.deployments?.find(item => !props.projectName || item.project === props.projectName)
  const state = String(task?.state || '').toUpperCase()
  const hasArtifact = Boolean(task?.artifact_commit)
  const integrated = ['MERGED', 'DEPLOYED_AND_VERIFIED'].includes(state)
  const verificationReceipt = task?.verification_receipt || task?.qa_receipt || task?.qa_receipt_id
  const independentlyVerified = Boolean(verificationReceipt)
  const deployed = state === 'DEPLOYED_AND_VERIFIED'
  return [
    { name: 'Outcome understood', detail: task ? task.slug : `Ready for a ${props.capability} outcome`, done: !!task, active: !task },
    { name: 'Best route selected', detail: task?.kind ? `${task.kind} route · policy governed` : 'Selected automatically after intake', done: !!task, active: state === 'QUEUED' },
    { name: 'Work executed', detail: hasArtifact ? `Artifact ${String(task.artifact_commit).slice(0, 12)}` : 'A recorded artifact commit is required', done: hasArtifact, active: ['RUNNING', 'VERIFYING'].includes(state) },
    { name: 'Independently verified', detail: independentlyVerified ? 'A linked QA receipt is present' : 'QA, accessibility, and regression receipt required', done: independentlyVerified, active: hasArtifact && !independentlyVerified },
    { name: 'Integrated', detail: integrated ? 'Artifact is recorded on the integration branch' : state === 'PHANTOM_UNVERIFIED' ? 'Merge claim lacks reachable artifact proof' : 'Not yet proven on the integration branch', done: integrated, active: state === 'DONE' },
    { name: 'Durable release', detail: deployed ? (deployment?.vercel_url || deployment?.note || 'Exact task artifact verified in production') : 'Merged is not deployed; exact-SHA production proof required', done: deployed, active: integrated && !deployed },
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
.proof-timeline{overflow:hidden;border:1px solid #d8ded9;border-radius:14px;background:#fff}.proof-timeline summary{display:flex;justify-content:space-between;align-items:center;padding:15px 17px;cursor:pointer;list-style:none}.proof-timeline summary span,.proof-timeline summary b,.proof-timeline summary small{display:block}.proof-timeline summary b{font-size:11px}.proof-timeline summary small{margin-top:3px;color:#777;font-size:9px}.proof-timeline summary i{font-size:8px;font-style:normal;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#194c36}.proof-timeline ol{display:grid;grid-template-columns:repeat(6,1fr);margin:0;padding:0;border-top:1px solid #e4e7e3;list-style:none}.proof-timeline li{position:relative;display:grid;grid-template-columns:24px 1fr;gap:8px;padding:14px 12px;border-right:1px solid #e4e7e3}.proof-timeline li:last-child{border:0}.proof-timeline li>span{display:grid;width:22px;height:22px;place-items:center;border:1px solid #d9dedb;border-radius:50%;color:#999;font-size:8px}.proof-timeline li.done>span{border-color:#9ab6a3;background:#edf5ef;color:#194c36}.proof-timeline li.active>span{border-color:#194c36;box-shadow:0 0 0 4px #e8f0ea}.proof-timeline li b,.proof-timeline li small{display:block}.proof-timeline li b{font-size:9px}.proof-timeline li small{margin-top:4px;color:#858b87;font-size:8px;line-height:1.4}@media(max-width:900px){.proof-timeline ol{grid-template-columns:1fr}.proof-timeline li{border-right:0;border-bottom:1px solid #e4e7e3}}
</style>
