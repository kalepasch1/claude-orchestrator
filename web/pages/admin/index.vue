<template>
  <div class="p-6">
    <div class="mb-6 flex items-center justify-between gap-3"><h2 class="text-xl font-semibold">Portfolio Overview</h2><NuxtLink to="/admin/capability-passport" class="rounded-lg border border-indigo-500/40 px-3 py-2 text-xs text-indigo-300 hover:bg-indigo-500/10">Capability passport & routing →</NuxtLink></div>

    <!-- App cards grid -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 mb-8">
      <div v-for="app in apps" :key="app.id"
           class="bg-gray-900 border border-gray-800 rounded-lg p-4 hover:border-indigo-500/50 transition-colors cursor-pointer"
           @click="navigateTo(`/admin/${app.id}`)">
        <div class="flex items-center justify-between mb-3">
          <h3 class="font-medium">{{ app.name }}</h3>
          <span class="w-2 h-2 rounded-full" :class="app.configured ? 'bg-green-500' : 'bg-gray-600'" />
        </div>
        <div class="text-xs text-gray-500">
          <div>Users: {{ app.userCount ?? '—' }}</div>
          <div>Events (24h): {{ app.eventCount ?? '—' }}</div>
          <div>Status: {{ app.configured ? 'Connected' : 'Not configured' }}</div>
        </div>
      </div>
    </div>

    <!-- Recent events across all apps -->
    <h3 class="text-lg font-medium mb-3">Recent Fleet Events</h3>
    <div class="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
      <div v-if="events.length === 0" class="p-8 text-center text-gray-500">
        No events yet. Configure ORCHESTRATOR_INGEST_URL in each app to start pushing events.
      </div>
      <div v-for="evt in events" :key="evt.id" class="flex items-center gap-3 px-4 py-2 border-b border-gray-800 last:border-0 hover:bg-gray-800/50">
        <span class="text-xs px-1.5 py-0.5 rounded font-medium"
              :class="{ 'bg-red-900/50 text-red-300': evt.severity === 'critical', 'bg-yellow-900/50 text-yellow-300': evt.severity === 'warn', 'bg-gray-800 text-gray-400': evt.severity === 'info' }">
          {{ evt.severity }}
        </span>
        <span class="text-xs text-indigo-400 w-20">{{ evt.product }}</span>
        <span class="text-sm flex-1">{{ evt.title }}</span>
        <span class="text-xs text-gray-600">{{ timeAgo(evt.at) }}</span>
      </div>
    </div>

    <!-- Pending approvals -->
    <h3 class="text-lg font-medium mt-6 mb-3">Pending Approvals</h3>
    <div class="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
      <div v-if="approvals.length === 0" class="p-8 text-center text-gray-500">
        No pending approvals.
      </div>
      <div v-for="a in approvals" :key="a.id" class="flex items-center gap-3 px-4 py-2 border-b border-gray-800 last:border-0">
        <span class="text-xs text-indigo-400 w-20">{{ a.product }}</span>
        <span class="text-sm flex-1">{{ a.title }}</span>
        <span class="text-xs px-1.5 py-0.5 rounded bg-indigo-900/50 text-indigo-300">{{ a.tier }}</span>
        <NuxtLink to="/sign-offs" class="text-xs px-2 py-1 rounded bg-indigo-900/50 text-indigo-300 hover:bg-indigo-800/50">Review decision brief</NuxtLink>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const apps = ref<any[]>([])
const events = ref<any[]>([])
const approvals = ref<any[]>([])

function timeAgo(dt: string) {
  const diff = Date.now() - new Date(dt).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

async function load() {
  const [appsRes, eventsRes, approvalsRes] = await Promise.allSettled([
    $fetch('/api/proxy/apps'),
    $fetch('/api/fleet/incidents'),
    $fetch('/api/fleet/approvals', { params: { status: 'pending' } }),
  ])
  if (appsRes.status === 'fulfilled') apps.value = (appsRes.value as any).apps ?? []
  if (eventsRes.status === 'fulfilled') events.value = ((eventsRes.value as any) ?? []).slice(0, 20)
  if (approvalsRes.status === 'fulfilled') approvals.value = (approvalsRes.value as any).items ?? []
}

onMounted(load)
</script>
