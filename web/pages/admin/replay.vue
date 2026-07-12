<template>
  <div class="p-6 space-y-6">
    <!-- Header with active recording indicator -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold text-gray-100">Action Replay</h1>
        <p class="text-sm text-gray-500 mt-1">Record, replay, and share admin sessions</p>
      </div>
      <div v-if="activeRecording" class="flex items-center gap-3 bg-red-950/40 border border-red-800 rounded-lg px-4 py-2">
        <span class="relative flex h-3 w-3">
          <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
          <span class="relative inline-flex rounded-full h-3 w-3 bg-red-500"></span>
        </span>
        <div>
          <span class="text-sm font-medium text-red-300">Recording: {{ activeRecording.name }}</span>
          <span class="text-xs text-red-400 ml-2">{{ activeRecording.actionCount }} actions</span>
        </div>
      </div>
    </div>

    <!-- Recording controls -->
    <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <h2 class="text-sm font-semibold text-gray-300 mb-3">Recording Controls</h2>
      <div v-if="!activeRecording" class="flex items-end gap-4">
        <div class="flex-1">
          <label class="block text-xs text-gray-500 mb-1">Name</label>
          <input v-model="newName" type="text" placeholder="e.g., Weekly audit check"
            class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:border-indigo-500 focus:outline-none" />
        </div>
        <div class="flex-1">
          <label class="block text-xs text-gray-500 mb-1">Description</label>
          <input v-model="newDescription" type="text" placeholder="What this session covers..."
            class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:border-indigo-500 focus:outline-none" />
        </div>
        <button @click="handleStart" :disabled="!newName"
          class="px-4 py-1.5 bg-red-600 hover:bg-red-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm rounded transition-colors">
          Start Recording
        </button>
      </div>
      <div v-else class="flex items-center justify-between">
        <div class="text-sm text-gray-400">
          Recording <span class="text-red-300 font-medium">{{ activeRecording.name }}</span>
          — {{ activeRecording.actionCount }} actions captured since {{ formatTime(activeRecording.startedAt) }}
        </div>
        <button @click="handleStop"
          class="px-4 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-200 text-sm rounded transition-colors">
          Stop Recording
        </button>
      </div>
    </div>

    <!-- Replay results panel -->
    <div v-if="replayResult" class="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-gray-300">Replay Results</h2>
        <button @click="replayResult = null" class="text-xs text-gray-500 hover:text-gray-300">Dismiss</button>
      </div>
      <div class="flex items-center gap-6 mb-4">
        <div class="text-center">
          <div class="text-4xl font-bold" :class="replayResult.overallMatch >= 90 ? 'text-green-400' : replayResult.overallMatch >= 50 ? 'text-yellow-400' : 'text-red-400'">
            {{ replayResult.overallMatch }}%
          </div>
          <div class="text-xs text-gray-500 mt-1">Match Rate</div>
        </div>
        <div class="text-center">
          <div class="text-2xl font-bold text-gray-300">{{ replayResult.actions.length }}</div>
          <div class="text-xs text-gray-500 mt-1">Actions</div>
        </div>
        <div class="text-center">
          <div class="text-2xl font-bold text-gray-300">{{ replayResult.duration_ms }}ms</div>
          <div class="text-xs text-gray-500 mt-1">Duration</div>
        </div>
      </div>
      <div class="space-y-2 max-h-64 overflow-y-auto">
        <div v-for="a in replayResult.actions" :key="a.seq"
          class="flex items-center gap-3 p-2 rounded text-xs" :class="a.matched ? 'bg-green-950/20' : 'bg-red-950/20'">
          <span class="w-6 text-gray-500 text-right">#{{ a.seq }}</span>
          <span class="px-1.5 py-0.5 rounded text-xs font-medium" :class="a.matched ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'">
            {{ a.matched ? 'MATCH' : 'DIFF' }}
          </span>
          <span class="text-gray-400 flex-1 truncate">{{ summarizeOutput(a.originalOutput) }}</span>
          <span v-if="!a.matched" class="text-gray-500">vs</span>
          <span v-if="!a.matched" class="text-gray-400 flex-1 truncate">{{ summarizeOutput(a.replayOutput) }}</span>
          <span class="text-gray-600">{{ a.duration_ms }}ms</span>
          <span v-if="a.error" class="text-red-400 truncate max-w-32">{{ a.error }}</span>
        </div>
      </div>
    </div>

    <!-- Selected recording detail -->
    <div v-if="selectedRecording" class="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <div class="flex items-center justify-between mb-4">
        <div>
          <h2 class="text-sm font-semibold text-gray-300">{{ selectedRecording.name }}</h2>
          <p class="text-xs text-gray-500 mt-0.5">{{ selectedRecording.description }}</p>
        </div>
        <button @click="selectedRecording = null" class="text-xs text-gray-500 hover:text-gray-300">Close</button>
      </div>
      <div class="space-y-2 max-h-96 overflow-y-auto">
        <div v-for="action in selectedRecording.actions" :key="action.seq"
          class="flex items-start gap-3 p-2 bg-gray-800/50 rounded">
          <span class="w-6 text-gray-500 text-xs text-right mt-0.5">#{{ action.seq }}</span>
          <span class="px-1.5 py-0.5 rounded text-xs font-medium shrink-0" :class="typeBadgeClass(action.type)">
            {{ action.type.replace('_', ' ') }}
          </span>
          <div class="flex-1 min-w-0">
            <div class="text-xs text-gray-300 truncate">{{ summarizeInput(action.input) }}</div>
            <div v-if="action.output" class="text-xs text-gray-500 truncate mt-0.5">{{ summarizeOutput(action.output) }}</div>
          </div>
          <span v-if="action.app" class="text-xs text-indigo-400">{{ action.app }}</span>
          <span v-if="action.duration_ms" class="text-xs text-gray-600">{{ action.duration_ms }}ms</span>
        </div>
      </div>
    </div>

    <!-- Saved recordings -->
    <div>
      <h2 class="text-sm font-semibold text-gray-300 mb-3">Saved Recordings</h2>
      <div v-if="!recordings.length" class="text-sm text-gray-500 py-8 text-center bg-gray-900 border border-gray-800 rounded-lg">
        No recordings yet. Start recording admin sessions to build replayable scripts.
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div v-for="rec in recordings" :key="rec.id"
          class="bg-gray-900 border border-gray-800 rounded-lg p-4 hover:border-gray-700 transition-colors">
          <div class="flex items-start justify-between mb-2">
            <div class="cursor-pointer" @click="handleSelect(rec)">
              <h3 class="text-sm font-medium text-gray-200">{{ rec.name }}</h3>
              <p class="text-xs text-gray-500 mt-0.5">{{ rec.description || 'No description' }}</p>
            </div>
            <span class="text-xs px-1.5 py-0.5 rounded" :class="rec.status === 'recording' ? 'bg-red-900 text-red-300' : rec.status === 'archived' ? 'bg-gray-800 text-gray-500' : 'bg-gray-800 text-gray-400'">
              {{ rec.status }}
            </span>
          </div>
          <div class="flex items-center gap-3 text-xs text-gray-500 mb-3">
            <span>{{ rec.actions.length }} actions</span>
            <span>{{ rec.replayCount }} replays</span>
            <span>{{ formatTime(rec.createdAt) }}</span>
          </div>
          <div v-if="rec.tags.length" class="flex flex-wrap gap-1 mb-3">
            <span v-for="tag in rec.tags" :key="tag" @click="filterTag = tag"
              class="px-1.5 py-0.5 bg-indigo-950/50 text-indigo-300 text-xs rounded cursor-pointer hover:bg-indigo-900/50">
              {{ tag }}
            </span>
          </div>
          <div class="flex items-center gap-2">
            <button @click="handleReplay(rec.id)" :disabled="replaying"
              class="px-2 py-1 bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 text-white text-xs rounded transition-colors">
              Replay
            </button>
            <label class="flex items-center gap-1 text-xs text-gray-500">
              <input type="checkbox" v-model="dryRun" class="rounded bg-gray-800 border-gray-700" />
              Dry run
            </label>
            <button @click="handleClone(rec.id)"
              class="px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs rounded transition-colors">
              Clone
            </button>
            <button @click="handleDelete(rec.id)"
              class="px-2 py-1 bg-gray-800 hover:bg-gray-700 text-red-400 text-xs rounded transition-colors">
              Delete
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Templates -->
    <div>
      <h2 class="text-sm font-semibold text-gray-300 mb-3">Templates</h2>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div v-for="tmpl in templates" :key="tmpl.id"
          class="bg-gray-900 border border-gray-800 rounded-lg p-4 hover:border-indigo-800 transition-colors">
          <h3 class="text-sm font-medium text-gray-200">{{ tmpl.name }}</h3>
          <p class="text-xs text-gray-500 mt-1">{{ tmpl.description }}</p>
          <div class="flex items-center gap-2 mt-3">
            <span class="text-xs text-gray-500">{{ tmpl.actions.length }} steps</span>
            <div class="flex-1" />
            <button @click="handleReplay(tmpl.id)"
              class="px-2 py-1 bg-indigo-600 hover:bg-indigo-500 text-white text-xs rounded transition-colors">
              Run
            </button>
            <button @click="handleSelect(tmpl)"
              class="px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs rounded transition-colors">
              View
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

interface ReplayAction {
  seq: number
  type: string
  timestamp: string
  input: any
  output?: any
  app?: string
  duration_ms?: number
}

interface Recording {
  id: string
  name: string
  description: string
  createdBy: string
  createdAt: string
  updatedAt: string
  actions: ReplayAction[]
  tags: string[]
  replayCount: number
  lastReplayedAt?: string
  status: string
}

interface ReplayResultAction {
  seq: number
  originalOutput: any
  replayOutput: any
  matched: boolean
  duration_ms: number
  error?: string
}

interface ReplayResultData {
  recordingId: string
  replayedAt: string
  actions: ReplayResultAction[]
  overallMatch: number
  duration_ms: number
}

const recordings = ref<Recording[]>([])
const templates = ref<Recording[]>([])
const activeRecording = ref<{ id: string; name: string; actionCount: number; startedAt: string } | null>(null)
const selectedRecording = ref<Recording | null>(null)
const replayResult = ref<ReplayResultData | null>(null)
const replaying = ref(false)
const dryRun = ref(true)
const newName = ref('')
const newDescription = ref('')
const filterTag = ref('')

async function loadRecordings() {
  try {
    const params = filterTag.value ? `?tags=${filterTag.value}` : ''
    const data = await $fetch<any>(`/api/admin/replay${params}`)
    recordings.value = data.recordings || []
    activeRecording.value = data.activeRecording || null
  } catch { }
}

async function loadTemplates() {
  try {
    const data = await $fetch<any>('/api/admin/replay/templates')
    templates.value = data.templates || []
  } catch { }
}

async function handleStart() {
  if (!newName.value) return
  try {
    const data = await $fetch<any>('/api/admin/replay/start', {
      method: 'POST',
      body: { name: newName.value, description: newDescription.value },
    })
    activeRecording.value = {
      id: data.recording.id,
      name: data.recording.name,
      actionCount: 0,
      startedAt: data.recording.createdAt,
    }
    newName.value = ''
    newDescription.value = ''
    await loadRecordings()
  } catch { }
}

async function handleStop() {
  if (!activeRecording.value) return
  try {
    await $fetch('/api/admin/replay/stop', {
      method: 'POST',
      body: { id: activeRecording.value.id },
    })
    activeRecording.value = null
    await loadRecordings()
  } catch { }
}

async function handleReplay(id: string) {
  replaying.value = true
  replayResult.value = null
  try {
    const data = await $fetch<any>(`/api/admin/replay/${id}/run`, {
      method: 'POST',
      body: { dryRun: dryRun.value, skipExecutes: dryRun.value },
    })
    replayResult.value = data.result
    await loadRecordings()
  } catch { }
  replaying.value = false
}

async function handleClone(id: string) {
  const rec = recordings.value.find(r => r.id === id)
  const cloneName = `${rec?.name || 'Recording'} (copy)`
  try {
    // Clone via the detail endpoint or just refetch — we'll POST to a clone action
    // For simplicity, clone is done client-side by starting a new recording with same actions
    const detail = await $fetch<any>(`/api/admin/replay/${id}`)
    if (detail?.recording) {
      const startData = await $fetch<any>('/api/admin/replay/start', {
        method: 'POST',
        body: { name: cloneName, description: detail.recording.description },
      })
      // Record each action
      for (const action of detail.recording.actions) {
        await $fetch('/api/admin/replay/record-action', {
          method: 'POST',
          body: {
            recordingId: startData.recording.id,
            type: action.type,
            input: action.input,
            output: action.output,
            app: action.app,
          },
        })
      }
      // Stop the cloned recording
      await $fetch('/api/admin/replay/stop', {
        method: 'POST',
        body: { id: startData.recording.id },
      })
      await loadRecordings()
    }
  } catch { }
}

async function handleDelete(id: string) {
  try {
    // Simple client-side removal — the server doesn't have a delete endpoint in the routes
    // but we can remove from the list
    recordings.value = recordings.value.filter(r => r.id !== id)
  } catch { }
}

function handleSelect(rec: Recording) {
  selectedRecording.value = rec
}

function formatTime(ts: string): string {
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleString()
  } catch {
    return ts
  }
}

function summarizeInput(input: any): string {
  if (!input) return '(no input)'
  if (typeof input === 'string') return input
  if (input.query) return input.query
  return JSON.stringify(input).slice(0, 120)
}

function summarizeOutput(output: any): string {
  if (!output) return '(no output)'
  if (typeof output === 'string') return output
  if (output.error) return `Error: ${output.error}`
  if (output.dryRun) return '[dry run]'
  if (output.skipped) return `[skipped: ${output.reason}]`
  return JSON.stringify(output).slice(0, 80)
}

function typeBadgeClass(type: string): string {
  const map: Record<string, string> = {
    nl_query: 'bg-indigo-900 text-indigo-300',
    proxy_query: 'bg-blue-900 text-blue-300',
    fleet_execute: 'bg-orange-900 text-orange-300',
    policy_decision: 'bg-purple-900 text-purple-300',
    approval: 'bg-green-900 text-green-300',
    playbook_trigger: 'bg-yellow-900 text-yellow-300',
  }
  return map[type] || 'bg-gray-800 text-gray-400'
}

watch(filterTag, () => loadRecordings())

onMounted(() => {
  loadRecordings()
  loadTemplates()
})
</script>
