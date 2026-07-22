<script setup lang="ts">
/**
 * ProofPackViewer — Dashboard component showing Common Brain deployments,
 * recent receipt digests, and proof-pack portfolio.
 *
 * Reads from controls table key "common_brain_deployments" via Supabase.
 */
const client = useSupabaseClient()

const deployments = ref<any[]>([])
const stats = ref<any>({})
const loading = ref(true)

async function load() {
  loading.value = true
  try {
    const { data } = await client
      .from('controls')
      .select('value')
      .eq('key', 'common_brain_deployments')
      .single()
    if (data?.value) {
      const store = typeof data.value === 'string' ? JSON.parse(data.value) : data.value
      deployments.value = (store.deployments || []).slice(-50).reverse()
      stats.value = store.stats || {}
    }
  } catch (e) {
    console.warn('ProofPackViewer: failed to load', e)
  }
  loading.value = false
}

onMounted(load)

// Also load tournament standings
const standings = ref<any[]>([])
async function loadStandings() {
  try {
    const { data } = await client
      .from('controls')
      .select('value')
      .eq('key', 'cade_tournaments')
      .single()
    if (data?.value) {
      const store = typeof data.value === 'string' ? JSON.parse(data.value) : data.value
      const s = store.standings || {}
      standings.value = Object.entries(s)
        .map(([model, v]: [string, any]) => ({
          model,
          wins: v.wins || 0,
          losses: v.losses || 0,
          rate: (v.wins || 0) / Math.max((v.wins || 0) + (v.losses || 0), 1),
        }))
        .sort((a: any, b: any) => b.wins - a.wins)
        .slice(0, 10)
    }
  } catch (e) {
    console.warn('ProofPackViewer: failed to load standings', e)
  }
}
onMounted(loadStandings)

function statusColor(status: string) {
  if (status === 'merged') return 'text-green-400'
  if (status === 'rollback') return 'text-red-400'
  return 'text-amber-400'
}

function timeAgo(ts: number) {
  const mins = Math.floor((Date.now() / 1000 - ts) / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}
</script>

<template>
  <div class="bg-slate-900 border border-slate-700 rounded-xl p-4">
    <div class="flex items-center gap-2 mb-4">
      <span class="text-lg font-bold">Proof-Pack Portfolio</span>
      <button @click="load(); loadStandings()" class="ml-auto text-xs text-slate-400 hover:text-slate-100">↻ Refresh</button>
    </div>

    <!-- Stats cards -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
      <div class="bg-slate-800 rounded-lg p-3 text-center">
        <div class="text-2xl font-bold text-slate-100">{{ stats.total || 0 }}</div>
        <div class="text-xs text-slate-400">Total Deployments</div>
      </div>
      <div class="bg-slate-800 rounded-lg p-3 text-center">
        <div class="text-2xl font-bold text-green-400">{{ stats.merged || 0 }}</div>
        <div class="text-xs text-slate-400">Merged</div>
      </div>
      <div class="bg-slate-800 rounded-lg p-3 text-center">
        <div class="text-2xl font-bold text-sky-400">{{ (stats.tokens_avoided || 0).toLocaleString() }}</div>
        <div class="text-xs text-slate-400">Tokens Avoided</div>
      </div>
      <div class="bg-slate-800 rounded-lg p-3 text-center">
        <div class="text-2xl font-bold text-amber-400">{{ (stats.minutes_saved || 0).toFixed(1) }}m</div>
        <div class="text-xs text-slate-400">Minutes Saved</div>
      </div>
    </div>

    <!-- Tournament Standings -->
    <div v-if="standings.length" class="mb-4">
      <div class="text-sm font-semibold text-slate-300 mb-2">Tournament Standings</div>
      <div class="bg-slate-800 rounded-lg overflow-hidden">
        <div v-for="s in standings" :key="s.model"
             class="flex items-center gap-2 px-3 py-1.5 border-b border-slate-700/50 last:border-0 text-sm">
          <span class="font-mono text-xs text-slate-300 flex-1 truncate">{{ s.model }}</span>
          <span class="text-green-400 text-xs w-12 text-right">{{ s.wins }}W</span>
          <span class="text-red-400 text-xs w-12 text-right">{{ s.losses }}L</span>
          <span class="text-xs w-14 text-right" :class="s.rate > 0.7 ? 'text-green-400' : s.rate > 0.4 ? 'text-amber-400' : 'text-red-400'">
            {{ (s.rate * 100).toFixed(0) }}%
          </span>
        </div>
      </div>
    </div>

    <!-- Recent Deployments -->
    <div class="text-sm font-semibold text-slate-300 mb-2">Recent Deployments</div>
    <div v-if="loading" class="text-slate-500 text-sm py-4 text-center">Loading…</div>
    <div v-else-if="!deployments.length" class="text-slate-500 text-sm py-4 text-center">No deployments yet</div>
    <div v-else class="space-y-2 max-h-96 overflow-y-auto">
      <div v-for="d in deployments" :key="d.task_id + d.timestamp"
           class="bg-slate-800 rounded-lg p-3 text-sm">
        <div class="flex items-center gap-2">
          <span class="font-bold text-xs uppercase" :class="statusColor(d.status)">{{ d.status }}</span>
          <span v-if="d.is_common_brain" class="text-xs bg-purple-900/60 text-purple-300 rounded px-1.5 py-0.5">BRAIN</span>
          <span class="text-slate-400 text-xs">{{ d.project }}</span>
          <span class="flex-1"></span>
          <span class="text-slate-500 text-xs">{{ timeAgo(d.timestamp) }}</span>
        </div>
        <div class="flex items-center gap-3 mt-1 text-xs text-slate-400">
          <span v-if="d.model">{{ d.model }}</span>
          <span v-if="d.domain" class="text-slate-500">{{ d.domain }}</span>
          <span v-if="d.cost_usd" class="text-amber-400">${{ d.cost_usd.toFixed(3) }}</span>
          <span v-if="d.tokens_avoided" class="text-sky-400">{{ d.tokens_avoided.toLocaleString() }} tokens saved</span>
          <span v-if="d.wall_s" class="text-slate-500">{{ d.wall_s.toFixed(1) }}s</span>
        </div>
        <div v-if="d.files && d.files.length" class="mt-1 text-xs text-slate-500 truncate">
          {{ d.files.slice(0, 5).join(', ') }}<span v-if="d.files.length > 5"> +{{ d.files.length - 5 }} more</span>
        </div>
      </div>
    </div>
  </div>
</template>
