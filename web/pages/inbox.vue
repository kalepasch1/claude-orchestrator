<script setup lang="ts">
definePageMeta({ layout: 'default' })
const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()

const inbox = ref<any[]>([])
const credRequests = ref<any[]>([])
const recentPrunes = ref<any[]>([])
const feedbackItems = ref<any[]>([])
const loading = ref(false)

async function loadAll() {
  loading.value = true
  const [i, c, pr, fb] = await Promise.all([
    supabase.from('v_action_inbox').select('*').limit(50),
    supabase.from('credential_requests').select('*').order('created_at', { ascending: false }).limit(30),
    supabase.from('resource_events').select('kind,detail,action,created_at').eq('kind', 'prune').order('created_at', { ascending: false }).limit(10),
    supabase.from('orchestrator_feedback').select('category,severity,status,observation,created_at').order('created_at', { ascending: false }).limit(50),
  ])
  inbox.value = (i.data || []).filter((item: any) => {
    const kind = String(item.kind ?? item.type ?? '').toLowerCase()
    if (kind === 'blocked_task') return false
    return !/\bblocked_task\b/.test(`${item.title || ''} ${item.message || ''}`.toLowerCase())
  })
  credRequests.value = c.data || []
  recentPrunes.value = pr.data || []
  feedbackItems.value = fb.data || []
  loading.value = false
}

const feedbackStats = computed(() => {
  const cats: Record<string, number> = {}
  const sevs: Record<string, number> = {}
  let newCount = 0
  for (const f of feedbackItems.value) {
    cats[f.category] = (cats[f.category] || 0) + 1
    sevs[f.severity] = (sevs[f.severity] || 0) + 1
    if (f.status === 'new') newCount++
  }
  return { cats, sevs, newCount, total: feedbackItems.value.length }
})

function kindColor(kind: string) {
  const k = (kind || '').toLowerCase()
  if (k === 'alert') return 'bg-red-50 text-red-600'
  if (k === 'warning') return 'bg-amber-50 text-amber-600'
  if (k === 'info') return 'bg-blue-50 text-blue-600'
  return 'bg-gray-200 text-gray-500'
}

function credStatusColor(status: string) {
  if (status === 'payment_required') return 'bg-red-50 text-red-600'
  if (status === 'pending') return 'bg-amber-50 text-amber-600'
  if (status === 'approved') return 'bg-green-50 text-green-600'
  return 'bg-gray-200 text-gray-500'
}

function sevColor(sev: string) {
  if (sev === 'critical') return 'text-red-600'
  if (sev === 'high') return 'text-orange-600'
  if (sev === 'med') return 'text-amber-600'
  return 'text-gray-400'
}

function ago(ts: string) {
  const d = Math.round((Date.now() - new Date(ts).getTime()) / 60000)
  return d < 60 ? `${d}m ago` : d < 1440 ? `${Math.round(d/60)}h ago` : `${Math.round(d/1440)}d ago`
}

let sub: any = null
onMounted(async () => {
  if (user.value) await loadAll()
  sub = supabase.channel('inbox-live')
    .on('postgres_changes', { event: '*', schema: 'public', table: 'v_action_inbox' }, () => loadAll())
    .subscribe()
})
onUnmounted(() => { if (sub) supabase.removeChannel(sub) })
watch(user, u => { if (u) loadAll() })
</script>

<template>
  <div class="min-h-screen bg-white text-gray-900">
    <div class="max-w-4xl mx-auto px-6 py-6 space-y-6">

      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-bold text-gray-900">Inbox</h1>
          <p class="text-sm text-gray-500 mt-0.5">Action items, credential requests, and feedback</p>
        </div>
        <button @click="loadAll" class="px-3 py-2 bg-gray-100 hover:bg-gray-200 text-gray-500 text-sm rounded-lg">↻ Refresh</button>
      </div>

      <div v-if="loading" class="text-center py-12 text-gray-400">Loading…</div>

      <!-- Action Inbox -->
      <div class="bg-gray-50 border border-gray-200 rounded-xl overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-200 flex items-center gap-2">
          <span class="text-sm font-semibold text-gray-900">Action Items</span>
          <span class="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">{{ inbox.length }}</span>
        </div>
        <div v-if="inbox.length === 0" class="px-5 py-8 text-center text-gray-400 text-sm">Inbox clear</div>
        <div v-else class="divide-y divide-gray-200">
          <div v-for="item in inbox" :key="item.id" class="px-5 py-3">
            <div class="flex items-start gap-3">
              <span class="text-xs px-2 py-0.5 rounded-full mt-0.5 flex-shrink-0" :class="kindColor(item.kind)">{{ item.kind }}</span>
              <div class="flex-1 min-w-0">
                <div class="text-sm text-gray-800 font-medium">{{ item.title }}</div>
                <div v-if="item.message" class="text-xs text-gray-500 mt-0.5">{{ item.message }}</div>
                <div v-if="item.project" class="text-xs text-gray-400 mt-0.5">{{ item.project }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Credential Requests -->
      <div class="bg-gray-50 border border-gray-200 rounded-xl overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-200 flex items-center gap-2">
          <span class="text-sm font-semibold text-gray-900">Credential Requests</span>
          <span v-if="credRequests.filter(c => c.status === 'payment_required').length > 0"
            class="text-xs bg-red-50 text-red-600 px-2 py-0.5 rounded-full">
            {{ credRequests.filter(c => c.status === 'payment_required').length }} payment required
          </span>
        </div>
        <div v-if="credRequests.length === 0" class="px-5 py-6 text-center text-gray-400 text-sm">No credential requests</div>
        <div v-else class="divide-y divide-gray-200">
          <div v-for="c in credRequests" :key="c.id" class="px-5 py-3 flex items-start gap-4"
            :class="c.status === 'payment_required' ? 'bg-red-500/5' : ''">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 mb-1">
                <span class="text-xs font-mono font-medium text-blue-600">{{ c.provider }}</span>
                <span class="text-xs px-1.5 py-0.5 rounded-full" :class="credStatusColor(c.status)">{{ c.status }}</span>
                <span v-if="c.project" class="text-xs text-gray-500">{{ c.project }}</span>
              </div>
              <div class="text-sm text-gray-700">{{ c.reason }}</div>
            </div>
            <span class="text-xs text-gray-400 flex-shrink-0">{{ c.created_at ? ago(c.created_at) : '' }}</span>
          </div>
        </div>
      </div>

      <!-- Recent Prune Events -->
      <div v-if="recentPrunes.length > 0" class="bg-gray-50 border border-gray-200 rounded-xl overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-200">
          <span class="text-sm font-semibold text-gray-900">Recent Prune Events</span>
        </div>
        <div class="divide-y divide-gray-200">
          <div v-for="p in recentPrunes" :key="p.created_at" class="px-5 py-2.5 flex items-center gap-4 text-xs">
            <span class="text-gray-400 flex-shrink-0">{{ p.created_at ? ago(p.created_at) : '' }}</span>
            <span class="text-gray-500 truncate">{{ p.action || p.detail }}</span>
          </div>
        </div>
      </div>

      <!-- Feedback Stats -->
      <div class="bg-gray-50 border border-gray-200 rounded-xl p-5 space-y-4">
        <div class="flex items-center justify-between">
          <span class="text-sm font-semibold text-gray-900">Feedback Summary</span>
          <span class="text-xs text-gray-500">{{ feedbackStats.total }} total · {{ feedbackStats.newCount }} new</span>
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div>
            <div class="text-xs text-gray-500 mb-2">By category</div>
            <div class="space-y-1">
              <div v-for="(count, cat) in feedbackStats.cats" :key="cat" class="flex justify-between text-xs">
                <span class="text-gray-500">{{ cat }}</span>
                <span class="font-mono text-gray-700">{{ count }}</span>
              </div>
            </div>
          </div>
          <div>
            <div class="text-xs text-gray-500 mb-2">By severity</div>
            <div class="space-y-1">
              <div v-for="(count, sev) in feedbackStats.sevs" :key="sev" class="flex justify-between text-xs">
                <span :class="sevColor(String(sev))">{{ sev }}</span>
                <span class="font-mono text-gray-700">{{ count }}</span>
              </div>
            </div>
          </div>
        </div>
        <!-- Recent feedback items -->
        <div v-if="feedbackItems.length > 0" class="space-y-2 pt-2 border-t border-gray-200">
          <div class="text-xs text-gray-500">Recent observations</div>
          <div v-for="f in feedbackItems.slice(0, 5)" :key="f.created_at" class="text-xs text-gray-500 flex gap-2">
            <span :class="sevColor(f.severity)" class="flex-shrink-0">{{ f.severity }}</span>
            <span class="truncate">{{ f.observation }}</span>
            <span class="text-gray-400 flex-shrink-0">{{ f.created_at ? ago(f.created_at) : '' }}</span>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>
