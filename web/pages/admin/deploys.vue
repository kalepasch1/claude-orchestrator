<template>
  <div class="p-6">
    <h2 class="text-xl font-semibold mb-6">Canary Deploy Mesh</h2>

    <!-- Fleet Health Matrix -->
    <div class="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-medium text-gray-300">Fleet Health Matrix</h3>
        <button
          class="text-xs px-3 py-1 rounded bg-gray-800 hover:bg-gray-700 text-gray-300 transition-colors"
          :disabled="healthLoading"
          @click="refreshHealth"
        >
          {{ healthLoading ? 'Checking...' : 'Refresh' }}
        </button>
      </div>
      <div class="flex flex-wrap gap-3">
        <div v-for="check in healthChecks" :key="check.app" class="flex items-center gap-2 bg-gray-800/50 rounded px-3 py-2">
          <span
            class="w-2.5 h-2.5 rounded-full"
            :class="check.healthy ? 'bg-green-500' : 'bg-red-500'"
          />
          <span class="text-sm text-gray-300">{{ check.app }}</span>
          <span class="text-xs text-gray-500">{{ check.latencyMs }}ms</span>
        </div>
        <div v-if="healthChecks.length === 0" class="text-sm text-gray-500">
          Click Refresh to run health checks
        </div>
      </div>
    </div>

    <!-- New Deploy Form -->
    <div class="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
      <h3 class="text-sm font-medium text-gray-300 mb-3">New Deploy</h3>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div>
          <label class="block text-xs text-gray-500 mb-1">Canary App</label>
          <select
            v-model="newDeploy.canaryApp"
            class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
          >
            <option value="">Select canary...</option>
            <option v-for="app in allApps" :key="app" :value="app">{{ app }}</option>
          </select>
        </div>
        <div>
          <label class="block text-xs text-gray-500 mb-1">Commit SHA (optional)</label>
          <input
            v-model="newDeploy.commitSha"
            type="text"
            placeholder="abc1234"
            class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500"
          />
        </div>
        <div class="flex items-end">
          <button
            class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-800 disabled:text-gray-600 text-sm font-medium rounded transition-colors"
            :disabled="!newDeploy.canaryApp || selectedTargets.length === 0 || deploying"
            @click="startDeploy"
          >
            {{ deploying ? 'Deploying...' : 'Start Canary Deploy' }}
          </button>
        </div>
      </div>
      <div class="mt-3">
        <label class="block text-xs text-gray-500 mb-2">Target Apps</label>
        <div class="flex flex-wrap gap-2">
          <label
            v-for="app in allApps"
            :key="app"
            class="flex items-center gap-1.5 bg-gray-800/50 rounded px-2.5 py-1.5 cursor-pointer hover:bg-gray-800 transition-colors"
          >
            <input
              type="checkbox"
              :value="app"
              v-model="selectedTargets"
              class="rounded border-gray-600 bg-gray-700 text-indigo-500 focus:ring-indigo-500"
            />
            <span class="text-xs text-gray-300">{{ app }}</span>
          </label>
        </div>
      </div>
    </div>

    <!-- Deploy History -->
    <div class="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
      <div class="px-4 py-3 border-b border-gray-800">
        <h3 class="text-sm font-medium text-gray-300">Deploy History</h3>
      </div>
      <div v-if="deploys.length === 0" class="p-8 text-center text-gray-500">
        No deploys yet. Create one above.
      </div>
      <div v-for="deploy in deploys" :key="deploy.id" class="border-b border-gray-800 last:border-0 px-4 py-3 hover:bg-gray-800/30">
        <div class="flex items-center gap-3 mb-2">
          <span
            class="text-xs px-2 py-0.5 rounded font-medium"
            :class="statusClass(deploy.status)"
          >
            {{ deploy.status }}
          </span>
          <span class="text-sm text-gray-300">Canary: {{ deploy.canaryApp }}</span>
          <span class="text-xs text-gray-500">{{ deploy.targetApps.length }} targets</span>
          <span v-if="deploy.commitSha" class="text-xs text-indigo-400 font-mono">{{ deploy.commitSha.slice(0, 7) }}</span>
          <span class="text-xs text-gray-600 ml-auto">{{ timeAgo(deploy.createdAt) }}</span>
        </div>
        <div v-if="deploy.error" class="text-xs text-red-400 mb-2">{{ deploy.error }}</div>
        <div v-if="deploy.healthChecks.length > 0" class="flex flex-wrap gap-2">
          <div
            v-for="(hc, i) in deploy.healthChecks"
            :key="i"
            class="flex items-center gap-1 text-xs"
          >
            <span
              class="w-1.5 h-1.5 rounded-full"
              :class="hc.healthy ? 'bg-green-500' : 'bg-red-500'"
            />
            <span class="text-gray-400">{{ hc.app }}</span>
            <span class="text-gray-600">{{ hc.latencyMs }}ms</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const allApps = ['apparently', 'tomorrow', 'smarter', 'galop', 'hisanta', 'pareto', 'orchestrator']

const healthChecks = ref<any[]>([])
const healthLoading = ref(false)
const deploys = ref<any[]>([])
const deploying = ref(false)

const newDeploy = ref({
  canaryApp: '',
  commitSha: '',
})
const selectedTargets = ref<string[]>([])

async function refreshHealth() {
  healthLoading.value = true
  try {
    const data = await $fetch('/api/admin/deploys/health')
    healthChecks.value = (data as any).checks || []
  } catch {}
  healthLoading.value = false
}

async function loadDeploys() {
  try {
    const data = await $fetch('/api/admin/deploys')
    deploys.value = (data as any).deploys || []
  } catch {}
}

async function startDeploy() {
  if (!newDeploy.value.canaryApp || selectedTargets.value.length === 0) return
  deploying.value = true
  try {
    await $fetch('/api/admin/deploys/create', {
      method: 'POST',
      body: {
        canaryApp: newDeploy.value.canaryApp,
        targetApps: selectedTargets.value,
        commitSha: newDeploy.value.commitSha || undefined,
      },
    })
    newDeploy.value = { canaryApp: '', commitSha: '' }
    selectedTargets.value = []
    // Wait a bit for deploy to progress, then reload
    setTimeout(() => loadDeploys(), 2000)
  } catch {}
  deploying.value = false
}

function statusClass(status: string): string {
  switch (status) {
    case 'complete': return 'bg-green-900/50 text-green-300'
    case 'reverted': return 'bg-red-900/50 text-red-300'
    case 'promoting':
    case 'canary_deploying':
    case 'canary_healthy': return 'bg-yellow-900/50 text-yellow-300'
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
  refreshHealth()
  loadDeploys()
})
</script>
