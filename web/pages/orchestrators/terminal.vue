<template>
  <div class="terminal-page">
    <div class="terminal-page__container">
      <DevelopmentTerminal />
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'default' })
useHead({ title: 'Trojun Terminal — Madeus' })
</script>

<style scoped>
.terminal-page {
  @apply min-h-screen py-8 px-4;
}
.terminal-page__container {
  @apply max-w-5xl mx-auto;
}
</style>
