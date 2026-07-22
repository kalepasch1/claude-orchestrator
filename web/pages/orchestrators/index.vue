<script setup lang="ts">
definePageMeta({ layout: 'default' })
import { ORCHESTRATOR_CAPABILITIES } from '~/config/orchestratorCapabilities'

const supabase = useSupabaseClient<any>()
const user = useSupabaseUser()

const CAPS = [
  { slug: 'deploy-orchestrator', name: 'Deployment', domain: 'devops', icon: '🚀', status: 'trusted', maturity: 86, summary: 'Canary deployments, rollbacks, release gates' },
  { slug: 'review-orchestrator', name: 'Code Review', domain: 'engineering', icon: '👁', status: 'trusted', maturity: 91, summary: 'Multi-model code review, security scanning' },
  { slug: 'optimize-orchestrator', name: 'Optimization', domain: 'engineering', icon: '⚡', status: 'trusted', maturity: 80, summary: 'Performance, cost, and prompt optimization' },
  { slug: 'preflight-inspector', name: 'Pre-flight', domain: 'engineering', icon: '✈', status: 'trusted', maturity: 88, summary: 'Pre-execution validation of state and deps' },
  { slug: 'remediation-orchestrator', name: 'Remediation', domain: 'engineering', icon: '🔧', status: 'trusted', maturity: 93, summary: 'Auto-diagnose and repair failing builds' },
  { slug: 'growth-orchestrator', name: 'Growth', domain: 'growth', icon: '📈', status: 'trusted', maturity: 79, summary: 'Growth experiments, A/B tests, conversions' },
  { slug: 'entity-formation', name: 'Entity Formation', domain: 'legal-ops', icon: '🏢', status: 'productizable', maturity: 95, summary: 'Jurisdiction-aware entity formation filings' },
  { slug: 'legal-orchestrator', name: 'Legal', domain: 'legal-ops', icon: '⚖', status: 'trusted', maturity: 87, summary: 'Legal review, compliance, contracts' },
  { slug: 'design-orchestrator', name: 'Chief Design', domain: 'product-design', icon: '🎨', status: 'trusted', maturity: 82, summary: 'UI/UX improvements, brand consistency' },
  { slug: 'security-orchestrator', name: 'Security', domain: 'security', icon: '🔒', status: 'trusted', maturity: 89, summary: 'RLS, access controls, key rotation' },
  { slug: 'colosseum-evaluator', name: 'Model Arena', domain: 'platform', icon: '🏟', status: 'experimental', maturity: 72, summary: 'Embedded model evaluation powering all routing' },
  { slug: 'learn-orchestrator', name: 'Learning', domain: 'platform', icon: '📚', status: 'trusted', maturity: 81, summary: 'Pattern capture and shared knowledge' },
  { slug: 'queue-orchestrator', name: 'Queue', domain: 'platform', icon: '📋', status: 'trusted', maturity: 84, summary: 'Task grooming, priority lanes, throughput' },
]

const DOMAINS = [
  { key: 'all', label: 'All Capabilities', icon: '◎' },
  { key: 'engineering', label: 'Engineering', icon: '⚙' },
  { key: 'devops', label: 'DevOps', icon: '🚀' },
  { key: 'product-design', label: 'Design', icon: '🎨' },
  { key: 'legal-ops', label: 'Legal', icon: '⚖' },
  { key: 'growth', label: 'Growth', icon: '📈' },
  { key: 'security', label: 'Security', icon: '🔒' },
  { key: 'platform', label: 'Platform', icon: '🏗' },
  { key: 'terminal', label: 'Command Terminal', icon: '▸' },
  { key: 'bots', label: 'Quality Bots', icon: '🤖' },
]

const MODELS = [
  { label: 'Sonnet 4.6', value: 'claude-sonnet-4-6' }, { label: 'Haiku 4.5', value: 'claude-haiku-4-5-20251001' },
  { label: 'Opus 4.8', value: 'claude-opus-4-8' }, { label: 'GPT-4o', value: 'gpt-4o' },
  { label: 'GPT-4o Mini', value: 'gpt-4o-mini' }, { label: 'Gemini 2.0 Flash', value: 'gemini/gemini-2.0-flash' },
  { label: 'Gemini 1.5 Pro', value: 'gemini/gemini-1.5-pro' }, { label: 'Qwen2.5 Coder', value: 'ollama/qwen2.5-coder:7b' },
  { label: 'Cowork Executor', value: 'cowork-executor' },
]

const SPECIALIST_BOTS = [
  { name: 'Change Type Analyzer', group: 'Triage', status: 'active' },
  { name: 'Impact Scope Assessor', group: 'Triage', status: 'active' },
  { name: 'Regression Detector', group: 'Triage', status: 'active' },
  { name: 'Pixel Inspector', group: 'Quality', status: 'active' },
  { name: 'Consistency Checker', group: 'Quality', status: 'active' },
  { name: 'A11y Validator', group: 'Quality', status: 'active' },
  { name: 'Engagement Tracker', group: 'Analytics', status: 'active' },
  { name: 'Heatmap Analyzer', group: 'Analytics', status: 'active' },
  { name: 'Brand Consistency Bot', group: 'Brand', status: 'active' },
  { name: 'Cognitive Load Sensor', group: 'UX', status: 'active' },
  { name: 'Attention Flow Mapper', group: 'UX', status: 'active' },
  { name: 'Anomaly Detector', group: 'Security', status: 'active' },
  { name: 'Threat Modeler', group: 'Security', status: 'active' },
  { name: 'Pattern Recognizer', group: 'Learning', status: 'active' },
  { name: 'Intent Predictor', group: 'Learning', status: 'active' },
]

const activeDomain = ref('all')
const terminalPrompt = ref('')
const terminalLoading = ref(false)
const terminalOutput = ref('')
const selectedModel = ref('claude-sonnet-4-6')
const selectedKind = ref('build')
const selectedMode = ref('build')
const routeInfo = ref('')
const showOverride = ref(false)
const projects = ref<any[]>([])
const recentTasks = ref<any[]>([])
const prompt = ref('')
const projectId = ref('')
const submitting = ref(false)
const notice = ref('')
const projectChoices = ref<any[]>([])

const commandCenters = ORCHESTRATOR_CAPABILITIES

const autopilotProof = [
  { name: 'Context understood', summary: 'Madeus identifies the right project, scope, constraints, and risk.' },
  { name: 'Best route selected', summary: 'Specialists and tools are chosen for the outcome, then re-evaluated as work changes.' },
  { name: 'Work independently proven', summary: 'Tests, evidence, accessibility, and regressions are checked before approval.' },
  { name: 'Release safely verified', summary: 'Only durable deployments are promoted, with proof and recovery recorded.' },
]

function stateClass(state: string) {
  if (state === 'DONE') return 'done'
  if (state === 'RUNNING') return 'running'
  if (state === 'FAILED') return 'failed'
  return 'queued'
}

async function authedFetch<T = any>(url: string, options: any = {}) {
  const { data: { session } } = await supabase.auth.getSession()
  return $fetch<T>(url, { ...options, headers: { ...(options.headers || {}), ...(session?.access_token ? { authorization: `Bearer ${session.access_token}` } : {}) } })
}

async function load() {
  const [projectResult, taskResult] = await Promise.all([
    supabase.from('projects').select('id,name').order('name'),
    supabase.from('tasks').select('id,slug,state,kind,created_at').order('created_at', { ascending: false }).limit(6),
  ])
  projects.value = projectResult.data || []
  recentTasks.value = taskResult.data || []
}

async function submit(chosenProject?: string) {
  if (!prompt.value.trim()) return
  submitting.value = true
  notice.value = ''
  projectChoices.value = []
  try {
    const result = await authedFetch<any>('/api/tasks/intake', { method: 'POST', body: { intent: prompt.value.trim(), project_id: chosenProject || projectId.value || undefined, source: 'command-center' } })
    notice.value = `Routed to ${result.project?.name || 'the right project'} · ${result.task?.slug || 'task queued'}`
    prompt.value = ''
    await load()
  } catch (error: any) {
    if (error?.statusCode === 409 || error?.data?.code === 'project_required') {
      projectChoices.value = error?.data?.projects || projects.value
      notice.value = 'Which project should Madeus change?'
    } else notice.value = error?.data?.message || error?.message || 'Madeus could not route this request.'
  } finally { submitting.value = false }
}

onMounted(async () => {
  await load()
  try {
    const pending = JSON.parse(sessionStorage.getItem('madeus:pending-command') || 'null')
    if (pending?.intent && Date.now() - Number(pending.created_at || 0) < 86_400_000) prompt.value = String(pending.intent)
    if (pending) sessionStorage.removeItem('madeus:pending-command')
  } catch { sessionStorage.removeItem('madeus:pending-command') }
})
</script>

<template>
  <main class="command-page">
    <section class="command-hero">
      <div class="hero-kicker"><span class="pulse-dot" /> Madeus command centers</div>
      <h1>One outcome in.<br><span>Every specialist coordinated.</span></h1>
      <p>Choose a focused workspace when you want controls and tools, or simply describe the outcome. Madeus handles routing, models, vendors, branches, research, QA, and release.</p>

      <form class="outcome-box" @submit.prevent="submit()">
        <div class="outcome-label">What should we accomplish?</div>
        <textarea v-model="prompt" rows="3" placeholder="Build, fix, research, design, review, or improve anything…" />
        <div class="outcome-footer">
          <label class="project-select">
            <span>Project</span>
            <select v-model="projectId">
              <option value="">Let Madeus detect it</option>
              <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option>
            </select>
          </label>
          <div class="autopilot-copy"><b>✦ Autopilot</b><span>Context, specialists, tools, verification, and release are handled for you</span></div>
          <button :disabled="submitting || !prompt.trim()">{{ submitting ? 'Routing…' : 'Start' }} <span>↗</span></button>
        </div>
        <div v-if="notice" class="routing-notice">{{ notice }}</div>
        <div v-if="projectChoices.length" class="project-choices">
          <button v-for="project in projectChoices" :key="project.id" type="button" @click="projectId = project.id; submit(project.id)">{{ project.name }}</button>
        </div>
      </form>
    </section>

    <section class="content-section">
      <div class="section-heading">
        <div><span>Focused workspaces</span><h2>Command centers for work you direct</h2></div>
        <p>Open one when you need domain tools, configurable outputs, previews, evidence, or approvals.</p>
      </div>
      <div class="center-grid">
        <NuxtLink v-for="center in commandCenters" :key="center.slug" :to="`/orchestrators/${center.slug}`" class="center-card">
          <div class="center-top"><span class="center-icon">{{ center.icon }}</span><span class="open-arrow">↗</span></div>
          <div class="eyebrow">{{ center.eyebrow }}</div>
          <h3>{{ center.name }}</h3>
          <p>{{ center.summary }}</p>
          <div class="action-list"><span v-for="action in center.actions" :key="action">{{ action }}</span></div>
        </NuxtLink>
      </div>
    </section>

      <!-- Specialist Bots -->
      <div v-else-if="activeDomain === 'bots'" class="p-6 max-w-4xl space-y-4">
        <h2 class="text-lg font-semibold text-gray-900" style="font-family: 'Fraunces', serif;">Quality Bot Fleet</h2>
        <p class="text-xs text-gray-500">60 bots across 15 groups powering automated quality, analytics, and optimization.</p>
        <div class="space-y-2">
          <div v-for="b in SPECIALIST_BOTS" :key="b.name" class="bg-white border border-gray-200 rounded-xl p-4 flex items-center justify-between">
            <div class="flex items-center gap-3">
              <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
              <div>
                <div class="text-sm text-gray-900">{{ b.name }}</div>
                <div class="text-[10px] text-gray-400">{{ b.group }}</div>
              </div>
            </div>
            <span class="text-[10px] text-emerald-600 font-medium">{{ b.status }}</span>
          </div>
        </div>
      </div>
      <div class="proof-grid">
        <article v-for="(item, index) in autopilotProof" :key="item.name"><b>{{ String(index + 1).padStart(2, '0') }}</b><div><h3>{{ item.name }}</h3><p>{{ item.summary }}</p></div><span>Included</span></article>
      </div>
    </section>

    <section v-if="recentTasks.length" class="content-section recent-section">
      <div class="section-heading"><div><span>Portfolio activity</span><h2>Recently routed</h2></div></div>
      <div class="recent-list"><article v-for="task in recentTasks" :key="task.id"><i :class="stateClass(task.state)" /><strong>{{ task.slug }}</strong><span>{{ task.kind || 'work' }}</span><small>{{ task.state }}</small></article></div>
    </section>
  </main>
</template>

<style scoped>
.command-page{min-height:100%;background:#fafafa;color:#111}.command-hero{padding:76px 40px 64px;border-bottom:1px solid #e7e7e7;background:radial-gradient(circle at 75% 0,#e8eeff 0,transparent 28%),linear-gradient(#fff,#fafafa)}.command-hero>*{max-width:1120px;margin-left:auto;margin-right:auto}.hero-kicker,.eyebrow,.section-heading span{font-size:11px;font-weight:700;letter-spacing:.13em;text-transform:uppercase;color:#5b5bd6}.pulse-dot{display:inline-block;width:7px;height:7px;margin-right:8px;border-radius:50%;background:#6d5dfc;box-shadow:0 0 0 5px #6d5dfc18}.command-hero h1{margin-top:22px;font-size:clamp(42px,6vw,76px);line-height:.98;letter-spacing:-.055em;font-weight:650}.command-hero h1 span{color:#777}.command-hero>p{margin-top:24px;max-width:760px;margin-left:calc((100% - 1120px)/2);font-size:17px;line-height:1.65;color:#626262}.outcome-box{margin-top:38px;padding:18px;border:1px solid #d9d9d9;border-radius:18px;background:#fff;box-shadow:0 20px 60px #1111}.outcome-label{font-size:12px;font-weight:700;color:#222}.outcome-box textarea{width:100%;resize:none;border:0;outline:0;padding:14px 0;font-size:20px;line-height:1.5;color:#111}.outcome-footer{display:flex;gap:18px;align-items:center;padding-top:14px;border-top:1px solid #eee}.project-select{display:flex;flex-direction:column;gap:3px}.project-select span{font-size:9px;text-transform:uppercase;letter-spacing:.1em;color:#999}.project-select select{min-width:180px;border:0;background:#f4f4f4;border-radius:8px;padding:8px 10px;font-size:12px}.autopilot-copy{display:flex;flex:1;gap:10px;align-items:center;font-size:11px;color:#777}.autopilot-copy b{color:#5b5bd6}.outcome-footer>button{border:0;border-radius:10px;padding:12px 22px;background:#111;color:#fff;font-weight:650}.outcome-footer>button:disabled{opacity:.35}.routing-notice{margin-top:12px;font-size:12px;color:#5252b8}.project-choices{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.project-choices button{border:1px solid #d8d8d8;border-radius:99px;background:#fff;padding:7px 11px;font-size:11px}.content-section,.platform-section{padding:72px 40px}.content-section>* , .platform-section>*{max-width:1120px;margin-left:auto;margin-right:auto}.section-heading{display:flex;justify-content:space-between;gap:40px;align-items:end;margin-bottom:28px}.section-heading h2{margin-top:8px;font-size:30px;letter-spacing:-.035em}.section-heading>p{max-width:480px;font-size:13px;line-height:1.6;color:#737373}.center-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.center-card{min-height:290px;padding:24px;border:1px solid #e0e0e0;border-radius:16px;background:#fff;color:inherit;text-decoration:none;transition:.2s}.center-card:hover{transform:translateY(-3px);border-color:#b7b2fa;box-shadow:0 18px 44px #1111110f}.center-top{display:flex;justify-content:space-between}.center-icon{display:grid;width:38px;height:38px;place-items:center;border-radius:10px;background:#f1efff;color:#4f46c8}.open-arrow{color:#aaa}.center-card h3{margin-top:10px;font-size:24px;letter-spacing:-.03em}.center-card p{margin-top:10px;min-height:63px;font-size:13px;line-height:1.6;color:#666}.action-list{display:flex;flex-wrap:wrap;gap:6px;margin-top:18px}.action-list span{padding:6px 8px;border-radius:6px;background:#f6f6f6;font-size:10px;color:#555}.platform-section{background:#111;color:#fff}.section-heading.inverse span{color:#9e95ff}.section-heading.inverse>p{color:#999}.platform-grid{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid #333}.platform-grid article{display:grid;grid-template-columns:42px 1fr auto;gap:10px;padding:22px 12px;border-bottom:1px solid #2d2d2d}.platform-grid article:nth-child(odd){border-right:1px solid #2d2d2d}.platform-grid b{font:11px monospace;color:#666}.platform-grid h3{font-size:14px}.platform-grid p{margin-top:5px;font-size:11px;line-height:1.5;color:#888}.platform-grid article>span{align-self:start;color:#76d69a;font-size:9px;text-transform:uppercase;letter-spacing:.1em}.recent-section{padding-top:56px}.recent-list article{display:grid;grid-template-columns:12px 1fr auto 80px;align-items:center;gap:12px;padding:14px 4px;border-bottom:1px solid #e6e6e6;font-size:12px}.recent-list i{width:7px;height:7px;border-radius:50%;background:#aaa}.recent-list i.done{background:#35a561}.recent-list i.running{background:#6658e8}.recent-list i.failed{background:#e04949}.recent-list span,.recent-list small{color:#888}@media(max-width:850px){.center-grid{grid-template-columns:1fr 1fr}.command-hero>p{margin-left:auto}.section-heading{align-items:start;flex-direction:column}.platform-grid{grid-template-columns:1fr}.platform-grid article:nth-child(odd){border-right:0}}@media(max-width:620px){.command-hero,.content-section,.platform-section{padding:44px 20px}.center-grid{grid-template-columns:1fr}.outcome-footer{align-items:stretch;flex-direction:column}.autopilot-copy{align-items:start;flex-direction:column}.project-select select{width:100%}.platform-grid article{grid-template-columns:30px 1fr}.platform-grid article>span{display:none}}
.command-page{background:#f7f7f3;color:#171717}.command-hero{border-color:#dedfd9;background:#fff}.hero-kicker,.eyebrow,.section-heading span{color:#194c36}.pulse-dot{background:#194c36;box-shadow:0 0 0 5px #e5efe9}.outcome-box{border-color:#d8dbd5;border-radius:14px;box-shadow:0 24px 70px #172d2210}.autopilot-copy b,.routing-notice{color:#194c36}.content-section,.autopilot-section{padding:72px 40px}.content-section>*,.autopilot-section>*{max-width:1120px;margin-left:auto;margin-right:auto}.center-card{border-color:#dedfd9;border-radius:12px}.center-card:hover{border-color:#8eac9b;box-shadow:0 18px 44px #193d2b12}.center-icon{background:#edf4ef;color:#194c36}.action-list span{background:#f1f2ee}.autopilot-section{border-block:1px solid #dfe1dc;background:#eef3ee}.proof-grid{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid #cfd8d1}.proof-grid article{display:grid;grid-template-columns:auto 1fr;gap:12px;padding:22px 18px;border-right:1px solid #cfd8d1}.proof-grid article:last-child{border-right:0}.proof-grid b{font:10px monospace;color:#668070}.proof-grid h3{font-size:14px}.proof-grid p{margin-top:6px;font-size:11px;line-height:1.55;color:#607066}.proof-grid article>span{grid-column:2;font-size:8px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#276746}.recent-list i.running{background:#194c36}@media(max-width:850px){.proof-grid{grid-template-columns:1fr 1fr}.proof-grid article:nth-child(2){border-right:0}}@media(max-width:620px){.autopilot-section{padding:44px 20px}.proof-grid{grid-template-columns:1fr}.proof-grid article{border-right:0;border-bottom:1px solid #cfd8d1}}
</style>
