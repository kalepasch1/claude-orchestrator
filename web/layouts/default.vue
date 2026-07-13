<template>
  <div class="flex h-screen bg-white text-gray-900 overflow-hidden">
    <!-- Sidebar -->
    <aside class="w-56 flex-shrink-0 bg-gray-50 border-r border-gray-200 flex flex-col">
      <!-- Branding -->
      <div class="px-4 py-4 border-b border-gray-200">
        <div class="mb-1">
          <div class="text-xs tracking-[0.25em] uppercase text-gray-900 font-semibold" style="font-family: 'Fraunces', serif; letter-spacing: 0.2em;">ORCHESTRATOR</div>
          <div class="text-[10px] text-gray-500 mt-0.5 tracking-wide">AI Control Platform</div>
        </div>
        <div class="mt-3 flex items-center gap-2">
          <span
            class="w-1.5 h-1.5 rounded-full flex-shrink-0"
            :class="runnerCount > 0 ? 'bg-emerald-500 dot-breathe' : 'bg-gray-300'"
          ></span>
          <span class="text-[11px] text-gray-500">{{ runnerCount }} active</span>
          <NuxtLink v-if="pendingCount > 0" to="/sign-offs" class="ml-auto">
            <span class="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 bg-red-500 text-white text-[10px] rounded-full font-bold">{{ pendingCount }}</span>
          </NuxtLink>
        </div>
      </div>
      <!-- Navigation -->
      <nav class="flex-1 overflow-y-auto py-2">
        <NuxtLink
          v-for="item in NAV_ITEMS"
          :key="item.to"
          :to="item.to"
          class="flex items-center gap-3 px-4 py-2 text-sm transition-colors"
          :class="isActive(item.to) ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'"
        >
          <span class="w-4 text-center flex-shrink-0 text-xs">{{ item.icon }}</span>
          <span>{{ item.label }}</span>
          <span v-if="item.to === '/sign-offs' && pendingCount > 0" class="ml-auto inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 bg-red-500 text-white text-[10px] rounded-full font-bold">{{ pendingCount }}</span>
        </NuxtLink>

        <div class="px-4 pt-4 pb-1">
          <div class="border-t border-gray-200"></div>
        </div>

        <NuxtLink
          to="/admin"
          class="flex items-center gap-3 px-4 py-2 text-sm transition-colors"
          :class="$route.path.startsWith('/admin') ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'"
        >
          <span class="w-4 text-center flex-shrink-0 text-xs">⚙</span>
          <span>Admin</span>
        </NuxtLink>
      </nav>

      <!-- Footer -->
      <div class="px-4 py-3 border-t border-gray-200">
        <div class="text-[10px] text-gray-400">v2.0</div>
      </div>
    </aside>

    <!-- Page content -->
    <main class="flex-1 overflow-y-auto bg-white">
      <slot />
    </main>
  </div>
</template>

<script setup lang="ts">
const supabase = useSupabaseClient<any>()
const runnerCount = ref(0)
const pendingCount = ref(0)

const NAV_ITEMS = [
  { label: 'Command Center', icon: '→', to: '/' },
  { label: 'Sign-offs',      icon: '○', to: '/sign-offs' },
  { label: 'Queue',          icon: '≡', to: '/queue' },
  { label: 'Orchestrators',  icon: '◈', to: '/orchestrators' },
  { label: 'Spend & ROI',    icon: '$', to: '/spend' },
  { label: 'Loops',          icon: '∞', to: '/loops' },
  { label: 'Inbox',          icon: '⊡', to: '/inbox' },
  { label: 'Fleet',          icon: '◉', to: '/fleet' },
  { label: 'Health',         icon: '♡', to: '/health' },
]

function isActive(to: string) {
  const route = useRoute()
  return to === '/' ? route.path === '/' : route.path.startsWith(to)
}

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
