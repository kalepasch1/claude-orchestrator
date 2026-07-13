<script setup lang="ts">
definePageMeta({ layout: 'default' })

const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()

async function authedFetch<T = any>(url: string, opts: any = {}): Promise<T> {
  const { data: { session } } = await supabase.auth.getSession()
  return $fetch<T>(url, {
    ...opts,
    headers: { ...(opts.headers || {}), ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}) },
  })
}

const approvals = ref<any[]>([])
const credRequests = ref<any[]>([])
const loading = ref(false)
const error = ref('')
const bulkApproving = ref(false)
const projectFilter = ref('all')

const OPERATOR_KINDS = ['operator', 'legal', 'secret', 'deploy']
const isCodeMerge = (a: any) => Boolean(a.slug || /\bmerge of\b/i.test(String(a.title || '')))
const isOperatorApproval = (a: any) => {
  if (isCodeMerge(a)) return false
  const text = `${a.title || ''} ${a.why || ''}`.toLowerCase()
  return OPERATOR_KINDS.includes(a.kind) ||
    (a.kind === 'material' && /\b(legal|regulatory|compliance|business[- ]model)\b/i.test(text)) ||
    (a.kind === 'self' && /\b(credential|secret|api key|token)\b/i.test(text))
}

const allProjects = computed(() => [...new Set(approvals.value.map(a => a.project).filter(Boolean))].sort())
const filtered = computed(() => {
  const list = approvals.value.filter(isOperatorApproval)
  return projectFilter.value === 'all' ? list : list.filter(a => a.project === projectFilter.value)
})

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const [a, c] = await Promise.all([
      supabase.from('approvals').select('*').eq('status', 'pending').order('created_at'),
      supabase.from('credential_requests').select('*').order('created_at', { ascending: false }).limit(20),
    ])
    if (a.error) throw a.error
    approvals.value = a.data || []
    credRequests.value = c.data || []
  } catch (e: any) {
    error.value = e?.message || String(e)
  } finally {
    loading.value = false
  }
}

async function decide(id: string, status: 'approved' | 'denied') {
  const approver = user.value?.email || 'dashboard'
  error.value = ''
  try {
    const res = await authedFetch<any>('/api/approvals/decide', { method: 'POST', body: { id, status, approver } })
    const next = res?.approval
    if (next?.status === 'pending') {
      const idx = approvals.value.findIndex(x => x.id === id)
      if (idx >= 0) approvals.value[idx] = next
    } else {
      approvals.value = approvals.value.filter(x => x.id !== id)
    }
  } catch (e: any) {
    error.value = e?.data?.message || e?.message || String(e)
  }
}

async function approveAll() {
  const items = filtered.value
  if (!items.length) return
  const scope = projectFilter.value === 'all' ? 'all projects' : projectFilter.value
  if (!confirm(`Approve ${items.length} sign-off(s) for ${scope}?`)) return
  bulkApproving.value = true
  try {
    for (const a of [...items]) {
      try { await decide(a.id, 'approved') } catch {}
    }
  } finally { bulkApproving.value = false }
}

function kindColor(kind: string) {
  if (kind === 'legal') return 'bg-red-500/20 text-red-300 border-red-800/40'
  if (kind === 'deploy') return 'bg-blue-500/20 text-blue-300 border-blue-800/40'
  if (kind === 'secret') return 'bg-purple-500/20 text-purple-300 border-purple-800/40'
  return 'bg-amber-500/20 text-amber-300 border-amber-800/40'
}

function riskColor(level: string) {
  if (!level) return 'text-slate-500'
  if (level === 'high') return 'text-red-400'
  if (level === 'medium') return 'text-amber-400'
  return 'text-green-400'
}

function ago(ts: string) {
  const d = Math.round((Date.now() - new Date(ts).getTime()) / 60000)
  return d < 60 ? `${d}m ago` : d < 1440 ? `${Math.round(d/60)}h ago` : `${Math.round(d/1440)}d ago`
}

let sub: any = null
onMounted(async () => {
  if (user.value) await loadAll()
  sub = supabase.channel('signoffs-live')
    .on('postgres_changes', { event: '*', schema: 'public', table: 'approvals' }, () => loadAll())
    .subscribe()
})
onUnmounted(() => { if (sub) supabase.removeChannel(sub) })
watch(user, u => { if (u) loadAll() })
</script>

<template>
  <div class="min-h-screen bg-[#0d1117] text-slate-300">
    <div class="max-w-4xl mx-auto px-6 py-6 space-y-6">

      <!-- Header -->
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-bold text-white">Sign-offs</h1>
          <p class="text-sm text-slate-500 mt-0.5">Operator approvals requiring human review</p>
        </div>
        <div class="flex items-center gap-3">
          <select v-model="projectFilter" class="select-dark text-sm">
            <option value="all">All projects</option>
            <option v-for="p in allProjects" :key="p" :value="p">{{ p }}</option>
          </select>
          <button @click="approveAll" :disabled="bulkApproving || !filtered.length"
            class="px-4 py-2 bg-green-700/40 hover:bg-green-700/60 text-green-300 text-sm rounded-lg transition-colors disabled:opacity-40">
            {{ bulkApproving ? 'Approving…' : `Approve All (${filtered.length})` }}
          </button>
          <button @click="loadAll" class="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-400 text-sm rounded-lg transition-colors">
            ↻
          </button>
        </div>
      </div>

      <div v-if="error" class="p-3 bg-red-500/10 border border-red-800/40 rounded-lg text-sm text-red-400">{{ error }}</div>
      <div v-if="loading" class="text-center py-12 text-slate-500">Loading sign-offs…</div>

      <!-- Approval Cards -->
      <div v-else-if="filtered.length === 0" class="text-center py-16 text-slate-600">
        <div class="text-4xl mb-3">✅</div>
        <div class="text-lg font-medium text-slate-500">No pending sign-offs</div>
        <div class="text-sm text-slate-600 mt-1">All gates are clear</div>
      </div>

      <div v-else class="space-y-4">
        <div v-for="a in filtered" :key="a.id"
          class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden"
          :class="a.kind === 'legal' ? 'border-red-900/50' : a.kind === 'deploy' ? 'border-blue-900/50' : ''">
          <div class="px-5 py-4">
            <!-- Top row -->
            <div class="flex items-start justify-between gap-4">
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 flex-wrap mb-2">
                  <span class="text-xs px-2 py-0.5 rounded-full border font-medium" :class="kindColor(a.kind)">{{ a.kind }}</span>
                  <span v-if="a.project" class="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded-full">{{ a.project }}</span>
                  <span v-if="a.risk" class="text-xs font-medium" :class="riskColor(a.risk)">risk: {{ a.risk }}</span>
                  <span v-if="a.legal_risk_level" class="text-xs px-2 py-0.5 rounded-full"
                    :class="a.legal_risk_level === 'high' ? 'bg-red-500/20 text-red-300' : 'bg-amber-500/20 text-amber-300'">
                    legal: {{ a.legal_risk_level }}
                  </span>
                  <span v-if="a.approvals_required > 1" class="text-xs bg-purple-500/20 text-purple-300 px-2 py-0.5 rounded-full">
                    {{ a.approvals_required }}-key
                  </span>
                  <span class="text-xs text-slate-600 ml-auto">{{ a.created_at ? ago(a.created_at) : '' }}</span>
                </div>
                <h3 class="text-base font-semibold text-white">{{ a.title }}</h3>
                <p v-if="a.why" class="text-sm text-slate-400 mt-1">{{ a.why }}</p>
                <p v-if="a.value" class="text-xs text-slate-500 mt-1 font-mono">{{ a.value }}</p>
              </div>
              <div class="flex gap-2 flex-shrink-0">
                <button @click="decide(a.id, 'approved')"
                  class="px-4 py-2 bg-green-700/30 hover:bg-green-600/50 text-green-300 text-sm font-medium rounded-lg border border-green-800/40 transition-colors">
                  Approve
                </button>
                <button @click="decide(a.id, 'denied')"
                  class="px-4 py-2 bg-red-700/30 hover:bg-red-600/50 text-red-300 text-sm font-medium rounded-lg border border-red-800/40 transition-colors">
                  Deny
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Credential Requests -->
      <div v-if="credRequests.length > 0" class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <div class="px-5 py-3 border-b border-slate-800">
          <span class="text-sm font-semibold text-white">Credential Requests</span>
          <span class="text-xs text-slate-500 ml-2">{{ credRequests.length }} request{{ credRequests.length !== 1 ? 's' : '' }}</span>
        </div>
        <div class="divide-y divide-slate-800">
          <div v-for="c in credRequests" :key="c.id" class="px-5 py-3 flex items-center gap-4">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 mb-0.5">
                <span class="text-xs font-mono text-blue-300">{{ c.provider }}</span>
                <span class="text-xs px-2 py-0.5 rounded-full"
                  :class="c.status === 'payment_required' ? 'bg-red-500/20 text-red-300' : c.status === 'pending' ? 'bg-amber-500/20 text-amber-300' : 'bg-green-500/20 text-green-300'">
                  {{ c.status }}
                </span>
                <span v-if="c.project" class="text-xs text-slate-500">{{ c.project }}</span>
              </div>
              <div class="text-sm text-slate-300 truncate">{{ c.reason }}</div>
            </div>
            <span class="text-xs text-slate-600">{{ c.created_at ? ago(c.created_at) : '' }}</span>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>

<style scoped>
.select-dark {
  @apply bg-slate-800 border border-slate-700 text-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 cursor-pointer;
}
</style>
