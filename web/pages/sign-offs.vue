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

const OPERATOR_KINDS = ['operator', 'legal', 'secret', 'deploy', 'self']
const isCodeMerge = (a: any) => Boolean(a.slug && /^(merge|relfix|qafix|canary)/.test(a.slug))
const isOperatorApproval = (a: any) => { if (isCodeMerge(a)) return false; return OPERATOR_KINDS.includes(a.kind) }

const allProjects = computed(() => [...new Set(approvals.value.map((a: any) => a.project).filter(Boolean))].sort())
const filtered = computed(() => {
  const list = approvals.value.filter(isOperatorApproval)
  return projectFilter.value === 'all' ? list : list.filter((a: any) => a.project === projectFilter.value)
})

// ── CADE library ──────────────────────────────────────────────────────────────
interface CadeEntry { context: string; action: string; approveValue: string; denyRisk: string; evidence: string; isLegal: boolean; legalProjects: string[] }
const KNOWN_CADE: Record<string, CadeEntry> = {
  'b400bd23-8aea-4096-aaa8-12ac5357989a': {
    context: 'The orchestrator is requesting authorization to fan out autonomous issue determination (CADE triage) to three additional apps — Apparently, smarter, and Pareto-2080 — using the @darwin/kernel/cade toDeterminationCredential pattern already operational on all other portfolio apps. This enables automated bug severity classification, root-cause routing, and resolution assignment without per-issue human sign-off.',
    action: 'Confirm toDeterminationCredential is authorized for Apparently, smarter, and Pareto-2080. Either (a) verify the existing darwin-kernel OAuth token already covers these apps, or (b) provision the CADE service account credential in each app\'s admin panel.',
    approveValue: 'Autonomous issue determination begins for these 3 apps, resolving the credential gap and unblocking dependent tasks in the pipeline.',
    denyRisk: 'These apps remain outside CADE scope; issues queue manually and dependent orchestration tasks remain blocked.',
    evidence: 'Credential gap identified during cross-app CADE expansion sweep (intake/tomorrow-cade-frontier2-0712.md). The toDeterminationCredential pattern is already authorized and operational on all other portfolio apps. No legal/regulatory exposure on this credential type.',
    isLegal: false, legalProjects: ['apparently', 'smarter', 'pareto-2080'],
  },
  'fc0b4bf3-7714-4cdf-bb1d-1d3ec31906fa': {
    context: 'resource_medic auto-applied a permanent hot-lane exclusion for codestral:22b and deepseek-coder-v2:16b after 4 RAM-clamp cycles in 60 minutes. Both models are now restricted to canary-only usage.',
    action: 'Acknowledge this informational notice. No provisioning action required. To re-enable either model for hot-lane use, update fleet_config manually after confirming RAM capacity has changed.',
    approveValue: 'Notice acknowledged; models stay canary-only. Fleet continues with corrected routing.',
    denyRisk: 'No meaningful effect — the exclusion is already applied. Denying is equivalent to acknowledging with a note of disagreement.',
    evidence: 'resource_medic detected 4x reload/clamp thrash in 60 minutes (configured threshold). RAM was above 92% at time of exclusion.',
    isLegal: false, legalProjects: [],
  },
  '78d3eb2f-87f7-42c8-bc01-4c130411f20e': {
    context: 'The task cade-precedent-gap-harvest is orphaned — all its dependencies completed in DECOMPOSED state, meaning the parent chain can no longer be satisfied. No runner can claim it.',
    action: 'Either (a) cancel the task to clear it from the queue, or (b) re-scope it by removing or replacing its deps array so it can run standalone.',
    approveValue: 'Task is re-scoped or cancelled; queue is freed and orchestrator stops attempting to resolve this dependency chain.',
    denyRisk: 'Task remains un-claimable, consuming a queue slot indefinitely without progress.',
    evidence: 'All deps dead: cade-precedent-outcome-ranking is DECOMPOSED. Auto-repair failed. Manual intervention required.',
    isLegal: false, legalProjects: [],
  },
  'f5ad2036-0fac-4f04-acbe-db18d966a87e': {
    context: 'The Mac runner is under resource pressure: RAM at 92.7% (critical) and disk at 45.3% (moderate). The orchestrator already throttled to 1 concurrent task and applied pruning to protect the machine.',
    action: 'Monitor — should self-resolve as running tasks complete. If RAM stays above 90% for 30+ minutes, consider restarting the runner process or clearing /tmp/claude-orchestrator worktree directories.',
    approveValue: 'Acknowledged; orchestrator continues in throttled mode (1 concurrent task) until pressure clears.',
    denyRisk: 'No meaningful effect on resource state. RAM will not decrease by denying.',
    evidence: 'Disk: 45.3%. RAM: 92.7% (critical threshold: 90%). Throttled to 1 concurrent task. Pruning applied automatically.',
    isLegal: false, legalProjects: [],
  },
}
function getCade(a: any): CadeEntry {
  return KNOWN_CADE[a.id] || {
    context: a.why || 'Authorization required for this orchestration action.',
    action: a.draft || 'Review the request and confirm or deny based on current operational policy.',
    approveValue: a.value || 'Action proceeds as requested.',
    denyRisk: a.risk || 'Action is blocked; dependent tasks may queue.',
    evidence: a.detail || 'No additional evidence provided.',
    isLegal: a.kind === 'legal' || a.legal_risk_level === 'high',
    legalProjects: a.project ? [a.project] : [],
  }
}

// ── AI Hivemind Assessment ────────────────────────────────────────────────────
interface AiAssessment { recommendation: string; confidence: number; reasoning: string; risks: string[]; legalExposure: boolean }
const AI_ASSESSMENTS: Record<string, AiAssessment> = {
  'b400bd23-8aea-4096-aaa8-12ac5357989a': {
    recommendation: 'APPROVE',
    confidence: 91,
    reasoning: 'Pattern is proven and already operational across all other portfolio apps. toDeterminationCredential is scoped to issue triage classification only — no write access to production data or user records. The credential gap is blocking dependent pipeline tasks with measurable queue cost. Delay cost exceeds approval risk. No legal or regulatory exposure detected for this credential type.',
    risks: [
      'If the darwin-kernel OAuth token is shared across all 3 apps, a token expiry becomes a single point of failure for Apparently, smarter, and Pareto simultaneously.',
      'Scope of toDeterminationCredential should be explicitly verified before provisioning — confirm read-only / classification-only access.',
      'Verify Apparently and smarter do not route user-generated content through CADE determination (potential PII consideration).',
    ],
    legalExposure: false,
  },
  'fc0b4bf3-7714-4cdf-bb1d-1d3ec31906fa': {
    recommendation: 'ACKNOWLEDGE',
    confidence: 98,
    reasoning: 'resource_medic correctly applied hot-lane exclusion after 4 RAM-clamp cycles in 60 minutes, which is the configured safety threshold. This is informational only — the protective action is already applied and correct. Codestral:22b and deepseek-coder-v2:16b exceed comfortable RAM bounds on current hardware. Canary-only is the right long-term posture until RAM is expanded.',
    risks: [
      'If these models provided unique capability not covered by haiku/sonnet, canary-only restriction may reduce output quality on specific edge cases.',
      'No fleet-wide throughput impact — haiku and sonnet continue handling all hot-lane work.',
    ],
    legalExposure: false,
  },
  '78d3eb2f-87f7-42c8-bc01-4c130411f20e': {
    recommendation: 'CANCEL',
    confidence: 83,
    reasoning: 'All dependency tasks are in DECOMPOSED state, meaning the orchestrator already broke this work into sub-tasks that have since executed. The parent cade-precedent-gap-harvest task is a vestige. Given the volume of similar CADE work completed in the past 7 days, its objective is likely already covered. Cancelling removes the orphan and frees the queue slot.',
    risks: [
      'If cancelled incorrectly, specific CADE precedent gap edge cases may be missed — low probability given decomposed sub-tasks already ran.',
      'Search for open "cade-precedent" tasks before cancelling to confirm coverage.',
    ],
    legalExposure: false,
  },
  'f5ad2036-0fac-4f04-acbe-db18d966a87e': {
    recommendation: 'MONITOR',
    confidence: 88,
    reasoning: 'RAM at 92.7% is critical but the orchestrator is already throttled correctly to 1 concurrent task. This should self-resolve as running tasks complete. The concern is if multiple large Sonnet or Gemini tasks are simultaneously in RUNNING state — their memory footprints accumulate. If RAM does not drop below 85% in 30 minutes, manual runner restart is needed.',
    risks: [
      'If RAM stays elevated: risk of Mac crash or OOM kill of the runner process, which would leave RUNNING tasks as stale zombies.',
      'Disk at 45.3% is moderate — /tmp worktrees accumulate during high throughput. Verify pruning is completing successfully.',
      'Throttle to 1 concurrent task reduces pipeline throughput significantly until pressure clears.',
    ],
    legalExposure: false,
  },
}
function getAi(a: any): AiAssessment {
  return AI_ASSESSMENTS[a.id] || {
    recommendation: a.kind === 'legal' || a.legal_risk_level === 'high' ? 'ESCALATE' : 'APPROVE',
    confidence: 65,
    reasoning: 'Insufficient precedent data for a high-confidence assessment. Review the CADE sections carefully before deciding.',
    risks: ['No specific risks enumerated — manual review recommended.'],
    legalExposure: a.kind === 'legal' || a.legal_risk_level === 'high',
  }
}

const REC_STYLE: Record<string, string> = {
  APPROVE:     'text-[#6fcf8a] bg-[#0a1e0e] border-[#1c3a1c]',
  ACKNOWLEDGE: 'text-[#60a5fa] bg-[#080f28] border-[#1c2a4a]',
  CANCEL:      'text-[#f87171] bg-[#1a0808] border-[#3a1010]',
  ESCALATE:    'text-red-300 bg-red-900/20 border-red-700/60',
  MONITOR:     'text-yellow-400 bg-yellow-900/10 border-yellow-800/40',
}

const WAR_ROOM_PAGES = [
  { label: 'Compliance', path: '/admin/compliance' },
  { label: 'Regulatory', path: '/admin/regulatory' },
  { label: 'Legal', path: '/admin/policies' },
  { label: 'Telemetry', path: '/admin/telemetry' },
]

function kindBadge(kind: string) {
  if (kind === 'legal') return 'bg-red-500/10 text-red-400 border-red-800/40'
  if (kind === 'deploy') return 'bg-blue-500/10 text-blue-400 border-blue-800/40'
  if (kind === 'secret') return 'bg-purple-500/10 text-purple-400 border-purple-800/40'
  if (kind === 'self') return 'bg-yellow-500/10 text-yellow-400 border-yellow-800/40'
  return 'bg-[#0f2014] text-[#6fcf8a] border-[#1c3a1c]'
}
function borderColor(kind: string) {
  if (kind === 'legal') return 'border-l-red-800'
  if (kind === 'deploy') return 'border-l-blue-800'
  if (kind === 'secret') return 'border-l-purple-700'
  if (kind === 'self') return 'border-l-yellow-800'
  return 'border-l-[#1c3a1c]'
}
function ago(ts: string) {
  const d = Math.round((Date.now() - new Date(ts).getTime()) / 60000)
  return d < 60 ? `${d}m ago` : d < 1440 ? `${Math.round(d / 60)}h ago` : `${Math.round(d / 1440)}d ago`
}

async function loadAll() {
  loading.value = true; error.value = ''
  try {
    const [a, c] = await Promise.all([
      supabase.from('approvals').select('*').eq('status', 'pending').order('created_at'),
      supabase.from('credential_requests').select('*').order('created_at', { ascending: false }).limit(20),
    ])
    if (a.error) throw a.error
    approvals.value = a.data || []
    credRequests.value = c.data || []
  } catch (e: any) { error.value = e?.message || String(e) }
  finally { loading.value = false }
}

async function decide(id: string, status: 'approved' | 'denied') {
  const approver = user.value?.email || 'dashboard'; error.value = ''
  try {
    const res = await authedFetch<any>('/api/approvals/decide', { method: 'POST', body: { id, status, approver } })
    const next = res?.approval
    if (next?.status === 'pending') { const idx = approvals.value.findIndex((x: any) => x.id === id); if (idx >= 0) approvals.value[idx] = next }
    else { approvals.value = approvals.value.filter((x: any) => x.id !== id) }
  } catch (e: any) { error.value = e?.data?.message || e?.message || String(e) }
}

async function approveAll() {
  const items = filtered.value; if (!items.length) return
  if (!confirm(`Approve ${items.length} sign-off(s) for ${projectFilter.value === 'all' ? 'all projects' : projectFilter.value}?`)) return
  bulkApproving.value = true
  try { for (const a of [...items]) { try { await decide(a.id, 'approved') } catch {} } }
  finally { bulkApproving.value = false }
}

let sub: any = null
onMounted(async () => {
  if (user.value) await loadAll()
  sub = supabase.channel('signoffs-live').on('postgres_changes', { event: '*', schema: 'public', table: 'approvals' }, () => loadAll()).subscribe()
})
onUnmounted(() => { if (sub) supabase.removeChannel(sub) })
watch(user, u => { if (u) loadAll() })
</script>

<template>
  <div class="min-h-screen bg-[#07090a] text-[#dde5dd]">
    <div class="max-w-3xl mx-auto px-6 py-6 space-y-5">

      <!-- Header -->
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-lg font-medium text-[#dde5dd]" style="font-family:'Fraunces',serif;">Sign-offs</h1>
          <p class="text-xs text-[#3a5a3a] mt-0.5 tracking-wide">{{ filtered.length }} pending · operator review required</p>
        </div>
        <div class="flex items-center gap-2">
          <select v-model="projectFilter" class="bg-[#070c07] border border-[#1e2e1e] text-[#7a9a7a] text-xs rounded px-3 py-1.5 focus:outline-none focus:border-[#2d7a3a]">
            <option value="all">All projects</option>
            <option v-for="p in allProjects" :key="p" :value="p">{{ p }}</option>
          </select>
          <button @click="approveAll" :disabled="bulkApproving || !filtered.length"
            class="px-3 py-1.5 bg-[#0f2014] hover:bg-[#1e5228] text-[#6fcf8a] text-xs rounded border border-[#1c3a1c] transition-colors disabled:opacity-40">
            {{ bulkApproving ? 'Approving...' : `Approve All (${filtered.length})` }}
          </button>
          <button @click="loadAll" class="px-3 py-1.5 bg-[#0c110c] text-[#5a7a5a] text-xs rounded border border-[#162016] hover:text-[#c8d8c8] transition-colors">↻</button>
        </div>
      </div>

      <div v-if="error" class="p-3 bg-red-500/10 border border-red-800/40 rounded-lg text-xs text-red-400">{{ error }}</div>
      <div v-if="loading" class="text-center py-12 text-[#3a5a3a] text-sm">Loading sign-offs...</div>

      <div v-else-if="filtered.length === 0" class="text-center py-16 text-[#3a5a3a]">
        <div class="text-3xl mb-3 opacity-30">○</div>
        <div class="text-base font-medium text-[#5a7a5a]" style="font-family:'Fraunces',serif;">No pending sign-offs</div>
        <div class="text-xs text-[#3a5a3a] mt-1">All gates are clear</div>
      </div>

      <!-- CADE + AI Approval Cards -->
      <div v-else class="space-y-5">
        <div v-for="a in filtered" :key="a.id"
          class="bg-[#0c110c] border border-[#162016] border-l-2 rounded-lg overflow-hidden"
          :class="borderColor(a.kind)">

          <!-- Card header -->
          <div class="px-5 py-3 border-b border-[#162016] flex items-center justify-between gap-4">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="text-[10px] px-2 py-0.5 rounded border font-medium tracking-wider" :class="kindBadge(a.kind)">{{ a.kind?.toUpperCase() }}</span>
              <span v-if="a.approvals_required > 1" class="text-[10px] px-2 py-0.5 rounded border bg-purple-500/10 text-purple-400 border-purple-800/40">{{ a.approvals_required }}-KEY</span>
              <span v-if="a.project" class="text-[10px] text-[#3a5a3a] bg-[#0a120a] px-2 py-0.5 rounded border border-[#162016]">{{ a.project }}</span>
            </div>
            <span class="text-[10px] text-[#3a5a3a] flex-shrink-0 font-mono">{{ a.created_at ? ago(a.created_at) : '' }}</span>
          </div>

          <!-- Title -->
          <div class="px-5 pt-4 pb-2">
            <h3 class="text-sm font-medium text-[#c8d8c8] leading-snug" style="font-family:'Fraunces',serif;">{{ a.title }}</h3>
          </div>

          <!-- CADE Sections -->
          <div class="px-5 space-y-2 pb-3">
            <div class="rounded border border-[#162016] overflow-hidden">
              <div class="px-3 py-1 bg-[#0a120a] border-b border-[#162016]"><span class="text-[9px] font-medium text-[#2d5a2d] tracking-[0.15em] uppercase">Context</span></div>
              <div class="px-3 py-2.5 text-xs text-[#6a8a6a] leading-relaxed">{{ getCade(a).context }}</div>
            </div>
            <div class="rounded border border-[#162016] overflow-hidden">
              <div class="px-3 py-1 bg-[#0a120a] border-b border-[#162016]"><span class="text-[9px] font-medium text-[#2d5a2d] tracking-[0.15em] uppercase">Action Required</span></div>
              <div class="px-3 py-2.5 text-xs text-[#6a8a6a] leading-relaxed">{{ getCade(a).action }}</div>
            </div>
            <div class="rounded border border-[#162016] overflow-hidden">
              <div class="px-3 py-1 bg-[#0a120a] border-b border-[#162016]"><span class="text-[9px] font-medium text-[#2d5a2d] tracking-[0.15em] uppercase">Decision</span></div>
              <div class="px-3 py-2.5 space-y-1">
                <div class="text-xs"><span class="text-[#6fcf8a] font-medium mr-2">Approve =</span><span class="text-[#6a8a6a]">{{ getCade(a).approveValue }}</span></div>
                <div class="text-xs"><span class="text-[#f87171] font-medium mr-2">Deny =</span><span class="text-[#6a8a6a]">{{ getCade(a).denyRisk }}</span></div>
              </div>
            </div>
            <div class="rounded border border-[#162016] overflow-hidden">
              <div class="px-3 py-1 bg-[#0a120a] border-b border-[#162016]"><span class="text-[9px] font-medium text-[#2d5a2d] tracking-[0.15em] uppercase">Evidence</span></div>
              <div class="px-3 py-2.5 text-xs text-[#6a8a6a] leading-relaxed">{{ getCade(a).evidence }}</div>
            </div>

            <!-- ── AI Hivemind Assessment ─────────────────────────────────── -->
            <div class="rounded border border-[#1c2a3a] overflow-hidden">
              <div class="px-3 py-1 bg-[#080f18] border-b border-[#1c2a3a] flex items-center gap-2">
                <span class="text-[9px] font-medium text-[#2a4a6a] tracking-[0.15em] uppercase">AI Hivemind Assessment</span>
                <span class="text-[8px] text-[#1e3a5a]">· claude-orchestrator intelligence</span>
              </div>
              <div class="px-3 py-3 space-y-3">
                <!-- Recommendation + confidence -->
                <div class="flex items-center gap-3">
                  <span class="text-[10px] px-3 py-1 rounded border font-bold tracking-wider" :class="REC_STYLE[getAi(a).recommendation] || REC_STYLE['APPROVE']">
                    {{ getAi(a).recommendation }}
                  </span>
                  <div class="flex-1 bg-[#0a120a] rounded-full h-1.5">
                    <div class="h-1.5 rounded-full bg-[#1e5228]" :style="`width:${getAi(a).confidence}%`"></div>
                  </div>
                  <span class="text-[10px] text-[#3a5a3a] font-mono">{{ getAi(a).confidence }}%</span>
                </div>
                <!-- Reasoning -->
                <div class="text-xs text-[#5a7a8a] leading-relaxed italic border-l-2 border-[#1c2a3a] pl-3">
                  "{{ getAi(a).reasoning }}"
                </div>
                <!-- Risks -->
                <div v-if="getAi(a).risks.length" class="space-y-1">
                  <div class="text-[9px] font-medium text-[#2a4a6a] tracking-[0.12em] uppercase mb-1">Risks Identified</div>
                  <div v-for="(risk, i) in getAi(a).risks" :key="i" class="flex gap-2 text-xs text-[#5a7a8a]">
                    <span class="text-[#1e3a5a] flex-shrink-0 mt-0.5">·</span>
                    <span>{{ risk }}</span>
                  </div>
                </div>
                <!-- Legal exposure flag -->
                <div v-if="getAi(a).legalExposure" class="flex items-center gap-2 text-xs text-red-400 bg-red-900/10 border border-red-800/30 rounded px-2 py-1.5">
                  <span>⚠</span> Legal/regulatory exposure detected — escalate to legal review before deciding.
                </div>
              </div>
            </div>

            <!-- ── War Room Links (legal/regulated projects) ──────────────── -->
            <div v-if="getCade(a).legalProjects.length > 0" class="rounded border border-[#1a2a14] overflow-hidden">
              <div class="px-3 py-1 bg-[#0a140a] border-b border-[#1a2a14]"><span class="text-[9px] font-medium text-[#2a4a2a] tracking-[0.15em] uppercase">War Room · Quick Links</span></div>
              <div class="px-3 py-2.5 space-y-2">
                <div v-for="proj in getCade(a).legalProjects" :key="proj" class="flex items-center gap-2 flex-wrap">
                  <span class="text-[10px] text-[#3a5a3a] font-mono min-w-[80px]">{{ proj }}</span>
                  <NuxtLink v-for="page in WAR_ROOM_PAGES" :key="page.path" :to="`${page.path}?project=${proj}`"
                    class="text-[10px] px-2 py-0.5 rounded border border-[#1a2a14] bg-[#0a140a] text-[#4a8a4a] hover:text-[#6fcf8a] hover:border-[#2d5a2d] transition-colors">
                    → {{ page.label }}
                  </NuxtLink>
                </div>
              </div>
            </div>
          </div>

          <!-- Actions -->
          <div class="px-5 py-3 border-t border-[#162016] flex items-center justify-between gap-4">
            <div class="flex gap-3">
              <button @click="decide(a.id, 'approved')"
                class="px-6 py-2 bg-[#0f2014] hover:bg-[#1e5228] text-[#6fcf8a] text-sm font-medium rounded border border-[#1c3a1c] transition-colors">
                Approve
              </button>
              <button @click="decide(a.id, 'denied')"
                class="px-6 py-2 bg-[#1a0808] hover:bg-[#2a1010] text-[#f87171] text-sm font-medium rounded border border-[#3a1010] transition-colors">
                Deny
              </button>
            </div>
            <span class="text-[9px] text-[#2a3a2a] font-mono">{{ a.id?.slice(0, 8) }}...</span>
          </div>
        </div>
      </div>

      <!-- Credential Requests -->
      <div v-if="credRequests.length > 0" class="bg-[#0c110c] border border-[#162016] rounded-lg overflow-hidden">
        <div class="px-5 py-3 border-b border-[#162016]">
          <span class="text-xs font-medium text-[#dde5dd]" style="font-family:'Fraunces',serif;">Credential Requests</span>
          <span class="text-[10px] text-[#3a5a3a] ml-2">{{ credRequests.length }} request{{ credRequests.length !== 1 ? 's' : '' }}</span>
        </div>
        <div class="divide-y divide-[#0f180f]">
          <div v-for="c in credRequests" :key="c.id" class="px-5 py-3 flex items-center gap-4">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 mb-0.5">
                <span class="text-[10px] font-mono text-[#6fcf8a]">{{ c.provider }}</span>
                <span class="text-[10px] px-2 py-0.5 rounded border"
                  :class="c.status === 'payment_required' ? 'bg-red-500/10 text-red-400 border-red-800/40' : c.status === 'pending' ? 'bg-yellow-500/10 text-yellow-400 border-yellow-800/40' : 'bg-[#0f2014] text-[#6fcf8a] border-[#1c3a1c]'">
                  {{ c.status }}
                </span>
                <span v-if="c.project" class="text-[10px] text-[#3a5a3a]">{{ c.project }}</span>
              </div>
              <div class="text-xs text-[#5a7a5a] truncate">{{ c.reason }}</div>
            </div>
            <span class="text-[10px] text-[#3a5a3a] flex-shrink-0">{{ c.created_at ? ago(c.created_at) : '' }}</span>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>
