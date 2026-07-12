<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-xl font-semibold">Auto-Remediation Playbooks</h2>
        <p class="text-sm text-gray-500 mt-1">
          Predefined response plans for known anomaly patterns. Playbooks auto-execute or queue for approval when triggered.
        </p>
      </div>
      <button
        class="px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors"
        @click="showCreateForm = !showCreateForm"
      >
        {{ showCreateForm ? 'Cancel' : '+ Create Playbook' }}
      </button>
    </div>

    <!-- Summary cards -->
    <div class="grid grid-cols-4 gap-4 mb-6">
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="text-xs text-gray-500 uppercase tracking-wider">Total Playbooks</div>
        <div class="text-2xl font-semibold mt-1">{{ playbooks.length }}</div>
      </div>
      <div class="bg-gray-900 border border-green-900/40 rounded-lg p-4">
        <div class="text-xs text-green-400 uppercase tracking-wider">Active</div>
        <div class="text-2xl font-semibold text-green-400 mt-1">{{ activeCount }}</div>
      </div>
      <div class="bg-gray-900 border border-yellow-900/40 rounded-lg p-4">
        <div class="text-xs text-yellow-400 uppercase tracking-wider">Pending Approval</div>
        <div class="text-2xl font-semibold text-yellow-400 mt-1">{{ pendingCount }}</div>
      </div>
      <div class="bg-gray-900 border border-indigo-900/40 rounded-lg p-4">
        <div class="text-xs text-indigo-400 uppercase tracking-wider">Total Executions</div>
        <div class="text-2xl font-semibold text-indigo-400 mt-1">{{ totalExecutions }}</div>
      </div>
    </div>

    <!-- Error -->
    <div v-if="error" class="bg-red-950/30 border border-red-800/40 rounded-lg p-4 mb-4">
      <div class="text-sm text-red-400">{{ error }}</div>
    </div>

    <!-- Create form -->
    <div v-if="showCreateForm" class="bg-gray-900 border border-gray-800 rounded-lg p-6 mb-6">
      <h3 class="text-sm font-semibold text-gray-300 mb-4">Create New Playbook</h3>
      <div class="grid grid-cols-2 gap-4 mb-4">
        <div>
          <label class="block text-xs text-gray-500 mb-1">Name</label>
          <input v-model="newPlaybook.name" class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200" placeholder="e.g. Error Spike Response" />
        </div>
        <div>
          <label class="block text-xs text-gray-500 mb-1">Metric Pattern (regex)</label>
          <input v-model="newPlaybook.metricPattern" class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200" placeholder="e.g. error_rate" />
        </div>
        <div class="col-span-2">
          <label class="block text-xs text-gray-500 mb-1">Description</label>
          <input v-model="newPlaybook.description" class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200" placeholder="What does this playbook do?" />
        </div>
        <div>
          <label class="block text-xs text-gray-500 mb-1">Minimum Severity</label>
          <select v-model="newPlaybook.severityMin" class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200">
            <option value="warning">Warning</option>
            <option value="critical">Critical</option>
          </select>
        </div>
        <div>
          <label class="block text-xs text-gray-500 mb-1">Cooldown (minutes)</label>
          <input v-model.number="newPlaybook.cooldownMin" type="number" class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200" placeholder="5" />
        </div>
        <div class="col-span-2 flex items-center gap-4">
          <label class="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
            <input v-model="newPlaybook.requiresApproval" type="checkbox" class="rounded bg-gray-800 border-gray-700" />
            Requires approval before execution
          </label>
        </div>
      </div>

      <!-- Steps builder -->
      <div class="mb-4">
        <label class="block text-xs text-gray-500 mb-2">Steps</label>
        <div v-for="(step, i) in newPlaybook.steps" :key="i" class="flex gap-2 mb-2">
          <select v-model="step.type" class="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 w-40">
            <option value="notify">Notify</option>
            <option value="toggle_feature">Toggle Feature</option>
            <option value="revert_deploy">Revert Deploy</option>
            <option value="scale">Scale</option>
            <option value="fleet_execute">Fleet Execute</option>
            <option value="custom">Custom</option>
          </select>
          <input v-model="step.description" class="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200" placeholder="Step description" />
          <button @click="newPlaybook.steps.splice(i, 1)" class="text-gray-600 hover:text-red-400 px-2">&#10005;</button>
        </div>
        <button @click="newPlaybook.steps.push({ type: 'notify', description: '' })" class="text-xs text-indigo-400 hover:text-indigo-300">+ Add Step</button>
      </div>

      <button
        class="px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors disabled:opacity-50"
        :disabled="!newPlaybook.name || !newPlaybook.metricPattern || newPlaybook.steps.length === 0"
        @click="createNewPlaybook"
      >
        Create Playbook
      </button>
    </div>

    <!-- Pending Executions -->
    <div v-if="pendingExecutions.length > 0" class="mb-6">
      <h3 class="text-sm font-semibold text-yellow-400 mb-3">Pending Approval</h3>
      <div class="space-y-2">
        <div
          v-for="exec in pendingExecutions"
          :key="exec.id"
          class="bg-gray-900 border border-yellow-800/40 rounded-lg p-4 flex items-center justify-between"
        >
          <div>
            <div class="text-sm font-medium text-gray-200">{{ exec.playbookName }}</div>
            <div class="text-xs text-gray-500 mt-1">
              Triggered by: {{ exec.triggeredBy }} | {{ timeAgo(exec.startedAt) }}
            </div>
            <div class="text-xs text-gray-600 mt-1">
              Steps: {{ exec.steps.map(s => s.step.description).join(' → ') }}
            </div>
          </div>
          <div class="flex gap-2">
            <button
              class="px-3 py-1.5 text-xs bg-green-700 hover:bg-green-600 text-white rounded transition-colors"
              @click="handleApproval(exec.id, 'approve')"
            >
              Approve
            </button>
            <button
              class="px-3 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 text-white rounded transition-colors"
              @click="handleApproval(exec.id, 'abort')"
            >
              Abort
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Playbook Cards -->
    <div class="mb-6">
      <h3 class="text-sm font-semibold text-gray-400 mb-3">Playbooks</h3>
      <div class="grid grid-cols-2 gap-4">
        <div
          v-for="pb in playbooks"
          :key="pb.id"
          class="bg-gray-900 border border-gray-800 rounded-lg p-4"
          :class="{ 'opacity-50': !pb.enabled }"
        >
          <div class="flex items-start justify-between mb-2">
            <div>
              <div class="text-sm font-medium text-gray-200">{{ pb.name }}</div>
              <div class="text-xs text-gray-500 mt-0.5">{{ pb.description }}</div>
            </div>
            <button
              class="text-xs px-2 py-1 rounded transition-colors"
              :class="pb.enabled ? 'bg-green-900/40 text-green-400 hover:bg-green-900/60' : 'bg-gray-800 text-gray-500 hover:bg-gray-700'"
              @click="togglePlaybook(pb)"
            >
              {{ pb.enabled ? 'ON' : 'OFF' }}
            </button>
          </div>

          <div class="space-y-2 mt-3">
            <div class="flex gap-4 text-xs text-gray-500">
              <span>Trigger: <span class="text-gray-400 font-mono">{{ pb.trigger.metricPattern }}</span></span>
              <span>Min: <span class="text-gray-400">{{ pb.trigger.severityMin }}</span></span>
            </div>

            <div class="text-xs text-gray-600">
              <span class="text-gray-500">Steps:</span>
              <span v-for="(step, i) in pb.steps" :key="i">
                {{ step.description }}<span v-if="i < pb.steps.length - 1" class="text-gray-700"> → </span>
              </span>
            </div>

            <div class="flex gap-4 text-xs text-gray-600">
              <span>Cooldown: {{ Math.round(pb.cooldownMs / 60000) }}m</span>
              <span>Executions: {{ pb.executionCount }}</span>
              <span v-if="pb.requiresApproval" class="text-yellow-600">Requires approval</span>
              <span v-if="pb.lastExecutedAt">Last: {{ timeAgo(pb.lastExecutedAt) }}</span>
            </div>
          </div>

          <div class="mt-3 pt-3 border-t border-gray-800">
            <button
              class="text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
              @click="manualTrigger(pb.id)"
            >
              Manual Trigger
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Execution History -->
    <div v-if="completedExecutions.length > 0">
      <h3 class="text-sm font-semibold text-gray-400 mb-3">Execution History</h3>
      <div class="space-y-2">
        <div
          v-for="exec in completedExecutions"
          :key="exec.id"
          class="bg-gray-900 border border-gray-800 rounded-lg p-4"
        >
          <div class="flex items-center justify-between mb-2">
            <div class="flex items-center gap-2">
              <span
                class="text-xs px-2 py-0.5 rounded font-medium uppercase tracking-wider"
                :class="{
                  'bg-green-900/50 text-green-300': exec.status === 'completed',
                  'bg-red-900/50 text-red-300': exec.status === 'failed',
                  'bg-gray-800 text-gray-400': exec.status === 'aborted',
                  'bg-blue-900/40 text-blue-300': exec.status === 'executing',
                }"
              >
                {{ exec.status }}
              </span>
              <span class="text-sm text-gray-200">{{ exec.playbookName }}</span>
            </div>
            <span class="text-xs text-gray-600">{{ timeAgo(exec.startedAt) }}</span>
          </div>

          <div class="flex gap-2 flex-wrap">
            <span
              v-for="(s, i) in exec.steps"
              :key="i"
              class="text-xs px-2 py-1 rounded"
              :class="{
                'bg-green-900/30 text-green-400': s.status === 'completed',
                'bg-red-900/30 text-red-400': s.status === 'failed',
                'bg-gray-800 text-gray-500': s.status === 'skipped' || s.status === 'pending',
                'bg-blue-900/30 text-blue-400': s.status === 'running',
              }"
            >
              {{ s.step.description }}
              <span v-if="s.error" class="ml-1 text-red-500">: {{ s.error }}</span>
            </span>
          </div>

          <div v-if="exec.completedAt" class="text-xs text-gray-600 mt-2">
            Duration: {{ Math.round((new Date(exec.completedAt).getTime() - new Date(exec.startedAt).getTime()) / 1000) }}s
          </div>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="playbooks.length === 0 && !error" class="bg-gray-900 border border-gray-800 rounded-lg p-12 text-center">
      <div class="text-gray-500 mb-2">No playbooks configured</div>
      <div class="text-xs text-gray-600">Click "Create Playbook" to add your first auto-remediation playbook.</div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

interface PlaybookStep {
  type: string
  app?: string
  action?: string
  payload?: any
  description: string
}

interface Playbook {
  id: string
  name: string
  description: string
  trigger: { metricPattern: string; severityMin: string; appPattern?: string }
  steps: PlaybookStep[]
  requiresApproval: boolean
  cooldownMs: number
  enabled: boolean
  lastExecutedAt?: string
  executionCount: number
}

interface PlaybookExecution {
  id: string
  playbookId: string
  playbookName: string
  triggeredBy: string
  status: string
  steps: { step: PlaybookStep; status: string; result?: any; error?: string }[]
  startedAt: string
  completedAt?: string
}

const playbooks = ref<Playbook[]>([])
const executions = ref<PlaybookExecution[]>([])
const error = ref<string | null>(null)
const showCreateForm = ref(false)

const newPlaybook = reactive({
  name: '',
  description: '',
  metricPattern: '',
  severityMin: 'warning' as 'warning' | 'critical',
  requiresApproval: false,
  cooldownMin: 5,
  steps: [{ type: 'notify', description: '' }] as { type: string; description: string }[],
})

const activeCount = computed(() => playbooks.value.filter(p => p.enabled).length)
const pendingExecutions = computed(() => executions.value.filter(e => e.status === 'pending_approval'))
const completedExecutions = computed(() => executions.value.filter(e => e.status !== 'pending_approval'))
const pendingCount = computed(() => pendingExecutions.value.length)
const totalExecutions = computed(() => executions.value.length)

function timeAgo(dateStr: string): string {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

async function fetchData() {
  try {
    error.value = null
    const data = await $fetch<{ playbooks: Playbook[]; executions: PlaybookExecution[] }>('/api/admin/playbooks')
    playbooks.value = data.playbooks
    executions.value = data.executions
  } catch (e: any) {
    error.value = e.data?.message || e.message || 'Failed to fetch playbooks'
  }
}

async function togglePlaybook(pb: Playbook) {
  try {
    await $fetch('/api/admin/playbooks/update', {
      method: 'POST',
      body: { id: pb.id, enabled: !pb.enabled },
    })
    await fetchData()
  } catch (e: any) {
    error.value = e.data?.message || e.message || 'Toggle failed'
  }
}

async function manualTrigger(playbookId: string) {
  try {
    await $fetch('/api/admin/playbooks/execute', {
      method: 'POST',
      body: { playbookId, triggeredBy: 'manual' },
    })
    await fetchData()
  } catch (e: any) {
    error.value = e.data?.message || e.message || 'Trigger failed'
  }
}

async function handleApproval(executionId: string, action: 'approve' | 'abort') {
  try {
    await $fetch('/api/admin/playbooks/approve', {
      method: 'POST',
      body: { executionId, action },
    })
    await fetchData()
  } catch (e: any) {
    error.value = e.data?.message || e.message || 'Approval action failed'
  }
}

async function createNewPlaybook() {
  try {
    await $fetch('/api/admin/playbooks/update', {
      method: 'POST',
      body: {
        create: true,
        name: newPlaybook.name,
        description: newPlaybook.description,
        trigger: {
          metricPattern: newPlaybook.metricPattern,
          severityMin: newPlaybook.severityMin,
        },
        steps: newPlaybook.steps.filter(s => s.description),
        requiresApproval: newPlaybook.requiresApproval,
        cooldownMs: newPlaybook.cooldownMin * 60000,
        enabled: true,
      },
    })
    showCreateForm.value = false
    newPlaybook.name = ''
    newPlaybook.description = ''
    newPlaybook.metricPattern = ''
    newPlaybook.severityMin = 'warning'
    newPlaybook.requiresApproval = false
    newPlaybook.cooldownMin = 5
    newPlaybook.steps = [{ type: 'notify', description: '' }]
    await fetchData()
  } catch (e: any) {
    error.value = e.data?.message || e.message || 'Create failed'
  }
}

onMounted(() => fetchData())

let refreshInterval: ReturnType<typeof setInterval>
onMounted(() => {
  refreshInterval = setInterval(() => fetchData(), 30_000)
})
onUnmounted(() => {
  clearInterval(refreshInterval)
})
</script>
