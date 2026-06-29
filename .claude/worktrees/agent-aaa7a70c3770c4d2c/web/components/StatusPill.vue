<script setup lang="ts">
// Reusable status pill — replaces the repeated inline
// `text-xs px-2 py-0.5 rounded-full font-semibold` + color-map markup.
// Caller passes the resolved tailwind class string via `tone`.
defineProps<{
  label: string | number | null | undefined
  tone?: string
}>()
</script>

<template>
  <span
    class="text-xs px-2 py-0.5 rounded-full font-semibold font-mono"
    :class="tone || 'bg-surface-raised text-slate-300'"
  >{{ label }}</span>
</template>
