<template>
  <div class="p-6">
    <h2 class="text-xl font-semibold mb-4">Fleet Event Feed</h2>
    <div class="flex gap-2 mb-4">
      <select v-model="filter.product" class="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm">
        <option value="">All apps</option>
        <option v-for="app in appIds" :key="app" :value="app">{{ app }}</option>
      </select>
      <select v-model="filter.severity" class="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm">
        <option value="">All severities</option>
        <option value="critical">Critical</option>
        <option value="warn">Warning</option>
        <option value="info">Info</option>
      </select>
    </div>

    <div class="bg-gray-900 border border-gray-800 rounded-lg divide-y divide-gray-800">
      <div v-for="evt in filtered" :key="evt.id" class="px-4 py-3 hover:bg-gray-800/50">
        <div class="flex items-center gap-3">
          <span class="text-xs px-1.5 py-0.5 rounded font-medium"
                :class="sevClass(evt.severity)">{{ evt.severity }}</span>
          <span class="text-xs text-indigo-400 w-20">{{ evt.product }}</span>
          <span class="text-xs text-gray-500 w-24">{{ evt.domain }}</span>
          <span class="text-sm flex-1 font-medium">{{ evt.title }}</span>
          <span class="text-xs text-gray-600">{{ timeAgo(evt.at || evt.created_at) }}</span>
        </div>
        <p v-if="evt.summary" class="text-xs text-gray-500 mt-1 ml-[11.5rem]">{{ evt.summary }}</p>
      </div>
      <div v-if="filtered.length === 0" class="p-8 text-center text-gray-500">No events matching filters</div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const appIds = ['apparently', 'tomorrow', 'smarter', 'galop', 'hisanta', 'pareto', 'orchestrator']
const filter = reactive({ product: '', severity: '' })
const events = ref<any[]>([])

const filtered = computed(() => events.value.filter(e =>
  (!filter.product || e.product === filter.product) &&
  (!filter.severity || e.severity === filter.severity)
))

function sevClass(s: string) {
  return { 'bg-red-900/50 text-red-300': s === 'critical', 'bg-yellow-900/50 text-yellow-300': s === 'warn', 'bg-gray-800 text-gray-400': s === 'info' }
}

function timeAgo(dt: string) {
  if (!dt) return ''
  const mins = Math.floor((Date.now() - new Date(dt).getTime()) / 60000)
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h`
  return `${Math.floor(hrs / 24)}d`
}

onMounted(async () => {
  try {
    const data = await $fetch<any[]>('/api/fleet/incidents')
    events.value = data ?? []
  } catch {}
})
</script>
