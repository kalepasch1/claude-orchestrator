<template>
  <div class="orchestrator-shell flex h-screen overflow-hidden" :class="[`density-${accessibility.density}`, `motion-${accessibility.motion}`, { 'contrast-high': accessibility.contrast === 'high', 'keyboard-first': accessibility.keyboard_first }]" :style="{ fontSize: `${accessibility.text_scale}em` }" :data-explanation-depth="accessibility.explanation_depth">
    <button v-if="sidebarOpen" class="fixed inset-0 z-30 bg-black/30 backdrop-blur-sm md:hidden" aria-label="Close navigation" @click="sidebarOpen = false" />
    <aside class="app-sidebar fixed inset-y-0 left-0 z-40 flex w-72 flex-shrink-0 flex-col transition-transform md:static md:w-60 md:translate-x-0" :class="sidebarOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'">
      <div class="brand-lockup">
        <NuxtLink to="/" class="brand-mark"><span class="brand-glyph">M</span><span><b>Madeus</b><small>Orchestrator</small></span></NuxtLink>
        <div class="fleet-status"><span :class="runnerCount > 0 ? 'live-dot' : 'live-dot muted'" />{{ runnerCount > 0 ? 'Fleet online' : 'Fleet offline' }}<NuxtLink v-if="pendingCount" to="/sign-offs">{{ pendingCount }}</NuxtLink></div>
      </div>
      <AdaptiveFocus :runner-count="runnerCount" :pending-approvals="pendingCount" :blocked-tasks="blockedCount" :ready-connectors="readyConnectorCount" />
      <nav class="app-navigation flex-1 overflow-y-auto">
        <NuxtLink
          v-for="item in NAV_ITEMS"
          :key="item.to"
          :to="item.to"
          @click="sidebarOpen = false"
          class="nav-item"
          :class="isActive(item.to) ? 'active' : ''"
        >
          <span class="nav-icon">{{ item.icon }}</span>
          <span>{{ item.label }}</span>
          <span v-if="item.to === '/sign-offs' && pendingCount > 0" class="nav-count critical">{{ pendingCount }}</span>
          <span v-else-if="item.to === '/queue' && blockedCount > 0" class="nav-count">{{ blockedCount }}</span>
          <span v-else-if="item.to === '/connectors' && readyConnectorCount > 0" class="connection-dot" />
        </NuxtLink>
        <div class="nav-divider" />
        <NuxtLink to="/admin/capability-passport" class="nav-item" :class="$route.path.startsWith('/admin') ? 'active' : ''"><span class="nav-icon">⚙</span><span>Settings & capabilities</span></NuxtLink>
      </nav>
      <div class="sidebar-footer">
        <div><span class="user-avatar">{{ String($route.meta?.userInitial || 'K').slice(0, 1) }}</span><span><b>Operator workspace</b><small>Control OS v2.2</small></span></div>
        <button aria-label="Sign out" title="Sign out" @click="signOut">↗</button>
      </div>
    </aside>
    <div class="flex min-w-0 flex-1 flex-col"><header class="mobile-header md:hidden"><button aria-label="Open navigation" @click="sidebarOpen = true">☰</button><span class="brand-glyph">M</span><b>Madeus</b></header><main class="app-main flex-1 overflow-y-auto"><slot /></main></div><UniversalCommand />
  </div>
</template>

<script setup lang="ts">
import { CANONICAL_NAVIGATION } from '~/config/navigation'
const supabase = useSupabaseClient<any>()
const route = useRoute()
const runnerCount = ref(0)
const pendingCount = ref(0)
const blockedCount = ref(0)
const readyConnectorCount = ref(0)
const sidebarOpen = ref(false)
const accessibility = reactive({ density: 'comfortable', explanation_depth: 'balanced', motion: 'system', contrast: 'system', text_scale: 1, keyboard_first: false })

const NAV_ITEMS = CANONICAL_NAVIGATION

function isActive(to: string) {
  return to === '/' ? route.path === '/' || route.path === '/index' : route.path.startsWith(to)
}

async function recordPageView(path: string) { try { const { data: { session } } = await supabase.auth.getSession(); await $fetch('/api/adaptive/event', { method: 'POST', body: { event: 'page_view', route: path, objective: localStorage.getItem('orchestrator:objective') || 'operate' }, headers: session?.access_token ? { authorization: `Bearer ${session.access_token}` } : {} }) } catch {} }

async function signOut() { await supabase.auth.signOut(); await navigateTo('/') }

function alive(r: any) { return (Date.now() - new Date(r.last_seen).getTime()) < 60000 }

async function loadCounts() {
  const [runners, approvals, blocked] = await Promise.all([
    supabase.from('runner_heartbeats').select('last_seen'),
    supabase.from('approvals').select('id', { count: 'exact', head: true }).eq('status', 'pending'),
    supabase.from('tasks').select('id', { count: 'exact', head: true }).in('state', ['BLOCKED', 'CONFLICT', 'TESTFAIL']),
  ])
  runnerCount.value = (runners.data || []).filter(alive).length
  pendingCount.value = approvals.count || 0
  blockedCount.value = blocked.count || 0
  try {
    const { data: { session } } = await supabase.auth.getSession()
    const response = await $fetch<any>('/api/connectors', { headers: session?.access_token ? { authorization: `Bearer ${session.access_token}` } : {} })
    readyConnectorCount.value = (response.connectors || []).reduce((sum: number, item: any) => sum + (item.connected_accounts || []).filter((account: any) => account.status === 'connected').length, 0)
  } catch { readyConnectorCount.value = 0 }
}

async function loadAccessibility() { try { const { data: { session } } = await supabase.auth.getSession(); if (!session?.access_token) return; const response = await $fetch<any>('/api/adaptive/evolution', { headers: { authorization: `Bearer ${session.access_token}` } }); Object.assign(accessibility, response.accessibility || {}) } catch {} }
function applyAccessibility(event: Event) { Object.assign(accessibility, (event as CustomEvent).detail || {}) }

onMounted(() => {
  loadCounts()
  loadAccessibility()
  window.addEventListener('orchestrator:accessibility', applyAccessibility)
  recordPageView(route.path === '/index' ? '/' : route.path)
  const timer = setInterval(loadCounts, 30000)
  onUnmounted(() => { clearInterval(timer); window.removeEventListener('orchestrator:accessibility', applyAccessibility) })
})
watch(() => route.path, path => recordPageView(path === '/index' ? '/' : path))
</script>
<style>
.orchestrator-shell.density-compact nav a{padding-top:.35rem;padding-bottom:.35rem}.orchestrator-shell.density-spacious nav a{padding-top:.75rem;padding-bottom:.75rem}.orchestrator-shell.contrast-high{filter:contrast(1.18)}.orchestrator-shell.motion-none *{animation:none!important;transition:none!important;scroll-behavior:auto!important}.orchestrator-shell.motion-reduced *{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}.orchestrator-shell.keyboard-first :focus-visible{outline:3px solid #2563eb;outline-offset:3px}@media(prefers-reduced-motion:reduce){.orchestrator-shell.motion-system *{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}
</style>
