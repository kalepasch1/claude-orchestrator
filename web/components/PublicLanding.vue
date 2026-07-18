<script setup lang="ts">
defineProps<{ signingIn?: boolean; authError?: string }>()
const emit = defineEmits<{ signIn: [admission: { mode: 'member' | 'referral'; grantToken?: string }] }>()

const accessOpen = ref(false)
const accessMode = ref<'referral' | 'exception'>('referral')
const referral = ref('')
const accessEmail = ref('')
const accessExplanation = ref('')
const accessBusy = ref(false)
const accessMessage = ref('')
const accessError = ref('')

function openAccess() { accessOpen.value = true; accessMode.value = 'referral'; accessError.value = ''; accessMessage.value = '' }
function existingMemberSignIn() { accessOpen.value = false; emit('signIn', { mode: 'member' }) }
async function verifyReferral() {
  accessBusy.value = true; accessError.value = ''
  try {
    const response = await $fetch<any>('/api/public/access/verify', { method: 'POST', body: { code: referral.value } })
    accessOpen.value = false
    emit('signIn', { mode: 'referral', grantToken: response.grant_token })
  } catch (error: any) { accessError.value = error?.data?.message || error?.message || 'This referral could not be verified.' }
  finally { accessBusy.value = false }
}
async function requestException() {
  accessBusy.value = true; accessError.value = ''; accessMessage.value = ''
  try {
    const response = await $fetch<any>('/api/public/access/request', { method: 'POST', body: { email: accessEmail.value, explanation: accessExplanation.value } })
    accessMessage.value = response.message
  } catch (error: any) { accessError.value = error?.data?.message || error?.message || 'Your request could not be submitted.' }
  finally { accessBusy.value = false }
}

const operatingLayers = [
  { number: '01', title: 'Understands the whole portfolio', copy: 'Companies, products, customers, people, code, accounts, policies, spend, and dependencies live in one continuously updated operating graph.' },
  { number: '02', title: 'Builds the right team for the outcome', copy: 'Madeus selects models, agents, tools, connectors, and human specialists for the work—not one default model for every problem.' },
  { number: '03', title: 'Moves work across the finish line', copy: 'Research becomes a decision. A decision becomes implementation. Implementation is tested, reviewed, deployed, measured, and improved.' },
  { number: '04', title: 'Knows when autonomy must stop', copy: 'Consequential actions carry context, predicted impact, evidence, permissions, and a clear approval boundary before anything irreversible happens.' },
]

const capabilities = [
  ['Portfolio context', 'A digital twin of every company and the relationships between them—so no action is optimized in isolation.'],
  ['Universal intent', 'Describe the outcome once. Madeus decomposes, routes, executes, and keeps the objective intact across every handoff.'],
  ['Best-capability routing', 'Use the strongest model, agent, MCP tool, connected account, or specialist for each step—with cost and rationale visible.'],
  ['Governed execution', 'Identity, permissions, evidence, policy, approvals, rollback, and signed receipts travel with every material action.'],
  ['Independent verification', 'Builders do not grade their own work. Separate checks validate behavior, quality, safety, and the promised outcome.'],
  ['Compounding intelligence', 'Every decision and result improves future routing, forecasts, playbooks, portfolio strategy, and institutional memory.'],
]

useHead({
  title: 'Madeus — The operating system for founders running multiple companies',
  meta: [
    { name: 'description', content: 'Describe the outcome once. Madeus coordinates models, agents, people, codebases, accounts, governance, verification, and release across your entire company portfolio.' },
    { property: 'og:title', content: 'Madeus — One founder. Many companies. One operating system.' },
    { property: 'og:description', content: 'An accountable orchestration system that turns founder intent into governed, verified outcomes.' },
    { name: 'theme-color', content: '#050505' },
  ],
})
</script>

<template>
  <main class="landing">
    <header class="site-nav">
      <a href="#top" class="logo-link" aria-label="Madeus home"><MadeusLogo /></a>
      <nav aria-label="Landing page navigation">
        <a href="#system">Platform</a>
        <a href="#capabilities">Capabilities</a>
        <a href="#governance">Governance</a>
      </nav>
      <button class="nav-login" :disabled="signingIn" @click="openAccess">
        {{ signingIn ? 'Opening…' : 'Enter Madeus' }} <span>↗</span>
      </button>
    </header>

    <section id="top" class="hero">
      <div class="hero-grid" aria-hidden="true"><i v-for="n in 24" :key="n" /></div>
      <div class="hero-copy">
        <p class="kicker"><span /> The private operating system for AI-native founders</p>
        <h1>You steer.<br><em>The hivemind moves five companies forward.</em></h1>
        <p class="hero-lead">Built for Claude- and GPT-native founders running 5+ startups at once. Madeus turns your direction into coordinated, verified work—while you remain at the helm and your full IP stays invisible to any single AI vendor.</p>
        <div class="hero-actions">
          <button class="button primary" :disabled="signingIn" @click="openAccess">{{ signingIn ? 'Opening workspace…' : 'Request entry' }} <span>→</span></button>
          <a class="button secondary" href="#system">See how it works <span>↓</span></a>
        </div>
        <p v-if="authError" class="auth-error" role="alert">{{ authError }}</p>
        <div class="hero-proof" aria-label="Madeus operating principles">
          <span><i /> Member referred</span><span>5+ companies</span><span>Cross-vendor IP shielding</span><span>Verified outcomes</span>
        </div>
      </div>

      <div class="command-model" aria-label="Illustration of Madeus routing a portfolio objective">
        <header><span class="model-logo"><MadeusMark /></span><span>Portfolio command</span><b><i /> live</b></header>
        <div class="portfolio-context"><span>CONTEXT</span><b>All companies</b><small>6 products · 14 codebases · 32 connected accounts</small></div>
        <div class="intent-card">
          <span>FOUNDER INTENT</span>
          <p>Launch the pricing change across the portfolio without disrupting active customers.</p>
          <div><b>Madeus plan</b><small>Impact modeled before execution</small></div>
        </div>
        <ol class="route-list">
          <li><time>01</time><span><b>Simulate</b><small>Customer, revenue, policy, and dependency effects</small></span><i>complete</i></li>
          <li><time>02</time><span><b>Assemble</b><small>Strategy, product, engineering, legal, and growth agents</small></span><i>complete</i></li>
          <li class="active"><time>03</time><span><b>Execute</b><small>Changes moving through isolated workstreams</small></span><i>running</i></li>
          <li><time>04</time><span><b>Verify &amp; release</b><small>Independent QA, staged rollout, and outcome receipt</small></span><i>queued</i></li>
        </ol>
        <footer><span>Expected portfolio value</span><b>+$2.4m</b><small>91% confidence · reversible rollout</small></footer>
      </div>
    </section>

    <section class="definition-strip" aria-label="Madeus definition">
      <span>MADEUS / 01</span>
      <p>Not another place to ask questions.</p>
      <strong>The system accountable for what happens next.</strong>
    </section>

    <section id="system" class="system-section">
      <div class="section-heading">
        <p>From prompt to proof</p>
        <h2>Answers are easy.<br>Outcomes are the work.</h2>
        <span>Most AI products stop at a response or a workflow. Madeus owns the complete loop—from context and judgment through execution, verification, release, and learning.</span>
      </div>
      <div class="layers">
        <article v-for="layer in operatingLayers" :key="layer.number">
          <span>{{ layer.number }}</span><div class="layer-signal" aria-hidden="true"><i /><i /><i /></div><h3>{{ layer.title }}</h3><p>{{ layer.copy }}</p>
        </article>
      </div>
    </section>

    <section class="outcome-loop">
      <div class="loop-copy">
        <p class="dark-kicker"><i /> Founder at the helm</p>
        <h2>You choose the destination.<br>The hivemind navigates.</h2>
        <p>This is the GPS, lane-departure warning, and creative route planner for your portfolio. You keep authority. The platform watches the whole terrain, warns before drift, and continually proposes faster, safer, higher-value routes.</p>
        <div class="loop-stats"><span><b>YOU</b> hold the wheel</span><span><b>CADE</b> predicts the road</span><span><b>∞</b> routes compared</span></div>
      </div>
      <div class="loop-console">
        <header><span>madeus / navigation-hivemind</span><b>FOUNDER CONTROLLED</b></header>
        <ol>
          <li><time>09:41:08</time><b>DESTINATION</b><span>Founder sets outcome, constraints, and authority</span><i>✓</i></li>
          <li><time>09:41:10</time><b>TERRAIN</b><span>AI maps portfolio effects and hidden dependencies</span><i>✓</i></li>
          <li><time>09:41:13</time><b>ROUTES</b><span>Hivemind compares cost, quality, speed, and risk</span><i>✓</i></li>
          <li class="live"><time>09:41:16</time><b>GUIDANCE</b><span>Better route found · 31% faster · $4,820 less</span><i>●</i></li>
          <li><time>—</time><b>GUARDRAIL</b><span>Lane warning before customer-impacting change</span><i>○</i></li>
          <li><time>—</time><b>ARRIVAL</b><span>Independent proof confirms the destination</span><i>○</i></li>
        </ol>
        <footer><span>Founder can pause, reroute, or override at every boundary</span><button type="button">Inspect rationale ↗</button></footer>
      </div>
    </section>

    <section class="hivemind-section">
      <div class="hivemind-copy">
        <p>Embedded capability hivemind</p>
        <h2>Not one assistant.<br><em>An expert organization on demand.</em></h2>
        <p>Legal scrutiny, product judgment, design craft, engineering execution, financial modeling, research, growth, security, and independent QA assemble around each objective—then dissolve when the work is done.</p>
        <div class="hive-receipt"><span>LIVE ASSEMBLY</span><b>18 capabilities · 7 models · 4 companies</b><small>Madeus chose this team for the objective, not the vendor contract.</small></div>
      </div>
      <div class="hive-orbit" aria-label="Animated Madeus capability hivemind">
        <div class="orbit-track track-one" /><div class="orbit-track track-two" /><div class="orbit-track track-three" />
        <div class="hive-core"><MadeusMark /><span>FOUNDER<br>OBJECTIVE</span></div>
        <div class="hive-node legal"><b>LEGAL</b><small>CADE dispute · policy · contracts</small></div>
        <div class="hive-node design"><b>DESIGN</b><small>Brand · product · visual QA</small></div>
        <div class="hive-node build"><b>BUILD</b><small>Architecture · code · release</small></div>
        <div class="hive-node research"><b>RESEARCH</b><small>Markets · evidence · strategy</small></div>
        <div class="hive-node growth"><b>GROWTH</b><small>Pricing · distribution · revenue</small></div>
        <div class="hive-node verify"><b>VERIFY</b><small>Independent · adversarial · signed</small></div>
        <i class="hive-particle p1" /><i class="hive-particle p2" /><i class="hive-particle p3" /><i class="hive-particle p4" />
      </div>
    </section>

    <section class="advantage-section">
      <div class="advantage-heading"><p>Two structural advantages</p><h2>Use every frontier model.<br>Depend on none of them.</h2><span>Madeus treats AI vendors as replaceable capabilities inside a protected execution fabric—optimizing every step while preventing any single provider from reconstructing your company.</span></div>
      <div class="advantage-grid">
        <article class="optimizer-card">
          <header><span>01 / MODEL MARKET</span><b><i /> optimizing live</b></header>
          <div class="model-market">
            <div class="model-row chosen"><span>CLAUDE</span><i><b style="width:92%" /></i><small>architecture</small><strong>$0.84</strong></div>
            <div class="model-row"><span>GPT</span><i><b style="width:78%" /></i><small>research</small><strong>$0.31</strong></div>
            <div class="model-row"><span>GEMINI</span><i><b style="width:68%" /></i><small>large context</small><strong>$0.19</strong></div>
            <div class="model-row"><span>LOCAL</span><i><b style="width:55%" /></i><small>private transforms</small><strong>$0.02</strong></div>
          </div>
          <div class="saving-route"><span>Quality floor</span><b>97%</b><span>Cost avoided</span><b>68%</b><span>Vendor lock-in</span><b>0</b></div>
          <h3>Portfolio-wide model economics.</h3><p>Every subtask is auctioned across eligible models using realized quality, reliability, latency, privacy, and marginal cost—not logo loyalty.</p>
        </article>
        <article class="privacy-card">
          <header><span>02 / IP SHIELD</span><b>need-to-know routing</b></header>
          <div class="shard-map">
            <div class="vault"><span>MADEUS</span><b>Encrypted project graph</b><small>Only you hold the complete context</small></div>
            <div class="vendor v1"><span>MODEL A</span><b>UI component</b><small>4% context</small></div>
            <div class="vendor v2"><span>MODEL B</span><b>Pricing research</b><small>3% context</small></div>
            <div class="vendor v3"><span>MODEL C</span><b>Test generation</b><small>2% context</small></div>
            <div class="vendor v4"><span>LOCAL</span><b>Secret-bearing join</b><small>private</small></div>
            <svg viewBox="0 0 600 260" aria-hidden="true"><path d="M300 130C220 130 190 52 105 52M300 130C385 130 410 52 500 52M300 130C210 130 180 210 92 210M300 130C390 130 420 210 510 210"/><circle cx="300" cy="130" r="4"/></svg>
          </div>
          <h3>No single AI vendor sees the invention.</h3><p>Madeus fragments work across providers, redacts unnecessary context, joins sensitive outputs inside your boundary, and keeps the full dependency graph out of every vendor transcript.</p>
        </article>
      </div>
    </section>

    <section id="capabilities" class="capability-section">
      <div class="section-heading compact">
        <p>One control plane</p>
        <h2>The leverage of a portfolio team.<br>Without the coordination tax.</h2>
        <span>Keep the tools and specialists that are already excellent. Madeus connects them into one context-aware operating system and fills the gaps dynamically.</span>
      </div>
      <div class="capability-grid">
        <article v-for="(capability, index) in capabilities" :key="capability[0]">
          <span>0{{ index + 1 }}</span><div class="capability-glyph" aria-hidden="true"><i /><i /><i /></div><h3>{{ capability[0] }}</h3><p>{{ capability[1] }}</p>
        </article>
      </div>
    </section>

    <section id="governance" class="portfolio-section">
      <div class="portfolio-visual">
        <header><MadeusLogo compact /><span>PORTFOLIO GRAPH</span><b><i /> synchronized</b></header>
        <div class="portfolio-map">
          <svg viewBox="0 0 680 410" aria-hidden="true">
            <defs><linearGradient id="routeGlow" x1="0" x2="1"><stop stop-color="#8d8d87"/><stop offset=".5" stop-color="#2f9a65"/><stop offset="1" stop-color="#8d8d87"/></linearGradient></defs>
            <path class="map-route r1" d="M340 202C270 145 225 90 135 88"/><path class="map-route r2" d="M340 202C420 142 455 88 552 88"/><path class="map-route r3" d="M340 202C260 265 220 320 120 328"/><path class="map-route r4" d="M340 202C420 265 470 316 565 328"/>
            <path class="map-route cross" d="M135 88C310 20 425 35 552 88M120 328C275 382 435 380 565 328"/>
            <circle class="pulse-dot d1" cx="225" cy="133" r="5"/><circle class="pulse-dot d2" cx="454" cy="125" r="5"/><circle class="pulse-dot d3" cx="238" cy="278" r="5"/><circle class="pulse-dot d4" cx="455" cy="275" r="5"/>
          </svg>
          <div class="map-core"><MadeusMark /><b>Portfolio<br>hivemind</b><small>26 objectives routing</small></div>
          <div class="company-node tomorrow"><span>TOMORROW</span><b>Risk &amp; markets</b><small><i /> pricing hedge simulated</small></div>
          <div class="company-node smarter"><span>SMARTER</span><b>Legal operating system</b><small><i /> 4 matters advanced</small></div>
          <div class="company-node studio"><span>STUDIO</span><b>Design &amp; venture</b><small><i /> brand system verified</small></div>
          <div class="company-node newco"><span>NEWCO 05</span><b>Stealth build</b><small><i /> release candidate ready</small></div>
          <div class="portfolio-ticker"><span>OPPORTUNITY FOUND</span><b>Tomorrow risk model → Smarter contract product</b><small>+$380k expected portfolio value</small></div>
        </div>
      </div>
      <div class="portfolio-copy">
        <p>Built for the multi-company founder</p>
        <h2>Your portfolio is already connected.<br><em>Your operating system should be too.</em></h2>
        <p>One company’s deployment changes another company’s cost. One customer relationship creates opportunities elsewhere. One connector, policy, or capability can safely serve the whole portfolio. Madeus sees—and operates—the system founders already hold in their heads.</p>
        <ul><li>Shared capability and connector passport</li><li>Cross-company dependency and opportunity graph</li><li>Portfolio-level cost, risk, and outcome optimization</li><li>Just-in-time guidance before consequential actions</li></ul>
      </div>
    </section>

    <section class="principles">
      <div><p>Designed for consequence</p><h2>Move faster.<br>Stay in control.</h2></div>
      <article><span>01</span><h3>Ambient, not attention-seeking.</h3><p>Agents work quietly and surface finished work, exceptions, and decisions—not a stream of supervision tasks.</p></article>
      <article><span>02</span><h3>Adaptive, not unpredictable.</h3><p>Madeus learns how you operate while permanent destinations, permissions, and constitutional boundaries stay stable.</p></article>
      <article><span>03</span><h3>Autonomous, not unaccountable.</h3><p>You can delegate execution without delegating responsibility. Rationale, evidence, reversibility, and outcomes remain visible.</p></article>
    </section>

    <section class="closing">
      <div class="closing-course" aria-hidden="true">
        <svg viewBox="0 0 1200 420"><path class="course-lane left" d="M-40 360C210 350 240 90 510 210S820 330 1240 55"/><path class="course-lane center" d="M-40 390C250 380 275 130 520 235S820 355 1240 90"/><path class="course-lane right" d="M-40 420C280 410 310 170 535 260S840 385 1240 125"/><circle cx="520" cy="235" r="7"/><circle cx="930" cy="245" r="5"/></svg>
        <span class="course-warning">BETTER ROUTE<br><b>31% faster</b></span><span class="course-arrival">VERIFIED ARRIVAL<br><b>Outcome proven</b></span>
      </div>
      <p>You hold the wheel. Madeus makes the whole map usable.</p>
      <h2>Five companies.<br>One founder’s direction.</h2>
      <button class="button light-cta" :disabled="signingIn" @click="openAccess">{{ signingIn ? 'Opening Madeus…' : 'Request member access' }} <span>→</span></button>
    </section>

    <div v-if="accessOpen" class="access-overlay" role="presentation" @click.self="accessOpen = false">
      <section class="access-modal" role="dialog" aria-modal="true" aria-labelledby="access-title">
        <header><MadeusLogo /><button type="button" aria-label="Close access request" @click="accessOpen = false">×</button></header>
        <div class="access-intro"><span>PRIVATE MEMBERSHIP</span><h2 id="access-title">Built for founders already operating at the edge.</h2><p>New membership is referral-only so the network can preserve trust, signal quality, and meaningful shared capability.</p></div>
        <div class="access-tabs" role="tablist"><button :class="{ active: accessMode === 'referral' }" @click="accessMode = 'referral'; accessError = ''; accessMessage = ''">I have a referral</button><button :class="{ active: accessMode === 'exception' }" @click="accessMode = 'exception'; accessError = ''; accessMessage = ''">Request an exception</button></div>
        <form v-if="accessMode === 'referral'" class="access-form" @submit.prevent="verifyReferral">
          <label for="referral-code">Member referral code</label><input id="referral-code" v-model="referral" autocomplete="one-time-code" placeholder="MDS-XXXXXXXXXX" required />
          <small>Referral codes are issued by existing members, limited-use, and verified before Google sign-in.</small>
          <button class="access-submit" :disabled="accessBusy || !referral.trim()">{{ accessBusy ? 'Verifying…' : 'Verify referral & continue' }} <span>→</span></button>
          <button type="button" class="member-login" @click="existingMemberSignIn">Already a member? Sign in without a referral ↗</button>
        </form>
        <form v-else class="access-form" @submit.prevent="requestException">
          <label for="access-email">Work email</label><input id="access-email" v-model="accessEmail" type="email" autocomplete="email" placeholder="you@company.com" required />
          <label for="access-explanation">Why should Madeus make an exception?</label><textarea id="access-explanation" v-model="accessExplanation" rows="5" minlength="80" maxlength="3000" placeholder="Tell us what you have built, how many companies you operate, and what the Madeus network could uniquely unlock…" required />
          <small>Explain the portfolio, your AI-native operating model, and the value you would contribute to the member network.</small>
          <button class="access-submit" :disabled="accessBusy || accessExplanation.trim().length < 80">{{ accessBusy ? 'Submitting…' : 'Submit for operator review' }} <span>→</span></button>
        </form>
        <p v-if="accessError" class="access-feedback error" role="alert">{{ accessError }}</p><p v-if="accessMessage" class="access-feedback success" role="status">{{ accessMessage }}</p>
        <footer>Admission does not broaden connector permissions or execution authority. Every account and consequential action remains separately consented and governed.</footer>
      </section>
    </div>

    <SystemStatusFooter />
    <footer class="site-footer"><MadeusLogo /><p>Outcome orchestration for the multi-company founder.</p><div><a href="#system">Platform</a><a href="#governance">Governance</a><span>© {{ new Date().getFullYear() }} Madeus</span></div></footer>
  </main>
</template>

<style scoped>
.landing{--black:#050505;--ink:#111;--muted:#6f6f6b;--line:#deded9;--paper:#f7f7f4;overflow:hidden;background:#fff;color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,sans-serif}.landing :deep(*){box-sizing:border-box}.site-nav{position:absolute;z-index:20;top:0;left:0;right:0;height:78px;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;padding:0 clamp(20px,3.5vw,56px);border-bottom:1px solid rgba(15,15,15,.09)}.logo-link{justify-self:start;color:var(--ink);text-decoration:none}.site-nav nav{display:flex;gap:32px}.site-nav nav a,.site-footer a{color:#555;text-decoration:none;font-size:11px}.site-nav nav a:hover,.site-footer a:hover{color:#000}.nav-login{justify-self:end;border:1px solid #161616;border-radius:999px;background:#0a0a0a;padding:10px 15px;color:#fff;font-size:10px;font-weight:650;cursor:pointer}.nav-login span{margin-left:18px}.nav-login:disabled,.button:disabled{cursor:wait;opacity:.55}.hero{position:relative;min-height:850px;display:grid;grid-template-columns:minmax(0,1.02fr) minmax(480px,.98fr);align-items:center;gap:5vw;padding:130px clamp(20px,3.5vw,56px) 76px;background:radial-gradient(circle at 88% 15%,rgba(45,106,82,.12),transparent 29%),#fafafa}.hero-grid{position:absolute;inset:78px 0 0;display:grid;grid-template-columns:repeat(6,1fr);pointer-events:none}.hero-grid i{border-right:1px solid rgba(0,0,0,.045);border-bottom:1px solid rgba(0,0,0,.045)}.hero-copy,.command-model{position:relative;z-index:2}.kicker,.dark-kicker{display:flex;align-items:center;gap:9px;margin:0 0 25px;color:#555;font:650 9px/1 JetBrains Mono,monospace;letter-spacing:.11em;text-transform:uppercase}.kicker span,.dark-kicker i,.command-model header b i,.portfolio-visual header b i{display:inline-block;width:6px;height:6px;border-radius:50%;background:#2f9a65;box-shadow:0 0 0 4px rgba(47,154,101,.13)}.hero h1,.section-heading h2,.loop-copy h2,.portfolio-copy h2,.principles h2,.closing h2{margin:0;font-weight:470;letter-spacing:-.065em;line-height:.95}.hero h1{max-width:820px;font-size:clamp(62px,7vw,112px)}.hero h1 em,.portfolio-copy h2 em{color:#7c7c76;font-style:normal}.hero-lead{max-width:720px;margin:34px 0 0;color:#575753;font-size:clamp(16px,1.45vw,21px);line-height:1.6;letter-spacing:-.018em}.hero-actions{display:flex;gap:11px;margin-top:36px}.button{min-width:178px;display:inline-flex;align-items:center;justify-content:space-between;border-radius:999px;padding:14px 17px;text-decoration:none;font-size:11px;transition:transform .18s,background .18s;cursor:pointer}.button:hover{transform:translateY(-2px)}.button.primary{border:1px solid #050505;background:#050505;color:#fff}.button.secondary{border:1px solid #cfcfca;background:rgba(255,255,255,.7);color:#111}.auth-error{max-width:520px;margin:14px 0 0;color:#b42318;font-size:11px}.hero-proof{display:flex;flex-wrap:wrap;gap:9px 22px;margin-top:47px;padding-top:18px;border-top:1px solid #d7d7d2;color:#777;font:600 8px/1 JetBrains Mono,monospace;letter-spacing:.06em;text-transform:uppercase}.hero-proof span:first-child{color:#222}.hero-proof i{display:inline-block;width:5px;height:5px;margin-right:7px;border-radius:50%;background:#2f9a65}.command-model{overflow:hidden;border:1px solid #292929;border-radius:18px;background:#080808;color:#fff;box-shadow:0 38px 100px rgba(0,0,0,.24)}.command-model>header{height:57px;display:flex;align-items:center;gap:10px;padding:0 17px;border-bottom:1px solid #242424;color:#a5a5a0;font:600 8px/1 JetBrains Mono,monospace;letter-spacing:.08em;text-transform:uppercase}.model-logo{width:24px;height:24px;color:#fff;--mark-ink:#080808;--mark-signal:#246949}.command-model>header b{display:flex;align-items:center;gap:8px;margin-left:auto;color:#6dc993;font-size:7px}.portfolio-context{display:grid;grid-template-columns:auto 1fr;gap:5px 13px;padding:18px 20px;border-bottom:1px solid #242424}.portfolio-context span,.intent-card>span{grid-row:1/3;color:#666;font:600 7px/1 JetBrains Mono,monospace;letter-spacing:.1em}.portfolio-context b{font-size:11px;font-weight:550}.portfolio-context small{color:#777;font-size:8px}.intent-card{margin:18px;border:1px solid #343434;border-radius:10px;background:#111;padding:17px}.intent-card p{margin:12px 0 18px;font-size:15px;line-height:1.45;letter-spacing:-.025em}.intent-card div{display:flex;justify-content:space-between;border-top:1px solid #2b2b2b;padding-top:12px}.intent-card div b{font-size:8px;font-weight:600}.intent-card div small{color:#72726f;font-size:7px}.route-list{margin:0;padding:0 18px;list-style:none}.route-list li{min-height:58px;display:grid;grid-template-columns:28px 1fr auto;gap:11px;align-items:center;border-top:1px solid #202020;color:#62625f}.route-list time{font:8px JetBrains Mono,monospace}.route-list span{display:flex;flex-direction:column;gap:4px}.route-list b{color:#aaa;font-size:9px;font-weight:550}.route-list small{font-size:7px}.route-list>li>i{font:normal 6px JetBrains Mono,monospace;text-transform:uppercase}.route-list li.active{margin:0 -18px;padding:0 18px;background:linear-gradient(90deg,rgba(74,190,124,.12),transparent);color:#6dc993}.route-list li.active b{color:#fff}.command-model>footer{display:grid;grid-template-columns:1fr auto;gap:4px 20px;margin-top:9px;padding:18px 20px;background:#101b15;border-top:1px solid #264433}.command-model>footer span{color:#7f9a88;font-size:8px}.command-model>footer b{font:500 23px/1 Inter,sans-serif}.command-model>footer small{grid-column:1/-1;color:#668071;font-size:7px}.definition-strip{display:grid;grid-template-columns:.45fr .8fr 1.6fr;gap:4vw;align-items:center;padding:34px clamp(20px,3.5vw,56px);border-top:1px solid #111;border-bottom:1px solid var(--line);background:#fff}.definition-strip span{font:8px JetBrains Mono,monospace}.definition-strip p{margin:0;color:#777;font-size:11px}.definition-strip strong{font-size:clamp(18px,2.2vw,31px);font-weight:500;letter-spacing:-.045em}.system-section,.capability-section{padding:140px clamp(20px,3.5vw,56px)}.section-heading{display:grid;grid-template-columns:.65fr 1.35fr 1fr;gap:5vw;align-items:start;margin-bottom:68px}.section-heading>p{margin:8px 0 0;font:650 9px/1 JetBrains Mono,monospace;letter-spacing:.11em;text-transform:uppercase}.section-heading h2{font-size:clamp(48px,5.8vw,86px)}.section-heading>span{max-width:460px;margin-top:8px;color:var(--muted);font-size:13px;line-height:1.7}.layers{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid #111;border-left:1px solid var(--line)}.layers article,.capability-grid article{min-height:390px;display:flex;flex-direction:column;padding:20px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}.layers article>span,.capability-grid article>span{font:8px JetBrains Mono,monospace}.layer-signal,.capability-glyph{height:115px;display:flex;align-items:center;justify-content:center}.layer-signal i{width:32px;height:32px;border:1px solid #888;border-radius:50%}.layer-signal i+ i{margin-left:-9px}.layer-signal i:nth-child(2){background:#111;border-color:#111}.layer-signal i:nth-child(3){width:14px;height:14px;background:#fff}.layers h3,.capability-grid h3{margin:auto 0 16px;font-size:19px;font-weight:550;letter-spacing:-.045em}.layers p,.capability-grid p{margin:0;color:var(--muted);font-size:10px;line-height:1.65}.outcome-loop{display:grid;grid-template-columns:1fr 1.1fr;gap:8vw;padding:145px clamp(20px,3.5vw,56px);background:#050505;color:#fff}.dark-kicker{color:#777}.dark-kicker i{background:#fff;box-shadow:0 0 0 4px rgba(255,255,255,.12)}.loop-copy h2{font-size:clamp(58px,6.6vw,96px)}.loop-copy>p:nth-of-type(2){max-width:620px;margin:36px 0 0;color:#94948f;font-size:13px;line-height:1.75}.loop-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:52px;border-top:1px solid #333}.loop-stats span{display:flex;flex-direction:column;padding-top:17px;color:#6f6f6b;font-size:8px}.loop-stats b{margin-bottom:5px;color:#fff;font-size:22px;font-weight:500}.loop-console{align-self:center;border:1px solid #383838;background:#0b0b0b;box-shadow:0 35px 90px rgba(0,0,0,.4)}.loop-console header,.loop-console footer{height:49px;display:flex;align-items:center;justify-content:space-between;padding:0 17px;border-bottom:1px solid #2d2d2d;color:#777;font:7px JetBrains Mono,monospace}.loop-console header b{color:#aaa;font-size:7px}.loop-console ol{margin:0;padding:0 19px;list-style:none}.loop-console li{min-height:57px;display:grid;grid-template-columns:66px 76px 1fr auto;gap:7px;align-items:center;border-bottom:1px solid #202020;color:#696966;font:7px JetBrains Mono,monospace}.loop-console li b{font-weight:500;color:#8c8c88}.loop-console li.live{margin:0 -19px;padding:0 19px;background:linear-gradient(90deg,rgba(255,255,255,.07),transparent);color:#fff}.loop-console li.live b{color:#fff}.loop-console footer{border-top:1px solid #2d2d2d;border-bottom:0}.loop-console footer button{border:0;background:none;color:#ddd;font:7px JetBrains Mono,monospace}.section-heading.compact{margin-bottom:82px}.capability-grid{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid #111;border-left:1px solid var(--line)}.capability-grid article{min-height:360px}.capability-glyph i{display:block;width:16px;height:68px;border:1px solid #aaa;border-radius:99px;transform:rotate(30deg)}.capability-glyph i:nth-child(2){height:96px;margin:0 4px;background:#111;border-color:#111}.capability-glyph i:nth-child(3){height:45px}.portfolio-section{display:grid;grid-template-columns:1.05fr .95fr;gap:8vw;align-items:center;padding:130px clamp(20px,3.5vw,56px);background:var(--paper)}.portfolio-visual{overflow:hidden;border:1px solid #ccc;border-radius:16px;background:#fff;box-shadow:0 30px 80px rgba(0,0,0,.09)}.portfolio-visual>header{height:60px;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;padding:0 16px;border-bottom:1px solid var(--line);font:7px JetBrains Mono,monospace;color:#777}.portfolio-visual>header b{justify-self:end;display:flex;align-items:center;gap:7px;color:#3d805b;font-size:7px}.company-grid{display:grid;grid-template-columns:1fr 1fr}.company-grid article{min-height:145px;display:flex;flex-direction:column;padding:20px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}.company-grid article:nth-child(2){border-right:0}.company-grid article>span{font:7px JetBrains Mono,monospace;color:#888}.company-grid article b{margin:auto 0 6px;font-size:14px;font-weight:550}.company-grid article small{color:#888;font-size:8px}.company-grid article.shared{grid-column:1/-1;min-height:170px;border-right:0;background:#0b0b0b;color:#fff}.company-grid article.shared span,.company-grid article.shared small{color:#777}.portfolio-copy>p:first-child{font:650 9px JetBrains Mono,monospace;letter-spacing:.1em;text-transform:uppercase}.portfolio-copy h2{margin-top:24px;font-size:clamp(42px,4.8vw,72px)}.portfolio-copy>p:nth-of-type(2){margin:32px 0 0;color:var(--muted);font-size:13px;line-height:1.75}.portfolio-copy ul{margin:30px 0 0;padding:0;list-style:none;border-top:1px solid #d4d4cf}.portfolio-copy li{padding:12px 0;border-bottom:1px solid #d4d4cf;font-size:10px}.portfolio-copy li:before{content:'✓';margin-right:10px;color:#2f7954}.principles{display:grid;grid-template-columns:1.2fr repeat(3,1fr);border-bottom:1px solid var(--line)}.principles>*{min-height:430px;padding:78px 28px;border-right:1px solid var(--line)}.principles>div{background:#f1f1ee}.principles>div p{margin:0;font:650 9px JetBrains Mono,monospace;letter-spacing:.1em;text-transform:uppercase}.principles h2{margin-top:112px;font-size:45px}.principles article{display:flex;flex-direction:column}.principles article>span{font:8px JetBrains Mono,monospace}.principles article h3{margin:auto 0 18px;font-size:20px;font-weight:550;letter-spacing:-.04em}.principles article p{margin:0;color:#777;font-size:10px;line-height:1.65}.closing{position:relative;overflow:hidden;padding:155px 20px;text-align:center;background:#050505;color:#fff}.closing>p{position:relative;z-index:2;margin:0;color:#888;font-size:11px}.closing h2{position:relative;z-index:2;margin:18px 0 48px;font-size:clamp(68px,9vw,138px)}.button.light-cta{position:relative;z-index:2;border:0;background:#fff;color:#111}.closing-signal{position:absolute;left:50%;top:50%;width:540px;height:540px;display:grid;place-items:center;transform:translate(-50%,-50%)}.closing-signal i{position:absolute;border:1px solid #242424;border-radius:50%;animation:signal 4s ease-in-out infinite}.closing-signal i:nth-child(1){width:190px;height:190px}.closing-signal i:nth-child(2){width:350px;height:350px;animation-delay:.4s}.closing-signal i:nth-child(3){width:520px;height:520px;animation-delay:.8s}.closing-signal :deep(.madeus-mark){width:54px;height:54px;color:#fff;--mark-ink:#050505;--mark-signal:#2f7954}.site-footer{display:grid;grid-template-columns:1fr 1fr 1fr;align-items:end;gap:25px;padding:52px clamp(20px,3.5vw,56px);background:#050505;color:#777;border-top:1px solid #222}.site-footer p{margin:0;font-size:9px}.site-footer>div{display:flex;justify-content:flex-end;gap:18px;align-items:center;font-size:8px}.site-footer :deep(.madeus-logo-mark){color:#fff;--mark-ink:#050505}.site-footer :deep(.madeus-wordmark b){color:#fff}@keyframes signal{0%,100%{opacity:.4;transform:scale(.92)}50%{opacity:1;transform:scale(1)}}@media(max-width:1050px){.hero{grid-template-columns:1fr;padding-top:150px}.hero-copy{max-width:900px}.command-model{width:min(720px,100%)}.layers{grid-template-columns:1fr 1fr}.outcome-loop,.portfolio-section{grid-template-columns:1fr}.capability-grid{grid-template-columns:1fr 1fr}.principles{grid-template-columns:1fr 1fr}.principles>div{grid-column:1/-1}.site-nav{grid-template-columns:1fr auto}.site-nav nav{display:none}}@media(max-width:680px){.site-nav{height:66px;padding:0 16px}.site-nav :deep(.madeus-wordmark small){display:none}.nav-login{padding:9px 11px}.nav-login span{margin-left:8px}.hero{min-height:auto;padding:118px 17px 62px;grid-template-columns:1fr}.hero-grid{top:66px;grid-template-columns:repeat(3,1fr)}.hero h1{font-size:17vw}.hero-lead{font-size:15px}.hero-actions{align-items:flex-start;flex-direction:column}.hero-proof{line-height:1.6}.command-model{margin-top:25px;border-radius:12px}.portfolio-context small,.intent-card div small{display:none}.route-list li{grid-template-columns:24px 1fr}.route-list>li>i{display:none}.definition-strip{grid-template-columns:1fr;gap:9px}.system-section,.capability-section{padding:90px 16px}.section-heading{display:block}.section-heading h2{margin:19px 0 25px}.layers,.capability-grid{grid-template-columns:1fr}.layers article,.capability-grid article{min-height:330px}.outcome-loop,.portfolio-section{padding:95px 17px}.loop-console li{grid-template-columns:54px 64px 1fr}.loop-console li i{display:none}.portfolio-visual>header{grid-template-columns:1fr auto}.portfolio-visual>header>span{display:none}.company-grid{grid-template-columns:1fr}.company-grid article{border-right:0}.company-grid article.shared{grid-column:auto}.principles{grid-template-columns:1fr}.principles>div{grid-column:auto}.principles>*{min-height:310px;padding:55px 22px}.principles h2{margin-top:70px}.closing{padding:110px 17px}.site-footer{grid-template-columns:1fr}.site-footer>div{justify-content:flex-start;flex-wrap:wrap}}@media(prefers-reduced-motion:reduce){.landing *{animation:none!important;scroll-behavior:auto!important}}
.command-model{animation:consoleFloat 7s ease-in-out infinite}.hero-grid i:nth-child(7n){animation:gridGlint 4.8s ease-in-out infinite}.hero-grid i:nth-child(11n){animation-delay:-2.1s}.route-list li.active{position:relative;overflow:hidden}.route-list li.active:after{content:'';position:absolute;inset:0;background:linear-gradient(90deg,transparent,rgba(109,201,147,.12),transparent);transform:translateX(-100%);animation:routeSweep 2.8s ease-in-out infinite}.loop-console li.live i{animation:liveBlink 1.5s ease-in-out infinite}.layers article,.capability-grid article{transition:background .24s ease,transform .24s ease,box-shadow .24s ease}.layers article:hover,.capability-grid article:hover{position:relative;z-index:2;transform:translateY(-5px);background:#fff;box-shadow:0 28px 70px #11111112}.site-nav{backdrop-filter:blur(12px)}@keyframes consoleFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-7px)}}@keyframes gridGlint{0%,72%,100%{background:transparent}80%{background:rgba(99,91,255,.055)}}@keyframes routeSweep{0%,38%{transform:translateX(-100%)}75%,100%{transform:translateX(100%)}}@keyframes liveBlink{0%,100%{opacity:.35}50%{opacity:1;text-shadow:0 0 12px #6dc993}}@media(prefers-reduced-motion:reduce){.command-model{animation:none}.landing *{animation:none!important;scroll-behavior:auto!important}}

.hivemind-section{display:grid;grid-template-columns:.88fr 1.12fr;gap:7vw;align-items:center;padding:130px clamp(20px,3.5vw,56px);background:#f1f1ee}.hivemind-copy>p:first-child,.advantage-heading>p{font:650 9px JetBrains Mono,monospace;letter-spacing:.1em;text-transform:uppercase}.hivemind-copy h2,.advantage-heading h2{margin:22px 0 0;font-size:clamp(48px,5.6vw,84px);font-weight:470;letter-spacing:-.065em;line-height:.96}.hivemind-copy h2 em{color:#777;font-style:normal}.hivemind-copy>p:nth-of-type(2){max-width:650px;margin:31px 0 0;color:#686864;font-size:13px;line-height:1.75}.hive-receipt{display:flex;flex-direction:column;gap:7px;margin-top:34px;border-left:2px solid #2f9a65;padding:13px 16px;background:rgba(255,255,255,.6)}.hive-receipt span{color:#45815f;font:7px JetBrains Mono,monospace}.hive-receipt b{font-size:11px}.hive-receipt small{color:#777;font-size:8px}.hive-orbit{position:relative;min-height:620px;border:1px solid #cecec9;border-radius:50%;background:radial-gradient(circle,#fff 0 11%,transparent 11.5%),radial-gradient(circle,rgba(47,154,101,.08),transparent 58%)}.orbit-track{position:absolute;inset:50%;border:1px solid #c6c6c1;border-radius:50%;transform:translate(-50%,-50%)}.track-one{width:39%;height:39%;border-style:dashed;animation:orbitSpin 21s linear infinite}.track-two{width:68%;height:68%;animation:orbitSpin 34s linear infinite reverse}.track-three{width:92%;height:92%;border-style:dashed;animation:orbitSpin 52s linear infinite}.hive-core{position:absolute;z-index:3;left:50%;top:50%;width:112px;height:112px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;transform:translate(-50%,-50%);border-radius:50%;background:#090909;color:#fff;box-shadow:0 0 0 12px rgba(255,255,255,.84),0 0 0 13px #cfcfca}.hive-core :deep(.madeus-mark){width:36px;height:36px;color:#fff;--mark-ink:#090909}.hive-core span{text-align:center;color:#aaa;font:6px/1.4 JetBrains Mono,monospace;letter-spacing:.08em}.hive-node{position:absolute;z-index:4;min-width:145px;padding:12px 14px;border:1px solid #bdbdb8;border-radius:10px;background:rgba(255,255,255,.94);box-shadow:0 10px 30px rgba(0,0,0,.06);animation:nodeFloat 5s ease-in-out infinite}.hive-node b,.hive-node small{display:block}.hive-node b{font:650 8px JetBrains Mono,monospace;letter-spacing:.08em}.hive-node small{margin-top:5px;color:#777;font-size:7px}.hive-node.legal{left:3%;top:18%}.hive-node.design{right:1%;top:16%;animation-delay:-1s}.hive-node.build{right:-2%;top:52%;animation-delay:-2s}.hive-node.research{left:0;top:57%;animation-delay:-3s}.hive-node.growth{left:26%;bottom:1%;animation-delay:-4s}.hive-node.verify{right:23%;bottom:0;animation-delay:-2.5s}.hive-particle{position:absolute;z-index:2;width:7px;height:7px;border-radius:50%;background:#2f9a65;box-shadow:0 0 14px #2f9a65}.p1{left:23%;top:34%;animation:particleOne 4s ease-in-out infinite}.p2{right:24%;top:32%;animation:particleTwo 5s ease-in-out infinite}.p3{left:29%;bottom:27%;animation:particleTwo 4.6s ease-in-out infinite reverse}.p4{right:28%;bottom:25%;animation:particleOne 5.4s ease-in-out infinite reverse}

.advantage-section{padding:135px clamp(20px,3.5vw,56px);background:#fff}.advantage-heading{display:grid;grid-template-columns:.55fr 1.4fr 1fr;gap:5vw;align-items:start;margin-bottom:66px}.advantage-heading h2{margin:0}.advantage-heading>span{color:#6f6f6b;font-size:13px;line-height:1.7}.advantage-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.advantage-grid article{min-height:610px;display:flex;flex-direction:column;overflow:hidden;border:1px solid #d7d7d2;border-radius:16px;background:#fafafa}.advantage-grid article>header{height:52px;display:flex;align-items:center;justify-content:space-between;padding:0 17px;border-bottom:1px solid #ddd;color:#777;font:7px JetBrains Mono,monospace}.advantage-grid article>header b{font-weight:500;color:#555}.advantage-grid article>header b i{display:inline-block;width:5px;height:5px;margin-right:6px;border-radius:50%;background:#2f9a65}.model-market{padding:24px}.model-row{display:grid;grid-template-columns:58px 1fr 105px 45px;gap:10px;align-items:center;min-height:49px;border-bottom:1px solid #e3e3df;color:#777}.model-row>span{font:7px JetBrains Mono,monospace}.model-row>i{height:4px;overflow:hidden;border-radius:4px;background:#deded9}.model-row>i b{display:block;height:100%;background:#999}.model-row.chosen>i b{background:#2f9a65;animation:barPulse 2.8s ease-in-out infinite}.model-row small{font-size:7px}.model-row strong{text-align:right;color:#222;font:8px JetBrains Mono,monospace}.saving-route{display:grid;grid-template-columns:1fr auto;gap:10px;margin:0 24px;padding:18px;border-radius:11px;background:#0a0a0a;color:#777;font-size:8px}.saving-route b{color:#79d49f;font:500 18px Inter,sans-serif}.advantage-grid h3{margin:auto 24px 13px;font-size:24px;font-weight:540;letter-spacing:-.045em}.advantage-grid article>p{margin:0 24px 25px;color:#777;font-size:10px;line-height:1.65}.shard-map{position:relative;height:350px;margin:0 18px}.shard-map svg{position:absolute;inset:0;width:100%;height:100%}.shard-map path{fill:none;stroke:#aaa;stroke-width:1;stroke-dasharray:5 6;animation:routeDash 18s linear infinite}.shard-map circle{fill:#2f9a65}.vault,.vendor{position:absolute;z-index:2;display:flex;flex-direction:column;border:1px solid #cfcfca;background:#fff;padding:11px}.vault{left:50%;top:50%;width:170px;transform:translate(-50%,-50%);border-color:#222;background:#090909;color:#fff;box-shadow:0 20px 40px rgba(0,0,0,.18)}.vendor{width:125px}.v1{left:0;top:20px}.v2{right:0;top:20px}.v3{left:0;bottom:18px}.v4{right:0;bottom:18px}.vault span,.vendor span{font:6px JetBrains Mono,monospace;color:#777}.vault b,.vendor b{margin-top:8px;font-size:9px}.vault small,.vendor small{margin-top:5px;color:#888;font-size:7px}

.portfolio-map{position:relative;min-height:510px;overflow:hidden;background:radial-gradient(circle at 50% 42%,rgba(47,154,101,.09),transparent 27%),linear-gradient(#fff,#f7f7f4)}.portfolio-map>svg{position:absolute;inset:0;width:100%;height:82%}.map-route{fill:none;stroke:url(#routeGlow);stroke-width:1.5;stroke-dasharray:7 8;animation:routeDash 18s linear infinite}.map-route.cross{stroke:#c5c5c0;stroke-width:1;animation-direction:reverse}.pulse-dot{fill:#2f9a65;filter:drop-shadow(0 0 6px #2f9a65);animation:mapPulse 2.2s ease-in-out infinite}.d2{animation-delay:-.5s}.d3{animation-delay:-1s}.d4{animation-delay:-1.5s}.map-core{position:absolute;z-index:3;left:50%;top:39%;width:116px;height:116px;display:flex;flex-direction:column;align-items:center;justify-content:center;transform:translate(-50%,-50%);border-radius:50%;background:#090909;color:#fff;box-shadow:0 0 0 12px rgba(255,255,255,.9),0 0 0 13px #aaa}.map-core :deep(.madeus-mark){width:30px;height:30px;color:#fff;--mark-ink:#090909}.map-core b{margin-top:7px;text-align:center;font-size:9px}.map-core small{margin-top:4px;color:#777;font-size:6px}.company-node{position:absolute;z-index:4;width:145px;padding:12px;border:1px solid #c7c7c2;border-radius:9px;background:rgba(255,255,255,.95);box-shadow:0 10px 30px rgba(0,0,0,.06);animation:nodeFloat 5s ease-in-out infinite}.company-node span,.company-node b,.company-node small{display:block}.company-node span{font:7px JetBrains Mono,monospace;color:#777}.company-node b{margin-top:7px;font-size:10px}.company-node small{margin-top:7px;color:#55816a;font-size:7px}.company-node small i{display:inline-block;width:5px;height:5px;margin-right:5px;border-radius:50%;background:#2f9a65}.company-node.tomorrow{left:4%;top:7%}.company-node.smarter{right:4%;top:7%;animation-delay:-1s}.company-node.studio{left:3%;bottom:24%;animation-delay:-2s}.company-node.newco{right:3%;bottom:24%;animation-delay:-3s}.portfolio-ticker{position:absolute;left:18px;right:18px;bottom:17px;display:grid;grid-template-columns:auto 1fr auto;gap:14px;align-items:center;border:1px solid #284d38;background:#0d1b13;padding:13px;color:#fff}.portfolio-ticker span{color:#6dc993;font:6px JetBrains Mono,monospace}.portfolio-ticker b{font-size:9px;font-weight:550}.portfolio-ticker small{color:#86ad95;font-size:7px}

.closing{min-height:650px;display:flex;flex-direction:column;align-items:center;justify-content:center}.closing-course{position:absolute;inset:auto 0 0;height:82%;pointer-events:none}.closing-course svg{position:absolute;inset:0;width:100%;height:100%}.course-lane{fill:none;stroke:#2d2d2d;stroke-width:2}.course-lane.center{stroke:#5c5c58;stroke-dasharray:10 12;animation:routeDash 20s linear infinite}.course-lane.right{stroke:#1d1d1d}.closing-course circle{fill:#6dc993;filter:drop-shadow(0 0 8px #6dc993);animation:mapPulse 2s ease-in-out infinite}.course-warning,.course-arrival{position:absolute;padding:9px 12px;border:1px solid #373737;background:#0a0a0a;color:#777;text-align:left;font:6px/1.5 JetBrains Mono,monospace}.course-warning{left:43%;bottom:39%}.course-arrival{right:12%;bottom:44%}.course-warning b,.course-arrival b{color:#ddd;font-size:8px}.closing>p,.closing h2,.button.light-cta{position:relative;z-index:3;text-shadow:0 2px 22px #050505}.closing h2{max-width:1100px;font-size:clamp(64px,8vw,118px)}

.access-overlay{position:fixed;z-index:1000;inset:0;display:grid;place-items:center;padding:20px;background:rgba(0,0,0,.68);backdrop-filter:blur(14px)}.access-modal{width:min(620px,100%);max-height:min(850px,calc(100vh - 32px));overflow:auto;border:1px solid #333;border-radius:18px;background:#f8f8f5;color:#111;box-shadow:0 40px 120px rgba(0,0,0,.45)}.access-modal>header{height:65px;display:flex;align-items:center;justify-content:space-between;padding:0 20px;border-bottom:1px solid #ddd}.access-modal>header button{border:0;background:none;color:#777;font-size:25px;cursor:pointer}.access-intro{padding:27px 27px 22px}.access-intro>span{color:#397b55;font:650 7px JetBrains Mono,monospace;letter-spacing:.1em}.access-intro h2{margin:13px 0 0;font-size:32px;font-weight:520;letter-spacing:-.055em;line-height:1.02}.access-intro p{margin:14px 0 0;color:#6d6d68;font-size:11px;line-height:1.6}.access-tabs{display:grid;grid-template-columns:1fr 1fr;margin:0 27px;border-bottom:1px solid #ccc}.access-tabs button{border:0;border-bottom:2px solid transparent;background:none;padding:12px 4px;color:#888;font-size:10px;cursor:pointer}.access-tabs button.active{border-color:#111;color:#111}.access-form{display:flex;flex-direction:column;gap:8px;padding:23px 27px}.access-form label{margin-top:4px;font:650 8px JetBrains Mono,monospace;letter-spacing:.07em;text-transform:uppercase}.access-form input,.access-form textarea{width:100%;border:1px solid #d0d0cb;border-radius:9px;outline:0;background:#fff;padding:13px;color:#111;font-size:12px;resize:vertical}.access-form input:focus,.access-form textarea:focus{border-color:#4f8667;box-shadow:0 0 0 3px rgba(47,154,101,.1)}.access-form small{color:#888;font-size:8px;line-height:1.5}.access-submit{display:flex;justify-content:space-between;margin-top:12px;border:0;border-radius:9px;background:#080808;padding:13px 15px;color:#fff;font-size:10px;font-weight:650;cursor:pointer}.access-submit:disabled{cursor:not-allowed;opacity:.38}.member-login{border:0;background:none;padding:9px;color:#666;font-size:9px;text-decoration:underline;text-underline-offset:4px;cursor:pointer}.access-feedback{margin:0 27px 18px;border-radius:8px;padding:11px;font-size:9px;line-height:1.5}.access-feedback.error{background:#fff0ee;color:#9d281e}.access-feedback.success{background:#eaf6ef;color:#267447}.access-modal>footer{border-top:1px solid #ddd;padding:14px 27px;color:#999;font-size:7px;line-height:1.5}

@keyframes orbitSpin{to{transform:translate(-50%,-50%) rotate(360deg)}}@keyframes nodeFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-7px)}}@keyframes particleOne{0%,100%{transform:translate(0,0);opacity:.25}50%{transform:translate(100px,90px);opacity:1}}@keyframes particleTwo{0%,100%{transform:translate(0,0);opacity:.25}50%{transform:translate(-90px,100px);opacity:1}}@keyframes routeDash{to{stroke-dashoffset:-180}}@keyframes mapPulse{0%,100%{opacity:.25;transform:scale(.7)}50%{opacity:1;transform:scale(1.35)}}@keyframes barPulse{0%,100%{opacity:.65}50%{opacity:1}}

@media(max-width:1050px){.hivemind-section{grid-template-columns:1fr}.hive-orbit{width:min(700px,100%);justify-self:center}.advantage-heading{grid-template-columns:1fr}.advantage-heading h2{margin-top:18px}.advantage-grid{grid-template-columns:1fr}.advantage-grid article{min-height:570px}}
@media(max-width:680px){.hivemind-section,.advantage-section{padding:90px 16px}.hivemind-copy h2,.advantage-heading h2{font-size:13vw}.hive-orbit{min-height:470px;border-radius:24px}.track-three{width:95%;height:88%}.hive-node{min-width:118px;padding:9px}.hive-node.legal{left:2%;top:11%}.hive-node.design{right:2%;top:10%}.hive-node.build{right:0;top:54%}.hive-node.research{left:0;top:56%}.hive-node.growth{left:8%;bottom:5%}.hive-node.verify{right:8%;bottom:4%}.hive-core{width:94px;height:94px}.advantage-grid article{min-height:540px}.model-row{grid-template-columns:48px 1fr 68px 38px}.shard-map{height:325px;margin:0 8px}.vendor{width:103px;padding:8px}.vault{width:140px}.portfolio-map{min-height:535px}.company-node{width:118px;padding:9px}.company-node.tomorrow{left:3%}.company-node.smarter{right:3%}.company-node.studio{left:3%;bottom:25%}.company-node.newco{right:3%;bottom:25%}.portfolio-ticker{grid-template-columns:1fr;gap:5px}.closing{min-height:600px}.course-warning{left:28%;bottom:30%}.course-arrival{right:4%;bottom:18%}.access-overlay{padding:8px}.access-modal{max-height:calc(100vh - 16px);border-radius:13px}.access-intro,.access-form{padding-left:18px;padding-right:18px}.access-tabs{margin:0 18px}.access-intro h2{font-size:28px}}
</style>
