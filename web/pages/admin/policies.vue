<template>
  <div class="p-6">
    <h2 class="text-xl font-semibold mb-2">Auto-Resolution Policies</h2>
    <p class="text-sm text-gray-500 mb-6">Rules that auto-handle common admin actions. The system learns from your approval patterns and suggests new policies.</p>

    <!-- Suggestions -->
    <div v-if="suggestions.length" class="mb-6">
      <h3 class="text-sm font-medium text-yellow-400 mb-2">Suggested Policies (based on approval history)</h3>
      <div v-for="s in suggestions" :key="s.name" class="bg-yellow-900/10 border border-yellow-800/30 rounded-lg p-4 mb-2">
        <div class="flex items-center justify-between">
          <div>
            <div class="text-sm font-medium">{{ s.name }}</div>
            <div class="text-xs text-gray-500">{{ s.description }} · {{ Math.round(s.confidence * 100) }}% confidence · {{ s.basedOn }} decisions</div>
          </div>
          <button class="text-xs px-3 py-1 bg-yellow-800/30 rounded hover:bg-yellow-800/50 text-yellow-300" @click="promoteSuggestion(s)">
            Enable Policy
          </button>
        </div>
      </div>
    </div>

    <!-- Active policies -->
    <div class="space-y-3">
      <div v-for="p in policies" :key="p.id" class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="flex items-center justify-between mb-2">
          <div class="flex items-center gap-2">
            <span class="w-2 h-2 rounded-full" :class="p.enabled ? 'bg-green-500' : 'bg-gray-600'" />
            <span class="font-medium text-sm">{{ p.name }}</span>
            <span class="text-xs px-1.5 py-0.5 rounded bg-indigo-900/50 text-indigo-300">{{ p.product }}</span>
            <span class="text-xs px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">{{ p.domain }}</span>
          </div>
          <div class="flex items-center gap-2">
            <span v-if="p.autoExecute" class="text-xs px-1.5 py-0.5 rounded bg-green-900/50 text-green-300">auto</span>
            <span v-else class="text-xs px-1.5 py-0.5 rounded bg-gray-800 text-gray-500">manual</span>
            <button class="text-xs text-gray-500 hover:text-gray-300" @click="togglePolicy(p)">
              {{ p.enabled ? 'Disable' : 'Enable' }}
            </button>
          </div>
        </div>
        <p class="text-xs text-gray-500">{{ p.description }}</p>
        <div class="flex gap-4 mt-2 text-xs text-gray-600">
          <span>Matched: {{ p.matchCount ?? 0 }}x</span>
          <span>Success: {{ p.successCount ?? 0 }}x</span>
          <span v-if="p.lastMatchedAt">Last: {{ timeAgo(p.lastMatchedAt) }}</span>
        </div>
      </div>
    </div>

    <div v-if="policies.length === 0" class="bg-gray-900 border border-gray-800 rounded-lg p-8 text-center text-gray-500">
      No policies configured. Seed policies will be created on first deploy.
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const policies = ref<any[]>([])
const suggestions = ref<any[]>([])

function timeAgo(dt: string) {
  if (!dt) return ''
  const mins = Math.floor((Date.now() - new Date(dt).getTime()) / 60000)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

async function togglePolicy(p: any) {
  p.enabled = !p.enabled
  await $fetch('/api/fleet/policies/toggle', { method: 'POST', body: { id: p.id, enabled: p.enabled } })
}

async function promoteSuggestion(s: any) {
  await $fetch('/api/fleet/policies/create', { method: 'POST', body: s })
  suggestions.value = suggestions.value.filter(x => x.name !== s.name)
  await loadPolicies()
}

async function loadPolicies() {
  try {
    const [pRes, sRes] = await Promise.allSettled([
      $fetch('/api/fleet/policies'),
      $fetch('/api/fleet/policies/suggestions'),
    ])
    if (pRes.status === 'fulfilled') policies.value = (pRes.value as any).policies ?? []
    if (sRes.status === 'fulfilled') suggestions.value = (sRes.value as any).suggestions ?? []
  } catch {}
}

onMounted(loadPolicies)
</script>
