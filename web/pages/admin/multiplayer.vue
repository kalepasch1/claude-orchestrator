<template>
  <div class="multiplayer-page">
    <div class="page-header">
      <h1>Multiplayer Hivemind</h1>
      <p class="subtitle">Real-time collaborative intelligence across agents, swarms, and projects</p>
    </div>
    <MultiplayerTerminal />
  </div>
</template>

<script setup lang="ts">
import MultiplayerTerminal from '~/components/MultiplayerTerminal.vue'

useHead({ title: 'Multiplayer Hivemind' })
</script>

<style scoped lang="postcss">
.multiplayer-page {
  @apply p-6 max-w-7xl mx-auto;
}

.page-header {
  @apply mb-6;

  h1 {
    @apply text-2xl font-bold text-slate-100;
  }

  .subtitle {
    @apply text-sm text-slate-400 mt-1;
  }
}
</style>
