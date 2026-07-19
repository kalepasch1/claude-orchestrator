<template>
  <svg class="madeus-mark" viewBox="0 0 48 48" role="img" :aria-label="label">
    <rect width="48" height="48" rx="12" fill="currentColor" />
    <path d="M11 34V14l13 14 13-14v20" fill="none" stroke="var(--mark-ink, white)" stroke-width="4.25" stroke-linecap="round" stroke-linejoin="round" />
    <path d="M20.75 24.5 24 28l3.25-3.5" fill="none" stroke="var(--mark-signal, #a7f3d0)" stroke-width="4.25" stroke-linecap="round" stroke-linejoin="round" />
  </svg>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ label?: string }>(), { label: 'Madeus' })
</script>

<style scoped>
.madeus-mark { display: block; width: 100%; height: 100%; }
</style>
