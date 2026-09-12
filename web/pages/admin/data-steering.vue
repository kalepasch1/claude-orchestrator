<script setup lang="ts">
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
function objectName(f: any) { return [f.object_schema, f.object_name].filter(Boolean).join('.') || '—' }

watch(user, (u) => { if (u) load() })
onMounted(() => { if (user.value) load() })
</script>

<template>
  <main class="ds">
    <header class="ds-head">
      <div>
        <span class="kicker">Database steering</span>
        <h1>Database steering</h1>
        <p>Every linked database is reviewed continuously and read-only. Findings steer coder agents and feed the internal legal-memo evidence ledger. Credentials never live here — only references.</p>
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

      <!-- Posture strip -->
      <section class="ds-posture" v-if="data.sources?.length">
        <article v-for="s in data.sources" :key="s.id" class="posture-card" :class="scoreClass(score(s.id))">
          <strong>{{ score(s.id) == null ? '—' : score(s.id)!.toFixed(0) }}</strong>
          <span class="posture-label">{{ s.label }}</span>
          <small>{{ s.provider }}<template v-if="data.posture?.[s.id]"> · {{ when(data.posture[s.id].taken_at) }}</template><template v-else> · no snapshot yet</template></small>
        </article>
      </section>

      <!-- Sources -->
      <section class="ds-card">
        <header><h2>Sources</h2><span>{{ data.sources?.length || 0 }} linked · {{ (data.sources || []).filter((s: any) => s.enabled).length }} active</span></header>
        <div v-if="!data.sources?.length" class="ds-empty inline">No databases are linked yet. Link one below.</div>
        <div v-else class="table-wrap">
          <table>
            <thead><tr><th>Label</th><th>Provider</th><th>Project</th><th>Status</th><th>Last scan</th><th>Credential</th><th></th></tr></thead>
            <tbody>
              <tr v-for="s in data.sources" :key="s.id">
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
      <section class="ds-card ds-link">
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
      <section class="ds-card">
        <header>
          <h2>Open findings</h2>
          <span class="sev-tally"><i v-for="sev in severityOrder" :key="sev" class="pill" :class="sev">{{ sev }} {{ data.findings?.open_by_severity?.[sev] || 0 }}</i></span>
        </header>
        <div v-if="!data.findings?.top?.length" class="ds-empty inline">No open findings in the last {{ days }} day{{ days === 1 ? '' : 's' }}.</div>
        <div v-else class="table-wrap">
          <table>
            <thead><tr><th>Severity</th><th>Project</th><th>Title</th><th>Object</th><th>First seen</th><th>Last seen</th><th>Remediation</th></tr></thead>
            <tbody>
              <tr v-for="f in data.findings.top" :key="f.id">
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
      <section class="ds-card" v-if="data.briefs?.length">
        <header><h2>Steering briefs</h2><span>Injected into every coder prompt for the project</span></header>
        <details v-for="b in data.briefs" :key="b.project" class="brief">
          <summary><b>{{ b.project }}</b><small>updated {{ when(b.updated_at) }} · {{ Object.entries(b.open_counts || {}).map(([k, v]) => `${k} ${v}`).join(' · ') || 'no open counts' }}</small></summary>
          <pre>{{ b.brief }}</pre>
        </details>
      </section>

      <!-- Memos -->
      <section class="ds-card">
        <header><h2>Legal-memo drafts</h2><span>Internal work product · not legal advice</span></header>
        <div v-if="!data.memos?.length" class="ds-empty inline">No memo drafts yet. They appear once findings carry evidence kinds.</div>
        <div v-else class="table-wrap">
          <table>
            <thead><tr><th>Title</th><th>Project</th><th>Status</th><th>Evidence</th><th>Strengths</th><th>Updated</th></tr></thead>
            <tbody>
              <template v-for="m in data.memos" :key="m.id">
                <tr class="clickable" :class="{ open: openMemoId === m.id }" @click="openMemo(m)">
                  <td><b>{{ m.title }}</b><small class="mono">{{ m.memo_kind }}</small></td>
                  <td>{{ m.project }}</td>
                  <td><span class="pill" :class="m.status">{{ m.status }}</span></td>
                  <td>{{ m.evidence_count }}</td>
                  <td>{{ strengths(m) }}</td>
                  <td>{{ when(m.updated_at) }}</td>
                </tr>
                <tr v-if="openMemoId === m.id" class="memo-row"><td colspan="6">
                  <details open class="memo-pane">
                    <summary>{{ memoLoading ? 'Loading memo…' : memoError ? memoError : `Memo body · ${memoDetail?.evidence?.length || 0} evidence rows` }}</summary>
                    <template v-if="memoDetail">
                      <p v-if="memoDetail.memo?.thesis" class="thesis">{{ memoDetail.memo.thesis }}</p>
                      <pre>{{ memoDetail.memo?.body || '(no body drafted yet — prose is generated once the evidence set changes)' }}</pre>
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
</template>

<style scoped>
.ds{max-width:1240px;margin:0 auto;padding:24px;color:#e7e7ea;font-size:13px}
.ds-head{display:flex;justify-content:space-between;gap:24px;align-items:flex-end;margin-bottom:20px;flex-wrap:wrap}
.ds-head h1{font-size:22px;font-weight:700;margin:4px 0 6px}
.ds-head p{color:#9a9aa2;max-width:720px;margin:0;line-height:1.5}
.kicker{font-size:10px;font-weight:750;letter-spacing:.14em;text-transform:uppercase;color:#b79cff}
.ds-filters{display:flex;gap:10px;align-items:flex-end}
.ds-filters label{display:flex;flex-direction:column;gap:4px;font-size:11px;color:#7a7a82}
select,input{background:#0f0f12;color:#e7e7ea;border:1px solid #2a2a30;border-radius:6px;padding:7px 9px;font-size:13px;font-family:inherit}
select:focus,input:focus{outline:none;border-color:#b79cff}
button{background:#6557d8;color:#fff;border:0;border-radius:6px;padding:7px 12px;font-size:12px;font-weight:600;cursor:pointer;font-family:inherit}
button:disabled{opacity:.5;cursor:default}
button.ghost{background:#26262c;color:#b5b5bd;border:1px solid #2a2a30;padding:5px 10px}
button.ghost:hover:not(:disabled){background:#2b2b31;color:#e7e7ea}
button.ghost.danger{color:#ff8a8a}
.ds-empty{padding:40px;text-align:center;color:#7a7a82;background:#17171b;border:1px solid #2a2a30;border-radius:10px}
.ds-empty.inline{padding:22px;border:0;background:transparent}
.ds-empty.error{color:#ff8a8a}
.ds-notice{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 14px;margin-bottom:14px;background:#123227;color:#5fe0a0;border:1px solid #1f4a39;border-radius:8px}
.ds-posture{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-bottom:16px}
.posture-card{background:#17171b;border:1px solid #2a2a30;border-radius:10px;padding:12px 14px;display:flex;flex-direction:column;gap:2px;border-left-width:3px}
.posture-card strong{font-size:22px;font-weight:700;line-height:1.1}
.posture-card .posture-label{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.posture-card small{color:#7a7a82;font-size:11px}
.posture-card.good{border-left-color:#5fe0a0}.posture-card.good strong{color:#5fe0a0}
.posture-card.warn{border-left-color:#f0b060}.posture-card.warn strong{color:#f0b060}
.posture-card.bad{border-left-color:#ff6b6b}.posture-card.bad strong{color:#ff6b6b}
.posture-card.none{border-left-color:#3a3a42}.posture-card.none strong{color:#7a7a82}
.ds-card{background:#17171b;border:1px solid #2a2a30;border-radius:10px;margin-bottom:16px;overflow:hidden}
.ds-card>header{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 16px;border-bottom:1px solid #2a2a30;flex-wrap:wrap}
.ds-card>header h2{font-size:14px;font-weight:700;margin:0}
.ds-card>header>span{color:#7a7a82;font-size:11px}
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse}
th{text-align:left;font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:#7a7a82;padding:8px 12px;border-bottom:1px solid #2a2a30;white-space:nowrap}
td{padding:9px 12px;border-bottom:1px solid #202026;vertical-align:top}
tr:last-child td{border-bottom:0}
td b{font-weight:600;display:block}
td small{display:block;color:#7a7a82;font-size:11px;margin-top:2px}
td small.err{color:#ff8a8a}
td.actions{white-space:nowrap;text-align:right}
td.actions button{margin-left:6px}
td.rem{max-width:320px;color:#b5b5bd}
tr.clickable{cursor:pointer}
tr.clickable:hover td{background:#1c1c21}
tr.clickable.open td{background:#1c1c21}
tr.memo-row td{background:#121216;padding:0 12px 12px}
.mono{font-family:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px}
.pill{display:inline-block;padding:2px 8px;border-radius:999px;font-size:10.5px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;background:#26262c;color:#b5b5bd;border:1px solid #2a2a30}
.pill.critical{background:#3a1a1e;color:#ff6b6b;border-color:#5a2a30}
.pill.high{background:#3a2418;color:#ff9a5c;border-color:#5a3a24}
.pill.medium{background:#33291a;color:#f0b060;border-color:#4d3d22}
.pill.low{background:#26313f;color:#7fb0ff;border-color:#2f4560}
.pill.info{background:#26262c;color:#9a9aa2}
.pill.active,.pill.supports,.pill.reviewed{background:#123227;color:#5fe0a0;border-color:#1f4a39}
.pill.paused,.pill.stale,.pill.draft{background:#33291a;color:#f0b060;border-color:#4d3d22}
.pill.unreachable,.pill.inactive,.pill.undermines{background:#3a1a1e;color:#ff6b6b;border-color:#5a2a30}
.pill.kind{background:#2b2340;color:#b79cff;border-color:#3d3160;text-transform:none;letter-spacing:0;font-family:'JetBrains Mono',ui-monospace,monospace}
.sev-tally{display:flex;gap:6px;flex-wrap:wrap}
.link-grid{display:grid;grid-template-columns:1fr 1.6fr;gap:0}
.link-way{padding:16px;position:relative}
.link-way+.link-way{border-left:1px solid #2a2a30}
.link-way h3{font-size:13px;font-weight:700;margin:0 0 6px}
.link-way p{color:#9a9aa2;line-height:1.55;margin:0}
.link-way a{color:#b79cff;text-decoration:underline}
.step{display:inline-flex;width:20px;height:20px;align-items:center;justify-content:center;border-radius:999px;background:#2b2340;color:#b79cff;font-size:11px;font-weight:700;margin-bottom:8px}
.form-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:8px 0 12px}
.form-grid label{display:flex;flex-direction:column;gap:4px;font-size:11px;color:#7a7a82}
.form-grid label.wide{grid-column:1/-1}
.form-grid small{color:#7a7a82;font-size:10.5px;line-height:1.4}
.form-error{color:#ff8a8a;margin-bottom:10px;font-size:12px}
.brief{border-bottom:1px solid #202026}
.brief:last-child{border-bottom:0}
.brief summary{padding:10px 16px;cursor:pointer;display:flex;gap:12px;align-items:baseline}
.brief summary small{color:#7a7a82}
pre{white-space:pre-wrap;word-break:break-word;font-family:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;line-height:1.55;color:#d0d0d6;background:#0f0f12;border:1px solid #2a2a30;border-radius:8px;padding:12px 14px;margin:0 16px 12px}
.memo-pane summary{padding:10px 0;cursor:pointer;color:#b5b5bd;font-size:12px}
.memo-pane .thesis{color:#e7e7ea;font-style:italic;margin:0 0 10px;line-height:1.5}
.memo-pane pre{margin:0 0 12px}
.memo-pane .evidence th,.memo-pane .evidence td{font-size:12px}
@media (max-width:900px){.link-grid{grid-template-columns:1fr}.link-way+.link-way{border-left:0;border-top:1px solid #2a2a30}.ds-head{align-items:flex-start}}
</style>
