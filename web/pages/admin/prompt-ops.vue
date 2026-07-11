<template>
  <div class="p-6">
    <h2 class="text-xl font-semibold mb-6">Prompt-Driven Ops</h2>

    <!-- Submit new prompt -->
    <div class="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
      <h3 class="text-sm font-medium text-gray-300 mb-3">Submit Command</h3>
      <p class="text-xs text-gray-500 mb-3">
        Write a natural-language admin command. Claude will parse it into fleet API calls.
      </p>
      <textarea
        v-model="promptContent"
        rows="6"
        placeholder="e.g., List all users across every app who signed up in the last 7 days.&#10;&#10;Or: Check health of all apps and report any that are down.&#10;&#10;Or: Create a policy to auto-disable users with failed logins > 10."
        class="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/50 font-mono"
        :disabled="submitting"
      />
      <div class="flex items-center gap-3 mt-3">
        <button
          class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-800 disabled:text-gray-600 text-sm font-medium rounded transition-colors"
          :disabled="!promptContent.trim() || submitting"
          @click="submitPrompt(false)"
        >
          {{ submitting ? 'Parsing...' : 'Parse Only' }}
        </button>
        <button
          class="px-4 py-2 bg-green-700 hover:bg-green-600 disabled:bg-gray-800 disabled:text-gray-600 text-sm font-medium rounded transition-colors"
          :disabled="!promptContent.trim() || submitting"
          @click="submitPrompt(true)"
        >
          {{ submitting ? 'Running...' : 'Parse & Execute' }}
        </button>
      </div>
    </div>

    <!-- Quick commands -->
    <div class="flex flex-wrap gap-2 mb-6">
      <button
        v-for="cmd in quickCommands"
        :key="cmd"
        class="text-xs px-3 py-1.5 rounded-lg bg-gray-900 border border-gray-800 text-gray-400 hover:text-gray-200 hover:border-indigo-500/50 transition-colors"
        @click="promptContent = cmd"
      >
        {{ cmd }}
      </button>
    </div>

    <!-- Operations list -->
    <div class="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
      <div class="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
        <h3 class="text-sm font-medium text-gray-300">Recent Operations</h3>
        <button
          class="text-xs text-gray-500 hover:text-gray-300 px-2 py-1 rounded hover:bg-gray-800"
          @click="loadOps"
        >
          Refresh
        </button>
      </div>

      <div v-if="ops.length === 0" class="p-8 text-center text-gray-500">
        No prompt operations yet. Submit a command above.
      </div>

      <div v-for="op in ops" :key="op.id" class="border-b border-gray-800 last:border-0">
        <div class="px-4 py-3 hover:bg-gray-800/30">
          <!-- Header -->
          <div class="flex items-center gap-3 mb-2">
            <span
              class="text-xs px-2 py-0.5 rounded font-medium"
              :class="statusClass(op.status)"
            >
              {{ op.status }}
            </span>
            <span class="text-xs text-gray-500 font-mono">{{ op.filename }}</span>
            <span class="text-xs text-gray-600 ml-auto">{{ timeAgo(op.createdAt) }}</span>
          </div>

          <!-- Intent -->
          <div v-if="op.intent" class="text-sm text-gray-300 mb-2">
            {{ op.intent }}
          </div>

          <!-- Content preview -->
          <div class="text-xs text-gray-500 mb-2 font-mono bg-gray-800/50 rounded px-3 py-2 max-h-20 overflow-hidden">
            {{ op.content.slice(0, 200) }}{{ op.content.length > 200 ? '...' : '' }}
          </div>

          <!-- Actions -->
          <div v-if="op.actions && op.actions.length > 0" class="mb-2">
            <div class="text-xs text-gray-500 mb-1">Actions ({{ op.actions.length }}):</div>
            <div v-for="(action, i) in op.actions" :key="i" class="flex items-center gap-2 text-xs ml-2 mb-0.5">
              <span class="text-indigo-400 font-mono">{{ action.method }}</span>
              <span class="text-gray-400 font-mono">{{ action.endpoint }}</span>
              <span v-if="action.description" class="text-gray-600">{{ action.description }}</span>
            </div>
          </div>

          <!-- Result -->
          <div v-if="op.result" class="mt-2">
            <div class="text-xs text-gray-500 mb-1">Result:</div>
            <pre class="text-xs text-gray-300 bg-gray-800/50 rounded px-3 py-2 overflow-x-auto max-h-40 whitespace-pre-wrap">{{ op.result }}</pre>
          </div>

          <!-- Error -->
          <div v-if="op.error" class="text-xs text-red-400 mt-1">{{ op.error }}</div>

          <!-- Execute button for parsed-but-not-executed ops -->
          <div v-if="op.status === 'parsed'" class="mt-2">
            <button
              class="text-xs px-3 py-1 rounded bg-green-900/50 text-green-300 hover:bg-green-800/50 transition-colors"
              @click="executeOp(op.id)"
            >
              Approve & Execute
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const promptContent = ref('')
const submitting = ref(false)
const ops = ref<any[]>([])

const quickCommands = [
  'List all users across every app',
  'Check health of all fleet apps',
  'Show recent fleet events and incidents',
  'List all auto-resolution policies',
  'Show tables in the apparently database',
]

async function loadOps() {
  try {
    const data = await $fetch('/api/admin/prompt-ops')
    ops.value = (data as any).ops || []
  } catch {}
}

async function submitPrompt(autoExecute: boolean) {
  if (!promptContent.value.trim() || submitting.value) return
  submitting.value = true
  try {
    await $fetch('/api/admin/prompt-ops/submit', {
      method: 'POST',
      body: {
        content: promptContent.value.trim(),
        autoExecute,
      },
    })
    promptContent.value = ''
    await loadOps()
  } catch {}
  submitting.value = false
}

async function executeOp(id: string) {
  try {
    await $fetch('/api/admin/prompt-ops/submit', {
      method: 'POST',
      body: { content: '', autoExecute: true },
    })
    await loadOps()
  } catch {}
}

function statusClass(status: string): string {
  switch (status) {
    case 'complete': return 'bg-green-900/50 text-green-300'
    case 'failed': return 'bg-red-900/50 text-red-300'
    case 'executing':
    case 'approved': return 'bg-yellow-900/50 text-yellow-300'
    case 'parsed': return 'bg-blue-900/50 text-blue-300'
    default: return 'bg-gray-800 text-gray-400'
  }
}

function timeAgo(iso: string): string {
  const d = new Date(iso)
  const secs = Math.floor((Date.now() - d.getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

onMounted(() => {
  loadOps()
})
</script>
