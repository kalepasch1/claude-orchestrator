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

// CADE fields for the known pending approval
const KNOWN_CADE: Record<string, { context: string; action: string; approveValue: string; denyRisk: string; evidence: string }> = {
  'b400bd23-8aea-4096-aaa8-12ac5357989a': {
    context: 'The orchestrator is requesting authorization to fan out autonomous issue determination (CADE triage) to three additional apps — Apparently, smarter, and Pareto-2080 — using the `@darwin/kernel/cade toDeterminationCredential` pattern already in use on other apps. This enables automated bug severity classification, root-cause routing, and resolution assignment without per-issue human sign-off.',
    action: 'Confirm that `toDeterminationCredential` is authorized for Apparently, smarter, and Pareto-2080. This may require logging into those systems and provisioning the CADE service account, or confirming the existing darwin-kernel OAuth token covers these apps.',
    approveValue: 'Autonomous issue determination begins for these 3 apps, resolving the credential gap and unblocking dependent tasks.',
    denyRisk: 'These apps remain outside CADE scope; issues queue manually and dependent orchestration tasks remain blocked.',
    evidence: 'Credential gap identified during cross-app CADE expansion sweep. The `toDeterminationCredential` pattern is already authorized and operational on all other apps in the portfolio.',
  },
}

function getCade(a: any) {
  return KNOWN_CADE[a.id] || {
    context: a.why || 'Authorization required for this orchestration action.',
    action: 'Review the request and confirm or deny based on current operational policy.',
    approveValue: a.value || 'Action proceeds as requested.',
    denyRisk: a.risk || 'Action is blocked; dependent tasks may queue.',
    evidence: a.detail || a.draft || 'No additional evidence provided.',
  }
}

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

function kindBadge(kind: string) {
  if (kind === 'legal') return 'bg-red-500/10 text-red-400 border-red-800/40'
  if (kind === 'deploy') return 'bg-blue-500/10 text-blue-400 border-blue-800/40'
  if (kind === 'secret') return 'bg-purple-500/10 text-purple-400 border-purple-800/40'
  return 'bg-[#0f2014] text-[#6fcf8a] border-[#1c3a1c]'
}

function riskBadge(level: string) {
  if (!level) return 'text-[#5a7a5a] border-[#162016] bg-[#0a120a]'
  if (level === 'high') return 'text-red-400 border-red-800/40 bg-red-500/10'
  if (level === 'medium') return 'text-yellow-400 border-yellow-800/40 bg-yellow-500/10'
  return 'text-[#6fcf8a] border-[#1c3a1c] bg-[#0f2014]'
}

function ago(ts: string) {
  const d = Math.round((Date.now() - new Date(ts).getTime()) / 60000)
  return d < 60 ? `${d}m ago` : d < 1440 ? `${Math.round(d / 60)}h ago` : `${Math.round(d / 1440)}d ago`
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
  <div class="min-h-screen bg-[#07090a] text-[#dde5dd]">
    <div class="max-w-4xl mx-auto px-6 py-6 space-y-6">

      <!-- Header -->
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-lg font-medium text-[#dde5dd]" style="font-family: 'Fraunces', serif;">Sign-offs</h1>
          <p class="text-xs text-[#3a5a3a] mt-0.5 tracking-wide">Operator approvals requiring human review</p>
        </div>
        <div class="flex items-center gap-3">
          <select
            v-model="projectFilter"
            class="bg-[#070c07] border border-[#1e2e1e] text-[#7a9a7a] text-xs rounded px-3 py-2 focus:outline-none focus:border-[#2d7a3a] cursor-pointer"
          >
            <option value="all">All projects</option>
            <option v-for="p in allProjects" :key="p" :value="p">{{ p }}</option>
          </select>
          <button
            @click="approveAll"
            :disabled="bulkApproving || !filtered.length"
            class="px-3 py-2 bg-[#0f2014] hover:bg-[#1e5228] text-[#6fcf8a] text-xs rounded border border-[#1c3a1c] transition-colors disabled:opacity-40"
          >
            {{ bulkApproving ? 'Approving...' : `Approve All (${filtered.length})` }}
          </button>
          <button
            @click="loadAll"
            class="px-3 py-2 bg-[#0c110c] hover:bg-[#0f180f] text-[#5a7a5a] text-xs rounded border border-[#162016] transition-colors"
          >↻</button>
        </div>
      </div>

      <div v-if="error" class="p-3 bg-red-500/10 border border-red-800/40 rounded-lg text-xs text-red-400">{{ error }}</div>
      <div v-if="loading" class="text-center py-12 text-[#3a5a3a] text-sm">Loading sign-offs...</div>

      <!-- Empty state -->
      <div v-else-if="filtered.length === 0" class="text-center py-16 text-[#3a5a3a]">
        <div class="text-3xl mb-3 opacity-30">○</div>
        <div class="text-base font-medium text-[#5a7a5a]" style="font-family: 'Fraunces', serif;">No pending sign-offs</div>
        <div class="text-xs text-[#3a5a3a] mt-1">All gates are clear</div>
      </div>

      <!-- CADE Approval Cards -->
      <div v-else class="space-y-5">
        <div
          v-for="a in filtered"
          :key="a.id"
          class="bg-[#0c110c] border border-[#162016] rounded-lg overflow-hidden"
          :class="a.kind === 'legal' ? 'border-l-2 border-l-red-800' : a.kind === 'deploy' ? 'border-l-2 border-l-blue-800' : 'border-l-2 border-l-[#1c3a1c]'"
        >
          <!-- Card header -->
          <div class="px-5 py-3 border-b border-[#162016] flex items-center justify-between gap-4">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="text-[10px] px-2 py-0.5 rounded border font-medium" :class="kindBadge(a.kind)">{{ a.kind?.toUpperCase() }}</span>
              <span v-if="a.risk || a.legal_risk_level" class="text-[10px] px-2 py-0.5 rounded border font-medium" :class="riskBadge(a.risk || a.legal_risk_level)">
                {{ (a.risk || a.legal_risk_level || '').toUpperCase() }} RISK
              </span>
              <span v-if="a.approvals_required > 1" class="text-[10px] px-2 py-0.5 rounded border bg-purple-500/10 text-purple-400 border-purple-800/40">{{ a.approvals_required }}-KEY</span>
              <span v-if="a.project" class="text-[10px] text-[#3a5a3a] bg-[#0a120a] px-2 py-0.5 rounded border border-[#162016]">{{ a.project }}</span>
            </div>
            <span class="text-[10px] text-[#3a5a3a] flex-shrink-0">{{ a.created_at ? ago(a.created_at) : '' }}</span>
          </div>

          <!-- Title -->
          <div class="px-5 pt-4 pb-3">
            <h3 class="text-sm font-medium text-[#c8d8c8] mb-1" style="font-family: 'Fraunces', serif;">{{ a.title }}</h3>
          </div>

          <!-- CADE sections -->
          <div class="px-5 space-y-2 pb-4">
            <!-- CONTEXT -->
            <div class="rounded border border-[#162016] overflow-hidden">
              <div class="px-3 py-1.5 bg-[#0a120a] border-b border-[#162016]">
                <span class="text-[10px] font-medium text-[#3a5a3a] tracking-[0.12em] uppercase">Context</span>
              </div>
              <div class="px-3 py-2.5 text-xs text-[#7a9a7a] leading-relaxed">{{ getCade(a).context }}</div>
            </div>

            <!-- ACTION REQUIRED -->
            <div class="rounded border border-[#162016] overflow-hidden">
              <div class="px-3 py-1.5 bg-[#0a120a] border-b border-[#162016]">
                <span class="text-[10px] font-medium text-[#3a5a3a] tracking-[0.12em] uppercase">Action Required</span>
              </div>
              <div class="px-3 py-2.5 text-xs text-[#7a9a7a] leading-relaxed">{{ getCade(a).action }}</div>
            </div>

            <!-- DECISION -->
            <div class="rounded border border-[#162016] overflow-hidden">
              <div class="px-3 py-1.5 bg-[#0a120a] border-b border-[#162016]">
                <span class="text-[10px] font-medium text-[#3a5a3a] tracking-[0.12em] uppercase">Decision</span>
              </div>
              <div class="px-3 py-2.5 space-y-1">
                <div class="text-xs"><span class="text-[#6fcf8a] font-medium mr-2">Approve =</span><span class="text-[#7a9a7a]">{{ getCade(a).approveValue }}</span></div>
                <div class="text-xs"><span class="text-[#f87171] font-medium mr-2">Deny =</span><span class="text-[#7a9a7a]">{{ getCade(a).denyRisk }}</span></div>
              </div>
            </div>

            <!-- EVIDENCE -->
            <div class="rounded border border-[#162016] overflow-hidden">
              <div class="px-3 py-1.5 bg-[#0a120a] border-b border-[#162016]">
                <span class="text-[10px] font-medium text-[#3a5a3a] tracking-[0.12em] uppercase">Evidence</span>
              </div>
              <div class="px-3 py-2.5 text-xs text-[#7a9a7a] leading-relaxed">{{ getCade(a).evidence }}</div>
            </div>
          </div>

          <!-- Actions -->
          <div class="px-5 py-3 border-t border-[#162016] flex items-center justify-between">
            <div class="flex gap-3">
              <button
                @click="decide(a.id, 'approved')"
                class="px-5 py-2 bg-[#0f2014] hover:bg-[#1e5228] text-[#6fcf8a] text-sm font-medium rounded border border-[#1c3a1c] transition-colors"
              >Approve</button>
              <button
                @click="decide(a.id, 'denied')"
                class="px-5 py-2 bg-[#1a0808] hover:bg-[#2a1010] text-[#f87171] text-sm font-medium rounded border border-[#3a1010] transition-colors"
              >Deny</button>
            </div>
            <span v-if="a.id === 'b400bd23-8aea-4096-aaa8-12ac5357989a'" class="text-[10px] text-[#3a5a3a] font-mono">id: {{ a.id.slice(0, 8) }}...</span>
          </div>
        </div>
      </div>

      <!-- Credential Requests -->
      <div v-if="credRequests.length > 0" class="bg-[#0c110c] border border-[#162016] rounded-lg overflow-hidden">
        <div class="px-5 py-3 border-b border-[#162016] flex items-center gap-2">
          <span class="text-xs font-medium text-[#dde5dd]" style="font-family: 'Fraunces', serif;">Credential Requests</span>
          <span class="text-[10px] text-[#3a5a3a]">{{ credRequests.length }} request{{ credRequests.length !== 1 ? 's' : '' }}</span>
        </div>
        <div class="divide-y divide-[#0f180f]">
          <div v-for="c in credRequests" :key="c.id" class="px-5 py-3 flex items-center gap-4">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 mb-0.5">
                <span class="text-[10px] font-mono text-[#6fcf8a]">{{ c.provider }}</span>
                <span
                  class="text-[10px] px-2 py-0.5 rounded border"
                  :class="c.status === 'payment_required' ? 'bg-red-500/10 text-red-400 border-red-800/40' : c.status === 'pending' ? 'bg-yellow-500/10 text-yellow-400 border-yellow-800/40' : 'bg-[#0f2014] text-[#6fcf8a] border-[#1c3a1c]'"
                >{{ c.status }}</span>
                <span v-if="c.project" class="text-[10px] text-[#3a5a3a]">{{ c.project }}</span>
              </div>
              <div class="text-xs text-[#7a9a7a] truncate">{{ c.reason }}</div>
            </div>
            <span class="text-[10px] text-[#3a5a3a] flex-shrink-0">{{ c.created_at ? ago(c.created_at) : '' }}</span>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>
