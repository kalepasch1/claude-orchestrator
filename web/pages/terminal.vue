<template>
  <div class="terminal-page">
    <DevelopmentTerminal />
  </div>
</template>

<script setup lang="ts">
import DevelopmentTerminal from '~/components/DevelopmentTerminal.vue'

definePageMeta({ layout: 'default' })
useHead({
  title: 'Development Terminal - Trojun',
  meta: [{ name: 'description', content: 'Orchestration console for Trojun cascade operations' }]
})
</script>

<style scoped lang="postcss">
.terminal-page {
  @apply h-screen flex flex-col bg-slate-950;
}
</style>
