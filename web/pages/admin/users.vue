<template>
  <div class="p-6">
    <h2 class="text-xl font-semibold mb-4">Cross-App User Search</h2>
    <div class="flex gap-2 mb-6">
      <input v-model="searchEmail" type="email" placeholder="Search by email..."
             class="flex-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
             @keydown.enter="search" />
      <button class="px-4 py-2 bg-indigo-600 rounded text-sm hover:bg-indigo-500" @click="search" :disabled="searching">
        {{ searching ? 'Searching...' : 'Search' }}
      </button>
    </div>

    <div v-if="results" class="space-y-3">
      <div class="text-sm text-gray-400 mb-2">Found in {{ results.found }} app{{ results.found !== 1 ? 's' : '' }}</div>
      <div v-for="r in results.results" :key="r.app" class="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div class="flex items-center gap-2 mb-2">
          <span class="text-sm font-medium text-indigo-400">{{ r.appName }}</span>
          <span class="text-xs text-gray-600">{{ r.user.id }}</span>
        </div>
        <div class="grid grid-cols-2 gap-2 text-xs text-gray-400">
          <div>Created: {{ new Date(r.user.created_at).toLocaleDateString() }}</div>
          <div>Last sign-in: {{ r.user.last_sign_in_at ? new Date(r.user.last_sign_in_at).toLocaleDateString() : 'Never' }}</div>
          <div>Provider: {{ r.user.provider ?? 'email' }}</div>
        </div>
      </div>
      <div v-if="results.found === 0" class="text-sm text-gray-500 text-center py-8">
        No accounts found for {{ searchEmail }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const searchEmail = ref('')
const searching = ref(false)
const results = ref<any>(null)

async function search() {
  if (!searchEmail.value) return
  searching.value = true
  try {
    results.value = await $fetch('/api/proxy/cross-app/users', { params: { email: searchEmail.value } })
  } finally {
    searching.value = false
  }
}
</script>
