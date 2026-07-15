<script setup lang="ts">
defineProps<{ proof?: any; gateway?: boolean; loading?: boolean }>()
</script>
<template>
  <div class="proof-ribbon" :class="{ loading }">
    <div><i :class="proof?.status === 200 ? 'ok' : ''" /><span>{{ loading ? 'Verifying release…' : proof?.status === 200 ? 'Live app verified' : 'Verification unavailable' }}</span></div>
    <span>Alias <b>{{ proof?.durableAlias ? 'durable' : 'unknown' }}</b></span>
    <span>Embed <b>{{ gateway ? 'secure gateway' : proof?.frameAllowed ? 'native' : 'pending' }}</b></span>
    <span v-if="proof?.deploymentId">Deploy <b>{{ proof.deploymentId }}</b></span>
    <span>Checked <b>{{ proof?.checkedAt ? new Date(proof.checkedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—' }}</b></span>
  </div>
</template>
<style scoped>
.proof-ribbon{display:flex;align-items:center;gap:14px;overflow-x:auto;padding:8px 11px;border-top:1px solid #e5e7eb;background:#fcfcfd;color:#9ca3af;font:8px/1.2 ui-monospace,SFMono-Regular,monospace;white-space:nowrap}.proof-ribbon>div{display:flex;align-items:center;gap:6px;color:#374151}.proof-ribbon i{width:6px;height:6px;border-radius:50%;background:#d1d5db}.proof-ribbon i.ok{background:#22a35a;box-shadow:0 0 0 3px #dcfce7}.proof-ribbon b{color:#4b5563;font-weight:650}.proof-ribbon.loading{opacity:.7}
</style>
