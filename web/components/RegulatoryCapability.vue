<script setup lang="ts">
type View = 'coverage' | 'foresight' | 'qualify' | 'evidence' | 'agreements' | 'relationships' | 'options' | 'resilience' | 'settings'
const supabase = useSupabaseClient<any>()
const state = ref<any>(null)
const view = ref<View>('coverage')
const busy = ref('')
const notice = ref('')
const showRelationship = ref(false)
const relationship = reactive({ counterparty_name: '', relationship_type: 'sponsor', covered_activities: '', jurisdictions: 'US-general' })
const assessmentText = ref('')
const forecast = reactive({ jurisdictions: 'US-general', readiness_score: 0, monthly_growth_rate: 0.08, license_expires_in_days: 365, ownership_change_in_days: null as number|null, law_change_in_days: null as number|null })
const agreement = reactive({ agreement_ref: '', relationship_id: '', terms_text: '', activate: false })
const feature = reactive({ project_ref: '', feature_key: '', jurisdiction: 'US-general', activity: '', covered: false, activate: false })

async function authed<T>(url: string, options: any = {}) {
  const { data: { session } } = await supabase.auth.getSession()
  return $fetch<T>(url, { ...options, headers: session?.access_token ? { authorization: `Bearer ${session.access_token}` } : {} })
}
async function load() {
  try { state.value = await authed('/api/hivemind/regulatory') }
  catch (error: any) { notice.value = error?.data?.message || error?.message || 'Regulatory capability status is temporarily unavailable.' }
}
async function act(key: string, body: any, success: string) {
  busy.value = key; notice.value = ''
  try { await authed('/api/hivemind/regulatory', { method: 'POST', body }); notice.value = success; await load() }
  catch (error: any) { notice.value = error?.data?.message || error?.message || 'That action could not be completed safely.' }
  finally { busy.value = '' }
}
const assist = (item: any, type = 'eligibility', provider = 'apparently') => act(`assist:${item.id}`, {
  action: 'assist', assistance_type: type, provider, confirm_external_share: true,
  assessment_id: type === 'code_boundary' ? item.id : null, readiness_path_id: type === 'eligibility' ? item.id : null,
  objective: type === 'code_boundary' ? `Prepare a reviewed operating boundary and remediation plan for ${item.activity}.` : `Prepare the evidence, documents, and operating changes required for ${item.target_capability} readiness.`,
}, 'A bounded brief was authorized and routed. Filings, contracts, and material changes still require fresh approval.')
const configure = () => act('configure', { action: 'configure', ...state.value.profile }, 'Autonomy and permission boundaries updated.')
const createRelationship = async () => {
  await act('relationship', { action: 'relationship', organization_approve: true, ...relationship,
    covered_activities: relationship.covered_activities.split(',').map(x => x.trim()).filter(Boolean), jurisdictions: relationship.jurisdictions.split(',').map(x => x.trim()).filter(Boolean),
  }, 'Relationship workspace created. Counterparty and regulator approval remain pending where required.')
  showRelationship.value = false
}
const assessDescription = async () => {
  if (!assessmentText.value.trim()) return
  await act('assess', { action: 'assess', source_type: 'user', summary: assessmentText.value, materiality: 'unknown' }, 'The activity was decomposed into coverage requirements and safer alternatives.')
  assessmentText.value = ''
}
const saveForecast = () => act('forecast', { action: 'forecast', ...forecast, jurisdictions: forecast.jurisdictions.split(',').map(x=>x.trim()).filter(Boolean) }, 'CADE refreshed the authority timeline and jurisdiction sequence.')
const saveAgreement = () => act('agreement', { action: 'agreement_controls', agreement_ref: agreement.agreement_ref, relationship_id: agreement.relationship_id || null, activate: agreement.activate, terms: agreement.terms_text.split('\n').map((text,index)=>({ key:`term_${index+1}`, text })).filter(x=>x.text.trim()) }, agreement.activate ? 'The agreement controls are active and monitored.' : 'A shadow control set was compiled for review without changing product behavior.')
const saveFeature = () => act('feature', { action: 'feature_control', ...feature }, feature.activate ? 'The jurisdiction control was activated with QA and rollback requirements.' : 'A shadow feature plan was prepared without changing the live product.')
const chooseOption = async (option:any) => {
  await act(`option:${option.id}`, { action:'select_strategy', option_id:option.id }, 'The strategy was selected. Confirm the bounded Apparently/Smarter handoff to begin execution.')
  await act(`assist:${option.id}`, { action:'assist', assistance_type:option.activation_action?.assistance_type || 'business_model', provider:option.activation_action?.provider || 'apparently', confirm_external_share:true, readiness_path_id:option.readiness_path_id, objective:`Prepare the selected regulatory strategy: ${option.title}.` }, 'The selected strategy was routed as a bounded, approval-aware workstream.')
}
const electSettlement = (control:any) => act(`settlement:${control.id}`, { action:'cade_settlement', agreement_control_id:control.id, organization_approve:true, governing_terms_ref:control.agreement_ref }, 'CADE settlement was elected on your side. Counterparty acceptance and enforceable agreement terms remain required.')
const sortedOptions = computed(() => [...(state.value?.strategy_options || [])].sort((a:any,b:any)=>Number(b.cade_score?.score||0)-Number(a.cade_score?.score||0)))
const money = (value: any) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(Number(value || 0) / 100)
onMounted(load)
</script>

<template>
  <section class="regulatory" aria-labelledby="regulatory-title">
    <header>
      <div><span>REGULATED CAPABILITY NETWORK</span><h2 id="regulatory-title">Build freely.<br><em>Cross boundaries deliberately.</em></h2></div>
      <div class="intro">
        <p>Madeus watches product, code, marketing, contracts, and operations for activities that may need a license, permit, registration, appointment, or supervised relationship. Routine analysis stays behind the scenes; authority remains yours.</p>
        <div class="status"><i :class="state?.summary?.contained_changes ? 'warn' : ''" /><b v-if="state">{{ state.summary.contained_changes ? `${state.summary.contained_changes} change${state.summary.contained_changes === 1 ? '' : 's'} safely contained` : 'Coverage monitor active' }}</b><b v-else>Checking operating boundaries…</b><button :disabled="busy === 'scan'" @click="act('scan',{ action:'scan' },'Every available activity signal was rechecked.')">Recheck</button></div>
      </div>
    </header>

    <div v-if="state" class="shell">
      <nav aria-label="Regulatory capability">
        <button v-for="item in [{id:'coverage',label:'Coverage'},{id:'foresight',label:'Foresight'},{id:'qualify',label:'Qualify'},{id:'evidence',label:'Evidence'},{id:'agreements',label:'Agreements'},{id:'relationships',label:'Relationships'},{id:'options',label:'Options'},{id:'resilience',label:'Resilience'},{id:'settings',label:'Controls'}]" :key="item.id" :class="{active:view===item.id}" @click="view=item.id as View">{{ item.label }}</button>
      </nav>

      <section v-if="view === 'coverage'" class="panel">
        <div class="metrics">
          <article><span>Boundaries to review</span><b>{{ state.summary.boundaries_to_review }}</b><small>Before affected activity goes live</small></article>
          <article><span>Ready to apply</span><b>{{ state.summary.application_ready }}</b><small>Evidence path completed</small></article>
          <article><span>Active coverage</span><b>{{ state.summary.active_relationships }}</b><small>Supervised relationships</small></article>
        </div>
        <form class="quick" @submit.prevent="assessDescription"><label><span>Check a proposed change</span><textarea v-model="assessmentText" rows="2" placeholder="Example: pay partners a percentage for investor introductions, or add a custodial wallet…" /></label><button :disabled="busy === 'assess' || !assessmentText.trim()">Check boundary</button></form>
        <div class="cards">
          <article v-for="item in state.assessments" :key="item.id">
            <div class="card-top"><span>{{ item.signal?.source_type || 'activity' }} · {{ Math.round(Number(item.confidence)*100) }}%</span><b :class="item.verdict">{{ item.verdict.replaceAll('_',' ') }}</b></div>
            <h3>{{ item.activity.replaceAll('_',' ') }}</h3>
            <p>{{ item.regulated_core?.trigger }}</p>
            <details><summary>Safer operating paths</summary><div v-for="alternative in item.safe_alternatives" :key="alternative.label" class="alternative"><b>{{ alternative.label }}</b><span>{{ alternative.boundary }}</span><small v-if="alternative.compensation">{{ alternative.compensation }}</small></div></details>
            <button :disabled="busy === `assist:${item.id}`" @click="assist(item,'code_boundary','combined')">Prepare a compliant path</button>
          </article>
          <div v-if="!state.assessments.length" class="empty">No likely regulated boundary is waiting for review. Continuous detection remains active.</div>
        </div>
      </section>

      <section v-else-if="view === 'foresight'" class="panel">
        <div class="heading"><div><span>CADE REGULATORY TEMPORAL TWIN</span><h3>Know where—and when—authority becomes valuable.</h3></div><p>CADE models jurisdiction order, sponsor versus license timing, renewal windows, ownership changes, growth thresholds, and regulatory change. Predictions expose uncertainty and refresh when assumptions move.</p></div>
        <form class="forecast-form" @submit.prevent="saveForecast"><label>Jurisdictions<input v-model="forecast.jurisdictions" placeholder="US-general, NY, CA" /></label><label>Readiness %<input v-model.number="forecast.readiness_score" type="number" min="0" max="100" /></label><label>Monthly growth<input v-model.number="forecast.monthly_growth_rate" type="number" step="0.01" min="0" /></label><label>License expiry, days<input v-model.number="forecast.license_expires_in_days" type="number" min="1" /></label><label>Ownership change, days<input v-model.number="forecast.ownership_change_in_days" type="number" min="0" placeholder="optional" /></label><label>Law change, days<input v-model.number="forecast.law_change_in_days" type="number" min="0" placeholder="optional" /></label><button>Simulate timing</button></form>
        <div v-for="scenario in state.foresight.scenarios" :key="scenario.id" class="scenario">
          <div class="scenario-advice"><span>{{ Math.round(Number(scenario.cade_prediction?.confidence||0)*100) }}% evidence confidence</span><h4>{{ scenario.cade_prediction?.timing_advisory }}</h4></div>
          <div class="sequence"><article v-for="entry in scenario.jurisdiction_sequence" :key="entry.jurisdiction"><b>0{{ entry.order }}</b><div><span>{{ entry.jurisdiction }}</span><strong>{{ entry.recommended_route.replaceAll('_',' ') }}</strong><small>Earliest sponsor {{ new Date(entry.earliest_sponsor_at).toLocaleDateString() }} · license {{ new Date(entry.earliest_license_at).toLocaleDateString() }}</small></div></article></div>
          <details><summary>Events that change the plan</summary><div v-for="event in scenario.authority_timeline" :key="event.at+event.type" class="timeline"><time>{{ new Date(event.at).toLocaleDateString() }}</time><b>{{ event.type.replaceAll('_',' ') }}</b><span>{{ event.effect }}</span></div></details>
        </div>
        <div class="feature-planner"><h4>Prepare a jurisdiction-specific feature mode</h4><form @submit.prevent="saveFeature"><input v-model="feature.project_ref" required placeholder="Project" /><input v-model="feature.feature_key" required placeholder="Feature key" /><input v-model="feature.jurisdiction" required placeholder="Jurisdiction" /><input v-model="feature.activity" required placeholder="Regulated activity" /><label><input v-model="feature.covered" type="checkbox" /> Authority verified</label><label><input v-model="feature.activate" type="checkbox" /> Activate after approval</label><button>{{ feature.activate ? 'Activate governed mode' : 'Prepare in shadow' }}</button></form></div>
        <div v-if="state.feature_controls.length" class="feature-list"><article v-for="control in state.feature_controls" :key="control.id"><div><span>{{control.project_ref}} · {{control.jurisdiction}}</span><h4>{{control.feature_key}}</h4></div><b>{{control.effective_state}}</b><small>{{control.enforcement_mode}}</small></article></div>
      </section>

      <section v-else-if="view === 'qualify'" class="panel">
        <div class="heading"><div><span>SHADOW-LICENSE PATHWAYS</span><h3>Become application-ready before the clock matters.</h3></div><p>Madeus tracks operating history, owners, training, capital, policies, systems, and evidence. It can prepare gaps with Apparently while every filing and representation remains permissioned.</p></div>
        <div class="paths">
          <article v-for="path in state.paths" :key="path.id">
            <div class="ring" :style="{ '--score': `${path.readiness_score*3.6}deg` }"><b>{{ path.readiness_score }}%</b></div>
            <div><span>{{ path.jurisdiction }}</span><h4>{{ path.target_capability }}</h4><p v-if="path.blockers.length">Next: {{ path.blockers.slice(0,2).map((x:any)=>x.label).join(' · ') }}</p><p v-else>Evidence path complete. Final legal and regulator checks remain.</p></div>
            <button :disabled="busy === `assist:${path.id}`" @click="assist(path)">{{ path.readiness_score === 100 ? 'Prepare application' : 'Close gaps' }}</button>
          </article>
        </div>
      </section>

      <section v-else-if="view === 'evidence'" class="panel">
        <div class="heading"><div><span>CONTINUOUS REGULATOR-READY EVIDENCE</span><h3>Build the examination file before anyone asks.</h3></div><p>Evidence remains in its system of record. Madeus stores bounded facts, hashes, verification, expiry, contradictions, and eligibility effects—then predicts what would delay, block, or endanger authority.</p></div>
        <div class="evidence-grid"><article v-for="room in state.evidence_rooms" :key="room.id"><div class="evidence-score"><b>{{room.completeness_score}}%</b><small>complete</small></div><div><span>{{room.jurisdiction}} · {{room.purpose.replaceAll('_',' ')}}</span><h4>{{room.target_capability}}</h4><p>{{room.freshness_score}}% fresh · {{room.contradiction_count}} contradiction{{room.contradiction_count===1?'':'s'}}</p><div v-if="room.eligibility_effects.length" class="eligibility-warning">{{room.eligibility_effects.length}} item{{room.eligibility_effects.length===1?'':'s'}} may delay or change eligibility.</div></div><button @click="assist({id:room.readiness_path_id,target_capability:room.target_capability},'eligibility','apparently')">Close evidence gaps</button></article></div>
      </section>

      <section v-else-if="view === 'agreements'" class="panel">
        <div class="heading"><div><span>EXECUTABLE AGREEMENTS + CADE SETTLEMENT</span><h3>Turn negotiated words into observable operating boundaries.</h3></div><p>Terms compile into shadow limits, approval gates, reporting duties, economics, service levels, cure periods, and termination triggers. Activation is explicit; interpretation confidence never substitutes for legal review.</p></div>
        <form class="agreement-form" @submit.prevent="saveAgreement"><input v-model="agreement.agreement_ref" required placeholder="Agreement reference or URL" /><select v-model="agreement.relationship_id"><option value="">No linked relationship</option><option v-for="item in state.relationships" :key="item.id" :value="item.id">{{item.counterparty_name}}</option></select><textarea v-model="agreement.terms_text" required rows="6" placeholder="Enter one bounded operative term per line. The full agreement remains in its source system." /><label><input v-model="agreement.activate" type="checkbox" /> Activate controls after compilation</label><button>{{agreement.activate?'Compile and activate':'Compile in shadow'}}</button></form>
        <div class="agreement-list"><article v-for="control in state.agreements.controls" :key="control.id"><div><span>{{control.status}} · {{Math.round(Number(control.interpretation_confidence)*100)}}% interpretation confidence</span><h4>{{control.agreement_ref}}</h4><p>{{control.executable_controls.length}} controls · {{control.reporting_schedule.length}} reporting duties · {{control.termination_rules.length}} termination rules</p></div><button :disabled="busy===`settlement:${control.id}`" @click="electSettlement(control)">Elect CADE settlement</button></article></div>
        <div v-if="state.agreements.obligations.length" class="obligations"><h4>Performance ledger</h4><article v-for="obligation in state.agreements.obligations" :key="obligation.id"><span>{{obligation.obligation_type.replaceAll('_',' ')}}</span><b>{{obligation.obligation_key}}</b><strong :class="obligation.status">{{obligation.status}}</strong><small>{{money(Number(obligation.direct_cost_cents)+Number(obligation.indirect_cost_cents))}} measured cost</small></article></div>
      </section>

      <section v-else-if="view === 'relationships'" class="panel">
        <div class="heading"><div><span>SPONSOR + PARTNER OPERATIONS</span><h3>One operating record for authority, economics, and obligations.</h3></div><button @click="showRelationship=!showRelationship">{{ showRelationship ? 'Cancel' : 'New relationship' }}</button></div>
        <form v-if="showRelationship" class="relationship-form" @submit.prevent="createRelationship"><input v-model="relationship.counterparty_name" required placeholder="Counterparty or sponsor" /><select v-model="relationship.relationship_type"><option>sponsor</option><option>authorized_delegate</option><option>associated_person</option><option>appointment</option><option>white_label</option><option>service_provider</option><option>referral</option><option>partnership</option><option>guarantee</option><option>subsidiary</option></select><input v-model="relationship.covered_activities" placeholder="Covered activities, comma separated" /><input v-model="relationship.jurisdictions" placeholder="Jurisdictions" /><button>Create governed workspace</button></form>
        <div class="relationships">
          <article v-for="item in state.relationships" :key="item.id">
            <div><span>{{ item.relationship_type.replaceAll('_',' ') }}</span><h4>{{ item.counterparty_name }}</h4><p>{{ item.covered_activities.join(' · ') || 'Coverage scope being prepared' }}</p></div>
            <div class="economics"><b>{{ money(item.economics?.monthly_price_cents) }}</b><small>modeled monthly supervision</small></div>
            <strong :class="item.status">{{ item.status.replaceAll('_',' ') }}</strong>
          </article>
          <div v-if="!state.relationships.length" class="empty">No governed sponsor or partner relationships yet.</div>
        </div>
        <aside v-if="state.attention.length"><b>Contained relationship changes</b><div v-for="event in state.attention" :key="event.id"><span>{{ event.event_type.replaceAll('_',' ') }}</span><p>{{ event.action_taken }}</p></div></aside>
      </section>

      <section v-else-if="view === 'options'" class="panel">
        <div class="heading"><div><span>FULL-COST LICENSE STRATEGY</span><h3>Choose the operating path—not merely the filing.</h3></div><p>Every option includes time to revenue, setup and recurring expense, management burden, opportunity cost, dependency risk, retained control, and expected value. One click prepares the selected path; external execution remains confirmed.</p></div>
        <div class="option-grid"><article v-for="option in sortedOptions.slice(0,18)" :key="option.id"><div class="option-score"><b>{{option.cade_score?.score}}</b><small>CADE</small></div><div><span>{{option.option_type.replaceAll('_',' ')}}</span><h4>{{option.title}}</h4><p>{{option.timeline?.estimated_months}} month{{option.timeline?.estimated_months===1?'':'s'}} to activate · {{money(option.direct_costs?.total_cents)}} direct · {{money(option.indirect_costs?.opportunity_cost_cents)}} opportunity cost</p><small>{{option.cade_score?.explanation}}</small></div><button :disabled="busy===`option:${option.id}`" @click="chooseOption(option)">Choose and prepare</button></article></div>
      </section>

      <section v-else-if="view === 'resilience'" class="panel">
        <div class="heading"><div><span>REGULATORY RESILIENCE TWIN</span><h3>See the exposure. Keep the outcome.</h3></div><p>Madeus continuously rehearses examinations, models contract-network concentration, detects primary-authority drift, and places short-lived authority receipts in the release path. The machinery stays backstage; only decisions and exceptions surface here.</p></div>
        <div class="metrics resilience-metrics">
          <article><span>Systemic cascade risk</span><b>{{ state.frontier.latest_by_type?.systemic_risk?.outcome?.cascade_risk_score ?? '—' }}</b><small>0–100 modeled concentration</small></article>
          <article><span>Examination readiness</span><b>{{ state.frontier.latest_by_type?.examination?.outcome?.examination_readiness_score ?? '—' }}<i v-if="state.frontier.latest_by_type?.examination">%</i></b><small>Adversarial evidence rehearsal</small></article>
          <article><span>Authority changes</span><b>{{ state.frontier.summary.authority_changes_to_review }}</b><small>Bounded review required</small></article>
        </div>
        <div class="resilience-grid">
          <article><span>RELEASE AUTHORITY</span><h4>{{ state.frontier.summary.releases_held ? `${state.frontier.summary.releases_held} release decision${state.frontier.summary.releases_held===1?'':'s'} held` : 'No release authority exceptions' }}</h4><p>CI/CD receives allow, hold, or block plus a short-lived policy receipt. Incomplete proof holds only affected capabilities; lawful variants remain available.</p></article>
          <article><span>REGULATOR ACCESS</span><h4>{{ state.frontier.summary.active_regulator_grants }} active bounded grant{{state.frontier.summary.active_regulator_grants===1?'':'s'}}</h4><p>Every grant is explicit, revocable, field-scoped, purpose-limited, and expiring. Underlying records stay in their source systems.</p></article>
          <article><span>DISPUTE PREVENTION</span><h4>{{ state.frontier.latest_by_type?.dispute_prevention?.outcome?.ambiguity_score ?? 'Continuous' }}{{state.frontier.latest_by_type?.dispute_prevention ? '/100 ambiguity' : ' contract review'}}</h4><p>Ambiguous terms are translated into measurable acceptance, evidence, notice, cure, change-control, and CADE-election boundaries before execution.</p></article>
        </div>
      </section>

      <section v-else class="panel settings">
        <div class="heading"><div><span>PERMISSION BOUNDARIES</span><h3>Autonomous analysis. Explicit authority.</h3></div><p>These controls never authorize a filing, contract signature, regulator representation, external message, or material product change.</p></div>
        <label><div><b>Continuous boundary detection</b><small>Analyze bounded indicators from portfolio activity.</small></div><input v-model="state.profile.autonomy.continuous_detection" type="checkbox" /></label>
        <label><div><b>Auto-prepare non-material improvements</b><small>Draft tests, checklists, and reversible internal adjustments.</small></div><input v-model="state.profile.autonomy.auto_non_material" type="checkbox" /></label>
        <label><div><b>Autonomous material changes</b><small>Off by default. Still requires configured thresholds and approval where authority is external.</small></div><input v-model="state.profile.autonomy.material_changes" type="checkbox" /></label>
        <label><div><b>Standing permission for bounded external briefs</b><small>Off by default. Without this, each Apparently or Smarter handoff requires a click.</small></div><input v-model="state.profile.autonomy.external_sharing" type="checkbox" /></label>
        <button :disabled="busy === 'configure'" @click="configure">Save controls</button>
      </section>
      <footer>{{ state.disclaimer }} Raw source code and documents are not copied into the network plane.</footer>
    </div>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
  </section>
</template>

<style scoped>
.regulatory{padding:104px clamp(18px,4vw,64px);background:#111;color:#f7f7f3}.regulatory>header,.shell{max-width:1220px;margin:auto}.regulatory>header{display:grid;grid-template-columns:1.2fr .8fr;gap:8vw;align-items:end}.regulatory header>div>span,.heading span,.panel>span{font:750 9px JetBrains Mono,monospace;letter-spacing:.14em;color:#68c18e}.regulatory h2{margin:17px 0 0;font-size:clamp(48px,6vw,86px);line-height:.94;letter-spacing:-.065em;font-weight:480}.regulatory h2 em{font-style:normal;color:#777}.intro>p,.heading>p{color:#aaa;font-size:12px;line-height:1.75}.status{display:flex;align-items:center;gap:10px;margin-top:20px;padding-top:14px;border-top:1px solid #343430;font:700 9px JetBrains Mono,monospace}.status i{width:8px;height:8px;border-radius:50%;background:#59b77f;box-shadow:0 0 0 4px #193226}.status i.warn{background:#e1a34f;box-shadow:0 0 0 4px #382a18}.status button{margin-left:auto;border:0;background:transparent;color:#ddd;text-decoration:underline;font:inherit}.shell{margin-top:46px;border:1px solid #343430;border-radius:15px;background:#191917;overflow:hidden}.shell>nav{display:flex;border-bottom:1px solid #343430;background:#141412}.shell>nav button{padding:16px 21px;border:0;border-right:1px solid #343430;background:transparent;color:#777;font-size:10px;font-weight:750}.shell>nav button.active{background:#f1f1ed;color:#111}.panel{min-height:500px;padding:28px}.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}.metrics article{padding:18px;border:1px solid #353532;border-radius:10px;background:#20201d}.metrics span,.metrics small{display:block;color:#888;font-size:9px}.metrics b{display:block;margin:7px 0;font-size:28px}.quick{display:grid;grid-template-columns:1fr auto;gap:12px;align-items:end;margin:22px 0;padding:18px;border-radius:11px;background:#f0f0ec;color:#111}.quick label{display:grid;gap:8px}.quick label span{font-size:10px;font-weight:750}.quick textarea,.relationship-form input,.relationship-form select{width:100%;box-sizing:border-box;border:1px solid #c9c9c3;border-radius:8px;background:#fff;padding:10px;font:10px/1.5 inherit;resize:vertical}.quick button,.cards article>button,.paths button,.heading>button,.relationship-form button,.settings>button{border:0;border-radius:8px;background:#66bd8a;color:#0b1b11;padding:11px 14px;font-size:9px;font-weight:800}.cards{display:grid;grid-template-columns:repeat(2,1fr);gap:9px}.cards>article{display:flex;flex-direction:column;padding:19px;border:1px solid #353532;border-radius:11px;background:#20201d}.card-top{display:flex;justify-content:space-between;gap:12px;font:700 8px JetBrains Mono,monospace;color:#888}.card-top b{color:#e7ad5c;text-transform:uppercase}.cards h3{margin:12px 0 7px;text-transform:capitalize;font-size:19px}.cards p,.heading p,.paths p,.relationships p{color:#9b9b95;font-size:10px;line-height:1.6}.cards details{margin:12px 0 16px;border-top:1px solid #383834;padding-top:11px;font-size:9px}.cards summary{cursor:pointer;color:#ccc;font-weight:750}.alternative{display:grid;gap:4px;margin-top:9px;padding-left:10px;border-left:2px solid #5baa7d}.alternative span,.alternative small{color:#999;line-height:1.5}.cards article>button{margin-top:auto;align-self:flex-start}.heading{display:grid;grid-template-columns:1fr .7fr;gap:7vw;align-items:end;margin-bottom:25px}.heading h3{max-width:650px;margin:7px 0 0;font-size:clamp(30px,4vw,54px);line-height:1;letter-spacing:-.05em}.paths,.relationships{display:grid;gap:9px}.paths article{display:grid;grid-template-columns:auto 1fr auto;gap:18px;align-items:center;padding:16px;border:1px solid #353532;border-radius:11px}.ring{--score:0deg;width:58px;height:58px;display:grid;place-items:center;border-radius:50%;background:radial-gradient(circle,#20201d 56%,transparent 58%),conic-gradient(#66bd8a var(--score),#383834 0)}.ring b{font-size:11px}.paths span,.relationships span{font:700 8px JetBrains Mono,monospace;color:#68c18e;text-transform:uppercase}.paths h4,.relationships h4{margin:5px 0 2px;font-size:16px;text-transform:capitalize}.relationship-form{display:grid;grid-template-columns:1.2fr 1fr 1.4fr 1fr auto;gap:8px;margin-bottom:18px;padding:14px;border-radius:10px;background:#ededE8}.relationships article{display:grid;grid-template-columns:1fr auto auto;gap:24px;align-items:center;padding:17px;border-bottom:1px solid #343430}.economics{text-align:right}.economics b,.economics small{display:block}.economics small{color:#777;font-size:8px}.relationships strong{padding:7px 9px;border-radius:6px;background:#343430;font:700 8px JetBrains Mono,monospace;text-transform:uppercase}.relationships strong.active{background:#1c3a29;color:#71c996}.panel aside{margin-top:20px;padding:16px;border-radius:10px;background:#33271a;color:#efc280}.panel aside div{display:flex;gap:15px;margin-top:9px;border-top:1px solid #564329;padding-top:9px}.panel aside p{margin:0;color:#d4b58c;font-size:9px}.settings>label{display:flex;justify-content:space-between;align-items:center;gap:24px;padding:17px 2px;border-bottom:1px solid #343430}.settings label div{display:grid;gap:5px}.settings label small{color:#888;font-size:9px}.settings input{width:34px;height:20px;accent-color:#66bd8a}.settings>button{margin-top:20px}.shell footer{padding:15px 28px;border-top:1px solid #343430;color:#777;font-size:8px;line-height:1.55}.empty{grid-column:1/-1;padding:28px;border:1px dashed #44443f;border-radius:10px;color:#888;font-size:10px}.notice{position:sticky;bottom:16px;z-index:6;max-width:760px;margin:18px auto 0;padding:13px 16px;border-radius:9px;background:#f0f0ec;color:#111;font-size:10px}@media(max-width:800px){.regulatory{padding:76px 16px}.regulatory>header,.heading{grid-template-columns:1fr;gap:22px}.shell>nav{overflow:auto}.panel{padding:18px}.metrics,.cards{grid-template-columns:1fr}.quick,.paths article,.relationships article,.relationship-form{grid-template-columns:1fr}.economics{text-align:left}}
.forecast-form{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding:16px;border-radius:11px;background:#ededE8;color:#111}.forecast-form label{display:grid;gap:5px;font-size:8px;font-weight:750}.forecast-form input,.feature-planner input,.agreement-form input,.agreement-form select,.agreement-form textarea{border:1px solid #c9c9c3;border-radius:7px;padding:9px;font:10px inherit}.forecast-form button,.feature-planner button,.agreement-form button,.evidence-grid button,.agreement-list button,.option-grid button{border:0;border-radius:8px;background:#66bd8a;color:#0b1b11;padding:10px 13px;font-size:8px;font-weight:800}.scenario{margin-top:16px;padding:20px;border:1px solid #353532;border-radius:11px}.scenario-advice span{font:700 8px JetBrains Mono,monospace;color:#68c18e}.scenario-advice h4{max-width:850px;margin:7px 0 18px;font-size:22px;line-height:1.25}.sequence{display:grid;grid-template-columns:repeat(2,1fr);gap:7px}.sequence article{display:flex;gap:13px;padding:13px;border-radius:8px;background:#22221f}.sequence article>b{color:#68c18e;font:700 11px JetBrains Mono,monospace}.sequence article div{display:grid;gap:3px}.sequence span,.sequence small{color:#888;font-size:8px}.sequence strong{font-size:10px;text-transform:capitalize}.scenario details{margin-top:15px}.timeline{display:grid;grid-template-columns:90px 130px 1fr;gap:12px;padding:9px;border-top:1px solid #353532;font-size:9px}.timeline time,.timeline span{color:#888}.feature-planner{margin-top:22px;padding:17px;border-radius:10px;background:#ededE8;color:#111}.feature-planner form{display:grid;grid-template-columns:repeat(4,1fr) auto auto auto;gap:7px;align-items:center}.feature-planner label{font-size:8px}.feature-list{margin-top:12px}.feature-list article{display:grid;grid-template-columns:1fr auto auto;gap:15px;padding:12px;border-bottom:1px solid #353532}.feature-list span{color:#68c18e;font:700 8px JetBrains Mono,monospace}.feature-list h4{margin:4px 0}.feature-list b,.feature-list small{text-transform:uppercase;font-size:8px}.evidence-grid,.agreement-list,.option-grid{display:grid;gap:9px}.evidence-grid article,.agreement-list article,.option-grid article{display:grid;grid-template-columns:auto 1fr auto;gap:17px;align-items:center;padding:17px;border:1px solid #353532;border-radius:10px}.evidence-score,.option-score{width:55px;height:55px;display:grid;place-content:center;text-align:center;border-radius:50%;background:#24362b}.evidence-score b,.option-score b{font-size:16px}.evidence-score small,.option-score small{color:#7ecb9d;font-size:7px}.evidence-grid span,.agreement-list span,.option-grid span{font:700 8px JetBrains Mono,monospace;color:#68c18e;text-transform:uppercase}.evidence-grid h4,.agreement-list h4,.option-grid h4{margin:5px 0;font-size:16px}.evidence-grid p,.agreement-list p,.option-grid p{margin:0;color:#999;font-size:9px}.eligibility-warning{margin-top:7px;color:#e3aa5b;font-size:8px}.agreement-form{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:18px;padding:16px;border-radius:10px;background:#ededE8;color:#111}.agreement-form textarea{grid-column:1/-1;resize:vertical}.agreement-form label{font-size:8px}.obligations{margin-top:20px}.obligations>article{display:grid;grid-template-columns:120px 1fr auto auto;gap:14px;padding:11px;border-bottom:1px solid #353532;font-size:8px}.obligations span{color:#68c18e;text-transform:uppercase}.obligations strong{color:#999;text-transform:uppercase}.obligations strong.at_risk,.obligations strong.breached{color:#e3aa5b}.obligations small{color:#888}.option-grid article>div:nth-child(2)>small{color:#777;font-size:8px;line-height:1.4}@media(max-width:800px){.forecast-form,.sequence,.feature-planner form,.evidence-grid article,.agreement-list article,.option-grid article,.agreement-form{grid-template-columns:1fr}.agreement-form textarea{grid-column:auto}.timeline,.obligations>article{grid-template-columns:1fr}}
.resilience-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px}.resilience-grid article{padding:20px;border:1px solid #353532;border-radius:10px;background:#20201d}.resilience-grid span{font:700 8px JetBrains Mono,monospace;color:#68c18e}.resilience-grid h4{margin:10px 0;font-size:18px}.resilience-grid p{color:#999;font-size:9px;line-height:1.65}.resilience-metrics b i{font-size:12px;font-style:normal;color:#777}@media(max-width:800px){.resilience-grid{grid-template-columns:1fr}}
</style>
