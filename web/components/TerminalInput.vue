<template>
  <div class="terminal-input" :class="{ 'terminal-input--focused': focused }">
    <span class="terminal-input__prompt">❯</span>
    <input
      ref="inputEl"
      v-model="value"
      class="terminal-input__field"
      :placeholder="placeholder"
      :disabled="disabled"
      autocomplete="off"
      autocorrect="off"
      autocapitalize="off"
      spellcheck="false"
      @keydown.enter.prevent="onSubmit"
      @keydown.up.prevent="navigateHistory(-1)"
      @keydown.down.prevent="navigateHistory(1)"
      @focus="focused = true"
      @blur="focused = false"
    />
    <button v-if="value && !disabled" class="terminal-input__submit" @click="onSubmit">
      <span class="terminal-input__submit-key">↵</span>
    </button>
    <div v-if="disabled" class="terminal-input__spinner">
      <div class="terminal-input__dot" />
      <div class="terminal-input__dot terminal-input__dot--delay-1" />
      <div class="terminal-input__dot terminal-input__dot--delay-2" />
    </div>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{
  modelValue?: string
  placeholder?: string
  disabled?: boolean
  history?: string[]
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: string): void
  (e: 'submit', v: string): void
}>()

const inputEl = ref<HTMLInputElement | null>(null)
const focused = ref(false)
const historyIndex = ref(-1)

const value = computed({
  get: () => props.modelValue ?? '',
  set: v => emit('update:modelValue', v),
})

function onSubmit() {
  const v = value.value.trim()
  if (!v || props.disabled) return
  historyIndex.value = -1
  emit('submit', v)
}

function navigateHistory(dir: -1 | 1) {
  const hist = props.history ?? []
  if (!hist.length) return
  historyIndex.value = Math.max(-1, Math.min(hist.length - 1, historyIndex.value + dir))
  if (historyIndex.value >= 0) emit('update:modelValue', hist[historyIndex.value])
}

function focus() { inputEl.value?.focus() }
defineExpose({ focus })
</script>

<style scoped>
.terminal-input { @apply flex items-center gap-3 px-4 py-3 rounded-lg border border-white/10 bg-white/5 transition-colors duration-150; }
.terminal-input--focused { @apply border-blue-500/50 bg-blue-500/5; }
.terminal-input__prompt { @apply text-blue-400 font-mono text-sm select-none; }
.terminal-input__field { @apply flex-1 bg-transparent text-slate-100 font-mono text-sm outline-none placeholder-slate-600; }
.terminal-input__submit { @apply flex items-center justify-center w-6 h-6 rounded bg-blue-500/20 text-blue-400 hover:bg-blue-500/40 transition-colors; }
.terminal-input__submit-key { @apply text-xs font-mono; }
.terminal-input__spinner { @apply flex items-center gap-1; }
.terminal-input__dot { @apply w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce; }
.terminal-input__dot--delay-1 { animation-delay: 0.1s; }
.terminal-input__dot--delay-2 { animation-delay: 0.2s; }
</style>
