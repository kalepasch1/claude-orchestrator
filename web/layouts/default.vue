<template>
  <div class="flex h-screen bg-[#0d1117] text-slate-300 overflow-hidden">
    <!-- Sidebar -->
    <aside class="w-56 flex-shrink-0 bg-[#0d1117] border-r border-slate-800 flex flex-col">
      <!-- Branding -->
      <div class="px-4 py-4 border-b border-slate-800">
        <div class="flex items-center gap-2">
          <span class="text-blue-400 text-lg">⬡</span>
          <div>
            <div class="text-sm font-bold text-white tracking-tight">Claude Orchestrator</div>
            <div class="text-xs text-slate-500">AI Platform Control</div>
          </div>
        </div>
        <div class="mt-3 flex items-center gap-3">
          <div class="flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full" :class="runnerCount > 0 ? 'bg-green-400 animate-pulse' : 'bg-slate-600'"></span>
            <span class="text-xs text-slate-400">{{ runnerCount }} runner{{ runnerCount !== 1 ? 's' : '' }}</span>
          </div>
          <NuxtLink to="/sign-offs" class="flex items-center gap-1">
            <span v-if="pendingCount > 0" class="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 bg-red-500 text-white text-xs rounded-full font-bold">{{ pendingCount }}</span>
          </NuxtLink>
        </div>
      </div>
      <!-- Navigation -->
      <nav class="flex-1 overflow-y-auto py-2 space-y-0.5">
        <NuxtLink to="/" class="nav-link" active-class="nav-active" exact>
          <span class="nav-icon">⌘</span> Command Center
        </NuxtLink>
        <NuxtLink to="/sign-offs" class="nav-link" active-class="nav-active">
          <span class="nav-icon">✅</span>
          Sign-offs
          <span v-if="pendingCount > 0" class="ml-auto inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 bg-red-500 text-white text-xs rounded-full font-bold">{{ pendingCount }}</span>
        </NuxtLink>
        <NuxtLink to="/queue" class="nav-link" active-class="nav-active">
          <span class="nav-icon">📋</span> Queue
        </NuxtLink>
        <NuxtLink to="/orchestrators" class="nav-link" active-class="nav-active">
          <span class="nav-icon">🤖</span> Orchestrators
        </NuxtLink>
        <NuxtLink to="/spend" class="nav-link" active-class="nav-active">
          <span class="nav-icon">💰</span> Spend &amp; ROI
        </NuxtLink>
        <NuxtLink to="/loops" class="nav-link" active-class="nav-active">
          <span class="nav-icon">🔄</span> Loops
        </NuxtLink>
        <NuxtLink to="/inbox" class="nav-link" active-class="nav-active">
          <span class="nav-icon">📥</span> Inbox
        </NuxtLink>
        <NuxtLink to="/fleet" class="nav-link" active-class="nav-active">
          <span class="nav-icon">🚀</span> Fleet
        </NuxtLink>
        <NuxtLink to="/health" class="nav-link" active-class="nav-active">
          <span class="nav-icon">❤️</span> Health
        </NuxtLink>

        <div class="px-4 pt-4 pb-1">
          <div class="border-t border-slate-800"></div>
        </div>
        <NuxtLink to="/admin" class="nav-link" active-class="nav-active">
          <span class="nav-icon">⚙️</span> Admin
        </NuxtLink>
      </nav>

      <!-- Footer -->
      <div class="px-4 py-3 border-t border-slate-800">
        <div class="text-xs text-slate-600">Orchestrator v2</div>
      </div>
    </aside>

    <!-- Page content -->
    <main class="flex-1 overflow-y-auto">
      <slot />
    </main>
  </div>
</template>

<script setup lang="ts">
const supabase = useSupabaseClient<any>()
const runnerCount = ref(0)
const pendingCount = ref(0)

function alive(r: any) { return (Date.now() - new Date(r.last_seen).getTime()) < 60000 }

async function loadCounts() {
  const [runners, approvals] = await Promise.all([
    supabase.from('runner_heartbeats').select('last_seen'),
    supabase.from('approvals').select('id', { count: 'exact', head: true }).eq('status', 'pending'),
  ])
  runnerCount.value = (runners.data || []).filter(alive).length
  pendingCount.value = approvals.count || 0
}

onMounted(() => {
  loadCounts()
  const timer = setInterval(loadCounts, 30000)
  onUnmounted(() => clearInterval(timer))
})
</script>

<style scoped>
.nav-link {
  @apply flex items-center gap-2 px-4 py-2 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 transition-colors rounded-none;
}
.nav-active {
  @apply bg-slate-800 text-white;
}
.nav-icon {
  @apply text-xs w-5 text-center flex-shrink-0;
}
</style>
