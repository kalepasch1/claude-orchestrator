<template>
  <div class="flex h-screen bg-gray-950 text-gray-200">
    <!-- Sidebar -->
    <aside class="w-56 bg-gray-900 border-r border-gray-800 flex flex-col">
      <div class="p-4 border-b border-gray-800">
        <h1 class="text-sm font-semibold text-indigo-400 tracking-wide">SMRTER OPS</h1>
        <p class="text-xs text-gray-500 mt-1">Unified Admin</p>
      </div>

      <nav class="flex-1 overflow-y-auto py-2">
        <!-- Overview -->
        <NuxtLink to="/admin" class="nav-link" active-class="nav-active">
          <span class="nav-icon">&#9673;</span> Overview
        </NuxtLink>
        <NuxtLink to="/admin/events" class="nav-link" active-class="nav-active">
          <span class="nav-icon">&#9889;</span> Event Feed
        </NuxtLink>
        <NuxtLink to="/admin/users" class="nav-link" active-class="nav-active">
          <span class="nav-icon">&#128100;</span> Cross-App Users
        </NuxtLink>
        <NuxtLink to="/admin/policies" class="nav-link" active-class="nav-active">
          <span class="nav-icon">&#128203;</span> Auto-Policies
        </NuxtLink>
        <NuxtLink to="/admin/chat" class="nav-link" active-class="nav-active">
          <span class="nav-icon">&#128172;</span> Chat
        </NuxtLink>
        <NuxtLink to="/admin/anomalies" class="nav-link" active-class="nav-active">
          <span class="nav-icon">&#9888;</span> Anomalies
        </NuxtLink>
        <NuxtLink to="/admin/revenue" class="nav-link" active-class="nav-active">
          <span class="nav-icon">&#128176;</span> Revenue
        </NuxtLink>
        <NuxtLink to="/admin/deploys" class="nav-link" active-class="nav-active">
          <span class="nav-icon">&#128640;</span> Deploys
        </NuxtLink>
        <NuxtLink to="/admin/prompt-ops" class="nav-link" active-class="nav-active">
          <span class="nav-icon">&#128221;</span> Prompt Ops
        </NuxtLink>

        <!-- App sections -->
        <div v-for="app in apps" :key="app.id" class="mt-2">
          <div class="px-4 py-1 text-xs font-medium text-gray-600 uppercase tracking-wider">{{ app.name }}</div>
          <NuxtLink :to="`/admin/${app.id}`" class="nav-link" active-class="nav-active">
            <span class="nav-dot" :class="app.configured ? 'bg-green-500' : 'bg-gray-600'" />
            Dashboard
          </NuxtLink>
          <NuxtLink :to="`/admin/${app.id}/users`" class="nav-link text-xs" active-class="nav-active">
            Users
          </NuxtLink>
          <NuxtLink :to="`/admin/${app.id}/data`" class="nav-link text-xs" active-class="nav-active">
            Data Explorer
          </NuxtLink>
        </div>
      </nav>

      <!-- Footer -->
      <div class="p-3 border-t border-gray-800">
        <NuxtLink to="/" class="text-xs text-gray-500 hover:text-gray-300">&larr; Fleet Ops</NuxtLink>
      </div>
    </aside>

    <!-- Main content -->
    <main class="flex-1 overflow-y-auto">
      <slot />
    </main>
  </div>
</template>

<script setup lang="ts">
const apps = ref([
  { id: 'apparently', name: 'Apparently', configured: true },
  { id: 'tomorrow', name: 'Tomorrow', configured: true },
  { id: 'smarter', name: 'Smarter', configured: true },
  { id: 'galop', name: 'Galop', configured: true },
  { id: 'hisanta', name: 'HiSanta', configured: true },
  { id: 'pareto', name: 'Pareto', configured: true },
  { id: 'orchestrator', name: 'Orchestrator', configured: true },
])

// Fetch actual config status
onMounted(async () => {
  try {
    const { data } = await useFetch('/api/proxy/apps')
    if (data.value?.apps) {
      apps.value = data.value.apps
    }
  } catch {}
})
</script>

<style scoped>
.nav-link {
  @apply flex items-center gap-2 px-4 py-1.5 text-sm text-gray-400 hover:text-gray-200 hover:bg-gray-800 transition-colors;
}
.nav-active {
  @apply text-indigo-400 bg-indigo-950/30 border-r-2 border-indigo-400;
}
.nav-icon {
  @apply text-xs w-5 text-center;
}
.nav-dot {
  @apply w-1.5 h-1.5 rounded-full inline-block;
}
</style>
