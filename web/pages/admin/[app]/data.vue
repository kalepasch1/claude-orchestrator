<template>
  <div class="p-6">
    <h2 class="text-xl font-semibold mb-4 capitalize">{{ appId }} — Data Explorer</h2>

    <div class="flex gap-2 mb-4">
      <input v-model="table" placeholder="Table name (e.g. profiles, bets, submissions)"
             class="flex-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none" />
      <input v-model.number="limit" type="number" class="w-20 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm" placeholder="Limit" />
      <button class="px-4 py-2 bg-indigo-600 rounded text-sm hover:bg-indigo-500" @click="query" :disabled="loading">
        {{ loading ? '...' : 'Query' }}
      </button>
    </div>

    <div v-if="error" class="text-sm text-red-400 bg-red-900/20 rounded p-3 mb-4">{{ error }}</div>

    <div v-if="data" class="bg-gray-900 border border-gray-800 rounded-lg overflow-x-auto">
      <div class="text-xs text-gray-500 px-4 py-2 border-b border-gray-800">{{ count }} rows total — showing {{ data.length }}</div>
      <table class="w-full text-xs">
        <thead class="bg-gray-800/50">
          <tr>
            <th v-for="col in columns" :key="col" class="text-left px-3 py-2 text-gray-500 font-medium whitespace-nowrap">{{ col }}</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-800/50">
          <tr v-for="(row, i) in data" :key="i" class="hover:bg-gray-800/30">
            <td v-for="col in columns" :key="col" class="px-3 py-1.5 text-gray-400 whitespace-nowrap max-w-[200px] truncate">
              {{ typeof row[col] === 'object' ? JSON.stringify(row[col]) : row[col] }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const route = useRoute()
const appId = computed(() => route.params.app as string)
const table = ref('')
const limit = ref(50)
const data = ref<any[] | null>(null)
const count = ref(0)
const error = ref('')
const loading = ref(false)

const columns = computed(() => data.value?.length ? Object.keys(data.value[0]) : [])

async function query() {
  if (!table.value) return
  loading.value = true
  error.value = ''
  try {
    const res = await $fetch<any>(`/api/proxy/${appId.value}/query`, {
      method: 'POST',
      body: { table: table.value, limit: limit.value, order: { column: 'created_at', ascending: false } },
    })
    data.value = res.data
    count.value = res.count ?? res.data?.length ?? 0
  } catch (e: any) {
    error.value = e.data?.message ?? e.message ?? 'Query failed'
    data.value = null
  } finally {
    loading.value = false
  }
}
</script>
