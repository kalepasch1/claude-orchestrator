<script setup lang="ts">
definePageMeta({ layout: 'default' })
</script>

<template>
  <HivemindGovernance />
  <section class="expert-controls">
    <details>
      <summary>
        <span>Advanced controls</span>
        <small>Sharing policy, verification, licensing, simulations, and network administration</small>
      </summary>
      <HivemindEconomy />
      <HivemindAdvanced />
    </details>
  </section>
</template>

<style scoped>
.expert-controls{padding:18px clamp(18px,4vw,64px) 80px;background:#f2f2ee}.expert-controls>details{max-width:1220px;margin:auto;border:1px solid #d3d3cd;border-radius:14px;background:#fff;overflow:hidden}.expert-controls summary{display:grid;gap:4px;padding:18px 21px;cursor:pointer;list-style:none}.expert-controls summary::-webkit-details-marker{display:none}.expert-controls summary span{font-size:12px;font-weight:760}.expert-controls summary small{color:#777;font-size:9px}.expert-controls :deep(section){border-top:1px solid #d3d3cd}
</style>
