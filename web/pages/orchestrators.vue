<script setup lang="ts">
definePageMeta({ layout: 'default' })
const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()

const capabilities = ref<any[]>([])
const loops = ref<any[]>([])
const loading = ref(false)

async function loadAll() {
  loading.value = true
  const [caps, lps] = await Promise.all([
    supabase.from('capabilities').select('*').order('maturity', { ascending: false }),
    supabase.from('loops').select('*').order('project'),
  ])
  capabilities.value = caps.data || []
  loops.value = lps.data || []
  loading.value = false
}

async function toggleLoop(loop: any) {
  await supabase.from('loops').update({ enabled: !loop.enabled }).eq('id', loop.id)
  loop.enabled = !loop.enabled
}

const byDomain = computed(() => {
  const m: Record<string, any[]> = {}
  for (const c of capabilities.value) {
    const d = c.domain || 'general'
    ;(m[d] ??= []).push(c)
  }
  return m
})

const loopsByType = computed(() => {
  const m: Record<string, any[]> = {}
  for (const l of loops.value) {
    const t = l.type || 'other'
    ;(m[t] ??= []).push(l)
  }
  return m
})

function statusGlow(status: string) {
  if (status === 'trusted') return 'ring-1 ring-blue-500/40 shadow-blue-500/10 shadow-lg'
  if (status === 'productizable') return 'ring-1 ring-green-500/30'
  return ''
}
function statusBadge(status: string) {
  if (status === 'trusted') return 'bg-blue-500/20 text-blue-300'
  if (status === 'productizable') return 'bg-green-500/20 text-green-300'
  if (status === 'experimental') return 'bg-slate-700 text-slate-400'
  return 'bg-slate-700 text-slate-500'
}
function healthColor(h: string) {
  if (h === 'healthy') return 'text-green-400'
  if (h === 'degraded') return 'text-amber-400'
  if (h === 'down') return 'text-red-400'
  return 'text-slate-500'
}
function maturityPct(m: any) { return Math.min(100, Math.max(0, Number(m || 0) * 100)) }

onMounted(() => { if (user.value) loadAll() })
watch(user, u => { if (u) loadAll() })
</script>

<template>
  <div class="min-h-screen bg-[#0d1117] text-slate-300">
    <div class="max-w-6xl mx-auto px-6 py-6 space-y-8">

      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-bold text-white">Orchestrators &amp; Capabilities</h1>
          <p class="text-sm text-slate-500 mt-0.5">AI capability registry and automation loops</p>
        </div>
        <button @click="loadAll" class="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-400 text-sm rounded-lg">↻ Refresh</button>
      </div>

      <div v-if="loading" class="text-center py-12 text-slate-600">Loading…</div>

      <!-- Capabilities by Domain -->
      <div v-for="(caps, domain) in byDomain" :key="domain" class="space-y-3">
        <h2 class="text-sm font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-2">
          <span class="w-1 h-4 bg-blue-500 rounded-full inline-block"></span>
          {{ domain }}
          <span class="text-slate-600 font-normal normal-case">{{ caps.length }}</span>
        </h2>
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <div v-for="cap in caps" :key="cap.id"
            class="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3 transition-shadow"
            :class="statusGlow(cap.status)">
            <div class="flex items-start justify-between gap-2">
              <h3 class="text-base font-semibold text-white leading-tight">{{ cap.name }}</h3>
              <span class="text-xs px-2 py-0.5 rounded-full flex-shrink-0" :class="statusBadge(cap.status)">{{ cap.status }}</span>
            </div>
            <p v-if="cap.summary" class="text-xs text-slate-500 leading-relaxed">{{ cap.summary }}</p>
            <div class="space-y-1">
              <div class="flex justify-between text-xs text-slate-500">
                <span>Maturity</span>
                <span class="font-mono">{{ Math.round(maturityPct(cap.maturity)) }}%</span>
              </div>
              <div class="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                <div class="h-full rounded-full transition-all"
                  :style="`width: ${maturityPct(cap.maturity)}%`"
                  :class="cap.maturity >= 0.8 ? 'bg-green-500' : cap.maturity >= 0.5 ? 'bg-blue-500' : 'bg-slate-600'">
                </div>
              </div>
            </div>
            <div class="flex items-center gap-2 flex-wrap">
              <span v-if="cap.slug" class="text-xs font-mono text-slate-600">{{ cap.slug }}</span>
              <span v-if="cap.regulated" class="text-xs bg-red-500/10 text-red-400 px-1.5 py-0.5 rounded">regulated</span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="!loading && Object.keys(byDomain).length === 0" class="text-center py-12 text-slate-600">
        No capabilities found in registry
      </div>

      <!-- Loops -->
      <div class="space-y-3">
        <h2 class="text-sm font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-2">
          <span class="w-1 h-4 bg-purple-500 rounded-full inline-block"></span>
          Automation Loops
        </h2>
        <div v-if="loops.length === 0" class="text-slate-600 text-sm">No loops configured</div>
        <div v-else class="space-y-4">
          <div v-for="(loopList, type) in loopsByType" :key="type">
            <div class="flex items-center gap-2 mb-2">
              <span class="text-xs text-slate-500 uppercase tracking-wide">{{ type }}</span>
              <span class="text-xs text-slate-700">{{ loopList.length }}</span>
              <span class="text-xs ml-auto" :class="loopList.every(l => l.health === 'healthy') ? 'text-green-500' : 'text-amber-500'">
                {{ loopList.filter(l => l.health === 'healthy').length }}/{{ loopList.length }} healthy
              </span>
            </div>
            <div class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
              <table class="w-full text-sm">
                <tbody class="divide-y divide-slate-800">
                  <tr v-for="l in loopList" :key="l.id" class="hover:bg-slate-800/30">
                    <td class="px-4 py-2.5 text-slate-300 font-medium">{{ l.project }}</td>
                    <td class="px-4 py-2.5 text-xs font-mono text-slate-500">{{ l.cadence_seconds ? `${l.cadence_seconds}s` : '—' }}</td>
                    <td class="px-4 py-2.5 text-xs" :class="healthColor(l.health)">{{ l.health || '—' }}</td>
                    <td class="px-4 py-2.5 text-right">
                      <button @click="toggleLoop(l)"
                        class="px-3 py-1 text-xs rounded-full border transition-colors"
                        :class="l.enabled ? 'border-green-700 text-green-400 hover:bg-green-400/10' : 'border-slate-700 text-slate-500 hover:bg-slate-700'">
                        {{ l.enabled ? 'enabled' : 'disabled' }}
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>
