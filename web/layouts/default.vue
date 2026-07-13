<template>
  <div class="flex h-screen bg-[#07090a] text-[#dde5dd] overflow-hidden">
    <!-- Sidebar -->
    <aside class="w-56 flex-shrink-0 bg-[#07090a] border-r border-[#162016] flex flex-col">
      <!-- Branding -->
      <div class="px-4 py-4 border-b border-[#162016]">
        <div class="mb-1">
          <div class="text-xs tracking-[0.25em] uppercase text-[#dde5dd] font-medium" style="font-family: 'Fraunces', serif; letter-spacing: 0.2em;">ORCHESTRATOR</div>
          <div class="text-[10px] text-[#3a5a3a] mt-0.5 tracking-wide">AI Control Platform</div>
        </div>
        <div class="mt-3 flex items-center gap-2">
          <span
            class="w-1.5 h-1.5 rounded-full flex-shrink-0"
            :class="runnerCount > 0 ? 'bg-[#6fcf8a] dot-breathe' : 'bg-[#1e2e1e]'"
          ></span>
          <span class="text-[11px] text-[#5a7a5a]">{{ runnerCount }} active</span>
          <NuxtLink v-if="pendingCount > 0" to="/sign-offs" class="ml-auto">
            <span class="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 bg-red-500/90 text-white text-[10px] rounded-full font-bold">{{ pendingCount }}</span>
          </NuxtLink>
        </div>
      </div>
      <!-- Navigation -->
      <nav class="flex-1 overflow-y-auto py-2">
        <NuxtLink
          to="/"
          class="flex items-center gap-3 px-4 py-2 text-sm transition-colors"
          :class="$route.path === '/' ? 'bg-[#0f2014] text-[#6fcf8a]' : 'text-[#5a7a5a] hover:bg-[#0c180e] hover:text-[#c8d8c8]'"
          exact
        >
          <span class="w-4 text-center flex-shrink-0 text-xs">→</span>
          <span>Command Center</span>
        </NuxtLink>
        <NuxtLink
          to="/sign-offs"
          class="flex items-center gap-3 px-4 py-2 text-sm transition-colors"
          :class="$route.path === '/sign-offs' ? 'bg-[#0f2014] text-[#6fcf8a]' : 'text-[#5a7a5a] hover:bg-[#0c180e] hover:text-[#c8d8c8]'"
        >
          <span class="w-4 text-center flex-shrink-0 text-xs">○</span>
          <span>Sign-offs</span>
          <span v-if="pendingCount > 0" class="ml-auto inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 bg-red-500/90 text-white text-[10px] rounded-full font-bold">{{ pendingCount }}</span>
        </NuxtLink>
        <NuxtLink
          to="/queue"
          class="flex items-center gap-3 px-4 py-2 text-sm transition-colors"
          :class="$route.path === '/queue' ? 'bg-[#0f2014] text-[#6fcf8a]' : 'text-[#5a7a5a] hover:bg-[#0c180e] hover:text-[#c8d8c8]'"
        >
          <span class="w-4 text-center flex-shrink-0 text-xs">≡</span>
          <span>Queue</span>
        </NuxtLink>
        <NuxtLink
          to="/orchestrators"
          class="flex items-center gap-3 px-4 py-2 text-sm transition-colors"
          :class="$route.path === '/orchestrators' ? 'bg-[#0f2014] text-[#6fcf8a]' : 'text-[#5a7a5a] hover:bg-[#0c180e] hover:text-[#c8d8c8]'"
        >
          <span class="w-4 text-center flex-shrink-0 text-xs">◈</span>
          <span>Orchestrators</span>
        </NuxtLink>
        <NuxtLink
          to="/spend"
          class="flex items-center gap-3 px-4 py-2 text-sm transition-colors"
          :class="$route.path === '/spend' ? 'bg-[#0f2014] text-[#6fcf8a]' : 'text-[#5a7a5a] hover:bg-[#0c180e] hover:text-[#c8d8c8]'"
        >
          <span class="w-4 text-center flex-shrink-0 text-xs">$</span>
          <span>Spend &amp; ROI</span>
        </NuxtLink>
        <NuxtLink
          to="/loops"
          class="flex items-center gap-3 px-4 py-2 text-sm transition-colors"
          :class="$route.path === '/loops' ? 'bg-[#0f2014] text-[#6fcf8a]' : 'text-[#5a7a5a] hover:bg-[#0c180e] hover:text-[#c8d8c8]'"
        >
          <span class="w-4 text-center flex-shrink-0 text-xs">∞</span>
          <span>Loops</span>
        </NuxtLink>
        <NuxtLink
          to="/inbox"
          class="flex items-center gap-3 px-4 py-2 text-sm transition-colors"
          :class="$route.path === '/inbox' ? 'bg-[#0f2014] text-[#6fcf8a]' : 'text-[#5a7a5a] hover:bg-[#0c180e] hover:text-[#c8d8c8]'"
        >
          <span class="w-4 text-center flex-shrink-0 text-xs">⊡</span>
          <span>Inbox</span>
        </NuxtLink>
        <NuxtLink
          to="/fleet"
          class="flex items-center gap-3 px-4 py-2 text-sm transition-colors"
          :class="$route.path === '/fleet' ? 'bg-[#0f2014] text-[#6fcf8a]' : 'text-[#5a7a5a] hover:bg-[#0c180e] hover:text-[#c8d8c8]'"
        >
          <span class="w-4 text-center flex-shrink-0 text-xs">◉</span>
          <span>Fleet</span>
        </NuxtLink>
        <NuxtLink
          to="/health"
          class="flex items-center gap-3 px-4 py-2 text-sm transition-colors"
          :class="$route.path === '/health' ? 'bg-[#0f2014] text-[#6fcf8a]' : 'text-[#5a7a5a] hover:bg-[#0c180e] hover:text-[#c8d8c8]'"
        >
          <span class="w-4 text-center flex-shrink-0 text-xs">♡</span>
          <span>Health</span>
        </NuxtLink>

        <div class="px-4 pt-4 pb-1">
          <div class="border-t border-[#162016]"></div>
        </div>

        <NuxtLink
          to="/admin"
          class="flex items-center gap-3 px-4 py-2 text-sm transition-colors"
          :class="$route.path === '/admin' ? 'bg-[#0f2014] text-[#6fcf8a]' : 'text-[#5a7a5a] hover:bg-[#0c180e] hover:text-[#c8d8c8]'"
        >
          <span class="w-4 text-center flex-shrink-0 text-xs">⚙</span>
          <span>Admin</span>
        </NuxtLink>
      </nav>

      <!-- Footer -->
      <div class="px-4 py-3 border-t border-[#162016]">
        <div class="text-[10px] text-[#3a5a3a] truncate">v2.0</div>
      </div>
    </aside>

    <!-- Page content -->
    <main class="flex-1 overflow-y-auto bg-[#07090a]">
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
