<script setup lang="ts">
definePageMeta({ layout: 'admin' })

interface TerminalOutput {
  type: 'command' | 'text' | 'tool' | 'error' | 'system'
  content: string
  tool?: string
  input?: any
  timestamp: number
}

interface HistoryEntry {
  command: string
  outputs: TerminalOutput[]
  loading: boolean
}

const inputRef = ref<HTMLInputElement | null>(null)
const scrollRef = ref<HTMLElement | null>(null)
const command = ref('')
const history = ref<HistoryEntry[]>([])
const commandHistory = ref<string[]>([])
const historyIndex = ref(-1)
const sessionId = ref('')
const conversationHistory = ref<Array<{ role: string; content: string }>>([])
const expandedTools = ref<Set<number>>(new Set())

// Quick-action presets
const presets = [
  { label: 'git status', cmd: 'git status' },
  { label: 'git log', cmd: 'git log --oneline -10' },
  { label: 'list pages', cmd: 'ls web/pages/' },
  { label: 'list components', cmd: 'ls web/components/' },
  { label: 'list API routes', cmd: 'find web/server/api -name "*.ts" | head -30' },
  { label: 'npm run build', cmd: 'cd web && npm run build' },
  { label: 'check deploys', cmd: 'check the latest vercel deployment status' },
  { label: 'run tests', cmd: 'cd web && npx vitest run --reporter=verbose 2>&1 | tail -40' },
]

function scrollToBottom() {
  nextTick(() => {
    if (scrollRef.value) {
      scrollRef.value.scrollTop = scrollRef.value.scrollHeight
    }
  })
}

function focusInput() {
  inputRef.value?.focus()
}

function toggleTool(index: number) {
  if (expandedTools.value.has(index)) {
    expandedTools.value.delete(index)
  } else {
    expandedTools.value.add(index)
  }
}

function formatToolLabel(tool: string, input: any): string {
  switch (tool) {
    case 'run_command': return `$ ${input?.command || 'command'}`
    case 'read_file': return `cat ${input?.path || 'file'}`
    case 'write_file': return `write → ${input?.path || 'file'}`
    case 'edit_file': return `edit → ${input?.path || 'file'}`
    case 'search_code': return `grep ${input?.pattern || 'pattern'}`
    case 'list_directory': return `ls ${input?.path || '.'}`
    case 'deploy_check': return 'deploy status'
    case 'supabase_query': return `sql: ${(input?.sql || '').slice(0, 40)}`
    default: return tool
  }
}

async function execute(cmd?: string) {
  const text = (cmd || command.value).trim()
  if (!text) return

  command.value = ''
  historyIndex.value = -1
  commandHistory.value.unshift(text)
  if (commandHistory.value.length > 100) commandHistory.value.length = 100

  const entry: HistoryEntry = {
    command: text,
    outputs: [],
    loading: true,
  }
  history.value.push(entry)
  scrollToBottom()

  try {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 90_000) // 90s timeout
    const result: any = await $fetch('/api/terminal/execute', {
      method: 'POST',
      signal: controller.signal,
      body: {
        command: text,
        history: conversationHistory.value.slice(-20),
        sessionId: sessionId.value || undefined,
      },
    })
    clearTimeout(timeout)

    if (result.sessionId) sessionId.value = result.sessionId

    // Add to conversation history for context
    conversationHistory.value.push({ role: 'user', content: text })

    for (const output of (result.outputs || [])) {
      entry.outputs.push({
        type: output.type,
        content: output.content,
        tool: output.tool,
        input: output.input,
        timestamp: Date.now(),
      })
    }

    // Build assistant summary for conversation context
    const summary = (result.outputs || [])
      .map((o: any) => o.content)
      .join('\n')
      .slice(0, 4000)
    conversationHistory.value.push({ role: 'assistant', content: summary })
  } catch (e: any) {
    const isTimeout = e?.name === 'AbortError' || e?.message?.includes('aborted')
    entry.outputs.push({
      type: 'error',
      content: isTimeout
        ? 'Request timed out (90s). The operation may still be running. Try a simpler command or break it into steps.'
        : (e?.data?.message || e?.message || 'Execution failed'),
      timestamp: Date.now(),
    })
  } finally {
    entry.loading = false
    scrollToBottom()
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (historyIndex.value < commandHistory.value.length - 1) {
      historyIndex.value++
      command.value = commandHistory.value[historyIndex.value]
    }
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (historyIndex.value > 0) {
      historyIndex.value--
      command.value = commandHistory.value[historyIndex.value]
    } else {
      historyIndex.value = -1
      command.value = ''
    }
  }
}

function clearTerminal() {
  history.value = []
  expandedTools.value.clear()
  history.value.push({
    command: '',
    outputs: [{ type: 'system', content: 'Terminal cleared. Session context preserved.', timestamp: Date.now() }],
    loading: false,
  })
}

function resetSession() {
  history.value = []
  conversationHistory.value = []
  commandHistory.value = []
  expandedTools.value.clear()
  sessionId.value = ''
}

function handleGlobalKeydown(e: KeyboardEvent) {
  if (e.ctrlKey && e.key === 'l') {
    e.preventDefault()
    clearTerminal()
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleGlobalKeydown)
  history.value.push({
    command: '',
    outputs: [{
      type: 'system',
      content: `Madeus Development Terminal v1.0
Connected to orchestrator repository. Full code execution available.
Type commands, ask questions, or describe what to build.

Quick start: git status | ls web/ | "create a new API endpoint for X"
Shortcuts: Ctrl+L clear | ↑↓ history
`,
      timestamp: Date.now(),
    }],
    loading: false,
  })
  focusInput()
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleGlobalKeydown)
})
</script>

<template>
  <div class="terminal-container" @click="focusInput">
    <!-- Terminal header -->
    <div class="terminal-header">
      <div class="terminal-title">
        <span class="terminal-dot red" />
        <span class="terminal-dot yellow" />
        <span class="terminal-dot green" />
        <span class="terminal-label">Development Terminal</span>
        <span class="terminal-session" v-if="sessionId">session:{{ sessionId.slice(0, 8) }}</span>
      </div>
      <div class="terminal-actions">
        <button
          v-for="preset in presets"
          :key="preset.cmd"
          class="terminal-preset"
          @click.stop="execute(preset.cmd)"
        >
          {{ preset.label }}
        </button>
        <button class="terminal-btn" @click.stop="clearTerminal" title="Clear terminal (Ctrl+L)">Clear</button>
        <button class="terminal-btn terminal-btn--danger" @click.stop="resetSession" title="Reset session and context">Reset</button>
      </div>
    </div>

    <!-- Terminal output area -->
    <div ref="scrollRef" class="terminal-output">
      <div v-for="(entry, ei) in history" :key="ei" class="terminal-entry">
        <!-- Command line -->
        <div v-if="entry.command" class="terminal-command-line">
          <span class="terminal-prompt">madeus</span>
          <span class="terminal-prompt-sep">:</span>
          <span class="terminal-prompt-dir">~/orchestrator</span>
          <span class="terminal-prompt-char">$</span>
          <span class="terminal-command-text">{{ entry.command }}</span>
        </div>

        <!-- Outputs -->
        <div v-for="(output, oi) in entry.outputs" :key="oi" class="terminal-output-block">
          <!-- System messages -->
          <pre v-if="output.type === 'system'" class="terminal-system">{{ output.content }}</pre>

          <!-- Tool execution output -->
          <div v-else-if="output.type === 'tool'" class="terminal-tool">
            <button
              class="terminal-tool-header"
              @click.stop="toggleTool(ei * 100 + oi)"
            >
              <span class="terminal-tool-icon">{{ expandedTools.has(ei * 100 + oi) ? '▼' : '▶' }}</span>
              <span class="terminal-tool-label">{{ formatToolLabel(output.tool!, output.input) }}</span>
              <span class="terminal-tool-badge">{{ output.tool }}</span>
            </button>
            <pre
              v-if="expandedTools.has(ei * 100 + oi) || !entry.outputs.some(o => o.type === 'text')"
              class="terminal-tool-output"
            >{{ output.content }}</pre>
          </div>

          <!-- Text response -->
          <div v-else-if="output.type === 'text'" class="terminal-text" v-html="renderMarkdown(output.content)" />

          <!-- Error -->
          <pre v-else-if="output.type === 'error'" class="terminal-error">Error: {{ output.content }}</pre>
        </div>

        <!-- Loading indicator -->
        <div v-if="entry.loading" class="terminal-loading">
          <span class="terminal-spinner" />
          <span>executing...</span>
        </div>
      </div>
    </div>

    <!-- Input area -->
    <div class="terminal-input-area">
      <span class="terminal-prompt">madeus</span>
      <span class="terminal-prompt-sep">:</span>
      <span class="terminal-prompt-dir">~/orchestrator</span>
      <span class="terminal-prompt-char">$</span>
      <input
        ref="inputRef"
        v-model="command"
        class="terminal-input"
        type="text"
        placeholder="Type a command, describe code to write, or ask a question..."
        spellcheck="false"
        autocomplete="off"
        @keydown.enter.exact.prevent="execute()"
        @keydown="handleKeydown"
      />
    </div>
  </div>
</template>

<script lang="ts">
// Render markdown-ish text for terminal output
function renderMarkdown(text: string): string {
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // Code blocks
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    return `<pre class="terminal-code-block"><code class="lang-${lang || 'text'}">${code.trim()}</code></pre>`
  })

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code class="terminal-inline-code">$1</code>')

  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')

  // Headers
  html = html.replace(/^### (.+)$/gm, '<div class="terminal-h3">$1</div>')
  html = html.replace(/^## (.+)$/gm, '<div class="terminal-h2">$1</div>')

  // Lists
  html = html.replace(/^- (.+)$/gm, '<div class="terminal-list-item">  · $1</div>')

  // Linebreaks
  html = html.replace(/\n\n/g, '<br/>')
  html = html.replace(/\n/g, '<br/>')

  return html
}
</script>

<style scoped>
.terminal-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0d1117;
  color: #c9d1d9;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', ui-monospace, monospace;
  font-size: 12px;
  line-height: 1.6;
  cursor: text;
}

/* Header */
.terminal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 14px;
  background: #161b22;
  border-bottom: 1px solid #30363d;
  flex-shrink: 0;
  overflow-x: auto;
}

.terminal-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.terminal-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.terminal-dot.red { background: #ff5f57; }
.terminal-dot.yellow { background: #febc2e; }
.terminal-dot.green { background: #28c840; }

.terminal-label {
  font-size: 11px;
  font-weight: 600;
  color: #8b949e;
  margin-left: 6px;
}

.terminal-session {
  font-size: 9px;
  color: #484f58;
  padding: 2px 6px;
  background: #21262d;
  border-radius: 4px;
}

.terminal-actions {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.terminal-preset {
  padding: 3px 8px;
  background: #21262d;
  border: 1px solid #30363d;
  border-radius: 4px;
  color: #58a6ff;
  font-size: 9px;
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s;
}
.terminal-preset:hover {
  background: #30363d;
  border-color: #58a6ff;
}

.terminal-btn {
  padding: 3px 10px;
  background: #21262d;
  border: 1px solid #30363d;
  border-radius: 4px;
  color: #8b949e;
  font-size: 9px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s;
}
.terminal-btn:hover {
  background: #30363d;
  color: #c9d1d9;
}
.terminal-btn--danger:hover {
  border-color: #f85149;
  color: #f85149;
}

/* Output area */
.terminal-output {
  flex: 1;
  overflow-y: auto;
  padding: 12px 14px;
}

.terminal-entry {
  margin-bottom: 12px;
}

.terminal-command-line {
  display: flex;
  align-items: baseline;
  gap: 0;
  margin-bottom: 4px;
  flex-wrap: wrap;
}

.terminal-prompt {
  color: #7ee787;
  font-weight: 600;
}
.terminal-prompt-sep {
  color: #8b949e;
}
.terminal-prompt-dir {
  color: #79c0ff;
}
.terminal-prompt-char {
  color: #8b949e;
  margin-right: 8px;
  margin-left: 1px;
}
.terminal-command-text {
  color: #f0f6fc;
  word-break: break-all;
}

/* Output blocks */
.terminal-output-block {
  margin: 2px 0;
}

.terminal-system {
  color: #484f58;
  margin: 0;
  font-family: inherit;
  font-size: inherit;
  white-space: pre-wrap;
  word-break: break-word;
}

.terminal-tool {
  margin: 4px 0;
  border-left: 2px solid #30363d;
}

.terminal-tool-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  background: none;
  border: none;
  color: #8b949e;
  font-family: inherit;
  font-size: 10px;
  cursor: pointer;
  width: 100%;
  text-align: left;
}
.terminal-tool-header:hover {
  color: #c9d1d9;
  background: #161b22;
}

.terminal-tool-icon {
  font-size: 8px;
  width: 10px;
  flex-shrink: 0;
}

.terminal-tool-label {
  color: #d2a8ff;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.terminal-tool-badge {
  padding: 1px 5px;
  background: #21262d;
  border-radius: 3px;
  font-size: 8px;
  color: #484f58;
  flex-shrink: 0;
}

.terminal-tool-output {
  margin: 0;
  padding: 6px 8px 6px 18px;
  color: #8b949e;
  font-family: inherit;
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 400px;
  overflow-y: auto;
  background: #0d1117;
}

.terminal-text {
  color: #c9d1d9;
  padding: 4px 0;
  line-height: 1.65;
}

.terminal-text :deep(.terminal-code-block) {
  margin: 6px 0;
  padding: 8px 10px;
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 4px;
  overflow-x: auto;
  font-size: 11px;
}
.terminal-text :deep(.terminal-code-block code) {
  color: #e6edf3;
}

.terminal-text :deep(.terminal-inline-code) {
  padding: 1px 5px;
  background: #21262d;
  border-radius: 3px;
  color: #79c0ff;
  font-size: 11px;
}

.terminal-text :deep(strong) {
  color: #f0f6fc;
  font-weight: 600;
}

.terminal-text :deep(.terminal-h2) {
  color: #f0f6fc;
  font-weight: 700;
  font-size: 13px;
  margin: 10px 0 4px;
}
.terminal-text :deep(.terminal-h3) {
  color: #e6edf3;
  font-weight: 600;
  font-size: 12px;
  margin: 8px 0 3px;
}
.terminal-text :deep(.terminal-list-item) {
  color: #8b949e;
}

.terminal-error {
  color: #f85149;
  margin: 0;
  font-family: inherit;
  font-size: inherit;
  white-space: pre-wrap;
  word-break: break-word;
  padding: 4px 8px;
  background: #f851490d;
  border-left: 2px solid #f85149;
}

/* Loading */
.terminal-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  color: #484f58;
  font-size: 11px;
}

.terminal-spinner {
  width: 8px;
  height: 8px;
  border: 1.5px solid #30363d;
  border-top-color: #58a6ff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Input area */
.terminal-input-area {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 10px 14px;
  background: #0d1117;
  border-top: 1px solid #21262d;
  flex-shrink: 0;
}

.terminal-input {
  flex: 1;
  background: none;
  border: none;
  outline: none;
  color: #f0f6fc;
  font-family: inherit;
  font-size: inherit;
  caret-color: #58a6ff;
}
.terminal-input::placeholder {
  color: #30363d;
}

/* Scrollbar */
.terminal-output::-webkit-scrollbar {
  width: 6px;
}
.terminal-output::-webkit-scrollbar-track {
  background: transparent;
}
.terminal-output::-webkit-scrollbar-thumb {
  background: #30363d;
  border-radius: 3px;
}
.terminal-output::-webkit-scrollbar-thumb:hover {
  background: #484f58;
}

/* Responsive */
@media (max-width: 820px) {
  .terminal-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
  }
  .terminal-actions {
    flex-wrap: wrap;
    gap: 3px;
  }
}
</style>
