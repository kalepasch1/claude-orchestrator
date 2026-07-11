<template>
  <div class="p-6">
    <div class="flex items-center gap-3 mb-6">
      <h2 class="text-xl font-semibold capitalize">{{ appId }}</h2>
      <span class="text-xs px-2 py-0.5 rounded" :class="config?.configured ? 'bg-green-900/50 text-green-300' : 'bg-gray-800 text-gray-500'">
        {{ config?.configured ? 'Connected' : 'Not configured' }}
      </span>
    </div>

    <div v-if="!config?.configured" class="bg-gray-900 border border-gray-800 rounded-lg p-8 text-center">
      <p class="text-gray-400">Set <code class="text-indigo-400">SUPABASE_URL_{{ appId.toUpperCase() }}</code> and <code class="text-indigo-400">SUPABASE_SERVICE_KEY_{{ appId.toUpperCase() }}</code> in the orchestrator's env to connect.</p>
    </div>

    <template v-else>
      <!-- Users summary -->
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-4">
        <h3 class="text-sm font-medium text-gray-400 mb-2">Users</h3>
        <div class="text-2xl font-semibold">{{ users.length }}</div>
        <div class="text-xs text-gray-500 mt-1">{{ recentSignins }} signed in last 7d</div>
      </div>

      <!-- Recent users table -->
      <div class="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <table class="w-full text-sm">
          <thead class="bg-gray-800/50">
            <tr>
              <th class="text-left px-4 py-2 text-xs text-gray-500 font-medium">Email</th>
              <th class="text-left px-4 py-2 text-xs text-gray-500 font-medium">Created</th>
              <th class="text-left px-4 py-2 text-xs text-gray-500 font-medium">Last Sign-in</th>
              <th class="text-left px-4 py-2 text-xs text-gray-500 font-medium">Provider</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-800">
            <tr v-for="u in users.slice(0, 20)" :key="u.id" class="hover:bg-gray-800/30">
              <td class="px-4 py-2 text-gray-300">{{ u.email }}</td>
              <td class="px-4 py-2 text-gray-500 text-xs">{{ new Date(u.created_at).toLocaleDateString() }}</td>
              <td class="px-4 py-2 text-gray-500 text-xs">{{ u.last_sign_in_at ? new Date(u.last_sign_in_at).toLocaleDateString() : '---' }}</td>
              <td class="px-4 py-2 text-gray-500 text-xs">{{ u.provider ?? 'email' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const route = useRoute()
const appId = computed(() => route.params.app as string)
const config = ref<any>(null)
const users = ref<any[]>([])

const recentSignins = computed(() => {
  const week = Date.now() - 7 * 86400000
  return users.value.filter(u => u.last_sign_in_at && new Date(u.last_sign_in_at).getTime() > week).length
})

onMounted(async () => {
  const [appsRes, usersRes] = await Promise.allSettled([
    $fetch('/api/proxy/apps'),
    $fetch(`/api/proxy/${appId.value}/users`),
  ])
  if (appsRes.status === 'fulfilled') {
    config.value = (appsRes.value as any).apps?.find((a: any) => a.id === appId.value)
  }
  if (usersRes.status === 'fulfilled') {
    users.value = (usersRes.value as any).users ?? []
  }
})
</script>
