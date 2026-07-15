<script setup lang="ts">
defineProps<{ signingIn?: boolean; authError?: string }>()
defineEmits<{ signIn: [] }>()

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
    { property: 'og:description', content: 'A portfolio operating system that turns founder intent into governed, verified outcomes.' },
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
      <button class="nav-login" :disabled="signingIn" @click="$emit('signIn')">
        {{ signingIn ? 'Opening…' : 'Enter Madeus' }} <span>↗</span>
      </button>
    </header>

    <section id="top" class="hero">
      <div class="hero-grid" aria-hidden="true"><i v-for="n in 24" :key="n" /></div>
      <div class="hero-copy">
        <p class="kicker"><span /> Portfolio operating system</p>
        <h1>One founder.<br><em>Every company in motion.</em></h1>
        <p class="hero-lead">Madeus turns a founder’s intent into coordinated, verified work across every company—using the right models, agents, people, codebases, accounts, and approvals for the outcome.</p>
        <div class="hero-actions">
          <button class="button primary" :disabled="signingIn" @click="$emit('signIn')">{{ signingIn ? 'Opening workspace…' : 'Enter Madeus' }} <span>→</span></button>
          <a class="button secondary" href="#system">See how it works <span>↓</span></a>
        </div>
        <p v-if="authError" class="auth-error" role="alert">{{ authError }}</p>
        <div class="hero-proof" aria-label="Madeus operating principles">
          <span><i /> One identity</span><span>Every company</span><span>Any capable model</span><span>Verified outcomes</span>
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
        <p class="dark-kicker"><i /> The accountable loop</p>
        <h2>Intent in.<br>Evidence out.</h2>
        <p>Madeus preserves the objective while work crosses tools, teams, companies, and models. Every handoff stays attributable. Every consequential action stays governed. Every result feeds the next decision.</p>
        <div class="loop-stats"><span><b>1</b> objective</span><span><b>∞</b> capable routes</span><span><b>1</b> accountable record</span></div>
      </div>
      <div class="loop-console">
        <header><span>madeus / outcome-ledger</span><b>PORTFOLIO</b></header>
        <ol>
          <li><time>09:41:08</time><b>UNDERSTAND</b><span>Portfolio context and constraints assembled</span><i>✓</i></li>
          <li><time>09:41:10</time><b>PREDICT</b><span>CADE impact model and alternatives compared</span><i>✓</i></li>
          <li><time>09:41:13</time><b>ROUTE</b><span>Best capabilities selected by task and policy</span><i>✓</i></li>
          <li class="live"><time>09:41:16</time><b>EXECUTE</b><span>Parallel workstreams advancing under budget</span><i>●</i></li>
          <li><time>—</time><b>VERIFY</b><span>Independent outcome and regression proof</span><i>○</i></li>
          <li><time>—</time><b>LEARN</b><span>Result updates the portfolio operating model</span><i>○</i></li>
        </ol>
        <footer><span>Every material action receipted</span><button type="button">Inspect rationale ↗</button></footer>
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
        <div class="company-grid">
          <article><span>TOMORROW</span><b>Risk &amp; markets</b><small>8 active objectives</small></article>
          <article><span>SMARTER</span><b>Legal operating system</b><small>12 active objectives</small></article>
          <article><span>MADEUS</span><b>Orchestration core</b><small>6 active objectives</small></article>
          <article class="shared"><span>SHARED CAPABILITIES</span><b>Identity · models · connectors · policy · evidence</b><small>Inherited safely across the portfolio</small></article>
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
      <div class="closing-signal" aria-hidden="true"><i /><i /><i /><MadeusMark /></div>
      <p>Stop operating each company one tab at a time.</p>
      <h2>Put the portfolio<br>in motion.</h2>
      <button class="button light-cta" :disabled="signingIn" @click="$emit('signIn')">{{ signingIn ? 'Opening Madeus…' : 'Enter Madeus' }} <span>→</span></button>
    </section>

    <footer class="site-footer"><MadeusLogo /><p>Outcome orchestration for the multi-company founder.</p><div><a href="#system">Platform</a><a href="#governance">Governance</a><span>© {{ new Date().getFullYear() }} Madeus</span></div></footer>
  </main>
</template>

<style scoped>
.landing{--black:#050505;--ink:#111;--muted:#6f6f6b;--line:#deded9;--paper:#f7f7f4;overflow:hidden;background:#fff;color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,sans-serif}.landing :deep(*){box-sizing:border-box}.site-nav{position:absolute;z-index:20;top:0;left:0;right:0;height:78px;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;padding:0 clamp(20px,3.5vw,56px);border-bottom:1px solid rgba(15,15,15,.09)}.logo-link{justify-self:start;color:var(--ink);text-decoration:none}.site-nav nav{display:flex;gap:32px}.site-nav nav a,.site-footer a{color:#555;text-decoration:none;font-size:11px}.site-nav nav a:hover,.site-footer a:hover{color:#000}.nav-login{justify-self:end;border:1px solid #161616;border-radius:999px;background:#0a0a0a;padding:10px 15px;color:#fff;font-size:10px;font-weight:650;cursor:pointer}.nav-login span{margin-left:18px}.nav-login:disabled,.button:disabled{cursor:wait;opacity:.55}.hero{position:relative;min-height:850px;display:grid;grid-template-columns:minmax(0,1.02fr) minmax(480px,.98fr);align-items:center;gap:5vw;padding:130px clamp(20px,3.5vw,56px) 76px;background:radial-gradient(circle at 88% 15%,rgba(45,106,82,.12),transparent 29%),#fafafa}.hero-grid{position:absolute;inset:78px 0 0;display:grid;grid-template-columns:repeat(6,1fr);pointer-events:none}.hero-grid i{border-right:1px solid rgba(0,0,0,.045);border-bottom:1px solid rgba(0,0,0,.045)}.hero-copy,.command-model{position:relative;z-index:2}.kicker,.dark-kicker{display:flex;align-items:center;gap:9px;margin:0 0 25px;color:#555;font:650 9px/1 JetBrains Mono,monospace;letter-spacing:.11em;text-transform:uppercase}.kicker span,.dark-kicker i,.command-model header b i,.portfolio-visual header b i{display:inline-block;width:6px;height:6px;border-radius:50%;background:#2f9a65;box-shadow:0 0 0 4px rgba(47,154,101,.13)}.hero h1,.section-heading h2,.loop-copy h2,.portfolio-copy h2,.principles h2,.closing h2{margin:0;font-weight:470;letter-spacing:-.065em;line-height:.95}.hero h1{max-width:820px;font-size:clamp(62px,7vw,112px)}.hero h1 em,.portfolio-copy h2 em{color:#7c7c76;font-style:normal}.hero-lead{max-width:720px;margin:34px 0 0;color:#575753;font-size:clamp(16px,1.45vw,21px);line-height:1.6;letter-spacing:-.018em}.hero-actions{display:flex;gap:11px;margin-top:36px}.button{min-width:178px;display:inline-flex;align-items:center;justify-content:space-between;border-radius:999px;padding:14px 17px;text-decoration:none;font-size:11px;transition:transform .18s,background .18s;cursor:pointer}.button:hover{transform:translateY(-2px)}.button.primary{border:1px solid #050505;background:#050505;color:#fff}.button.secondary{border:1px solid #cfcfca;background:rgba(255,255,255,.7);color:#111}.auth-error{max-width:520px;margin:14px 0 0;color:#b42318;font-size:11px}.hero-proof{display:flex;flex-wrap:wrap;gap:9px 22px;margin-top:47px;padding-top:18px;border-top:1px solid #d7d7d2;color:#777;font:600 8px/1 JetBrains Mono,monospace;letter-spacing:.06em;text-transform:uppercase}.hero-proof span:first-child{color:#222}.hero-proof i{display:inline-block;width:5px;height:5px;margin-right:7px;border-radius:50%;background:#2f9a65}.command-model{overflow:hidden;border:1px solid #292929;border-radius:18px;background:#080808;color:#fff;box-shadow:0 38px 100px rgba(0,0,0,.24)}.command-model>header{height:57px;display:flex;align-items:center;gap:10px;padding:0 17px;border-bottom:1px solid #242424;color:#a5a5a0;font:600 8px/1 JetBrains Mono,monospace;letter-spacing:.08em;text-transform:uppercase}.model-logo{width:24px;height:24px;color:#fff;--mark-ink:#080808;--mark-signal:#246949}.command-model>header b{display:flex;align-items:center;gap:8px;margin-left:auto;color:#6dc993;font-size:7px}.portfolio-context{display:grid;grid-template-columns:auto 1fr;gap:5px 13px;padding:18px 20px;border-bottom:1px solid #242424}.portfolio-context span,.intent-card>span{grid-row:1/3;color:#666;font:600 7px/1 JetBrains Mono,monospace;letter-spacing:.1em}.portfolio-context b{font-size:11px;font-weight:550}.portfolio-context small{color:#777;font-size:8px}.intent-card{margin:18px;border:1px solid #343434;border-radius:10px;background:#111;padding:17px}.intent-card p{margin:12px 0 18px;font-size:15px;line-height:1.45;letter-spacing:-.025em}.intent-card div{display:flex;justify-content:space-between;border-top:1px solid #2b2b2b;padding-top:12px}.intent-card div b{font-size:8px;font-weight:600}.intent-card div small{color:#72726f;font-size:7px}.route-list{margin:0;padding:0 18px;list-style:none}.route-list li{min-height:58px;display:grid;grid-template-columns:28px 1fr auto;gap:11px;align-items:center;border-top:1px solid #202020;color:#62625f}.route-list time{font:8px JetBrains Mono,monospace}.route-list span{display:flex;flex-direction:column;gap:4px}.route-list b{color:#aaa;font-size:9px;font-weight:550}.route-list small{font-size:7px}.route-list>li>i{font:normal 6px JetBrains Mono,monospace;text-transform:uppercase}.route-list li.active{margin:0 -18px;padding:0 18px;background:linear-gradient(90deg,rgba(74,190,124,.12),transparent);color:#6dc993}.route-list li.active b{color:#fff}.command-model>footer{display:grid;grid-template-columns:1fr auto;gap:4px 20px;margin-top:9px;padding:18px 20px;background:#101b15;border-top:1px solid #264433}.command-model>footer span{color:#7f9a88;font-size:8px}.command-model>footer b{font:500 23px/1 Inter,sans-serif}.command-model>footer small{grid-column:1/-1;color:#668071;font-size:7px}.definition-strip{display:grid;grid-template-columns:.45fr .8fr 1.6fr;gap:4vw;align-items:center;padding:34px clamp(20px,3.5vw,56px);border-top:1px solid #111;border-bottom:1px solid var(--line);background:#fff}.definition-strip span{font:8px JetBrains Mono,monospace}.definition-strip p{margin:0;color:#777;font-size:11px}.definition-strip strong{font-size:clamp(18px,2.2vw,31px);font-weight:500;letter-spacing:-.045em}.system-section,.capability-section{padding:140px clamp(20px,3.5vw,56px)}.section-heading{display:grid;grid-template-columns:.65fr 1.35fr 1fr;gap:5vw;align-items:start;margin-bottom:68px}.section-heading>p{margin:8px 0 0;font:650 9px/1 JetBrains Mono,monospace;letter-spacing:.11em;text-transform:uppercase}.section-heading h2{font-size:clamp(48px,5.8vw,86px)}.section-heading>span{max-width:460px;margin-top:8px;color:var(--muted);font-size:13px;line-height:1.7}.layers{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid #111;border-left:1px solid var(--line)}.layers article,.capability-grid article{min-height:390px;display:flex;flex-direction:column;padding:20px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}.layers article>span,.capability-grid article>span{font:8px JetBrains Mono,monospace}.layer-signal,.capability-glyph{height:115px;display:flex;align-items:center;justify-content:center}.layer-signal i{width:32px;height:32px;border:1px solid #888;border-radius:50%}.layer-signal i+ i{margin-left:-9px}.layer-signal i:nth-child(2){background:#111;border-color:#111}.layer-signal i:nth-child(3){width:14px;height:14px;background:#fff}.layers h3,.capability-grid h3{margin:auto 0 16px;font-size:19px;font-weight:550;letter-spacing:-.045em}.layers p,.capability-grid p{margin:0;color:var(--muted);font-size:10px;line-height:1.65}.outcome-loop{display:grid;grid-template-columns:1fr 1.1fr;gap:8vw;padding:145px clamp(20px,3.5vw,56px);background:#050505;color:#fff}.dark-kicker{color:#777}.dark-kicker i{background:#fff;box-shadow:0 0 0 4px rgba(255,255,255,.12)}.loop-copy h2{font-size:clamp(58px,6.6vw,96px)}.loop-copy>p:nth-of-type(2){max-width:620px;margin:36px 0 0;color:#94948f;font-size:13px;line-height:1.75}.loop-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:52px;border-top:1px solid #333}.loop-stats span{display:flex;flex-direction:column;padding-top:17px;color:#6f6f6b;font-size:8px}.loop-stats b{margin-bottom:5px;color:#fff;font-size:22px;font-weight:500}.loop-console{align-self:center;border:1px solid #383838;background:#0b0b0b;box-shadow:0 35px 90px rgba(0,0,0,.4)}.loop-console header,.loop-console footer{height:49px;display:flex;align-items:center;justify-content:space-between;padding:0 17px;border-bottom:1px solid #2d2d2d;color:#777;font:7px JetBrains Mono,monospace}.loop-console header b{color:#aaa;font-size:7px}.loop-console ol{margin:0;padding:0 19px;list-style:none}.loop-console li{min-height:57px;display:grid;grid-template-columns:66px 76px 1fr auto;gap:7px;align-items:center;border-bottom:1px solid #202020;color:#696966;font:7px JetBrains Mono,monospace}.loop-console li b{font-weight:500;color:#8c8c88}.loop-console li.live{margin:0 -19px;padding:0 19px;background:linear-gradient(90deg,rgba(255,255,255,.07),transparent);color:#fff}.loop-console li.live b{color:#fff}.loop-console footer{border-top:1px solid #2d2d2d;border-bottom:0}.loop-console footer button{border:0;background:none;color:#ddd;font:7px JetBrains Mono,monospace}.section-heading.compact{margin-bottom:82px}.capability-grid{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid #111;border-left:1px solid var(--line)}.capability-grid article{min-height:360px}.capability-glyph i{display:block;width:16px;height:68px;border:1px solid #aaa;border-radius:99px;transform:rotate(30deg)}.capability-glyph i:nth-child(2){height:96px;margin:0 4px;background:#111;border-color:#111}.capability-glyph i:nth-child(3){height:45px}.portfolio-section{display:grid;grid-template-columns:1.05fr .95fr;gap:8vw;align-items:center;padding:130px clamp(20px,3.5vw,56px);background:var(--paper)}.portfolio-visual{overflow:hidden;border:1px solid #ccc;border-radius:16px;background:#fff;box-shadow:0 30px 80px rgba(0,0,0,.09)}.portfolio-visual>header{height:60px;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;padding:0 16px;border-bottom:1px solid var(--line);font:7px JetBrains Mono,monospace;color:#777}.portfolio-visual>header b{justify-self:end;display:flex;align-items:center;gap:7px;color:#3d805b;font-size:7px}.company-grid{display:grid;grid-template-columns:1fr 1fr}.company-grid article{min-height:145px;display:flex;flex-direction:column;padding:20px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}.company-grid article:nth-child(2){border-right:0}.company-grid article>span{font:7px JetBrains Mono,monospace;color:#888}.company-grid article b{margin:auto 0 6px;font-size:14px;font-weight:550}.company-grid article small{color:#888;font-size:8px}.company-grid article.shared{grid-column:1/-1;min-height:170px;border-right:0;background:#0b0b0b;color:#fff}.company-grid article.shared span,.company-grid article.shared small{color:#777}.portfolio-copy>p:first-child{font:650 9px JetBrains Mono,monospace;letter-spacing:.1em;text-transform:uppercase}.portfolio-copy h2{margin-top:24px;font-size:clamp(42px,4.8vw,72px)}.portfolio-copy>p:nth-of-type(2){margin:32px 0 0;color:var(--muted);font-size:13px;line-height:1.75}.portfolio-copy ul{margin:30px 0 0;padding:0;list-style:none;border-top:1px solid #d4d4cf}.portfolio-copy li{padding:12px 0;border-bottom:1px solid #d4d4cf;font-size:10px}.portfolio-copy li:before{content:'✓';margin-right:10px;color:#2f7954}.principles{display:grid;grid-template-columns:1.2fr repeat(3,1fr);border-bottom:1px solid var(--line)}.principles>*{min-height:430px;padding:78px 28px;border-right:1px solid var(--line)}.principles>div{background:#f1f1ee}.principles>div p{margin:0;font:650 9px JetBrains Mono,monospace;letter-spacing:.1em;text-transform:uppercase}.principles h2{margin-top:112px;font-size:45px}.principles article{display:flex;flex-direction:column}.principles article>span{font:8px JetBrains Mono,monospace}.principles article h3{margin:auto 0 18px;font-size:20px;font-weight:550;letter-spacing:-.04em}.principles article p{margin:0;color:#777;font-size:10px;line-height:1.65}.closing{position:relative;overflow:hidden;padding:155px 20px;text-align:center;background:#050505;color:#fff}.closing>p{position:relative;z-index:2;margin:0;color:#888;font-size:11px}.closing h2{position:relative;z-index:2;margin:18px 0 48px;font-size:clamp(68px,9vw,138px)}.button.light-cta{position:relative;z-index:2;border:0;background:#fff;color:#111}.closing-signal{position:absolute;left:50%;top:50%;width:540px;height:540px;display:grid;place-items:center;transform:translate(-50%,-50%)}.closing-signal i{position:absolute;border:1px solid #242424;border-radius:50%;animation:signal 4s ease-in-out infinite}.closing-signal i:nth-child(1){width:190px;height:190px}.closing-signal i:nth-child(2){width:350px;height:350px;animation-delay:.4s}.closing-signal i:nth-child(3){width:520px;height:520px;animation-delay:.8s}.closing-signal :deep(.madeus-mark){width:54px;height:54px;color:#fff;--mark-ink:#050505;--mark-signal:#2f7954}.site-footer{display:grid;grid-template-columns:1fr 1fr 1fr;align-items:end;gap:25px;padding:52px clamp(20px,3.5vw,56px);background:#050505;color:#777;border-top:1px solid #222}.site-footer p{margin:0;font-size:9px}.site-footer>div{display:flex;justify-content:flex-end;gap:18px;align-items:center;font-size:8px}.site-footer :deep(.madeus-logo-mark){color:#fff;--mark-ink:#050505}.site-footer :deep(.madeus-wordmark b){color:#fff}@keyframes signal{0%,100%{opacity:.4;transform:scale(.92)}50%{opacity:1;transform:scale(1)}}@media(max-width:1050px){.hero{grid-template-columns:1fr;padding-top:150px}.hero-copy{max-width:900px}.command-model{width:min(720px,100%)}.layers{grid-template-columns:1fr 1fr}.outcome-loop,.portfolio-section{grid-template-columns:1fr}.capability-grid{grid-template-columns:1fr 1fr}.principles{grid-template-columns:1fr 1fr}.principles>div{grid-column:1/-1}.site-nav{grid-template-columns:1fr auto}.site-nav nav{display:none}}@media(max-width:680px){.site-nav{height:66px;padding:0 16px}.site-nav :deep(.madeus-wordmark small){display:none}.nav-login{padding:9px 11px}.nav-login span{margin-left:8px}.hero{min-height:auto;padding:118px 17px 62px;grid-template-columns:1fr}.hero-grid{top:66px;grid-template-columns:repeat(3,1fr)}.hero h1{font-size:17vw}.hero-lead{font-size:15px}.hero-actions{align-items:flex-start;flex-direction:column}.hero-proof{line-height:1.6}.command-model{margin-top:25px;border-radius:12px}.portfolio-context small,.intent-card div small{display:none}.route-list li{grid-template-columns:24px 1fr}.route-list>li>i{display:none}.definition-strip{grid-template-columns:1fr;gap:9px}.system-section,.capability-section{padding:90px 16px}.section-heading{display:block}.section-heading h2{margin:19px 0 25px}.layers,.capability-grid{grid-template-columns:1fr}.layers article,.capability-grid article{min-height:330px}.outcome-loop,.portfolio-section{padding:95px 17px}.loop-console li{grid-template-columns:54px 64px 1fr}.loop-console li i{display:none}.portfolio-visual>header{grid-template-columns:1fr auto}.portfolio-visual>header>span{display:none}.company-grid{grid-template-columns:1fr}.company-grid article{border-right:0}.company-grid article.shared{grid-column:auto}.principles{grid-template-columns:1fr}.principles>div{grid-column:auto}.principles>*{min-height:310px;padding:55px 22px}.principles h2{margin-top:70px}.closing{padding:110px 17px}.site-footer{grid-template-columns:1fr}.site-footer>div{justify-content:flex-start;flex-wrap:wrap}}@media(prefers-reduced-motion:reduce){.landing *{animation:none!important;scroll-behavior:auto!important}}
</style>
