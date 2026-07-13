<template>
  <div v-if="errorApps.length > 0" class="bg-red-900/60 border border-red-700 rounded-lg px-4 py-3 mb-6">
    <div class="flex items-center gap-2 mb-2">
      <span class="text-red-400 text-lg">&#9888;</span>
      <span class="text-sm font-semibold text-red-300">Deploy Errors</span>
    </div>
    <div class="flex flex-wrap gap-3">
      <div v-for="e in errorApps" :key="e.app" class="flex items-center gap-2 bg-red-950/50 rounded px-3 py-1.5">
        <span class="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
        <span class="text-sm text-red-200 font-medium">{{ e.app }}</span>
        <span class="text-xs text-red-400">{{ e.ageHours }}h in ERROR</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
const errorApps = ref<{ app: string; ageHours: number }[]>([])

onMounted(async () => {
  try {
    const data = await $fetch('/api/admin/deploys/errors')
    if (data?.errors) {
      errorApps.value = data.errors
    }
  } catch {}
})
</script>
