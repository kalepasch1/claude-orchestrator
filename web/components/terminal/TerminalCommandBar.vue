<template>
  <div class="command-bar border-t border-slate-800 bg-slate-900/80">
    <div class="flex items-center px-3 py-2">
      <span class="text-emerald-400 mr-2 font-bold text-sm">$</span>
      <input
        ref="inputEl"
        v-model="currentInput"
        type="text"
        placeholder="Type a command... (help for available commands)"
        class="flex-1 bg-transparent border-none text-sm text-slate-200 placeholder-slate-600 focus:outline-none font-mono"
        @keydown.enter="submit"
        @keydown.up.prevent="historyUp"
        @keydown.down.prevent="historyDown"
        @keydown.tab.prevent="autocomplete"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

const props = defineProps<{
  history: string[]
}>()

const emit = defineEmits<{
  execute: [command: string]
}>()

const currentInput = ref('')
const historyIndex = ref(-1)
const inputEl = ref<HTMLInputElement>()

function submit() {
  const cmd = currentInput.value.trim()
  if (!cmd) return
  emit('execute', cmd)
  currentInput.value = ''
  historyIndex.value = -1
}

function historyUp() {
  if (historyIndex.value < props.history.length - 1) {
    historyIndex.value++
    currentInput.value = props.history[historyIndex.value]
  }
}

function historyDown() {
  if (historyIndex.value > 0) {
    historyIndex.value--
    currentInput.value = props.history[historyIndex.value]
  } else {
    historyIndex.value = -1
    currentInput.value = ''
  }
}

const commands = ['clear', 'refresh', 'status', 'deploy', 'cascade', 'help']

function autocomplete() {
  const input = currentInput.value.trim().toLowerCase()
  if (!input) return
  const match = commands.find(c => c.startsWith(input))
  if (match) currentInput.value = match + ' '
}

onMounted(() => {
  inputEl.value?.focus()
})
</script>
