<template>
  <div ref="container" class="stream-output">
    <div v-if="!lines.length" class="stream-output__empty">
      <span class="stream-output__cursor">▋</span>
    </div>
    <div v-for="(line, i) in lines" :key="i" class="stream-output__line" :class="lineClass(line)">
      <span v-if="line.kind === 'tool'" class="stream-output__tool-tag">{{ line.tool }}</span>
      <span class="stream-output__text" v-html="renderLine(line.text)" />
    </div>
    <div v-if="streaming" class="stream-output__line">
      <span class="stream-output__cursor">▋</span>
    </div>
  </div>
</template>

<script setup lang="ts">
export interface OutputLine {
  kind: 'text' | 'tool' | 'error' | 'system'
  text: string
  tool?: string
}

const props = defineProps<{
  lines: OutputLine[]
  streaming?: boolean
}>()

const container = ref<HTMLElement | null>(null)

watch(() => props.lines.length, async () => {
  await nextTick()
  if (container.value) container.value.scrollTop = container.value.scrollHeight
})

function lineClass(line: OutputLine) {
  return {
    'stream-output__line--error': line.kind === 'error',
    'stream-output__line--tool': line.kind === 'tool',
    'stream-output__line--system': line.kind === 'system',
  }
}

function renderLine(text: string): string {
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/`([^`]+)`/g, '<code class="stream-inline-code">$1</code>')
}
</script>

<style scoped>
.stream-output { @apply font-mono text-sm leading-relaxed overflow-y-auto space-y-0.5; max-height: 400px; scrollbar-width: thin; }
.stream-output__empty { @apply text-slate-600; }
.stream-output__line { @apply text-slate-300 whitespace-pre-wrap break-words; }
.stream-output__line--error { @apply text-red-400; }
.stream-output__line--system { @apply text-slate-500 italic; }
.stream-output__line--tool { @apply text-slate-400; }
.stream-output__tool-tag { @apply inline-block text-xs px-1.5 py-0.5 rounded bg-blue-900/40 text-blue-300 mr-2 font-mono; }
.stream-output__cursor { @apply text-blue-400 animate-pulse; }
:deep(.stream-inline-code) { @apply bg-white/10 text-emerald-300 px-1 rounded text-xs; }
</style>
