<template>
  <span class="madeus-logo" :class="{ compact }">
    <span class="madeus-logo-mark"><MadeusMark label="Madeus" /></span>
    <span class="madeus-wordmark"><b>MADEUS</b><small v-if="!compact">ORCHESTRATOR</small></span>
  </span>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ compact?: boolean }>(), { compact: false })
</script>

<style scoped>
.madeus-logo { display: inline-flex; align-items: center; gap: 10px; color: inherit; }
.madeus-logo-mark { width: 30px; height: 30px; color: #090909; }
.madeus-wordmark { display: flex; flex-direction: column; line-height: 1; }
.madeus-wordmark b { font-size: 13px; font-weight: 720; letter-spacing: .16em; }
.madeus-wordmark small { margin-top: 5px; color: #8b8b86; font: 600 7px/1 'JetBrains Mono', monospace; letter-spacing: .17em; }
.compact .madeus-logo-mark { width: 25px; height: 25px; }
.compact .madeus-wordmark b { font-size: 12px; }
</style>
