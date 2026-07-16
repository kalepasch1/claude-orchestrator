<script setup lang="ts">
type View = 'coverage' | 'qualify' | 'relationships' | 'settings'
const supabase = useSupabaseClient<any>()
const state = ref<any>(null)
const view = ref<View>('coverage')
const busy = ref('')
const notice = ref('')
const showRelationship = ref(false)
const relationship = reactive({ counterparty_name: '', relationship_type: 'sponsor', covered_activities: '', jurisdictions: 'US-general' })
const assessmentText = ref('')

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
        <button v-for="item in [{id:'coverage',label:'Coverage'},{id:'qualify',label:'Qualify'},{id:'relationships',label:'Relationships'},{id:'settings',label:'Controls'}]" :key="item.id" :class="{active:view===item.id}" @click="view=item.id as View">{{ item.label }}</button>
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
</style>
