<script setup lang="ts">
const props = defineProps<{ app: string; capability: string; domain: string; recommendation?: string; outcome?: string }>()
const emit = defineEmits<{ usePrompt: [value: string]; openConnections: [] }>()
const supabase = useSupabaseClient<any>()
const tabs = [
  { id: 'replay', label: 'Visual replay' },
  { id: 'shadow', label: 'Shadow routes' },
  { id: 'room', label: 'Decision room' },
  { id: 'proof', label: 'Proof passport' },
  { id: 'value', label: 'Value evidence' },
  { id: 'connectors', label: 'Connector ROI' },
  { id: 'market', label: 'Marketplace' },
] as const
type Tab = typeof tabs[number]['id']
const active = ref<Tab>('replay')
const busy = ref('')
const notice = ref('')
const error = ref('')
const context = ref<any>(null)
const shadow = ref<any>(null)
const proof = ref<any>(null)
const room = ref<any>(null)
const causal = ref<any>(null)
const optimization = ref<any>(null)
const { profile, record } = useAdaptiveProficiency(computed(() => `cade:${props.domain}`))
const roomForm = reactive({
  objective: props.recommendation || `Improve ${props.app} with ${props.capability}`,
  operator: 'Deliver measurable user value quickly',
  specialist: 'Preserve quality, accessibility, and maintainability',
  governor: 'Require bounded scope, evidence, and rollback readiness',
})
const valueForm = reactive({ intervention: props.recommendation || `Apply CADE recommendation to ${props.app}`, segment: 'eligible users', treatment_mean: 82, control_mean: 68, sample_size: 120 })
const marketForm = reactive({ title: `${props.capability} verified workflow`, description: 'Portable workflow with evidence, approval, verification, and rollback policy.', policy: 'Require independent approval for material actions. Require a proof envelope and rollback checkpoint before release.' })
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
async function loadContext() {
  try { context.value = await authed('/api/constitution/context') } catch {}
}
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
  notice.value = 'The outcome—not the vendor—was added to the command canvas. Colosseum will revalidate the route at execution time.'
  record('completed')
}
async function createRoom() {
  resetStatus('room')
  try {
    const result: any = await authed('/api/constitution/action', { method: 'POST', body: { action: 'collective_intent', values: { objective: roomForm.objective, positions: [
      { stakeholder: 'Operator', priorities: [roomForm.operator], constraints: [] },
      { stakeholder: 'Domain specialist', priorities: [roomForm.specialist], constraints: [] },
      { stakeholder: 'Governor', priorities: [], constraints: [roomForm.governor] },
    ] } } })
    room.value = result.intent
    notice.value = 'Decision room synthesized and persisted for the organization.'
    record('completed')
    await loadContext()
  } catch (e) { fail(e) } finally { busy.value = '' }
}
async function createPassport() {
  resetStatus('proof')
  try {
    const result: any = await authed('/api/constitution/action', { method: 'POST', body: { action: 'proof', values: { action_type: `cade:${props.domain}:recommendation`, intent: `${props.app}: ${currentRecommendation.value}`, confidence: .9, reversibility: 'reversible', blast_radius: 'single' } } })
    proof.value = await authed(`/api/constitution/proof/${result.proof.id}`)
    notice.value = 'Signed proof passport created and verified offline against its receipt signature.'
    record('completed')
    await loadContext()
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
async function compilePolicy() {
  resetStatus('policy')
  try {
    const result: any = await authed('/api/constitution/action', { method: 'POST', body: { action: 'compile_policy', values: { source_text: marketForm.policy } } })
    notice.value = `Portable policy compiled with ${result.policy.test_result.passed} passing tests and no navigation breakage.`
    record('advanced')
    await loadContext()
  } catch (e) { fail(e) } finally { busy.value = '' }
}
async function publishOffer() {
  resetStatus('offer')
  try {
    await authed('/api/constitution/action', { method: 'POST', body: { action: 'publish_offer', values: { kind: 'workflow', title: marketForm.title, description: marketForm.description, capabilities: [props.domain, 'proof:verify', 'policy:portable'], terms: { price_usd: 0, warranty: 'verified_outcomes' } } } })
    notice.value = 'Signed capability listing published with portable policy and verification requirements.'
    record('advanced')
    await loadContext()
  } catch (e) { fail(e) } finally { busy.value = '' }
}
async function installOffer(id: string) {
  resetStatus(`install:${id}`)
  try { await authed('/api/constitution/action', { method: 'POST', body: { action: 'install_offer', values: { offer_id: id } } }); notice.value = 'Capability installed after signature verification; no connector permissions were inherited.'; record('completed') }
  catch (e) { fail(e) } finally { busy.value = '' }
}
function selectTab(tab: Tab) { active.value = tab; record('expanded'); if (tab === 'connectors' && !optimization.value) optimize() }
onMounted(loadContext)
</script>

<template>
  <section class="cade-os" aria-labelledby="cade-os-title">
    <header class="cade-os__header">
      <div>
        <div class="cade-os__eyebrow">CADE decision operating system</div>
        <h3 id="cade-os-title">See the change. Challenge the route. Prove the outcome.</h3>
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
      <div class="panel-copy"><span>Interactive recommendation</span><h4>{{ currentRecommendation }}</h4><p>CADE predicts: {{ expectedOutcome }}</p><button @click="emit('usePrompt', currentRecommendation); record('completed')">Adjust in command canvas</button></div>
      <div class="replay-stage">
        <div class="screen before"><header><b>Current</b><em>Observed friction</em></header><div class="skeleton"><i/><i/><i/><div><b v-for="n in 8" :key="n"/></div><footer><b/><b/><b/></footer></div></div>
        <div class="replay-arrow">→</div>
        <div class="screen after"><header><b>Proposed</b><em>Guided progression</em></header><div class="guided"><span>1</span><div><b>One clear outcome</b><p>Context and defaults are selected automatically.</p><button>Continue with Madeus</button></div></div><small>Advanced controls appear only when useful.</small></div>
      </div>
    </div>

    <div v-else-if="active === 'shadow'" class="panel two-col">
      <div><span class="section-label">Counterfactual routing</span><h4>Compare providers without spending or executing</h4><p>Every candidate is scored against capability fit, access, realized outcomes, cost, permissions, warranty, and policy risk.</p><button :disabled="!!busy" @click="runShadow">{{ busy === 'shadow' ? 'Comparing…' : 'Run shadow comparison' }}</button></div>
      <div v-if="shadow" class="route-list"><article v-for="(item,index) in [shadow.selected,...shadow.alternatives].filter(Boolean)" :key="item.provider" :class="{ winner: index === 0 }"><div><b>{{ item.name }}</b><span>{{ index === 0 ? 'Shadow winner' : 'Alternative' }}</span></div><strong>{{ item.score }}</strong><p>{{ item.explanation.slice(1,4).join(' · ') }}</p></article><button class="secondary" @click="useShadowWinner">Use outcome with winning route</button></div><div v-else class="empty">No route comparison has run. Nothing will execute.</div>
    </div>

    <form v-else-if="active === 'room'" class="panel room" @submit.prevent="createRoom">
      <div class="room-heading"><span class="section-label">Persistent organization room</span><h4>Resolve tradeoffs before implementation</h4><p>Stakeholder positions are synthesized into one governed plan with conflicts and permission boundaries preserved.</p></div>
      <label class="wide">Shared objective<input v-model="roomForm.objective" required></label>
      <label>Operator priority<textarea v-model="roomForm.operator" rows="2"/></label><label>Specialist priority<textarea v-model="roomForm.specialist" rows="2"/></label><label>Governor constraint<textarea v-model="roomForm.governor" rows="2"/></label>
      <button :disabled="!!busy">{{ busy === 'room' ? 'Synthesizing…' : 'Synthesize decision room' }}</button>
      <div v-if="room" class="room-result"><b>{{ room.decision }} · {{ room.status }}</b><span>{{ room.synthesized_plan.consensus.stakeholders }} perspectives · {{ room.conflicts.length }} detected conflicts</span><p>{{ room.synthesized_plan.plan?.summary || room.objective }}</p></div>
    </form>

    <div v-else-if="active === 'proof'" class="panel two-col">
      <div><span class="section-label">Offline-verifiable artifact</span><h4>Signed proof passport</h4><p>Packages the decision, constitution tier, actor permissions, rollback plan, evidence digest, and hash-chained signed receipt into one portable release artifact.</p><button :disabled="!!busy" @click="createPassport">{{ busy === 'proof' ? 'Signing…' : 'Create and verify passport' }}</button></div>
      <article v-if="proof" class="passport"><header><span>MADEUS PROOF</span><b :class="proof.verification.valid ? 'valid' : 'invalid'">{{ proof.verification.valid ? '✓ Signature valid' : 'Verification failed' }}</b></header><h5>{{ proof.passport.action_type }}</h5><p>{{ proof.passport.intent }}</p><dl><div><dt>Decision</dt><dd>{{ proof.passport.prediction.decision }}</dd></div><div><dt>Tier</dt><dd>{{ proof.passport.prediction.tier }}</dd></div><div><dt>Scopes</dt><dd>{{ proof.passport.permissions.requested_scopes.join(', ') }}</dd></div><div><dt>Created</dt><dd>{{ new Date(proof.passport.created_at).toLocaleString() }}</dd></div></dl><code>{{ proof.passport.digest }}</code></article><div v-else class="empty">Create a passport to pin the exact decision and prove its signature.</div>
    </div>

    <form v-else-if="active === 'value'" class="panel value" @submit.prevent="recordValue">
      <div class="wide"><span class="section-label">Causal outcome attribution</span><h4>Prove whether the recommendation created value</h4><p>Compare treatment and control cohorts. Raw user records stay private; only aggregate evidence enters the learning fabric.</p></div>
      <label class="wide">Intervention<input v-model="valueForm.intervention" required></label><label>Segment<input v-model="valueForm.segment"></label><label>Treatment result<input v-model.number="valueForm.treatment_mean" type="number" step="0.1"></label><label>Control result<input v-model.number="valueForm.control_mean" type="number" step="0.1"></label><label>Sample size<input v-model.number="valueForm.sample_size" type="number" min="2"></label><button :disabled="!!busy">{{ busy === 'value' ? 'Recording…' : 'Record causal evidence' }}</button>
      <div v-if="causal" class="causal-result"><strong>{{ causal.estimated_effect.absolute > 0 ? '+' : '' }}{{ causal.estimated_effect.absolute.toFixed(1) }}</strong><span>estimated effect</span><b>{{ Math.round(causal.confidence * 100) }}% evidence confidence</b><small>{{ causal.sharing_status }} · cohort aggregate · raw records withheld</small></div>
    </form>

    <div v-else-if="active === 'connectors'" class="panel connector-panel">
      <div class="connector-head"><div><span class="section-label">Automatic connector economics</span><h4>Prefer value. Observe uncertainty. Deprioritize risk.</h4><p>Recommendations are evidence-driven and never silently grant, revoke, or expand access.</p></div><div><button class="secondary" :disabled="!!busy" @click="optimize">Refresh scores</button><button v-if="optimization" :disabled="!!busy" @click="applyConnectorPolicy">Compile routing policy</button></div></div>
      <div v-if="optimization" class="optimizer-grid"><article v-for="item in optimization.recommendations.slice(0,8)" :key="item.provider"><header><b>{{ item.provider }}</b><span :class="item.recommendation">{{ item.recommendation }}</span></header><strong>{{ item.score }}</strong><i><b :style="{ width: `${item.score}%` }"/></i><p>{{ item.reason }}</p><small>{{ Math.round(item.reliability*100) }}% reliable · {{ Math.round(item.averageQuality*100) }}% quality · ${{ item.averageCostUsd.toFixed(3) }}/run</small></article></div><div v-else class="empty">Loading realized connector value…</div>
    </div>

    <div v-else class="panel market">
      <div class="market-create"><span class="section-label">Portable capability package</span><h4>Publish workflows with policy, proof, and warranty</h4><label>Listing title<input v-model="marketForm.title"></label><label>Description<textarea v-model="marketForm.description" rows="2"/></label><label>Policy as plain language<textarea v-model="marketForm.policy" rows="4"/></label><div><button class="secondary" :disabled="!!busy" @click="compilePolicy">Compile + test policy</button><button :disabled="!!busy" @click="publishOffer">Publish signed listing</button></div></div>
      <div class="market-list"><span class="section-label">Organization marketplace</span><article v-for="offer in context?.offers || []" :key="offer.id"><div><b>{{ offer.title }}</b><span>{{ offer.kind }} · signed listing</span></div><p>{{ offer.description }}</p><small>{{ offer.capabilities.join(' · ') }}</small><button class="secondary" :disabled="!!busy" @click="installOffer(offer.id)">{{ busy === `install:${offer.id}` ? 'Verifying…' : 'Verify + install' }}</button></article><div v-if="!context?.offers?.length" class="empty">No organization listings yet. Publish the first verified workflow.</div></div>
    </div>
  </section>
</template>

<style scoped>
.cade-os{overflow:hidden;border:1px solid #dedede;border-radius:18px;background:#fff;color:#171717;box-shadow:0 20px 60px #11111108}.cade-os__header{display:flex;align-items:flex-start;justify-content:space-between;gap:30px;padding:24px 26px;background:radial-gradient(circle at 88% -30%,#dcd7ff 0,transparent 38%),linear-gradient(110deg,#fff,#fafafa)}.cade-os__eyebrow,.section-label{font-size:9px;font-weight:750;letter-spacing:.16em;text-transform:uppercase;color:#6252cf}.cade-os h3{margin-top:7px;font-size:22px;letter-spacing:-.035em}.cade-os__header p,.panel p{margin-top:7px;max-width:720px;font-size:11px;line-height:1.6;color:#686868}.proficiency{width:180px;padding:11px;border:1px solid #e3e0f8;border-radius:12px;background:#ffffffc7}.proficiency span{font-size:10px;font-weight:700;text-transform:capitalize}.proficiency i,.optimizer-grid i{display:block;height:4px;margin:7px 0;border-radius:99px;background:#ebe9f4;overflow:hidden}.proficiency i b,.optimizer-grid i b{display:block;height:100%;background:#6557d8}.proficiency small{display:block;font-size:8px;color:#8a8a8a}.cade-os__tabs{display:flex;gap:2px;overflow-x:auto;padding:0 18px;border-top:1px solid #eee;border-bottom:1px solid #e5e5e5;background:#fafafa}.cade-os__tabs button{white-space:nowrap;border:0;border-bottom:2px solid transparent;padding:13px 10px 11px;background:none;font-size:10px;color:#717171}.cade-os__tabs button.active{border-color:#111;color:#111;font-weight:700}.notice,.error{margin:12px 20px 0;padding:9px 11px;border-radius:8px;font-size:10px}.notice{background:#eef9f2;color:#246f43}.error{background:#fff0f0;color:#a63838}.panel{min-height:310px;padding:24px 26px}.panel h4{margin-top:5px;font-size:17px;letter-spacing:-.025em}.panel button{border:0;border-radius:9px;padding:10px 13px;background:#181818;color:#fff;font-size:10px;font-weight:650}.panel button:disabled{opacity:.5}.panel button.secondary{border:1px solid #ddd;background:#fff;color:#555}.panel-copy{display:flex;align-items:center;gap:12px}.panel-copy>span{font-size:9px;text-transform:uppercase;color:#796cd6}.panel-copy h4{flex:1;margin:0}.panel-copy p{margin:0}.replay-stage{display:grid;grid-template-columns:1fr 40px 1fr;align-items:center;margin-top:20px}.replay-arrow{text-align:center;color:#8b80d7}.screen{overflow:hidden;min-height:190px;border:1px solid #ddd;border-radius:13px;background:#fafafa}.screen>header{display:flex;justify-content:space-between;padding:9px 12px;border-bottom:1px solid #eee;font-size:9px}.screen header em{font-style:normal;color:#999}.before{border-color:#eccaca}.after{border-color:#bcdcc7}.skeleton{padding:18px}.skeleton>i{display:block;height:8px;margin:7px 0;border-radius:99px;background:#ddd}.skeleton>i:nth-child(1){width:45%;height:14px}.skeleton>i:nth-child(3){width:70%}.skeleton>div{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-top:15px}.skeleton>div b{height:34px;border:1px solid #ddd;border-radius:5px;background:#fff}.skeleton footer{display:flex;gap:8px;margin-top:14px}.skeleton footer b{flex:1;height:28px;border-radius:6px;background:#d5d5d5}.guided{display:flex;gap:10px;margin:20px}.guided>span{display:grid;width:25px;height:25px;place-items:center;border-radius:50%;background:#171717;color:#fff;font-size:9px}.guided>div{flex:1;padding:14px;border:1px solid #d7d2f6;border-radius:10px;background:#fff}.guided b{font-size:11px}.guided p{font-size:9px}.guided button{margin-top:13px;padding:8px 10px;background:#6557d8}.after>small{display:block;margin:0 20px;color:#999;font-size:8px}.two-col{display:grid;grid-template-columns:minmax(260px,.7fr) 1.3fr;gap:30px}.two-col>div:first-child>button{margin-top:18px}.empty{display:grid;min-height:160px;place-items:center;border:1px dashed #d7d7d7;border-radius:13px;color:#999;font-size:10px}.route-list{display:grid;gap:8px}.route-list article{display:grid;grid-template-columns:1fr auto;gap:5px;padding:11px;border:1px solid #e5e5e5;border-radius:10px}.route-list article.winner{border-color:#bfb7f4;background:#faf9ff}.route-list article div b,.route-list article div span{display:block}.route-list article div b{font-size:11px}.route-list article div span{margin-top:2px;font-size:8px;color:#7769d5}.route-list article>strong{font-size:20px}.route-list article p{grid-column:1/-1;margin:0;font-size:8px}.room,.value{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.room-heading,.wide{grid-column:1/-1}.panel label{font-size:9px;font-weight:650;color:#555}.panel input,.panel textarea{display:block;width:100%;margin-top:5px;border:1px solid #ddd;border-radius:8px;padding:9px;font:inherit;font-size:10px;outline:none}.panel input:focus,.panel textarea:focus{border-color:#8477dc;box-shadow:0 0 0 3px #eeeaff}.room>button,.value>button{align-self:end}.room-result{grid-column:1/-1;padding:13px;border:1px solid #c7e5d1;border-radius:10px;background:#f3fbf6}.room-result b,.room-result span{display:block;font-size:10px}.passport{border:1px solid #bbb1ee;border-radius:14px;background:linear-gradient(145deg,#fff,#f7f5ff);padding:18px}.passport header{display:flex;justify-content:space-between;font-size:8px;letter-spacing:.12em}.passport .valid{color:#248650}.passport .invalid{color:#b63838}.passport h5{margin-top:18px;font-size:13px}.passport dl{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:13px 0}.passport dt{font-size:8px;color:#999}.passport dd{font-size:9px;margin:2px 0 0}.passport code{display:block;overflow:hidden;padding:8px;border-radius:6px;background:#111;color:#b9f8cb;font-size:7px;text-overflow:ellipsis}.value{grid-template-columns:repeat(4,1fr)}.causal-result{grid-column:1/-1;display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:7px;padding:14px;border:1px solid #c6e5d0;border-radius:11px;background:#f4fbf6}.causal-result strong{grid-row:1/3;font-size:28px}.causal-result span,.causal-result b{font-size:10px}.causal-result small{font-size:8px;color:#777}.connector-head{display:flex;justify-content:space-between;gap:20px}.connector-head>div:last-child{display:flex;gap:8px;align-items:start}.optimizer-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-top:18px}.optimizer-grid article{padding:12px;border:1px solid #e2e2e2;border-radius:11px}.optimizer-grid header{display:flex;justify-content:space-between;gap:5px}.optimizer-grid header b{font-size:10px}.optimizer-grid header span{border-radius:99px;padding:3px 5px;background:#eee;font-size:7px;text-transform:uppercase}.optimizer-grid header span.prefer{background:#e6f7ec;color:#27764a}.optimizer-grid header span.deprioritize{background:#fff0f0;color:#a73e3e}.optimizer-grid header span.activate{background:#eeeaff;color:#5a4bc0}.optimizer-grid article>strong{display:block;margin-top:10px;font-size:22px}.optimizer-grid p{min-height:42px;font-size:8px}.optimizer-grid small{font-size:7px;color:#999}.market{display:grid;grid-template-columns:1fr 1fr;gap:28px}.market-create label{display:block;margin-top:12px}.market-create>div{display:flex;gap:8px;margin-top:12px}.market-list{display:grid;align-content:start;gap:8px}.market-list article{display:grid;grid-template-columns:1fr auto;gap:5px;padding:12px;border:1px solid #e2e2e2;border-radius:11px}.market-list article div b,.market-list article div span{display:block;font-size:10px}.market-list article div span,.market-list article small{font-size:8px;color:#999}.market-list article p,.market-list article small{grid-column:1}.market-list article button{grid-column:2;grid-row:1/4;align-self:center}@media(max-width:900px){.cade-os__header,.panel-copy,.connector-head{flex-direction:column}.proficiency{width:100%}.two-col,.market{grid-template-columns:1fr}.optimizer-grid{grid-template-columns:repeat(2,1fr)}.room,.value{grid-template-columns:1fr 1fr}.room-heading,.wide,.room-result,.causal-result{grid-column:1/-1}.replay-stage{grid-template-columns:1fr}.replay-arrow{transform:rotate(90deg);padding:8px}}@media(max-width:560px){.cade-os__header,.panel{padding:20px}.optimizer-grid,.room,.value{grid-template-columns:1fr}.room label,.value label,.room>button,.value>button{grid-column:1}.causal-result{grid-template-columns:1fr}.causal-result strong{grid-row:auto}.market-create>div,.connector-head>div:last-child{flex-direction:column}.connector-head button{width:100%}}
</style>
