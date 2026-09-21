<script setup lang="ts">
import { isTypingTarget, reduceKey, type KeyState, type SteeringView } from '~/utils/steeringKeys'

definePageMeta({ layout: 'default' })

const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()

async function authedFetch<T = any>(url: string, opts: any = {}): Promise<T> {
  const { data: { session } } = await supabase.auth.getSession()
  return $fetch<T>(url, { ...opts, headers: { ...(opts.headers || {}), ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}) } })
}

// Mirrors runner/db_steering_contract.py PROVIDERS (minus 'other', which the runner reserves).
const PROVIDERS = ['supabase', 'postgres', 'mysql', 'aws_rds', 'aws_aurora', 'aws_redshift', 'gcp_cloudsql', 'gcp_alloydb', 'gcp_bigquery', 'azure_postgres', 'azure_mysql', 'neon', 'planetscale', 'cockroachdb', 'snowflake', 'mongodb']
const REFERENCE_FORMS = 'env:NAME · keychain:NAME · doppler:PATH · onepassword:op://vault/item/field · vault:<connector account id> · file:/abs/path'

const loading = ref(true), error = ref(''), notice = ref('')
const days = ref(7), project = ref('')
const data = ref<any>({ sources: [], posture: {}, findings: { open_by_severity: {}, top: [] }, briefs: [], memos: [] })
const busy = ref<Record<string, boolean>>({})
const form = reactive({ provider: 'postgres', label: '', project: '', ref: '', region: '', credential_ref: '' })
const saving = ref(false), formError = ref('')
const insightData = ref<any>({ insights: { total: 0, byKind: {}, byRisk: {}, top: [], pathways: [], gaps: [] }, matrix: null, quality: null, missing: [] })
const insightError = ref(''), insightKind = ref(''), openInsightId = ref(''), railOpen = ref(false)
const openMemoId = ref(''), memoDetail = ref<any>(null), memoLoading = ref(false), memoError = ref('')

const projects = computed(() => [...new Set([...(data.value.sources || []).map((s: any) => s.project), ...(data.value.memos || []).map((m: any) => m.project)].filter(Boolean))].sort() as string[])
const sourceById = computed(() => Object.fromEntries((data.value.sources || []).map((s: any) => [s.id, s])))
const severityOrder = ['critical', 'high', 'medium', 'low', 'info']

async function load() {
  loading.value = true; error.value = ''
  try { data.value = await authedFetch('/api/db-steering', { params: { days: days.value, ...(project.value ? { project: project.value } : {}) } }) }
  catch (e: any) { error.value = e?.data?.message || e?.message || 'Database steering data is unavailable.' }
  finally { loading.value = false }
}
async function loadInsights() {
  insightError.value = ''
  try { insightData.value = await authedFetch('/api/db-steering/insights') }
  catch (e: any) { insightError.value = e?.data?.message || e?.message || 'Expert insights are unavailable.' }
}
async function act(source: any, action: 'pause' | 'resume' | 'remove') {
  if (action === 'remove' && !confirm(`Remove ${source.label}? Its findings and posture history are deleted with it. The encrypted credential, if any, stays in Connectors until revoked there.`)) return
  busy.value = { ...busy.value, [source.id]: true }
  try { await authedFetch(`/api/db-steering/sources/${source.id}`, { method: 'POST', body: { action } }); notice.value = `${source.label}: ${action}d.`; await load() }
  catch (e: any) { error.value = e?.data?.message || e?.message || `Could not ${action} ${source.label}.` }
  finally { busy.value = { ...busy.value, [source.id]: false } }
}
async function register() {
  formError.value = ''
  if (!form.ref.trim()) { formError.value = 'A ref (project ref, host, instance or project id) is required.'; return }
  if (/:\/\/[^/\s]*:[^/\s]*@/.test(form.credential_ref) || /:\/\/[^/\s]*:[^/\s]*@/.test(form.ref)) { formError.value = 'That looks like a connection string with a password in it. Store the secret in a vault and paste its reference instead.'; return }
  saving.value = true
  try {
    const body: any = { provider: form.provider, label: form.label.trim() || form.ref.trim(), ref: form.ref.trim(), project: form.project.trim() || undefined, region: form.region.trim() || undefined, credential_ref: form.credential_ref.trim() || undefined }
    const result = await authedFetch<any>('/api/db-steering/sources', { method: 'POST', body })
    notice.value = `Registered ${result.source?.label || body.label} (${result.source?.credential_kind || 'fleet-token'}).`
    form.label = ''; form.ref = ''; form.region = ''; form.credential_ref = ''
    await load()
  } catch (e: any) { formError.value = e?.data?.message || e?.message || 'Registration failed.' }
  finally { saving.value = false }
}
async function openMemo(memo: any) {
  if (openMemoId.value === memo.id) { openMemoId.value = ''; memoDetail.value = null; return }
  openMemoId.value = memo.id; memoDetail.value = null; memoError.value = ''; memoLoading.value = true
  try { memoDetail.value = await authedFetch(`/api/db-steering/memos/${memo.id}`) }
  catch (e: any) { memoError.value = e?.data?.message || e?.message || 'Memo unavailable.' }
  finally { memoLoading.value = false }
}

function when(value: any) { if (!value) return '—'; const d = new Date(value); return isNaN(d.getTime()) ? '—' : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }
function truncate(value: any, n = 120) { const s = String(value || ''); return s.length > n ? s.slice(0, n - 1) + '…' : s }
function score(sourceId: string) { const snap = data.value.posture?.[sourceId]; return snap?.score == null ? null : Number(snap.score) }
function scoreClass(value: number | null) { return value == null ? 'none' : value >= 85 ? 'good' : value >= 60 ? 'warn' : 'bad' }
function strengths(memo: any) { const args = Array.isArray(memo.arguments) ? memo.arguments : []; if (!args.length) return '—'; const tally: Record<string, number> = {}; for (const a of args) { const k = String(a?.strength || 'unknown'); tally[k] = (tally[k] || 0) + 1 } return Object.entries(tally).map(([k, v]) => `${v} ${k}`).join(', ') }
function gauntletText(g: any) { if (!g || typeof g !== 'object') return ''; const v = String(g.verdict || g.position || g.opinion || '').trim(); const s = String(g.summary || '').trim(); return truncate([v && `Verdict: ${v}`, s].filter(Boolean).join(' — ') || truncate(JSON.stringify(g), 400), 600) }
function objectName(f: any) { return [f.object_schema, f.object_name].filter(Boolean).join('.') || '—' }
const trackedSources = computed(() => (data.value.sources || []).filter((s: any) => data.value.posture?.[s.id]))
const healthScore = computed<number | null>(() => { const scores = trackedSources.value.map((s: any) => Number(data.value.posture[s.id]?.score)).filter((v: number) => !isNaN(v)); return scores.length ? Math.min(...scores) : null })
const healthTrend = computed<number | null>(() => {
  // trend of the worst source — the one the score card shows
  let worstId = '', worstScore = Infinity
  for (const s of trackedSources.value) {
    const cur = Number(data.value.posture[s.id]?.score)
    if (!isNaN(cur) && cur < worstScore) { worstScore = cur; worstId = s.id }
  }
  if (!worstId) return null
  const prev = Number(data.value.posturePrev?.[worstId]?.score)
  return isNaN(prev) ? null : worstScore - prev
})
const attentionCount = computed(() => (data.value.findings?.open_by_severity?.critical || 0) + (data.value.findings?.open_by_severity?.high || 0))
const memoSummary = computed(() => {
  const ms = data.value.memos || []
  return { total: ms.filter((m: any) => (m.evidence_count || 0) > 0).length, reviewed: ms.filter((m: any) => m.gauntlet_at).length, stale: ms.filter((m: any) => m.status === 'stale').length }
})


// ── expert insights, the docket matrix and local-output quality ─────────────────────────
const LENS_LABEL: Record<string, string> = { regulatory_gap: 'Regulatory gap', enforcement_trend: 'Enforcement trend', cross_industry_analog: 'Cross-industry analog', innovation_pathway: 'Innovation pathway', red_team: 'Red team', opportunity: 'Opportunity' }
const LENS_ORDER = Object.keys(LENS_LABEL)
const RISK_ORDER = ['existential', 'high', 'medium', 'low', 'upside']
const KIND_ORDER = ['action', 'gap', 'tripwire', 'innovation', 'opportunity', 'assumption']
const shownInsights = computed(() => (insightData.value.insights?.top || []).filter((i: any) => !insightKind.value || i.kind === insightKind.value))
function cell(lens: string, band: string) { return (insightData.value.matrix?.cells || []).find((c: any) => c.lens === lens && c.risk_band === band) || { total: 0, pending: 0, answered: 0 } }
function heat(total: number) { const max = insightData.value.matrix?.max || 1; return total ? 0.1 + 0.75 * (total / max) : 0 }
function pct(value: any) { return value == null ? '—' : `${Math.round(Number(value) * 100)}%` }

// ── rail + keyboard: g <key> jumps, j / k walk rows, Enter opens, Escape closes ─────────
const views = computed<SteeringView[]>(() => [
  { key: 'o', id: 'overview', label: 'Overview', rows: 0 },
  { key: 'i', id: 'insights', label: 'Expert insights', rows: shownInsights.value.length },
  { key: 'x', id: 'matrix', label: 'Docket matrix', rows: 0 },
  { key: 'q', id: 'quality', label: 'Local output quality', rows: (insightData.value.quality?.callers || []).length },
  { key: 's', id: 'sources', label: 'Sources', rows: (data.value.sources || []).length },
  { key: 'f', id: 'findings', label: 'Open findings', rows: (data.value.findings?.top || []).length },
  { key: 'b', id: 'briefs', label: 'Steering briefs', rows: (data.value.briefs || []).length },
  { key: 'm', id: 'memos', label: 'Memo drafts', rows: (data.value.memos || []).length },
  { key: 'l', id: 'link', label: 'Link a database', rows: 0 },
])
// Just-in-time guidance: what deserves attention right now, most consequential first. Each
// item names one action and runs it; nothing is listed merely because it exists.
interface Guide { id: string; tone: 'bad' | 'warn' | 'good'; title: string; detail: string; cta: string; run: () => void }
const guidance = computed<Guide[]>(() => {
  const out: Guide[] = []
  const failing = (data.value.sources || []).filter((s: any) => s.enabled && (s.consecutive_failures || 0) >= 3)
  if (failing.length) out.push({ id: 'failing', tone: 'bad', title: `${failing.length} source${failing.length === 1 ? ' is' : 's are'} failing to scan`, detail: failing.slice(0, 3).map((s: any) => s.label).join(', '), cta: 'Open sources', run: () => go('sources') })
  if (attentionCount.value) out.push({ id: 'gaps', tone: 'bad', title: `${attentionCount.value} critical or high gap${attentionCount.value === 1 ? ' is' : 's are'} open`, detail: 'Most severe first; each names its remediation.', cta: 'Review findings', run: () => go('findings') })
  const worst = (insightData.value.quality?.callers || []).find((c: any) => c.flagged > 0)
  if (worst) out.push({ id: 'quality', tone: 'warn', title: `${worst.caller} keeps producing ${String(worst.worst).replace(/_/g, ' ')} output`, detail: `${worst.flagged} of ${worst.calls} recent local-model calls flagged.`, cta: 'See quality', run: () => go('quality') })
  const m = insightData.value.matrix
  if (m?.empty) out.push({ id: 'matrix', tone: 'warn', title: `${m.empty} lens × risk cells have never been asked`, detail: `Innovation share ${pct(m.innovationShare)}. Generation fills the emptiest cells first.`, cta: 'Open matrix', run: () => go('matrix') })
  if (memoSummary.value.stale) out.push({ id: 'memos', tone: 'warn', title: `${memoSummary.value.stale} memo${memoSummary.value.stale === 1 ? ' is' : 's are'} behind the evidence`, detail: 'Drafting catches up one memo per cycle.', cta: 'Open memos', run: () => go('memos') })
  const pathways = insightData.value.insights?.pathways?.length || 0
  if (pathways) out.push({ id: 'pathways', tone: 'good', title: `${pathways} innovation pathway${pathways === 1 ? '' : 's'} ready to read`, detail: String(insightData.value.insights.pathways[0]?.insight || '').slice(0, 120), cta: 'Read insights', run: () => go('insights') })
  return out.slice(0, 5)
})

const keys = ref<KeyState>({ active: 'overview', row: 0, pendingG: false, focus: 'rail' })
function focusRow(id: string, row: number) {
  const el = document.querySelector<HTMLElement>(`#sec-${id} [data-row="${row}"]`)
  if (el) { el.focus({ preventScroll: true }); el.scrollIntoView({ block: 'nearest' }) }
}
function go(id: string, focusRail = true) {
  keys.value = { ...keys.value, active: id, row: 0, focus: 'rail' }; railOpen.value = false
  window.scrollTo({ top: 0, behavior: 'auto' })   // one view at a time: a jump replaces the view, it does not travel
  if (focusRail) nextTick(() => document.querySelector<HTMLElement>(`[data-rail="${id}"]`)?.focus({ preventScroll: true }))
}
function openRow(id: string, row: number) {
  if (id === 'memos') { const m = (data.value.memos || [])[row]; if (m) openMemo(m) }
  else if (id === 'insights') { const i = shownInsights.value[row]; if (i) openInsightId.value = openInsightId.value === i.id ? '' : i.id }
  else document.querySelector<HTMLElement>(`#sec-${id} [data-row="${row}"]`)?.click()
}
function onKey(e: KeyboardEvent) {
  if (e.metaKey || e.ctrlKey || e.altKey) return
  const target = e.target as HTMLElement | null
  // A row reached with Tab or a click is the current row too: one owner for Enter, so a
  // focused row is never toggled twice (once here, once by its own handler).
  const rowEl = target?.closest?.('[data-row]') as HTMLElement | null
  const section = rowEl?.closest('section')?.id?.replace('sec-', '')
  if (rowEl && section) keys.value = { ...keys.value, active: section, row: Number(rowEl.getAttribute('data-row')) || 0, focus: 'rows' }
  // On Overview the number keys run the guidance items, Superhuman-style.
  if (keys.value.active === 'overview' && !isTypingTarget(target?.tagName, target?.isContentEditable) && /^[1-5]$/.test(e.key)) {
    const item = guidance.value[Number(e.key) - 1]
    if (item) { e.preventDefault(); item.run(); return }
  }
  const { state, effect } = reduceKey(keys.value, e.key, views.value, isTypingTarget(target?.tagName, target?.isContentEditable))
  keys.value = state
  if (effect.type === 'none') return
  e.preventDefault()
  if (effect.type === 'go') go(effect.id)
  else if (effect.type === 'row') focusRow(state.active, effect.row)
  else if (effect.type === 'open') openRow(state.active, effect.row)
  else if (effect.type === 'close') { openInsightId.value = ''; openMemoId.value = ''; railOpen.value = false }
}

watch(user, (u) => { if (u) { load(); loadInsights() } })
onMounted(() => { if (user.value) { load(); loadInsights() } window.addEventListener('keydown', onKey) })
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="ds-shell" :class="{ 'rail-open': railOpen }">
    <button v-if="railOpen" class="rail-scrim" aria-label="Close navigation" @click="railOpen = false"></button>
    <nav class="ds-rail" aria-label="Steering sections">
      <div class="rail-brand"><span class="rail-mark">⛁</span><b>Steering</b></div>
      <button v-for="v in views" :key="v.id" class="rail-item" :class="{ active: keys.active === v.id }" :data-rail="v.id"
              :aria-current="keys.active === v.id ? 'true' : undefined" @click="go(v.id, false)">
        <span>{{ v.label }}</span><kbd>g {{ v.key }}</kbd>
      </button>
      <p class="rail-help"><kbd>j</kbd> <kbd>k</kbd> move · <kbd>Enter</kbd> open · <kbd>Esc</kbd> close</p>
    </nav>
  <main class="ds">
    <header class="ds-head" id="sec-overview">
      <div>
        <button class="rail-toggle" aria-label="Open navigation" @click="railOpen = true"><span></span><span></span><span></span></button>
        <span class="kicker">Steering</span>
        <h1 class="serif">Data and expert steering</h1>
        <p>Read-only review and expert verdicts, turned into steering.</p>
      </div>
      <div class="ds-filters">
        <label>Project<select v-model="project" @change="load"><option value="">All projects</option><option v-for="p in projects" :key="p" :value="p">{{ p }}</option></select></label>
        <label>Window<select v-model.number="days" @change="load"><option :value="1">24 hours</option><option :value="7">7 days</option><option :value="30">30 days</option><option :value="90">90 days</option></select></label>
        <button class="ghost" :disabled="loading" @click="load">{{ loading ? 'Loading…' : 'Refresh' }}</button>
      </div>
    </header>

    <div v-if="!user" class="ds-empty">Sign in to view database steering.</div>
    <div v-else-if="error" class="ds-empty error">{{ error }} <button class="ghost" @click="load">Retry</button></div>
    <template v-else>
      <div v-if="notice" class="ds-notice">{{ notice }}<button class="ghost" @click="notice = ''">Dismiss</button></div>

      <!-- Next best action: computed just in time, never more than five, each runnable by number -->
      <section class="guide" v-show="keys.active === 'overview'" aria-label="Next best actions">
        <p v-if="!guidance.length" class="guide-calm serif">Nothing needs you. The loop is steering.</p>
        <button v-for="(g, n) in guidance" :key="g.id" class="guide-item" :class="g.tone" @click="g.run()">
          <kbd>{{ n + 1 }}</kbd>
          <span class="guide-text"><b>{{ g.title }}</b><small>{{ g.detail }}</small></span>
          <span class="guide-cta">{{ g.cta }} →</span>
        </button>
      </section>

      <!-- Plain-English health cards: what a human decides from in 5 seconds -->
      <section class="ds-cards" v-if="data.sources?.length || data.memos?.length" v-show="keys.active === 'overview'">
        <article class="ds-card" :class="scoreClass(healthScore)">
          <strong>{{ healthScore == null ? '—' : healthScore.toFixed(0) }}<small v-if="healthTrend != null" class="trend">{{ healthTrend > 0 ? '▲ +' : healthTrend < 0 ? '▼ ' : '' }}{{ Math.abs(healthTrend ?? 0).toFixed(1) }}</small></strong>
          <span>Posture{{ project ? '' : ' (worst source)' }}<br><small>{{ healthScore == null ? '' : healthScore >= 85 ? 'healthy' : healthScore >= 60 ? 'watch it' : 'act soon' }}</small></span>
        </article>
        <article class="ds-card" :class="attentionCount ? 'bad' : 'good'">
          <strong>{{ attentionCount }}</strong>
          <span>Need attention now<br><small>open critical/high gaps</small></span>
        </article>
        <article class="ds-card" :class="data.closeouts?.not_confirmed ? 'warn' : 'good'">
          <strong>{{ data.closeouts?.open_prs ?? 0 }}</strong>
          <span>Fixes in flight<br><small>{{ data.closeouts?.verified ?? 0 }} verified on live{{ data.closeouts?.not_confirmed ? ` · ${data.closeouts.not_confirmed} unproven` : '' }}</small></span>
        </article>
        <article class="ds-card good">
          <strong>{{ memoSummary.total }}</strong>
          <span>Memos evidence-backed<br><small>{{ memoSummary.reviewed }} gauntlet-reviewed · {{ memoSummary.stale }} stale</small></span>
        </article>
      </section>

      <!-- Posture strip -->
      <section class="ds-posture" v-if="data.sources?.length" v-show="keys.active === 'overview'">
        <!-- only sources with a reading: a wall of dashes for inactive projects says nothing -->
        <article v-for="s in trackedSources" :key="s.id" class="posture-card" :class="scoreClass(score(s.id))">
          <strong>{{ score(s.id) == null ? '—' : score(s.id)!.toFixed(0) }}</strong>
          <span class="posture-label">{{ s.label }}</span>
          <small>{{ s.provider }}<template v-if="data.posture?.[s.id]"> · {{ when(data.posture[s.id].taken_at) }}</template><template v-else> · no snapshot yet</template></small>
        </article>
      </section>


      <!-- Expert insights -->
      <section class="ds-card" id="sec-insights" v-show="keys.active === 'insights'">
        <header>
          <h2>Expert insights</h2>
          <span>{{ insightData.insights?.total || 0 }} active · internal, under attorney review — not legal advice</span>
        </header>
        <div v-if="insightError" class="ds-empty inline error">{{ insightError }} <button class="ghost" @click="loadInsights">Retry</button></div>
        <template v-else>
          <div v-if="insightData.insights?.pathways?.length" class="pathways">
            <h3>Innovation pathways</h3>
            <article v-for="p in insightData.insights.pathways.slice(0, 4)" :key="p.id" class="pathway">
              <span class="pill upside">{{ p.vertical }}</span>
              <p class="serif">{{ p.insight }}</p>
            </article>
          </div>
          <div class="chip-row" role="group" aria-label="Filter insights by kind">
            <button class="chip" :class="{ on: !insightKind }" @click="insightKind = ''">All {{ insightData.insights?.total || 0 }}</button>
            <button v-for="k in KIND_ORDER" :key="k" class="chip" :class="{ on: insightKind === k }" @click="insightKind = insightKind === k ? '' : k">{{ k }} {{ insightData.insights?.byKind?.[k] || 0 }}</button>
          </div>
          <div v-if="!shownInsights.length" class="ds-empty inline">No insights yet. They appear as soon as the expert panels mint verdict cards; run <span class="mono">python3 runner/steering_insights.py sync</span> to distil existing ones.</div>
          <ul v-else class="insight-list">
            <li v-for="(i, n) in shownInsights" :key="i.id" class="insight" :class="{ open: openInsightId === i.id }" tabindex="0" :data-row="n"
                @click="openInsightId = openInsightId === i.id ? '' : i.id">
              <div class="insight-meta"><span class="pill" :class="i.risk_band">{{ i.risk_band }}</span><span class="pill kind">{{ i.kind }}</span><small>{{ i.vertical }} · {{ LENS_LABEL[i.lens] || i.lens }} · confidence {{ i.confidence ?? '—' }} · card {{ String(i.card_id || '').slice(0, 8) }}</small></div>
              <p class="serif">{{ i.insight }}</p>
              <p v-if="openInsightId === i.id && i.rationale" class="rationale">{{ i.rationale }}</p>
            </li>
          </ul>
        </template>
      </section>

      <!-- Docket matrix -->
      <section class="ds-card" id="sec-matrix" v-show="keys.active === 'matrix'">
        <header>
          <h2>Docket matrix</h2>
          <span v-if="insightData.matrix">{{ insightData.matrix.total }} questions · {{ insightData.matrix.empty }} of {{ insightData.matrix.cells.length }} cells empty · innovation share {{ pct(insightData.matrix.innovationShare) }} · marked high {{ pct(insightData.matrix.highPriorityShare) }}</span>
        </header>
        <div v-if="!insightData.matrix?.total" class="ds-empty inline">The docket is empty or not readable yet.</div>
        <template v-else>
          <div class="table-wrap">
            <table class="matrix">
              <thead><tr><th>Lens</th><th v-for="b in RISK_ORDER" :key="b">{{ b }}</th></tr></thead>
              <tbody>
                <tr v-for="l in LENS_ORDER" :key="l">
                  <th scope="row">{{ LENS_LABEL[l] }}</th>
                  <td v-for="b in RISK_ORDER" :key="b" :class="{ empty: !cell(l, b).total }" :style="{ '--heat': heat(cell(l, b).total) }"
                      :title="`${LENS_LABEL[l]} × ${b}: ${cell(l, b).total} questions, ${cell(l, b).answered} answered`">
                    <b>{{ cell(l, b).total || '·' }}</b><small v-if="cell(l, b).total">{{ cell(l, b).answered }} answered</small>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="matrix-note">Empty cells are what the panels have never been asked. Generation fills the emptiest cells first and reserves a share for the three innovation lenses.<template v-if="insightData.matrix.untagged"> {{ insightData.matrix.untagged }} legacy questions carry no stored tags yet (<span class="mono">docket_matrix.py backfill</span>).</template></p>
          <div class="vertical-row"><span v-for="(v, name) in insightData.matrix.byVertical" :key="name" class="pill kind">{{ name }} {{ v.answered }}/{{ v.total }} answered</span></div>
        </template>
      </section>

      <!-- Local output quality -->
      <section class="ds-card" id="sec-quality" v-show="keys.active === 'quality'">
        <header>
          <h2>Local output quality</h2>
          <span v-if="insightData.quality">last {{ insightData.quality.rows }} local calls · {{ insightData.quality.graded }} graded · {{ insightData.quality.replays }} cache replays · mean quality {{ insightData.quality.meanQuality ?? '—' }}</span>
        </header>
        <div v-if="!insightData.quality?.callers?.length" class="ds-empty inline">No local-model calls recorded yet.</div>
        <div v-else class="table-wrap">
          <table>
            <thead><tr><th>Caller</th><th>Calls</th><th>Fresh work</th><th>Graded</th><th>Mean quality</th><th>Flagged</th><th>Most common defect</th></tr></thead>
            <tbody>
              <tr v-for="(c, n) in insightData.quality.callers.slice(0, 25)" :key="c.caller" tabindex="0" :data-row="n">
                <td class="mono">{{ c.caller }}</td><td>{{ c.calls }}</td><td>{{ c.fresh }}</td><td>{{ c.graded }}</td>
                <td><span class="pill" :class="c.meanQuality == null ? 'none' : c.meanQuality >= 0.85 ? 'good' : c.meanQuality >= 0.6 ? 'warn' : 'bad'">{{ c.meanQuality ?? 'ungraded' }}</span></td>
                <td>{{ c.flagged }}</td><td>{{ c.worst === 'ok' ? '—' : c.worst.replace(/_/g, ' ') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Sources -->
      <section class="ds-card" id="sec-sources" v-show="keys.active === 'sources'">
        <header><h2>Sources</h2><span>{{ data.sources?.length || 0 }} linked · {{ (data.sources || []).filter((s: any) => s.enabled).length }} active</span></header>
        <div v-if="!data.sources?.length" class="ds-empty inline">No databases are linked yet. Link one below.</div>
        <div v-else class="table-wrap">
          <table>
            <thead><tr><th>Label</th><th>Provider</th><th>Project</th><th>Status</th><th>Last scan</th><th>Credential</th><th></th></tr></thead>
            <tbody>
              <tr v-for="(s, n) in data.sources" :key="s.id" tabindex="0" :data-row="n">
                <td><b>{{ s.label }}</b><small class="mono">{{ s.ref }}</small></td>
                <td><span class="mono">{{ s.provider }}</span><small>{{ s.dialect }}<template v-if="s.region"> · {{ s.region }}</template></small></td>
                <td>{{ s.project || '—' }}</td>
                <td><span class="pill" :class="s.status">{{ s.status }}</span><small v-if="s.last_error" class="err">{{ truncate(s.last_error, 60) }}</small></td>
                <td>{{ when(s.last_scan_at) }}<small v-if="s.consecutive_failures">{{ s.consecutive_failures }} consecutive failures</small></td>
                <td><span class="pill kind">{{ s.credential_kind }}</span></td>
                <td class="actions">
                  <button v-if="s.enabled" class="ghost" :disabled="busy[s.id]" @click="act(s, 'pause')">Pause</button>
                  <button v-else class="ghost" :disabled="busy[s.id]" @click="act(s, 'resume')">Resume</button>
                  <button class="ghost danger" :disabled="busy[s.id]" @click="act(s, 'remove')">Remove</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Link a database -->
      <section class="ds-card ds-link" id="sec-link" v-show="keys.active === 'link'">
        <header><h2>Link a database</h2><span>Two ways. Both store a reference, never a secret.</span></header>
        <div class="link-grid">
          <div class="link-way">
            <span class="step">1</span>
            <h3>Connectors → Databases</h3>
            <p>Paste credentials once on the <NuxtLink to="/connectors">Connectors page</NuxtLink> under <b>Databases</b>. They are encrypted at rest and decrypted only by the fleet runner; a source is registered here automatically with a <span class="mono">vault:</span> reference.</p>
          </div>
          <form class="link-way" @submit.prevent="register">
            <span class="step">2</span>
            <h3>Register with a credential reference</h3>
            <div class="form-grid">
              <label>Provider<select v-model="form.provider"><option v-for="p in PROVIDERS" :key="p" :value="p">{{ p }}</option></select></label>
              <label>Label<input v-model="form.label" placeholder="prod-orders"></label>
              <label>Project<input v-model="form.project" placeholder="fleet project name (optional)"></label>
              <label>Ref<input v-model="form.ref" required placeholder="project ref · host · instance · project id"></label>
              <label>Region<input v-model="form.region" placeholder="us-east-1 (optional)"></label>
              <label class="wide">Credential reference<input v-model="form.credential_ref" class="mono" :placeholder="form.provider === 'supabase' ? 'blank = fleet Management API token' : 'env:PROD_DB_URL'"><small>Accepted forms: {{ REFERENCE_FORMS }}. A DSN or password is refused.</small></label>
            </div>
            <div v-if="formError" class="form-error">{{ formError }}</div>
            <button type="submit" :disabled="saving">{{ saving ? 'Registering…' : 'Register source' }}</button>
          </form>
        </div>
      </section>

      <!-- Open findings -->
      <section class="ds-card" id="sec-findings" v-show="keys.active === 'findings'">
        <header>
          <h2>Open findings</h2>
          <span class="sev-tally"><i v-for="sev in severityOrder" :key="sev" class="pill" :class="sev">{{ sev }} {{ data.findings?.open_by_severity?.[sev] || 0 }}</i></span>
        </header>
        <div v-if="!data.findings?.top?.length" class="ds-empty inline">No open findings in the last {{ days }} day{{ days === 1 ? '' : 's' }}.</div>
        <div v-else class="table-wrap">
          <table>
            <thead><tr><th>Severity</th><th>Project</th><th>Title</th><th>Object</th><th>First seen</th><th>Last seen</th><th>Remediation</th></tr></thead>
            <tbody>
              <tr v-for="(f, n) in data.findings.top" :key="f.id" tabindex="0" :data-row="n">
                <td><span class="pill" :class="f.severity">{{ f.severity }}</span></td>
                <td>{{ f.project || sourceById[f.source_id]?.project || '—' }}<small>{{ sourceById[f.source_id]?.label || '' }}</small></td>
                <td><b>{{ f.title }}</b><small>{{ f.category }} · {{ f.probe_id }}<template v-if="f.task_slug"> · task {{ f.task_slug }}</template></small></td>
                <td class="mono">{{ objectName(f) }}</td>
                <td>{{ when(f.first_seen_at) }}</td>
                <td>{{ when(f.last_seen_at) }}<small v-if="f.occurrences > 1">×{{ f.occurrences }}</small></td>
                <td class="rem" :title="f.remediation || ''">{{ truncate(f.remediation) || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Briefs -->
      <section class="ds-card" id="sec-briefs" v-show="keys.active === 'briefs'">
        <header><h2>Steering briefs</h2><span>Injected into every coder prompt for the project</span></header>
        <details v-for="(b, n) in data.briefs" :key="b.project" class="brief">
          <summary :data-row="n"><b>{{ b.project }}</b><small>updated {{ when(b.updated_at) }} · {{ Object.entries(b.open_counts || {}).map(([k, v]) => `${k} ${v}`).join(' · ') || 'no open counts' }}</small></summary>
          <pre class="reading">{{ b.brief }}</pre>
        </details>
      </section>

      <!-- Memos -->
      <section class="ds-card" id="sec-memos" v-show="keys.active === 'memos'">
        <header><h2>Legal-memo drafts</h2><span>Internal work product · not legal advice</span></header>
        <div v-if="!data.memos?.length" class="ds-empty inline">No memo drafts yet. They appear once findings carry evidence kinds.</div>
        <div v-else class="table-wrap">
          <table>
            <thead><tr><th>Title</th><th>Project</th><th>Status</th><th>Evidence</th><th>Strengths</th><th>Updated</th></tr></thead>
            <tbody>
              <template v-for="(m, n) in data.memos" :key="m.id">
                <tr class="clickable" :class="{ open: openMemoId === m.id }" tabindex="0" :data-row="n" @click="openMemo(m)">
                  <td><b>{{ m.title }}</b><small class="mono">{{ m.memo_kind }}</small></td>
                  <td>{{ m.project }}</td>
                  <td><span class="pill" :class="m.status">{{ m.status }}</span><span v-if="m.gauntlet_at" class="pill gauntleted" title="Expert-corps gauntlet reviewed">gauntlet</span></td>
                  <td>{{ m.evidence_count }}</td>
                  <td>{{ strengths(m) }}</td>
                  <td>{{ when(m.updated_at) }}</td>
                </tr>
                <tr v-if="openMemoId === m.id" class="memo-row"><td colspan="6">
                  <details open class="memo-pane">
                    <summary>{{ memoLoading ? 'Loading memo…' : memoError ? memoError : `Memo body · ${memoDetail?.evidence?.length || 0} evidence rows` }}</summary>
                    <template v-if="memoDetail">
                      <div v-if="memoDetail.memo?.gauntlet_at" class="gauntlet-card">
                        <b>Expert-corps gauntlet · {{ when(memoDetail.memo.gauntlet_at) }}</b>
                        <p>{{ gauntletText(memoDetail.memo.gauntlet) || 'Reviewed (verdict payload not displayable).' }}</p>
                      </div>
                      <p v-if="memoDetail.memo?.thesis" class="thesis">{{ memoDetail.memo.thesis }}</p>
                      <pre class="serif reading">{{ memoDetail.memo?.body || '(no body drafted yet — prose is generated once the evidence set changes)' }}</pre>
                      <div v-if="memoDetail.evidence?.length" class="table-wrap">
                        <table class="evidence">
                          <thead><tr><th>Argument</th><th>Direction</th><th>Weight</th><th>Finding</th><th>Severity</th><th>Status</th></tr></thead>
                          <tbody><tr v-for="ev in memoDetail.evidence" :key="ev.id"><td class="mono">{{ ev.argument_key }}</td><td><span class="pill" :class="ev.direction">{{ ev.direction }}</span></td><td>{{ ev.weight }}</td><td>{{ ev.finding?.title || ev.finding_id }}</td><td><span v-if="ev.finding" class="pill" :class="ev.finding.severity">{{ ev.finding.severity }}</span></td><td>{{ ev.finding?.status || '—' }}</td></tr></tbody>
                        </table>
                      </div>
                    </template>
                  </details>
                </td></tr>
              </template>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </main>
  </div>
</template>

<style scoped>
/* The Apparently Steer workspace language: a white, light workspace; warm hairlines; the
   Apparently red for focus and selection only; serif on reading surfaces; navigation owned
   by the rail. Tokens mirror _layers/steer/standalone/console/app/app.css. */
.ds-shell{--bg:#ffffff;--sunk:#f3f3f0;--ink:#181817;--ink-soft:#686762;--ink-faint:#8c8b85;--line:#e4e3de;--line-soft:#eeede8;
  --accent:#b42318;--accent-soft:#fff2f0;--accent-line:#f6d2cc;--good:#3f6b4a;--good-soft:#eff5f0;--warn:#8a5a12;--warn-soft:#fbf3e6;--bad:#b42318;--bad-soft:#fff2f0;
  display:flex;align-items:flex-start;min-height:100vh;background:var(--bg);color:var(--ink);font-family:'Inter',system-ui,sans-serif;-webkit-font-smoothing:antialiased;font-size:13.5px;line-height:1.5}
.serif{font-family:'Libre Caslon Display','Iowan Old Style',Georgia,serif;font-weight:400}
.mono{font-family:'JetBrains Mono','SF Mono',ui-monospace,monospace;font-size:12px}
.ds-shell :focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}

.ds-rail{position:sticky;top:0;flex:0 0 230px;width:230px;height:100vh;overflow-y:auto;overscroll-behavior:contain;padding:20px 14px;border-right:1px solid var(--line);background:#fff;display:flex;flex-direction:column;gap:2px;z-index:40}
.rail-brand{display:flex;align-items:center;gap:9px;padding:0 8px 16px;font-size:15px;letter-spacing:-.01em}
.rail-mark{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:7px;background:var(--accent-soft);border:1px solid var(--accent-line);color:var(--accent);font-size:13px}
.rail-item{display:flex;align-items:center;justify-content:space-between;gap:8px;width:100%;padding:9px 10px;border:0;border-radius:8px;background:none;color:var(--ink-soft);font:inherit;font-weight:600;text-align:left;cursor:pointer}
.rail-item:hover{background:var(--sunk);color:var(--ink)}
.rail-item.active{background:var(--accent-soft);color:var(--accent);box-shadow:inset 2px 0 0 var(--accent)}
kbd{font-family:'JetBrains Mono','SF Mono',ui-monospace,monospace;font-size:10.5px;color:var(--ink-faint);background:var(--sunk);border:1px solid var(--line);border-radius:4px;padding:1px 5px;white-space:nowrap}
.rail-item.active kbd{color:var(--accent);background:#fff;border-color:var(--accent-line)}
.rail-help{margin:auto 8px 0;padding-top:16px;color:var(--ink-faint);font-size:11.5px}
.rail-toggle{display:none;width:34px;height:34px;padding:8px;border:1px solid var(--line);border-radius:8px;background:#fff;margin-bottom:10px;cursor:pointer}
.rail-toggle span{display:block;height:1.5px;background:var(--ink);margin:3px 0;border-radius:2px}
.rail-scrim{display:none;position:fixed;inset:0;border:0;background:rgba(24,24,23,.28);z-index:35}

.ds{flex:1 1 auto;min-width:0;max-width:1180px;padding:28px 32px 80px;display:flex;flex-direction:column;gap:18px}
.ds-head{display:flex;justify-content:space-between;align-items:flex-end;gap:24px;flex-wrap:wrap;scroll-margin-top:16px}
.kicker{display:block;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--accent)}
h1{margin:4px 0 6px;font-size:34px;line-height:1.1;letter-spacing:-.01em}
.ds-head p{margin:0;max-width:66ch;color:var(--ink-soft)}
.ds-filters{display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap}
label{display:flex;flex-direction:column;gap:4px;font-size:11.5px;font-weight:600;color:var(--ink-soft)}
select,input{font:inherit;color:var(--ink);background:#fff;border:1px solid var(--line);border-radius:8px;padding:7px 10px;min-width:0}
select:focus,input:focus{outline:2px solid var(--accent);outline-offset:1px;border-color:var(--accent-line)}
button{font:inherit;font-weight:600;cursor:pointer;border-radius:8px;border:1px solid var(--ink);background:var(--ink);color:#fff;padding:8px 14px}
button:disabled{opacity:.5;cursor:default}
button.ghost{background:#fff;color:var(--ink);border-color:var(--line)}
button.ghost:hover{background:var(--sunk)}
button.ghost.danger{color:var(--bad);border-color:var(--accent-line)}

.ds-empty{padding:22px;border:1px dashed var(--line);border-radius:12px;color:var(--ink-soft);background:var(--sunk)}
.ds-empty.inline{padding:14px 16px;border-radius:10px}
.ds-empty.error{color:var(--bad);background:var(--bad-soft);border-color:var(--accent-line)}
.ds-notice{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 14px;border:1px solid var(--good);background:var(--good-soft);color:var(--good);border-radius:10px}

.guide{display:flex;flex-direction:column;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:#fff}
.guide-calm{margin:0;padding:22px 20px;font-size:20px;color:var(--ink-soft)}
.guide-item{display:flex;align-items:center;gap:14px;width:100%;padding:13px 16px;border:0;border-top:1px solid var(--line-soft);border-radius:0;background:#fff;color:var(--ink);text-align:left;font-weight:400}
.guide-item:first-child{border-top:0}
.guide-item:hover,.guide-item:focus-visible{background:var(--accent-soft);outline:none;box-shadow:inset 2px 0 0 var(--accent)}
.guide-item.bad kbd{color:var(--bad);border-color:var(--accent-line);background:var(--bad-soft)}
.guide-item.good kbd{color:var(--good);border-color:#cfe0d3;background:var(--good-soft)}
.guide-text{display:flex;flex-direction:column;gap:2px;min-width:0;flex:1 1 auto}
.guide-text b{font-weight:600}
.guide-text small{color:var(--ink-faint);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.guide-cta{flex:0 0 auto;color:var(--accent);font-weight:600;font-size:12.5px;white-space:nowrap}
.ds-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
.ds-cards .ds-card{display:flex;align-items:center;gap:14px;padding:16px 18px}
.ds-cards strong{font-family:'Libre Caslon Display',Georgia,serif;font-weight:400;font-size:38px;line-height:1}
.ds-cards small{color:var(--ink-faint)}
.trend{font-family:'Inter',system-ui,sans-serif;font-size:12px;margin-left:6px}
.ds-card{border:1px solid var(--line);border-radius:12px;background:#fff;padding:18px 20px;scroll-margin-top:16px;min-width:0}
.ds-card.good{border-left:3px solid var(--good)} .ds-card.warn{border-left:3px solid var(--warn)} .ds-card.bad{border-left:3px solid var(--bad)}
.ds-card>header{display:flex;justify-content:space-between;align-items:baseline;gap:16px;flex-wrap:wrap;margin-bottom:14px}
h2{margin:0;font-size:15px;font-weight:700;letter-spacing:-.005em}
h3{margin:0 0 8px;font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-faint)}
.ds-card>header span{color:var(--ink-faint);font-size:12px}

.ds-posture{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.posture-card{border:1px solid var(--line);border-radius:10px;padding:12px 14px;display:flex;flex-direction:column;gap:2px;min-width:0;background:#fff}
.posture-card strong{font-family:'Libre Caslon Display',Georgia,serif;font-weight:400;font-size:28px;line-height:1}
.posture-card.good strong{color:var(--good)} .posture-card.warn strong{color:var(--warn)} .posture-card.bad strong{color:var(--bad)} .posture-card.none strong{color:var(--ink-faint)}
.posture-label{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.posture-card small{color:var(--ink-faint);font-size:11.5px}

.table-wrap{overflow-x:auto;border:1px solid var(--line-soft);border-radius:10px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-faint);background:var(--sunk);padding:9px 12px;white-space:nowrap}
td{padding:10px 12px;border-top:1px solid var(--line-soft);vertical-align:top}
td small,td b+small{display:block;color:var(--ink-faint);font-size:11.5px;margin-top:2px}
td small.err{color:var(--bad)}
tbody tr:focus-visible,tbody tr.open,.insight:focus-visible{background:var(--accent-soft);outline:none;box-shadow:inset 2px 0 0 var(--accent)}
tr.clickable{cursor:pointer} tr.clickable:hover{background:var(--sunk)}
td.actions{white-space:nowrap;display:flex;gap:6px} td.rem{max-width:320px;color:var(--ink-soft)}

.pill{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;border:1px solid var(--line);background:var(--sunk);color:var(--ink-soft);font-style:normal;white-space:nowrap}
.pill.critical,.pill.existential,.pill.bad,.pill.unreachable,.pill.undermines{background:var(--bad-soft);color:var(--bad);border-color:var(--accent-line)}
.pill.high,.pill.warn,.pill.stale,.pill.paused{background:var(--warn-soft);color:var(--warn);border-color:#ecd9b4}
.pill.good,.pill.active,.pill.supports,.pill.reviewed,.pill.upside{background:var(--good-soft);color:var(--good);border-color:#cfe0d3}
.pill.gauntleted{background:#fff;color:var(--accent);border-color:var(--accent-line);margin-left:6px}
.sev-tally{display:flex;gap:6px;flex-wrap:wrap}

.pathways{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin-bottom:16px}
.pathways h3{grid-column:1/-1;margin:0}
.pathway{border:1px solid #cfe0d3;background:var(--good-soft);border-radius:10px;padding:12px 14px;min-width:0}
.pathway p,.insight p{margin:6px 0 0;font-size:16px;line-height:1.45;color:var(--ink)}
.chip-row{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.chip{padding:4px 11px;border-radius:999px;border:1px solid var(--line);background:#fff;color:var(--ink-soft);font-size:12px}
.chip.on{background:var(--accent-soft);color:var(--accent);border-color:var(--accent-line)}
.insight-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;border:1px solid var(--line-soft);border-radius:10px;max-height:560px;overflow-y:auto}
.insight{padding:12px 14px;border-top:1px solid var(--line-soft);cursor:pointer} .insight:first-child{border-top:0}
.insight:hover{background:var(--sunk)}
.insight-meta{display:flex;gap:6px;align-items:center;flex-wrap:wrap} .insight-meta small{color:var(--ink-faint);font-size:11.5px}
.rationale{font-family:'Inter',system-ui,sans-serif!important;font-size:12.5px!important;color:var(--ink-soft)!important;border-left:2px solid var(--line);padding-left:10px}

table.matrix th[scope=row]{text-transform:none;letter-spacing:0;font-size:12.5px;color:var(--ink);background:#fff;border-top:1px solid var(--line-soft)}
table.matrix td{text-align:center;min-width:92px;background:color-mix(in srgb,var(--accent) calc(var(--heat,0)*100%),#fff)}
table.matrix td b{display:block;font-family:'Libre Caslon Display',Georgia,serif;font-weight:400;font-size:20px}
table.matrix td.empty{background:repeating-linear-gradient(135deg,#fff,#fff 6px,var(--sunk) 6px,var(--sunk) 12px);color:var(--ink-faint)}
.matrix-note{margin:12px 0 8px;color:var(--ink-soft);max-width:80ch}
.vertical-row{display:flex;gap:6px;flex-wrap:wrap}

.ds-link .link-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}
.link-way{border:1px solid var(--line-soft);border-radius:10px;padding:16px;display:flex;flex-direction:column;gap:10px;min-width:0}
.link-way p{margin:0;color:var(--ink-soft)} .link-way a{color:var(--accent)}
.step{display:inline-flex;width:22px;height:22px;align-items:center;justify-content:center;border-radius:50%;background:var(--accent-soft);color:var(--accent);border:1px solid var(--accent-line);font-size:11px;font-weight:700}
.form-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px} .form-grid .wide{grid-column:1/-1}
.form-grid small{font-weight:400;color:var(--ink-faint)}
.form-error{color:var(--bad);background:var(--bad-soft);border:1px solid var(--accent-line);border-radius:8px;padding:8px 10px}

.brief{border-top:1px solid var(--line-soft);padding:10px 0} .brief:first-of-type{border-top:0}
.brief summary{cursor:pointer;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap} .brief summary small{color:var(--ink-faint)}
pre{margin:10px 0 0;white-space:pre-wrap;word-break:break-word;background:var(--sunk);border:1px solid var(--line-soft);border-radius:10px;padding:14px 16px;font-family:'JetBrains Mono','SF Mono',ui-monospace,monospace;font-size:12px;line-height:1.55;color:var(--ink)}
pre.serif.reading{font-family:'Libre Caslon Display','Iowan Old Style',Georgia,serif;font-size:16px;line-height:1.6;background:#fff;max-width:74ch}
.memo-row td{background:var(--sunk)} .memo-pane summary{cursor:pointer;font-weight:600;color:var(--ink-soft)}
.thesis{font-family:'Libre Caslon Display',Georgia,serif;font-size:18px;line-height:1.4;margin:12px 0 4px;max-width:70ch}
.gauntlet-card{border:1px solid var(--accent-line);background:var(--accent-soft);border-radius:10px;padding:12px 14px;margin:10px 0}
.gauntlet-card p{margin:6px 0 0;color:var(--ink)}
table.evidence{margin-top:12px}

@media (max-width:900px){
  .ds-rail{position:fixed;left:0;top:0;transform:translateX(-100%);transition:transform .18s ease;box-shadow:0 0 0 1px var(--line)}
  .rail-open .ds-rail{transform:none} .rail-open .rail-scrim{display:block}
  .rail-toggle{display:block}
  .ds{padding:18px 16px 64px}
  h1{font-size:27px}
}
@media (max-width:480px){
  .guide-cta{display:none}
  .ds-cards{grid-template-columns:1fr 1fr} .ds-cards strong{font-size:30px}
  .ds-card{padding:14px} .pathway p,.insight p{font-size:15px}
  td.actions{flex-direction:column}
}
@media (prefers-reduced-motion:reduce){.ds-rail{transition:none}}
</style>
