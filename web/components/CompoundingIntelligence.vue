<script setup lang="ts">
const props = withDefaults(defineProps<{ compact?: boolean; initialScope?: string; initialRef?: string; initialLabel?: string; projectId?: string }>(), {
  compact: false, initialScope: 'portfolio', initialRef: 'portfolio', initialLabel: 'Entire orchestrator portfolio', projectId: '',
})
const supabase = useSupabaseClient<any>()
const scopeType = ref(props.initialScope)
const scopeRef = ref(props.initialRef)
const label = ref(props.initialLabel)
const mode = ref('shadow')
const data = ref<any>(null)
const busy = ref(false)
const notice = ref('')
const stages = ['Observe', 'Propose', 'Shadow', 'Verify', 'Graduate', 'Share']
const activeStage = ref(2)
let motion: any

async function authedFetch<T = any>(url: string, opts: any = {}) {
  const { data: { session } } = await supabase.auth.getSession()
  return $fetch<T>(url, { ...opts, headers: { ...(opts.headers || {}), ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}) } })
}
async function refresh() {
  try { data.value = await authedFetch('/api/improvement/recommendations', { query: { scope_type: scopeType.value, scope_ref: scopeRef.value, label: label.value } }) }
  catch { data.value = { recommendation: { score: 84, expectedLift: 17, targetKpi: 'first_pass_rate', rationale: 'Connect telemetry to receive a live CADE recommendation.', mode: 'observe' }, loops: [], credits: 0 } }
}
async function activate() {
  busy.value = true; notice.value = ''
  try {
    const result: any = await authedFetch('/api/improvement/activate', { method: 'POST', body: { scope_type: scopeType.value, scope_ref: scopeRef.value, label: label.value, mode: mode.value, project_id: props.projectId || undefined, target_kpi: data.value?.recommendation?.targetKpi } })
    notice.value = `${result.loop.label} is now running in ${result.loop.mode.replace('_', ' ')} mode.`
    await refresh()
  } catch (error: any) { notice.value = error?.data?.message || error?.message || 'The loop could not be activated.' }
  finally { busy.value = false }
}
watch([scopeType, scopeRef], refresh)
onMounted(() => { refresh(); motion = setInterval(() => { activeStage.value = (activeStage.value + 1) % stages.length }, 1800) })
onUnmounted(() => clearInterval(motion))
</script>

<template>
  <section class="compound" :class="{ compact }">
    <div class="compound-copy">
      <span class="eyebrow"><i /> Compounding intelligence</span>
      <h2>Every objective can improve the system that completed it.</h2>
      <p>CADE identifies high-leverage surfaces, creates a bounded candidate loop, shadow-tests it against the current system, independently verifies the gain, and rolls back automatically if a protected KPI moves the wrong way.</p>
      <div class="scope-form">
        <label>Improve
          <select v-model="scopeType">
            <option value="portfolio">Entire portfolio</option><option value="application">Application</option><option value="orchestrator">Agent / orchestrator</option><option value="workflow">Workflow</option><option value="code">Code surface</option><option value="component">Specified component</option>
          </select>
        </label>
        <label>Exact boundary<input v-model="scopeRef" placeholder="e.g. release-train or packages/router" /></label>
        <label>Safety mode<select v-model="mode"><option value="observe">Observe only</option><option value="shadow">Shadow test</option><option value="bounded_autonomy">Bounded autonomy</option></select></label>
      </div>
      <div class="recommendation">
        <div><strong>{{ data?.recommendation?.score ?? 84 }}</strong><span>/100</span></div>
        <p><b>CADE recommends {{ data?.recommendation?.mode ?? 'shadow' }} mode</b><small>{{ data?.recommendation?.rationale }} Expected lift: +{{ data?.recommendation?.expectedLift ?? 17 }}% on {{ data?.recommendation?.targetKpi?.replaceAll('_', ' ') }}.</small></p>
      </div>
      <div class="actions"><button :disabled="busy || !scopeRef.trim()" @click="activate">{{ busy ? 'Binding safeguards…' : 'Activate verified loop' }} <span>↗</span></button><NuxtLink to="/loops">Open improvement control center</NuxtLink></div>
      <p v-if="notice" class="notice">{{ notice }}</p>
    </div>

    <div class="compound-visual" aria-label="Dynamic self-improvement lifecycle">
      <header><span>CADE / improvement fabric</span><b><i /> SHADOW LIVE</b></header>
      <div class="orbit">
        <div class="core"><span>+{{ data?.recommendation?.expectedLift ?? 17 }}%</span><small>verified candidate</small></div>
        <i v-for="n in 3" :key="n" :class="`ring r${n}`" />
        <span v-for="(stage,index) in stages" :key="stage" class="stage" :class="[{ active: activeStage === index }, `s${index}`]"><i />{{ stage }}</span>
      </div>
      <div class="signal-grid">
        <div><span>CONTROL</span><b>Current route</b><i><em style="width:78%" /></i></div>
        <div><span>CANDIDATE</span><b>Adaptive route</b><i><em class="green" style="width:94%" /></i></div>
      </div>
      <div class="guardrail"><span>Locked invariants</span><b>Authority</b><b>Secrets</b><b>Privacy</b><b>Budget</b><b>Independent QA</b></div>
      <footer><div><span>HIVEMIND VALUE</span><strong>{{ data?.credits ?? 0 }} credits</strong></div><p>Share only the privacy-safe pattern after blind validation. Verified downstream value earns platform rebates.</p><button>Contribution policy ↗</button></footer>
    </div>
  </section>
</template>

<style scoped>
.compound{--green:#82ff9c;display:grid;grid-template-columns:.88fr 1.12fr;gap:clamp(32px,5vw,80px);padding:clamp(36px,5vw,78px);border:1px solid #25282d;border-radius:24px;background:#090b0d;color:#f8fafc;overflow:hidden}.compound-copy{align-self:center}.eyebrow{display:flex;align-items:center;gap:9px;color:#9da4ad;font:650 10px/1 ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase}.eyebrow i{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 18px var(--green)}h2{max-width:620px;margin:22px 0 20px;font-size:clamp(34px,4vw,64px);font-weight:450;line-height:.98;letter-spacing:-.055em}.compound-copy>p{max-width:630px;color:#9da4ad;font-size:13px;line-height:1.75}.scope-form{display:grid;grid-template-columns:1fr 1.2fr 1fr;gap:8px;margin-top:26px}.scope-form label{display:flex;flex-direction:column;gap:6px;color:#737a84;font:8px ui-monospace,monospace;text-transform:uppercase}.scope-form input,.scope-form select{min-width:0;height:40px;padding:0 10px;border:1px solid #2a2e34;border-radius:8px;background:#111419;color:#e8ebef;font:10px Inter,sans-serif;text-transform:none}.recommendation{display:grid;grid-template-columns:58px 1fr;gap:12px;align-items:center;margin-top:14px;padding:13px;border:1px solid rgba(130,255,156,.3);border-radius:10px;background:rgba(130,255,156,.055)}.recommendation>div strong{font:500 24px ui-monospace,monospace;color:var(--green)}.recommendation>div span{color:#707781;font-size:9px}.recommendation p{display:flex;flex-direction:column;margin:0}.recommendation b{font-size:11px}.recommendation small{margin-top:4px;color:#89919b;font-size:9px;line-height:1.5}.actions{display:flex;align-items:center;gap:18px;margin-top:17px}.actions button{padding:12px 16px;border-radius:8px;background:var(--green);color:#071009;font-size:10px;font-weight:700}.actions button:disabled{opacity:.4}.actions a{color:#aab0b8;font-size:9px;text-underline-offset:4px}.notice{color:var(--green)!important;font-size:9px!important}.compound-visual{position:relative;min-height:545px;border:1px solid #2a2e34;border-radius:16px;background:radial-gradient(circle at 50% 38%,rgba(130,255,156,.08),transparent 31%),#0d1014;box-shadow:0 28px 70px rgba(0,0,0,.45)}.compound-visual header{height:45px;display:flex;align-items:center;justify-content:space-between;padding:0 15px;border-bottom:1px solid #25292e;color:#737b85;font:8px ui-monospace,monospace;text-transform:uppercase}.compound-visual header b{display:flex;align-items:center;gap:7px;color:var(--green)}.compound-visual header b i{width:5px;height:5px;border-radius:50%;background:var(--green);animation:pulse 1.4s infinite}.orbit{position:relative;height:310px}.core{position:absolute;z-index:4;left:50%;top:50%;width:115px;height:115px;transform:translate(-50%,-50%);display:grid;place-content:center;border:1px solid rgba(130,255,156,.6);border-radius:50%;background:#101a14;text-align:center;box-shadow:0 0 50px rgba(130,255,156,.14)}.core span{font:500 24px ui-monospace,monospace;color:var(--green)}.core small{margin-top:5px;color:#87918a;font-size:7px;text-transform:uppercase}.ring{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);border:1px solid #252a2f;border-radius:50%;animation:spin 22s linear infinite}.r1{width:180px;height:180px}.r2{width:250px;height:250px;animation-direction:reverse}.r3{width:310px;height:310px}.stage{position:absolute;z-index:5;display:flex;align-items:center;gap:5px;padding:5px 7px;border:1px solid #2b3036;border-radius:99px;background:#11151a;color:#747c86;font:7px ui-monospace,monospace;text-transform:uppercase;transition:.35s}.stage i{width:4px;height:4px;border-radius:50%;background:#515962}.stage.active{border-color:rgba(130,255,156,.6);color:#dfffe5;box-shadow:0 0 18px rgba(130,255,156,.12)}.stage.active i{background:var(--green);box-shadow:0 0 8px var(--green)}.s0{left:7%;top:21%}.s1{left:37%;top:5%}.s2{right:7%;top:22%}.s3{right:7%;bottom:21%}.s4{left:39%;bottom:5%}.s5{left:6%;bottom:21%}.signal-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:0 14px 14px}.signal-grid>div{padding:10px;border:1px solid #24282e;border-radius:8px}.signal-grid span{display:block;color:#646c76;font:7px ui-monospace,monospace}.signal-grid b{display:block;margin:5px 0 9px;font-size:9px}.signal-grid div>i{display:block;height:3px;background:#252a30}.signal-grid em{display:block;height:100%;background:#707985}.signal-grid em.green{background:var(--green);box-shadow:0 0 10px rgba(130,255,156,.5)}.guardrail{display:flex;gap:5px;align-items:center;padding:9px 14px;border-top:1px solid #24282e;border-bottom:1px solid #24282e;color:#606873;font-size:7px}.guardrail span{margin-right:auto;text-transform:uppercase}.guardrail b{padding:3px 5px;border:1px solid #2c3138;border-radius:99px;font-weight:500}.compound-visual footer{display:grid;grid-template-columns:auto 1fr auto;gap:14px;align-items:center;padding:14px}.compound-visual footer div{display:flex;flex-direction:column}.compound-visual footer span{color:#636b74;font:7px ui-monospace,monospace}.compound-visual footer strong{margin-top:4px;color:var(--green);font:500 13px ui-monospace,monospace}.compound-visual footer p{margin:0;color:#7a828c;font-size:8px;line-height:1.45}.compound-visual footer button{color:#b4bac2;font-size:8px}.compact{grid-template-columns:1fr 1fr;padding:34px}.compact h2{font-size:36px}.compact .compound-visual{min-height:505px}@keyframes spin{to{transform:translate(-50%,-50%) rotate(360deg)}}@keyframes pulse{50%{opacity:.35;transform:scale(.7)}}@media(max-width:950px){.compound{grid-template-columns:1fr}.scope-form{grid-template-columns:1fr}.compound-visual{min-height:530px}}@media(prefers-reduced-motion:reduce){.compound *{animation:none!important;transition:none!important}}
</style>
