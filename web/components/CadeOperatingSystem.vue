<script setup lang="ts">
const props = defineProps<{ app: string; capability: string; domain: string; projectId?: string; recommendation?: string; outcome?: string }>()
const emit = defineEmits<{ usePrompt: [value: string] }>()
const supabase = useSupabaseClient<any>()
const tabs = [
  { id: 'replay', label: 'Journey reconstruction' },
  { id: 'shadow', label: 'Why this route' },
  { id: 'room', label: 'Decision room' },
  { id: 'proof', label: 'Proof passport' },
  { id: 'value', label: 'Outcome simulation' },
  { id: 'connectors', label: 'Reliability twin' },
  { id: 'market', label: 'System sync' },
] as const
type Tab = typeof tabs[number]['id']
const active = ref<Tab>('replay')
const busy = ref('')
const notice = ref('')
const error = ref('')
const shadow = ref<any>(null)
const proof = ref<any>(null)
const room = ref<any>(null)
const causal = ref<any>(null)
const optimization = ref<any>(null)
const simulation = ref<any>(null)
const failureTwin = ref<any>(null)
const memory = ref<any>(null)
const queued = ref<any>(null)
const { profile, record } = useAdaptiveProficiency(computed(() => `cade:${props.domain}`))
const roomForm = reactive({
  objective: props.recommendation || `Improve ${props.app} with ${props.capability}`,
  operator: 'Deliver measurable user value quickly',
  specialist: 'Preserve quality, accessibility, and maintainability',
  governor: 'Require bounded scope, evidence, and rollback readiness',
  dissent: 'No unresolved objection may be hidden from the final decision.',
  support: 80,
})
const valueForm = reactive({ intervention: props.recommendation || `Apply Madeus recommendation to ${props.app}`, segment: 'eligible users', treatment_mean: 82, control_mean: 68, sample_size: 120 })
const currentRecommendation = computed(() => props.recommendation || `Reduce friction in the highest-value ${props.domain} journey with guided progression and verified execution.`)
const expectedOutcome = computed(() => props.outcome || 'Faster task completion with fewer errors and a measurable verification trail.')
const guidanceCopy = computed(() => profile.value.explanationDepth === 'detailed'
  ? 'Madeus lets you inspect the proposed experience, compare routes without execution, gather stakeholder constraints, and carry signed proof into release.'
  : profile.value.explanationDepth === 'balanced'
    ? 'Preview, challenge, prove, and measure this recommendation before execution.'
    : 'Counterfactual → consensus → proof → outcome.')

async function authed<T = any>(url: string, options: any = {}) {
  const { data: { session } } = await supabase.auth.getSession()
  return $fetch<T>(url, { ...options, headers: { ...(options.headers || {}), ...(session?.access_token ? { authorization: `Bearer ${session.access_token}` } : {}) } })
}
function resetStatus(action: string) { busy.value = action; notice.value = ''; error.value = '' }
function fail(e: any) { error.value = e?.data?.message || e?.message || 'The governed action could not be completed.'; busy.value = '' }
async function runShadow() {
  resetStatus('shadow')
  try {
    shadow.value = await authed('/api/connectors/route-plan', { method: 'POST', body: { capability: props.domain, intent: `Shadow-only comparison for ${props.app}: ${currentRecommendation.value}` } })
    notice.value = 'Compared eligible routes without executing work or changing provider priority.'
    record('completed')
  } catch (e) { fail(e) } finally { busy.value = '' }
}
function useShadowWinner() {
  if (!shadow.value?.selected) return
  emit('usePrompt', `${currentRecommendation.value}\n\nUse the verified shadow winner only if it still satisfies organization policy. Success criterion: ${expectedOutcome.value}`)
  notice.value = 'The outcome—not the vendor—was added to the command canvas. Madeus will revalidate the best route at execution time.'
  record('completed')
}
async function createRoom() {
  resetStatus('room')
  try {
    const result: any = await authed('/api/constitution/action', { method: 'POST', body: { action: 'collective_intent', values: { objective: roomForm.objective, positions: [
      { stakeholder: 'Operator', priorities: [roomForm.operator], constraints: [], vote: roomForm.support },
      { stakeholder: 'Domain specialist', priorities: [roomForm.specialist], constraints: [], vote: roomForm.support },
      { stakeholder: 'Governor', priorities: [], constraints: [roomForm.governor], dissent: roomForm.dissent, vote: roomForm.support },
    ] } } })
    room.value = result.intent
    notice.value = 'Decision room synthesized and persisted for the organization.'
    record('completed')
  } catch (e) { fail(e) } finally { busy.value = '' }
}
async function simulateOutcome() {
  resetStatus('simulate')
  try {
    const result: any = await authed('/api/adaptive/evolution', { method: 'POST', body: { action: 'simulate_interface', objective: currentRecommendation.value } })
    simulation.value = result.simulation
    notice.value = 'A shadow interface twin projected the outcome without changing navigation or production behavior.'
    record('advanced')
  } catch (e) { fail(e) } finally { busy.value = '' }
}
async function compileMemory() {
  resetStatus('memory')
  try {
    const result: any = await authed('/api/constitution/action', { method: 'POST', body: { action: 'compile_memory', values: { objective: roomForm.objective } } })
    memory.value = result.memory
    notice.value = 'Organization intent, policies, outcomes, and incident lessons were compiled into governed guidance.'
    record('advanced')
  } catch (e) { fail(e) } finally { busy.value = '' }
}
async function runFailureTwin() {
  resetStatus('failure-twin')
  try {
    const route: any = shadow.value || await authed('/api/connectors/route-plan', { method: 'POST', body: { capability: props.domain, intent: `Continuity simulation for ${props.app}: ${currentRecommendation.value}` } })
    shadow.value = route
    failureTwin.value = { failed: route.selected, fallback: route.alternatives?.find((item: any) => item.connected) || route.alternatives?.[0] || null, permissions_preserved: true, execution: false }
    notice.value = failureTwin.value.fallback ? 'Failure simulated. A least-privilege fallback is available; no work executed.' : 'Failure simulated. No eligible fallback is currently ready; connect one before relying on continuity.'
    record('advanced')
  } catch (e) { fail(e) } finally { busy.value = '' }
}
async function queueSystemSync() {
  resetStatus('system-sync')
  try {
    const intent = `Synchronize the production ${props.capability} system for ${props.app}. Reconcile code tokens, reusable components, brand assets, motion behavior, derivatives, accessibility states, and connected design or content systems bidirectionally. Detect drift, preview every material change, preserve source ownership, and finish with independent verification and the normal release train.`
    const result: any = await authed('/api/tasks/intake', { method: 'POST', body: { intent, project_id: props.projectId || undefined } })
    queued.value = result.task
    notice.value = `System synchronization queued as ${result.task.slug}; Madeus will choose connected tools and request only missing access.`
    record('completed')
  } catch (e) { fail(e) } finally { busy.value = '' }
}
async function implementReconstructedJourney() {
  resetStatus('journey')
  try {
    const intent = `${currentRecommendation.value}\n\nReconstruct the complete current ${props.app} journey from observed behavior, identify every fragmented handoff, implement the proposed governed journey, and verify this outcome: ${expectedOutcome.value}. Preserve canonical navigation and produce a before/after preview, independent QA, accessibility evidence, rollback checkpoint, and normal verified release.`
    const result: any = await authed('/api/tasks/intake', { method: 'POST', body: { intent, project_id: props.projectId || undefined } })
    queued.value = result.task
    notice.value = `Journey implementation queued as ${result.task.slug}; route selection, QA, proof, and release remain automatic.`
    record('completed')
  } catch (e) { fail(e) } finally { busy.value = '' }
}
function exportPassport() {
  if (!proof.value || !import.meta.client) return
  const blob = new Blob([JSON.stringify(proof.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `madeus-proof-${proof.value.passport.id || Date.now()}.json`; link.click(); URL.revokeObjectURL(url)
  notice.value = 'Portable proof passport exported for offline review.'
}
async function createPassport() {
  resetStatus('proof')
  try {
    const result: any = await authed('/api/constitution/action', { method: 'POST', body: { action: 'proof', values: { action_type: `cade:${props.domain}:recommendation`, intent: `${props.app}: ${currentRecommendation.value}`, confidence: .9, reversibility: 'reversible', blast_radius: 'single' } } })
    proof.value = await authed(`/api/constitution/proof/${result.proof.id}`)
    notice.value = 'Signed proof passport created and verified offline against its receipt signature.'
    record('completed')
  } catch (e) { fail(e) } finally { busy.value = '' }
}
async function recordValue() {
  resetStatus('value')
  try {
    const result: any = await authed('/api/constitution/action', { method: 'POST', body: { action: 'causal_evidence', values: valueForm } })
    causal.value = result.evidence
    notice.value = 'Causal evidence recorded privately and linked to the organizational learning fabric.'
    record('completed')
  } catch (e) { fail(e) } finally { busy.value = '' }
}
async function optimize() {
  resetStatus('connectors')
  try { optimization.value = await authed('/api/connectors/optimize'); notice.value = 'Portfolio connectors rescored from realized reliability, quality, cost, access, and policy incidents.'; record('completed') }
  catch (e) { fail(e) } finally { busy.value = '' }
}
async function applyConnectorPolicy() {
  if (!optimization.value) return
  resetStatus('connector-policy')
  const preferred = optimization.value.recommendations.filter((item: any) => item.recommendation === 'prefer').map((item: any) => item.provider)
  const deprioritized = optimization.value.recommendations.filter((item: any) => item.recommendation === 'deprioritize').map((item: any) => item.provider)
  try {
    await authed('/api/constitution/action', { method: 'POST', body: { action: 'compile_policy', values: { source_text: `Prefer ${preferred.join(', ') || 'providers with verified outcomes'}. Require approval before using or restoring ${deprioritized.join(', ') || 'providers below the value threshold'}. Always require least-privilege connector scope and an execution proof.` } } })
    notice.value = 'Routing preference compiled and tested. It remains reviewable; credentials were not granted or revoked.'
    record('advanced')
  } catch (e) { fail(e) } finally { busy.value = '' }
}
function selectTab(tab: Tab) { active.value = tab; record('expanded'); if (tab === 'connectors' && !optimization.value) optimize() }
</script>

<template>
  <section class="cade-os" aria-labelledby="cade-os-title">
    <header class="cade-os__header">
      <div>
        <div class="cade-os__eyebrow">Outcome intelligence</div>
        <h3 id="cade-os-title">Understand the recommendation. Test it safely. Implement it with proof.</h3>
        <p>{{ guidanceCopy }}</p>
      </div>
      <div class="proficiency" :title="`Observed proficiency score: ${profile.score}/100`"><span>{{ profile.stage }}</span><i><b :style="{ width: `${profile.score}%` }" /></i><small>Interface depth adapts from observed use</small></div>
    </header>

    <nav class="cade-os__tabs" aria-label="Decision intelligence tools">
      <button v-for="tab in tabs" :key="tab.id" :aria-selected="active === tab.id" :class="{ active: active === tab.id }" @click="selectTab(tab.id)">{{ tab.label }}</button>
    </nav>

    <div v-if="notice" role="status" class="notice">{{ notice }}</div>
    <div v-if="error" role="alert" class="error">{{ error }}</div>

    <div v-if="active === 'replay'" class="panel replay">
      <div class="panel-copy"><span>Reconstructed journey</span><h4>{{ currentRecommendation }}</h4><p>Expected outcome: {{ expectedOutcome }}</p><button :disabled="!!busy" @click="implementReconstructedJourney">{{ busy === 'journey' ? 'Queuing…' : 'Implement reconstructed journey' }}</button></div>
      <div class="replay-stage">
        <div class="screen before"><header><b>Current journey</b><em>4 handoffs · observed friction</em></header><div class="skeleton"><i/><i/><i/><div><b v-for="n in 8" :key="n"/></div><footer><b/><b/><b/></footer></div></div>
        <div class="replay-arrow">→</div>
        <div class="screen after"><header><b>Executable proposal</b><em>1 governed flow</em></header><div class="guided"><span>1</span><div><b>One clear outcome</b><p>Context and defaults are selected automatically.</p><button>Continue with Madeus</button></div></div><small>Advanced controls appear only when useful. Proof is retained at every handoff.</small></div>
      </div>
    </div>

    <div v-else-if="active === 'shadow'" class="panel two-col">
      <div><span class="section-label">Outcome-level route inspector</span><h4>See why Madeus chose this route</h4><p>Madeus evaluates capability fit, available access, realized reliability, quality, cost, permissions, warranty, and policy risk. Vendor mechanics stay hidden until they help a decision.</p><button :disabled="!!busy" @click="runShadow">{{ busy === 'shadow' ? 'Explaining…' : 'Explain current best route' }}</button></div>
      <div v-if="shadow" class="route-list"><div class="route-why"><b>Why selected</b><p>{{ shadow.explanation.why_selected }}</p><small>Policy v{{ shadow.explanation.policy_version }} · permissions checked · receipt {{ shadow.receipt.id }}</small></div><article v-for="(item,index) in [shadow.selected,...shadow.alternatives].filter(Boolean)" :key="item.provider" :class="{ winner: index === 0 }"><div><b>{{ item.name }}</b><span>{{ index === 0 ? 'Best verified fit' : 'Eligible fallback' }}</span></div><strong>{{ item.score }}</strong><p>{{ item.explanation.slice(1,5).join(' · ') }}</p></article><button class="secondary" @click="useShadowWinner">Use this outcome; revalidate at execution</button></div><div v-else class="empty">Ask for an explanation to create a durable route receipt. Nothing will execute.</div>
    </div>

    <form v-else-if="active === 'room'" class="panel room" @submit.prevent="createRoom">
      <div class="room-heading"><span class="section-label">Persistent organization room</span><h4>Resolve tradeoffs before implementation</h4><p>Stakeholder positions are synthesized into one governed plan with conflicts and permission boundaries preserved.</p></div>
      <label class="wide">Shared objective<input v-model="roomForm.objective" required></label>
      <label>Operator priority<textarea v-model="roomForm.operator" rows="2"/></label><label>Specialist priority<textarea v-model="roomForm.specialist" rows="2"/></label><label>Governor constraint<textarea v-model="roomForm.governor" rows="2"/></label>
      <label class="wide">Recorded dissent<textarea v-model="roomForm.dissent" rows="2"/></label><label>Support for this direction · {{ roomForm.support }}%<input v-model.number="roomForm.support" type="range" min="0" max="100"></label>
      <div class="room-actions"><button :disabled="!!busy">{{ busy === 'room' ? 'Synthesizing…' : 'Synthesize signed decision' }}</button><button type="button" class="secondary" :disabled="!!busy" @click="compileMemory">{{ busy === 'memory' ? 'Compiling…' : 'Refresh organization memory' }}</button></div>
      <div v-if="room" class="room-result"><b>{{ room.decision }} · {{ room.status }}</b><span>{{ room.synthesized_plan.consensus.stakeholders }} perspectives · {{ room.conflicts.length }} detected conflicts</span><p>{{ room.synthesized_plan.plan?.summary || room.objective }}</p></div>
      <div v-if="memory" class="memory-result"><b>Intent memory ready</b><span>{{ memory.memory_graph.nodes.length }} governed signals · {{ memory.compiled_guidance.before_action.length }} pre-action checks</span><p>Future routes can now account for prior intent, policy, causal evidence, and incident lessons without copying private raw records.</p></div>
    </form>

    <div v-else-if="active === 'proof'" class="panel two-col">
      <div><span class="section-label">Portable, offline-verifiable artifact</span><h4>Signed proof passport</h4><p>Packages the decision, constitution tier, actor permissions, rollback plan, evidence digest, and hash-chained signed receipt for customers, boards, counsel, auditors, or regulators.</p><button :disabled="!!busy" @click="createPassport">{{ busy === 'proof' ? 'Signing…' : 'Create and verify passport' }}</button></div>
      <article v-if="proof" class="passport"><header><span>MADEUS PROOF</span><b :class="proof.verification.valid ? 'valid' : 'invalid'">{{ proof.verification.valid ? '✓ Signature valid' : 'Verification failed' }}</b></header><h5>{{ proof.passport.action_type }}</h5><p>{{ proof.passport.intent }}</p><dl><div><dt>Decision</dt><dd>{{ proof.passport.prediction.decision }}</dd></div><div><dt>Tier</dt><dd>{{ proof.passport.prediction.tier }}</dd></div><div><dt>Scopes</dt><dd>{{ proof.passport.permissions.requested_scopes.join(', ') }}</dd></div><div><dt>Created</dt><dd>{{ new Date(proof.passport.created_at).toLocaleString() }}</dd></div></dl><code>{{ proof.passport.digest }}</code><button class="export" @click="exportPassport">Export verified JSON</button></article><div v-else class="empty">Create a passport to pin the exact decision and prove its signature.</div>
    </div>

    <form v-else-if="active === 'value'" class="panel value" @submit.prevent="recordValue">
      <div class="wide"><span class="section-label">Project-aware outcome simulation</span><h4>Forecast first. Then prove what actually happened.</h4><p>The interface twin projects completion impact from observed behavior without changing production. Treatment and control evidence then measures the realized outcome; raw user records remain private.</p><button type="button" class="secondary simulate-button" :disabled="!!busy" @click="simulateOutcome">{{ busy === 'simulate' ? 'Simulating…' : 'Run zero-impact interface twin' }}</button></div>
      <label class="wide">Intervention<input v-model="valueForm.intervention" required></label><label>Segment<input v-model="valueForm.segment"></label><label>Treatment result<input v-model.number="valueForm.treatment_mean" type="number" step="0.1"></label><label>Control result<input v-model.number="valueForm.control_mean" type="number" step="0.1"></label><label>Sample size<input v-model.number="valueForm.sample_size" type="number" min="2"></label><button :disabled="!!busy">{{ busy === 'value' ? 'Recording…' : 'Record causal evidence' }}</button>
      <div v-if="causal" class="causal-result"><strong>{{ causal.estimated_effect.absolute > 0 ? '+' : '' }}{{ causal.estimated_effect.absolute.toFixed(1) }}</strong><span>estimated effect</span><b>{{ Math.round(causal.confidence * 100) }}% evidence confidence</b><small>{{ causal.sharing_status }} · cohort aggregate · raw records withheld</small></div>
      <div v-if="simulation" class="simulation-result"><b>Shadow forecast</b><strong>+{{ Math.round(simulation.projected_outcome.expected_completion_lift * 100) }}%</strong><span>projected completion</span><small>{{ Math.round(simulation.projected_outcome.confidence * 100) }}% confidence · {{ Math.round(simulation.projected_outcome.time_to_action_reduction * 100) }}% faster time to action · zero navigation drift</small></div>
    </form>

    <div v-else-if="active === 'connectors'" class="panel connector-panel">
      <div class="connector-head"><div><span class="section-label">Connector reliability twin</span><h4>Know the fallback before a provider fails</h4><p>Simulate provider unavailability, permission expiry, and degraded quality against live route eligibility. Nothing executes and access never expands silently.</p></div><div><button :disabled="!!busy" @click="runFailureTwin">{{ busy === 'failure-twin' ? 'Simulating…' : 'Simulate primary failure' }}</button><button class="secondary" :disabled="!!busy" @click="optimize">Refresh realized value</button><button v-if="optimization" class="secondary" :disabled="!!busy" @click="applyConnectorPolicy">Compile preference</button></div></div>
      <div v-if="failureTwin" class="failure-result"><div><span>Unavailable primary</span><b>{{ failureTwin.failed?.name || 'No primary route' }}</b></div><i>→</i><div><span>Continuity route</span><b>{{ failureTwin.fallback?.name || 'Connection required' }}</b><small v-if="failureTwin.fallback">{{ Math.round(failureTwin.fallback.reliability*100) }}% realized reliability · score {{ failureTwin.fallback.score }}</small></div><em>{{ failureTwin.execution ? 'Executed' : 'Simulation only' }}</em></div>
      <div v-if="optimization" class="optimizer-grid"><article v-for="item in optimization.recommendations.slice(0,8)" :key="item.provider"><header><b>{{ item.provider }}</b><span :class="item.recommendation">{{ item.recommendation }}</span></header><strong>{{ item.score }}</strong><i><b :style="{ width: `${item.score}%` }"/></i><p>{{ item.reason }}</p><small>{{ Math.round(item.reliability*100) }}% reliable · {{ Math.round(item.averageQuality*100) }}% quality · ${{ item.averageCostUsd.toFixed(3) }}/run</small></article></div><div v-else class="empty">Loading realized connector value…</div>
    </div>

    <div v-else class="panel sync-panel">
      <div><span class="section-label">Bidirectional capability synchronization</span><h4>Keep production, reusable systems, and specialist tools aligned</h4><p>Madeus detects drift across production code, tokens, reusable components, brand assets, motion, accessibility states, derivative formats, and connected tools. It chooses the appropriate connector automatically and asks only when access is missing.</p><div class="sync-actions"><button :disabled="!!busy" @click="queueSystemSync">{{ busy === 'system-sync' ? 'Queuing…' : 'Audit + synchronize system' }}</button><button class="secondary" @click="navigateTo('/connectors')">Manage optional connections</button></div><div v-if="queued" class="sync-proof"><b>✓ Queued {{ queued.slug }}</b><span>Drift audit → preview → independent verification → governed release</span></div></div>
      <div class="sync-map"><article><span>Production truth</span><b>Code · tokens · components</b><small>Verified before any write</small></article><i>⇄</i><article><span>Creative systems</span><b>Design · brand · motion</b><small>Source ownership preserved</small></article><i>⇄</i><article><span>Derivatives</span><b>Channels · formats · locales</b><small>Generated from approved masters</small></article></div>
    </div>
  </section>
</template>

<style scoped>
.cade-os{overflow:hidden;border:1px solid #dedede;border-radius:18px;background:#fff;color:#171717;box-shadow:0 20px 60px #11111108}.cade-os__header{display:flex;align-items:flex-start;justify-content:space-between;gap:30px;padding:24px 26px;background:radial-gradient(circle at 88% -30%,#dcd7ff 0,transparent 38%),linear-gradient(110deg,#fff,#fafafa)}.cade-os__eyebrow,.section-label{font-size:9px;font-weight:750;letter-spacing:.16em;text-transform:uppercase;color:#6252cf}.cade-os h3{margin-top:7px;font-size:22px;letter-spacing:-.035em}.cade-os__header p,.panel p{margin-top:7px;max-width:720px;font-size:11px;line-height:1.6;color:#686868}.proficiency{width:180px;padding:11px;border:1px solid #e3e0f8;border-radius:12px;background:#ffffffc7}.proficiency span{font-size:10px;font-weight:700;text-transform:capitalize}.proficiency i,.optimizer-grid i{display:block;height:4px;margin:7px 0;border-radius:99px;background:#ebe9f4;overflow:hidden}.proficiency i b,.optimizer-grid i b{display:block;height:100%;background:#6557d8}.proficiency small{display:block;font-size:8px;color:#8a8a8a}.cade-os__tabs{display:flex;gap:2px;overflow-x:auto;padding:0 18px;border-top:1px solid #eee;border-bottom:1px solid #e5e5e5;background:#fafafa}.cade-os__tabs button{white-space:nowrap;border:0;border-bottom:2px solid transparent;padding:13px 10px 11px;background:none;font-size:10px;color:#717171}.cade-os__tabs button.active{border-color:#111;color:#111;font-weight:700}.notice,.error{margin:12px 20px 0;padding:9px 11px;border-radius:8px;font-size:10px}.notice{background:#eef9f2;color:#246f43}.error{background:#fff0f0;color:#a63838}.panel{min-height:310px;padding:24px 26px}.panel h4{margin-top:5px;font-size:17px;letter-spacing:-.025em}.panel button{border:0;border-radius:9px;padding:10px 13px;background:#181818;color:#fff;font-size:10px;font-weight:650}.panel button:disabled{opacity:.5}.panel button.secondary{border:1px solid #ddd;background:#fff;color:#555}.panel-copy{display:flex;align-items:center;gap:12px}.panel-copy>span{font-size:9px;text-transform:uppercase;color:#796cd6}.panel-copy h4{flex:1;margin:0}.panel-copy p{margin:0}.replay-stage{display:grid;grid-template-columns:1fr 40px 1fr;align-items:center;margin-top:20px}.replay-arrow{text-align:center;color:#8b80d7}.screen{overflow:hidden;min-height:190px;border:1px solid #ddd;border-radius:13px;background:#fafafa}.screen>header{display:flex;justify-content:space-between;padding:9px 12px;border-bottom:1px solid #eee;font-size:9px}.screen header em{font-style:normal;color:#999}.before{border-color:#eccaca}.after{border-color:#bcdcc7}.skeleton{padding:18px}.skeleton>i{display:block;height:8px;margin:7px 0;border-radius:99px;background:#ddd}.skeleton>i:nth-child(1){width:45%;height:14px}.skeleton>i:nth-child(3){width:70%}.skeleton>div{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-top:15px}.skeleton>div b{height:34px;border:1px solid #ddd;border-radius:5px;background:#fff}.skeleton footer{display:flex;gap:8px;margin-top:14px}.skeleton footer b{flex:1;height:28px;border-radius:6px;background:#d5d5d5}.guided{display:flex;gap:10px;margin:20px}.guided>span{display:grid;width:25px;height:25px;place-items:center;border-radius:50%;background:#171717;color:#fff;font-size:9px}.guided>div{flex:1;padding:14px;border:1px solid #d7d2f6;border-radius:10px;background:#fff}.guided b{font-size:11px}.guided p{font-size:9px}.guided button{margin-top:13px;padding:8px 10px;background:#6557d8}.after>small{display:block;margin:0 20px;color:#999;font-size:8px}.two-col{display:grid;grid-template-columns:minmax(260px,.7fr) 1.3fr;gap:30px}.two-col>div:first-child>button{margin-top:18px}.empty{display:grid;min-height:160px;place-items:center;border:1px dashed #d7d7d7;border-radius:13px;color:#999;font-size:10px}.route-list{display:grid;gap:8px}.route-list article{display:grid;grid-template-columns:1fr auto;gap:5px;padding:11px;border:1px solid #e5e5e5;border-radius:10px}.route-list article.winner{border-color:#bfb7f4;background:#faf9ff}.route-list article div b,.route-list article div span{display:block}.route-list article div b{font-size:11px}.route-list article div span{margin-top:2px;font-size:8px;color:#7769d5}.route-list article>strong{font-size:20px}.route-list article p{grid-column:1/-1;margin:0;font-size:8px}.room,.value{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.room-heading,.wide{grid-column:1/-1}.panel label{font-size:9px;font-weight:650;color:#555}.panel input,.panel textarea{display:block;width:100%;margin-top:5px;border:1px solid #ddd;border-radius:8px;padding:9px;font:inherit;font-size:10px;outline:none}.panel input:focus,.panel textarea:focus{border-color:#8477dc;box-shadow:0 0 0 3px #eeeaff}.room>button,.value>button{align-self:end}.room-result{grid-column:1/-1;padding:13px;border:1px solid #c7e5d1;border-radius:10px;background:#f3fbf6}.room-result b,.room-result span{display:block;font-size:10px}.passport{border:1px solid #bbb1ee;border-radius:14px;background:linear-gradient(145deg,#fff,#f7f5ff);padding:18px}.passport header{display:flex;justify-content:space-between;font-size:8px;letter-spacing:.12em}.passport .valid{color:#248650}.passport .invalid{color:#b63838}.passport h5{margin-top:18px;font-size:13px}.passport dl{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:13px 0}.passport dt{font-size:8px;color:#999}.passport dd{font-size:9px;margin:2px 0 0}.passport code{display:block;overflow:hidden;padding:8px;border-radius:6px;background:#111;color:#b9f8cb;font-size:7px;text-overflow:ellipsis}.value{grid-template-columns:repeat(4,1fr)}.causal-result{grid-column:1/-1;display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:7px;padding:14px;border:1px solid #c6e5d0;border-radius:11px;background:#f4fbf6}.causal-result strong{grid-row:1/3;font-size:28px}.causal-result span,.causal-result b{font-size:10px}.causal-result small{font-size:8px;color:#777}.connector-head{display:flex;justify-content:space-between;gap:20px}.connector-head>div:last-child{display:flex;gap:8px;align-items:start}.optimizer-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-top:18px}.optimizer-grid article{padding:12px;border:1px solid #e2e2e2;border-radius:11px}.optimizer-grid header{display:flex;justify-content:space-between;gap:5px}.optimizer-grid header b{font-size:10px}.optimizer-grid header span{border-radius:99px;padding:3px 5px;background:#eee;font-size:7px;text-transform:uppercase}.optimizer-grid header span.prefer{background:#e6f7ec;color:#27764a}.optimizer-grid header span.deprioritize{background:#fff0f0;color:#a73e3e}.optimizer-grid header span.activate{background:#eeeaff;color:#5a4bc0}.optimizer-grid article>strong{display:block;margin-top:10px;font-size:22px}.optimizer-grid p{min-height:42px;font-size:8px}.optimizer-grid small{font-size:7px;color:#999}.market{display:grid;grid-template-columns:1fr 1fr;gap:28px}.market-create label{display:block;margin-top:12px}.market-create>div{display:flex;gap:8px;margin-top:12px}.market-list{display:grid;align-content:start;gap:8px}.market-list article{display:grid;grid-template-columns:1fr auto;gap:5px;padding:12px;border:1px solid #e2e2e2;border-radius:11px}.market-list article div b,.market-list article div span{display:block;font-size:10px}.market-list article div span,.market-list article small{font-size:8px;color:#999}.market-list article p,.market-list article small{grid-column:1}.market-list article button{grid-column:2;grid-row:1/4;align-self:center}@media(max-width:900px){.cade-os__header,.panel-copy,.connector-head{flex-direction:column}.proficiency{width:100%}.two-col,.market{grid-template-columns:1fr}.optimizer-grid{grid-template-columns:repeat(2,1fr)}.room,.value{grid-template-columns:1fr 1fr}.room-heading,.wide,.room-result,.causal-result{grid-column:1/-1}.replay-stage{grid-template-columns:1fr}.replay-arrow{transform:rotate(90deg);padding:8px}}@media(max-width:560px){.cade-os__header,.panel{padding:20px}.optimizer-grid,.room,.value{grid-template-columns:1fr}.room label,.value label,.room>button,.value>button{grid-column:1}.causal-result{grid-template-columns:1fr}.causal-result strong{grid-row:auto}.market-create>div,.connector-head>div:last-child{flex-direction:column}.connector-head button{width:100%}}
.cade-os__header{background:#f3f6f2}.cade-os__eyebrow,.section-label,.panel-copy>span{color:#194c36}.proficiency{border-color:#d7e1da}.proficiency i,.optimizer-grid i{background:#dde5df}.proficiency i b,.optimizer-grid i b{background:#194c36}.guided>div{border-color:#cddbd1}.guided button{background:#194c36}.route-list article.winner{border-color:#9ebba8;background:#f4f8f4}.route-list article div span{color:#35694f}.panel input:focus,.panel textarea:focus{border-color:#57856b;box-shadow:0 0 0 3px #e5efe8}.passport{border-color:#adc3b5;background:#f4f8f4}.optimizer-grid header span.activate{background:#e7f0e9;color:#194c36}
.route-why{padding:12px;border-radius:10px;background:#edf3ee}.route-why b{font-size:9px;text-transform:uppercase;letter-spacing:.12em;color:#194c36}.route-why p{margin:4px 0}.route-why small{font-size:8px;color:#718078}.room-actions{display:flex;align-items:end;gap:7px}.memory-result{grid-column:1/-1;padding:13px;border:1px solid #cbd9cf;border-radius:10px;background:#f5f8f5}.memory-result b,.memory-result span{display:block;font-size:10px}.passport .export{width:100%;margin-top:10px;border:1px solid #c8d6cc;background:#fff;color:#194c36}.simulate-button{margin-top:10px}.simulation-result{grid-column:1/-1;display:grid;grid-template-columns:auto auto 1fr;align-items:center;gap:7px;padding:14px;border:1px solid #bfd4c5;border-radius:11px;background:#edf3ee}.simulation-result b{font-size:9px;text-transform:uppercase;letter-spacing:.12em}.simulation-result strong{font-size:24px}.simulation-result span{font-size:10px}.simulation-result small{grid-column:1/-1;color:#637269;font-size:8px}.failure-result{display:grid;grid-template-columns:1fr auto 1fr auto;align-items:center;gap:14px;margin-top:16px;padding:14px;border:1px solid #c8d6cc;border-radius:12px;background:#f5f8f5}.failure-result div span,.failure-result div b,.failure-result div small{display:block}.failure-result div span{font-size:8px;text-transform:uppercase;color:#77827b}.failure-result div b{margin-top:3px;font-size:11px}.failure-result div small{margin-top:3px;color:#758078;font-size:8px}.failure-result i{color:#194c36;font-style:normal}.failure-result em{border-radius:99px;padding:5px 7px;background:#fff;color:#5e6b62;font-size:8px;font-style:normal}.sync-panel{display:grid;grid-template-columns:.8fr 1.2fr;gap:30px}.sync-actions{display:flex;gap:8px;margin-top:18px}.sync-proof{margin-top:12px;padding:10px;border-radius:9px;background:#edf3ee}.sync-proof b,.sync-proof span{display:block;font-size:9px}.sync-proof span{margin-top:3px;color:#657269}.sync-map{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;align-items:center;gap:8px}.sync-map article{min-height:125px;padding:15px;border:1px solid #d9e1db;border-radius:12px;background:#f8faf8}.sync-map span,.sync-map b,.sync-map small{display:block}.sync-map span{font-size:8px;text-transform:uppercase;color:#617568}.sync-map b{margin-top:15px;font-size:11px}.sync-map small{margin-top:8px;color:#89918c;font-size:8px}.sync-map i{color:#194c36;font-style:normal}@media(max-width:900px){.sync-panel{grid-template-columns:1fr}.sync-map{grid-template-columns:1fr}.sync-map i{transform:rotate(90deg);text-align:center}}@media(max-width:560px){.room-actions,.sync-actions{flex-direction:column;align-items:stretch}.failure-result{grid-template-columns:1fr}.failure-result i{transform:rotate(90deg)}.simulation-result{grid-template-columns:1fr}}
</style>
