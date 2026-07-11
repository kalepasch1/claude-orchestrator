<template>
  <div class="flex flex-col h-full">
    <!-- Header -->
    <div class="border-b border-gray-800 px-6 py-3 flex items-center gap-3">
      <span class="text-lg">NL Admin</span>
      <span class="text-xs text-gray-500">Ask anything about your fleet</span>
      <button
        v-if="messages.length > 0"
        class="ml-auto text-xs text-gray-500 hover:text-gray-300 px-2 py-1 rounded hover:bg-gray-800"
        @click="clearChat"
      >
        Clear
      </button>
    </div>

    <!-- Messages -->
    <div ref="messagesContainer" class="flex-1 overflow-y-auto px-6 py-4 space-y-4">
      <!-- Empty state -->
      <div v-if="messages.length === 0" class="flex flex-col items-center justify-center h-full text-center">
        <div class="text-4xl mb-4 opacity-50">&#128172;</div>
        <h3 class="text-lg font-medium text-gray-300 mb-2">Fleet Intelligence</h3>
        <p class="text-sm text-gray-500 max-w-md mb-6">
          Ask natural language questions about your apps, users, events, and policies across the entire fleet.
        </p>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-lg">
          <button
            v-for="example in examples"
            :key="example"
            class="text-left text-xs px-3 py-2 rounded-lg bg-gray-900 border border-gray-800 text-gray-400 hover:text-gray-200 hover:border-indigo-500/50 transition-colors"
            @click="submitQuery(example)"
          >
            {{ example }}
          </button>
        </div>
      </div>

      <!-- Message list -->
      <div v-for="(msg, i) in messages" :key="i" class="max-w-3xl" :class="msg.role === 'user' ? 'ml-auto' : ''">
        <!-- User message -->
        <div v-if="msg.role === 'user'" class="bg-indigo-900/30 border border-indigo-800/50 rounded-lg px-4 py-2.5 text-sm inline-block max-w-lg ml-auto">
          {{ msg.content }}
        </div>

        <!-- Assistant message -->
        <div v-else class="space-y-3">
          <div class="bg-gray-900 border border-gray-800 rounded-lg px-4 py-3">
            <!-- Rendered markdown-ish response -->
            <div class="text-sm leading-relaxed prose-invert" v-html="renderResponse(msg.content)" />
          </div>

          <!-- Data tables if present -->
          <div v-if="msg.data && msg.data.length > 0">
            <div v-for="(d, j) in msg.data" :key="j" class="mt-2">
              <div class="text-xs text-gray-500 mb-1">
                {{ d.tool }}{{ d.input?.app ? ` (${d.input.app})` : '' }}{{ d.input?.table ? ` &mdash; ${d.input.table}` : '' }}
              </div>
              <div v-if="getTableRows(d.result)" class="overflow-x-auto bg-gray-900/50 border border-gray-800 rounded-lg">
                <table class="min-w-full text-xs">
                  <thead>
                    <tr class="border-b border-gray-800">
                      <th
                        v-for="col in getTableColumns(d.result)"
                        :key="col"
                        class="px-3 py-2 text-left text-gray-400 font-medium whitespace-nowrap"
                      >
                        {{ col }}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="(row, ri) in getTableRows(d.result).slice(0, 50)"
                      :key="ri"
                      class="border-b border-gray-800/50 hover:bg-gray-800/30"
                    >
                      <td
                        v-for="col in getTableColumns(d.result)"
                        :key="col"
                        class="px-3 py-1.5 text-gray-300 whitespace-nowrap max-w-xs truncate"
                      >
                        {{ formatCell(row[col]) }}
                      </td>
                    </tr>
                  </tbody>
                </table>
                <div v-if="getTableRows(d.result).length > 50" class="px-3 py-2 text-xs text-gray-500">
                  Showing 50 of {{ getTableRows(d.result).length }} rows
                </div>
              </div>
            </div>
          </div>

          <!-- Tool call count -->
          <div v-if="msg.toolCalls" class="text-xs text-gray-600">
            {{ msg.toolCalls }} API call{{ msg.toolCalls > 1 ? 's' : '' }} made
          </div>
        </div>
      </div>

      <!-- Loading state -->
      <div v-if="loading" class="max-w-3xl">
        <div class="bg-gray-900 border border-gray-800 rounded-lg px-4 py-3">
          <div class="flex items-center gap-2 text-sm text-gray-400">
            <span class="inline-block w-1.5 h-1.5 bg-indigo-400 rounded-full animate-pulse" />
            <span class="inline-block w-1.5 h-1.5 bg-indigo-400 rounded-full animate-pulse" style="animation-delay: 0.2s" />
            <span class="inline-block w-1.5 h-1.5 bg-indigo-400 rounded-full animate-pulse" style="animation-delay: 0.4s" />
            <span class="ml-1">Querying fleet...</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Input area -->
    <div class="border-t border-gray-800 px-6 py-3">
      <form class="flex gap-3 max-w-3xl" @submit.prevent="submitQuery(inputText)">
        <input
          v-model="inputText"
          type="text"
          placeholder="Ask about users, events, data across all apps..."
          class="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-4 py-2.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/50"
          :disabled="loading"
          @keydown.enter.exact.prevent="submitQuery(inputText)"
        />
        <button
          type="submit"
          :disabled="loading || !inputText.trim()"
          class="px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-800 disabled:text-gray-600 text-sm font-medium rounded-lg transition-colors"
        >
          Send
        </button>
      </form>
      <div class="text-xs text-gray-600 mt-1.5">
        Uses Claude to translate your question into API calls across the fleet
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  data?: any[]
  toolCalls?: number
}

const inputText = ref('')
const messages = ref<ChatMessage[]>([])
const loading = ref(false)
const messagesContainer = ref<HTMLElement>()

const examples = [
  'Show me all users across every app',
  'How many events happened in the last 24 hours?',
  'List all active auto-policies',
  'Which apps are currently configured?',
  'Find user kale@smrter.us across all apps',
  'What tables are available in the apparently database?',
]

function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

function clearChat() {
  messages.value = []
}

function renderResponse(text: string): string {
  // Simple markdown-to-HTML: tables, bold, code, headers, lists
  let html = escapeHtml(text)

  // Headers
  html = html.replace(/^### (.+)$/gm, '<h4 class="text-sm font-semibold text-gray-200 mt-3 mb-1">$1</h4>')
  html = html.replace(/^## (.+)$/gm, '<h3 class="text-base font-semibold text-gray-200 mt-3 mb-1">$1</h3>')

  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong class="text-gray-100">$1</strong>')

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code class="bg-gray-800 px-1 py-0.5 rounded text-indigo-300 text-xs">$1</code>')

  // Code blocks
  html = html.replace(/```[\s\S]*?```/g, (match) => {
    const code = match.replace(/```\w*\n?/, '').replace(/\n?```$/, '')
    return `<pre class="bg-gray-800 rounded p-3 text-xs overflow-x-auto my-2"><code>${code}</code></pre>`
  })

  // Markdown tables
  html = html.replace(/(\|.+\|(?:\n\|.+\|)+)/g, (tableBlock) => {
    const lines = tableBlock.trim().split('\n')
    if (lines.length < 2) return tableBlock

    const headerCells = lines[0].split('|').filter(c => c.trim())
    // Skip separator line
    const startIdx = lines[1].match(/^[\s|:-]+$/) ? 2 : 1
    const bodyLines = lines.slice(startIdx)

    let table = '<div class="overflow-x-auto my-2"><table class="min-w-full text-xs border border-gray-800 rounded">'
    table += '<thead><tr class="bg-gray-800/50">'
    for (const h of headerCells) {
      table += `<th class="px-3 py-1.5 text-left text-gray-400 font-medium">${h.trim()}</th>`
    }
    table += '</tr></thead><tbody>'
    for (const line of bodyLines) {
      const cells = line.split('|').filter(c => c.trim())
      table += '<tr class="border-t border-gray-800/50">'
      for (const c of cells) {
        table += `<td class="px-3 py-1.5 text-gray-300">${c.trim()}</td>`
      }
      table += '</tr>'
    }
    table += '</tbody></table></div>'
    return table
  })

  // Lists
  html = html.replace(/^- (.+)$/gm, '<li class="ml-4 text-gray-300">$1</li>')
  html = html.replace(/(<li[^>]*>.*<\/li>\n?)+/g, '<ul class="list-disc my-1">$&</ul>')

  // Numbered lists
  html = html.replace(/^\d+\. (.+)$/gm, '<li class="ml-4 text-gray-300">$1</li>')

  // Line breaks
  html = html.replace(/\n\n/g, '<br/><br/>')
  html = html.replace(/\n/g, '<br/>')

  return html
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function getTableRows(result: any): any[] | null {
  if (!result) return null
  if (Array.isArray(result.data) && result.data.length > 0) return result.data
  if (Array.isArray(result.users) && result.users.length > 0) return result.users
  if (Array.isArray(result.policies) && result.policies.length > 0) return result.policies
  if (Array.isArray(result.results) && result.results.length > 0) return result.results
  if (Array.isArray(result.incidents) && result.incidents.length > 0) return result.incidents
  if (Array.isArray(result.apps) && result.apps.length > 0) return result.apps
  if (Array.isArray(result.tables) && result.tables.length > 0) return result.tables
  return null
}

function getTableColumns(result: any): string[] {
  const rows = getTableRows(result)
  if (!rows || rows.length === 0) return []
  // Get columns from first row, limit to reasonable count
  const cols = Object.keys(rows[0])
  return cols.slice(0, 12)
}

function formatCell(value: any): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value).slice(0, 100)
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  const str = String(value)
  return str.length > 80 ? str.slice(0, 77) + '...' : str
}

async function submitQuery(query: string) {
  const trimmed = query.trim()
  if (!trimmed || loading.value) return

  inputText.value = ''
  messages.value.push({ role: 'user', content: trimmed })
  scrollToBottom()

  loading.value = true
  try {
    const result = await $fetch('/api/admin/nl-query', {
      method: 'POST',
      body: {
        query: trimmed,
        // Send last few exchanges as context
        history: messages.value
          .slice(-10)
          .filter(m => m.role === 'user' || m.role === 'assistant')
          .map(m => ({ role: m.role, content: m.content })),
      },
    })

    messages.value.push({
      role: 'assistant',
      content: (result as any).response || 'No response received.',
      data: (result as any).data,
      toolCalls: (result as any).toolCalls,
    })
  } catch (e: any) {
    messages.value.push({
      role: 'assistant',
      content: `Error: ${e.data?.message || e.message || 'Failed to process query'}`,
    })
  } finally {
    loading.value = false
    scrollToBottom()
  }
}
</script>
