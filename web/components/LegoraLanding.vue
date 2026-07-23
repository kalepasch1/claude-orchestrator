<script setup lang="ts">
defineProps<{ signingIn?: boolean; authError?: string }>()
const emit = defineEmits<{ signIn: [admission: { mode: 'member' | 'referral'; grantToken?: string }] }>()

const open = ref(false)
const code = ref('')
const busy = ref(false)
const error = ref('')
const activeLayer = ref(0)

const layers = [
  { number: '01', name: 'Private context', detail: 'Companies, code, documents, decisions, people, and policy become one governed working memory.' },
  { number: '02', name: 'Agentic harness', detail: 'Madeus plans the work, assembles specialists, and preserves the objective through every handoff.' },
  { number: '03', name: 'Best-capability routing', detail: 'Models, tools, agents, and people are selected by quality, privacy, speed, reliability, and cost.' },
  { number: '04', name: 'Execution and proof', detail: 'Work is tested independently, governed by policy, released safely, and returned with durable evidence.' },
]

const innovations = [
  { index: '01', name: 'Illuminati', label: 'Development optimization', title: 'Every release makes the next one sharper.', body: 'Illuminati finds the constraint, selects the smallest high-leverage improvement, and independently proves the result before the learning compounds.', glyph: '✦', tags: ['Route', 'Build', 'Verify', 'Learn'] },
  { index: '02', name: 'Portfolio network', label: 'Shared intelligence', title: 'One company learns. Every company improves.', body: 'Turn proven experience into reusable guidance across the portfolio—without compromising the independence or privacy of any company.', glyph: '◎', tags: ['Private precedent', 'Cross-company signal', 'Proven context'] },
  { index: '03', name: 'Company OS', label: 'Full management suite', title: 'Every function moves through one operating surface.', body: 'Legal, compliance, finance, marketing, people, security, revenue, and operations share context without losing ownership or authority.', glyph: '◇', tags: ['Legal', 'Growth', 'Finance', 'Operations'] },
]

const functions = ['Engineering', 'Legal', 'Compliance', 'Marketing', 'Finance', 'People', 'Security', 'Operations']

async function enter() {
  if (!code.value.trim()) {
    open.value = false
    emit('signIn', { mode: 'member' })
    return
  }
  busy.value = true
  error.value = ''
  try {
    const result = await $fetch<any>('/api/public/access/verify', { method: 'POST', body: { code: code.value } })
    open.value = false
    emit('signIn', { mode: 'referral', grantToken: result.grant_token })
  } catch (cause: any) {
    error.value = cause?.data?.message || cause?.message || 'This referral could not be verified.'
  } finally {
    busy.value = false
  }
}

useHead({
  title: 'Madeus — The private operating system for company building',
  meta: [
    { name: 'theme-color', content: '#0b0c0b' },
    { name: 'description', content: 'Private intelligence and governed execution for founders operating multiple companies.' },
  ],
})
</script>

<template>
  <main class="landing" data-release-surface="public-command-center">
    <div class="announcement">The private operating system for multi-company founders <a href="#system">Explore Madeus <span>→</span></a></div>

    <header class="nav">
      <nav aria-label="Primary navigation">
        <a href="#system">Platform</a><a href="#capabilities">Capabilities</a><a href="#security">Security</a>
      </nav>
      <a class="wordmark" href="#top" aria-label="Madeus home">MADEUS</a>
      <div class="nav-right"><button class="login" @click="open = true">Log in</button><button class="demo" @click="open = true">Enter Madeus <span>↗</span></button></div>
    </header>

    <section id="top" class="hero">
      <div class="hero-art" aria-hidden="true">
        <div class="horizon" /><div class="arc arc-a" /><div class="arc arc-b" /><div class="arc arc-c" />
        <div class="monolith"><span>M</span><i /><i /><i /></div>
        <div class="hero-signal signal-a">Context qualified</div><div class="hero-signal signal-b">Route verified</div><div class="hero-signal signal-c">Proof retained</div>
      </div>
      <div class="hero-copy">
        <p>Private intelligence. Governed execution.</p>
        <h1>Company building,<br>without limits.</h1>
        <div class="hero-bottom"><p>Madeus understands your portfolio, coordinates the best available intelligence, and carries work from direction to independently verified outcome.</p><button @click="open = true">Request access <span>→</span></button></div>
      </div>
      <div class="scroll-cue"><span>Discover Madeus</span><i /></div>
    </section>

    <section class="trust-strip"><p>ONE DIRECTION ACROSS</p><div><span v-for="item in ['Companies', 'Products', 'People', 'Knowledge', 'Capital', 'Risk']" :key="item">{{ item }}</span></div></section>

    <section id="system" class="system-section">
      <header class="section-heading"><p>Introducing the Madeus OS</p><h2>The agentic operating system<br>for company building.</h2></header>
      <div class="system-layout">
        <div class="system-visual">
          <div class="system-core"><span>M</span><small>MADEUS</small></div>
          <div class="system-ring ring-one" /><div class="system-ring ring-two" />
          <span class="node n1">Knowledge</span><span class="node n2">Models</span><span class="node n3">Tools</span><span class="node n4">People</span><span class="node n5">Policy</span><span class="node n6">Proof</span>
        </div>
        <div class="layer-list">
          <button v-for="(layer, index) in layers" :key="layer.name" :class="{ active: activeLayer === index }" @click="activeLayer = index">
            <span>{{ layer.number }}</span><div><b>{{ layer.name }}</b><p>{{ layer.detail }}</p></div><i>↗</i>
          </button>
        </div>
      </div>
      <footer class="system-footer"><p>A single private system connecting information, communication, judgment, and execution across your portfolio.</p><button @click="open = true">Explore the operating system <span>↗</span></button></footer>
    </section>

    <section id="capabilities" class="innovations">
      <header class="section-heading inverse"><p>Core systems</p><h2>Built to compound.</h2></header>
      <div class="innovation-grid">
        <article v-for="item in innovations" :key="item.name">
          <header><span>{{ item.index }}</span><b>{{ item.name }}</b><small>{{ item.label }}</small></header>
          <div class="innovation-art" aria-hidden="true"><span>{{ item.glyph }}</span><i /><i /><i /></div>
          <h3>{{ item.title }}</h3><p>{{ item.body }}</p>
          <footer><span v-for="tag in item.tags" :key="tag">{{ tag }}</span></footer>
        </article>
      </div>
    </section>

    <section class="functions-section">
      <header class="section-heading"><p>Every team. Every function.</p><h2>One operating surface<br>for the whole company.</h2></header>
      <div class="function-grid"><article v-for="(item, index) in functions" :key="item"><span>0{{ index + 1 }}</span><h3>{{ item }}</h3><i>↗</i></article></div>
      <div class="function-copy"><p>Madeus handles complex work end-to-end—from initial direction through research, execution, approval, release, and institutional memory.</p><button @click="open = true">See Madeus in action <span>→</span></button></div>
    </section>

    <section class="outcomes">
      <div class="outcome-copy"><p>From direction to proof</p><h2>Answers are easy.<br>Outcomes are the work.</h2></div>
      <div class="outcome-sequence"><article><span>01</span><h3>Understand</h3><p>Load the relevant company context, constraints, dependencies, and prior decisions.</p></article><article><span>02</span><h3>Coordinate</h3><p>Assemble the strongest specialists, tools, models, and execution path.</p></article><article><span>03</span><h3>Deliver</h3><p>Turn direction into tested, reviewable, governed work across every function.</p></article><article><span>04</span><h3>Prove</h3><p>Verify independently, release safely, and preserve evidence for the next decision.</p></article></div>
    </section>

    <section id="security" class="security">
      <div><p>Private by architecture</p><h2>Your operating context<br>remains yours.</h2><p>Need-to-know routing, explicit authority, isolated company context, independent verification, and durable receipts are built into every action.</p><button @click="open = true">Review the trust model <span>↗</span></button></div>
      <div class="security-board"><header><span>MADEUS / TRUST FABRIC</span><b><i /> Operational</b></header><article><span>Context boundary</span><b>Private</b></article><article><span>Vendor exposure</span><b>Minimized</b></article><article><span>Execution authority</span><b>Explicit</b></article><article><span>Independent verification</span><b>Required</b></article><footer>Policy travels with the work.</footer></div>
    </section>

    <section class="closing"><p>Madeus</p><h2>One direction.<br>Every company in motion.</h2><button @click="open = true">Request member access <span>→</span></button></section>

    <footer class="footer"><a class="footer-wordmark" href="#top">MADEUS</a><p>Private intelligence and governed execution for the multi-company founder.</p><nav><a href="#system">Platform</a><a href="#capabilities">Capabilities</a><a href="#security">Security</a><span>© {{ new Date().getFullYear() }} Madeus</span></nav></footer>

    <div v-if="open" class="overlay" @click.self="open = false">
      <section class="modal" role="dialog" aria-modal="true" aria-labelledby="member-title">
        <header><b>MADEUS</b><button aria-label="Close" @click="open = false">×</button></header>
        <div><p>Private membership</p><h2 id="member-title">Enter Madeus.</h2><span>Use a member referral, or continue if your account is already admitted.</span>
          <form @submit.prevent="enter"><label>Referral code <small>Optional for members</small></label><input v-model="code" placeholder="MDS-XXXXXXXXXX"><button :disabled="busy">{{ busy ? 'Verifying…' : code.trim() ? 'Verify and continue' : 'Existing member sign in' }} <i>→</i></button></form>
          <p v-if="error || authError" class="error">{{ error || authError }}</p>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.landing{--black:#0b0c0b;--white:#f7f7f3;--paper:#eeeee8;--line:#d7d7d0;--muted:#656760;--green:#173f2c;background:var(--white);color:var(--black);font-family:Inter,Arial,sans-serif}.landing *{box-sizing:border-box}.landing button,.landing a{font:inherit}.announcement{height:42px;display:flex;align-items:center;justify-content:center;gap:17px;background:var(--green);color:#fff;font-size:12px}.announcement a{color:#fff;text-decoration:none;opacity:.78}.announcement a:hover{opacity:1}.nav{position:absolute;z-index:10;top:42px;left:0;right:0;height:78px;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;padding:0 24px;color:#fff}.nav nav{display:flex;gap:31px}.nav a{color:inherit;text-decoration:none;font-size:12px}.wordmark{font-size:22px!important;font-weight:600!important;letter-spacing:.03em}.nav-right{justify-self:end;display:flex;align-items:center;gap:20px}.nav-right button{border:0;background:transparent;color:#fff;cursor:pointer;font-size:12px}.nav-right .demo{display:flex;align-items:center;gap:16px;border-radius:99px;background:var(--green);padding:10px 11px 10px 17px}.demo span{display:grid;width:22px;height:22px;place-items:center;border-radius:50%;background:#fff;color:var(--green)}
.hero{position:relative;min-height:calc(100svh - 42px);overflow:hidden;background:var(--black);color:#fff}.hero:after{position:absolute;inset:0;background:linear-gradient(180deg,#0000 35%,#0009 100%);content:""}.hero-art{position:absolute;inset:0;overflow:hidden;background:radial-gradient(circle at 55% 42%,#343633 0,#151614 28%,#090a09 65%)}.horizon{position:absolute;left:-10%;right:-10%;top:55%;height:1px;background:#fff2;box-shadow:0 0 70px 22px #fff1}.arc{position:absolute;left:50%;top:50%;border:1px solid #ffffff18;border-radius:50%;transform:translate(-50%,-50%);animation:orbit 25s linear infinite}.arc-a{width:70vw;height:70vw}.arc-b{width:45vw;height:45vw;animation-direction:reverse}.arc-c{width:92vw;height:35vw;transform:translate(-50%,-50%) rotate(19deg)}.monolith{position:absolute;left:50%;top:48%;width:130px;height:330px;display:flex;align-items:center;justify-content:center;border:1px solid #fff4;background:linear-gradient(135deg,#ffffff1c,#0007);box-shadow:0 0 100px #fff2;transform:translate(-50%,-50%);backdrop-filter:blur(4px)}.monolith span{font-size:46px;font-weight:500}.monolith i{position:absolute;left:0;right:0;height:1px;background:#fff2}.monolith i:nth-of-type(1){top:25%}.monolith i:nth-of-type(2){top:50%}.monolith i:nth-of-type(3){top:75%}.hero-signal{position:absolute;border:1px solid #ffffff29;background:#0b0c0ba6;padding:9px 12px;color:#d9dbd5;font:9px ui-monospace,monospace;letter-spacing:.08em;text-transform:uppercase;backdrop-filter:blur(8px);animation:float 7s ease-in-out infinite}.signal-a{left:20%;top:34%}.signal-b{right:18%;top:43%;animation-delay:-2s}.signal-c{right:27%;bottom:22%;animation-delay:-4s}.hero-copy{position:absolute;z-index:2;left:24px;right:24px;bottom:43px}.hero-copy>p{margin:0 0 13px;font:10px ui-monospace,monospace;letter-spacing:.14em;text-transform:uppercase}.hero h1{max-width:1040px;margin:0;font-size:clamp(65px,8.5vw,136px);font-weight:430;letter-spacing:-.07em;line-height:.86}.hero-bottom{display:flex;align-items:flex-end;justify-content:space-between;gap:30px;margin-top:30px}.hero-bottom p{max-width:610px;margin:0;color:#d0d1cc;font-size:14px;line-height:1.65}.hero-bottom button,.system-footer button,.function-copy button,.security button,.closing button{display:flex;align-items:center;justify-content:space-between;gap:34px;border:0;border-radius:99px;background:#fff;padding:14px 15px 14px 20px;color:var(--black);cursor:pointer;font-size:12px}.scroll-cue{position:absolute;z-index:2;right:24px;top:50%;display:flex;align-items:center;gap:12px;transform:rotate(90deg) translateX(50%);transform-origin:right;color:#ffffffa3;font-size:9px;letter-spacing:.08em;text-transform:uppercase}.scroll-cue i{width:52px;height:1px;background:#fff7}
.trust-strip{display:grid;grid-template-columns:220px 1fr;align-items:center;padding:36px 24px;border-bottom:1px solid var(--line)}.trust-strip p{font:9px ui-monospace,monospace;letter-spacing:.12em}.trust-strip div{display:grid;grid-template-columns:repeat(6,1fr)}.trust-strip span{color:#74766f;font-size:13px;text-align:center}
.system-section,.functions-section{padding:135px 24px}.section-heading{display:grid;grid-template-columns:1fr 2.4fr;gap:40px;max-width:1400px;margin:0 auto 74px}.section-heading>p,.outcome-copy>p,.security>div>p:first-child,.closing>p,.modal>div>p{font:10px ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase}.section-heading h2{margin:0;font-size:clamp(51px,6vw,94px);font-weight:430;letter-spacing:-.065em;line-height:.94}.system-layout{display:grid;grid-template-columns:1.1fr .9fr;max-width:1400px;margin:auto;border:1px solid var(--line)}.system-visual{position:relative;min-height:620px;overflow:hidden;background:var(--paper)}.system-visual:before{position:absolute;inset:0;background-image:linear-gradient(#0b0c0b0b 1px,transparent 1px),linear-gradient(90deg,#0b0c0b0b 1px,transparent 1px);background-size:40px 40px;content:""}.system-core{position:absolute;z-index:2;left:50%;top:50%;display:grid;width:118px;height:118px;place-items:center;border-radius:50%;background:var(--black);color:#fff;transform:translate(-50%,-50%)}.system-core span{font-size:32px}.system-core small{font:7px ui-monospace,monospace;letter-spacing:.12em}.system-ring{position:absolute;left:50%;top:50%;border:1px solid #0b0c0b3b;border-radius:50%;transform:translate(-50%,-50%)}.ring-one{width:320px;height:320px}.ring-two{width:500px;height:500px}.node{position:absolute;z-index:2;border:1px solid #bfc0b9;background:var(--white);padding:9px 12px;font:9px ui-monospace,monospace}.n1{left:14%;top:22%}.n2{right:15%;top:19%}.n3{left:9%;bottom:26%}.n4{right:11%;bottom:22%}.n5{left:46%;top:10%}.n6{left:44%;bottom:9%;border-color:var(--green);color:var(--green)}.layer-list{background:#fff}.layer-list button{width:100%;min-height:154px;display:grid;grid-template-columns:42px 1fr auto;gap:18px;padding:28px;border:0;border-bottom:1px solid var(--line);background:#fff;color:var(--black);text-align:left;cursor:pointer}.layer-list button:last-child{border-bottom:0}.layer-list button.active{background:var(--black);color:#fff}.layer-list button>span{font:9px ui-monospace,monospace}.layer-list b{font-size:21px;font-weight:500}.layer-list p{max-width:520px;margin:13px 0 0;color:#70726c;font-size:11px;line-height:1.6}.layer-list .active p{color:#bfc0ba}.layer-list i{font-style:normal}.system-footer{max-width:1400px;margin:0 auto;display:flex;justify-content:space-between;align-items:center;padding:31px 0;border-bottom:1px solid var(--black)}.system-footer p{max-width:620px;color:var(--muted);font-size:13px;line-height:1.6}.system-footer button,.function-copy button{border:1px solid var(--black)}
.innovations{padding:135px 24px;background:var(--black);color:#fff}.section-heading.inverse{margin-bottom:55px}.innovation-grid{display:grid;grid-template-columns:repeat(3,1fr);max-width:1400px;margin:auto;border-top:1px solid #ffffff45;border-left:1px solid #ffffff45}.innovation-grid article{min-height:650px;display:flex;flex-direction:column;padding:25px;border-right:1px solid #ffffff45;border-bottom:1px solid #ffffff45}.innovation-grid header{display:grid;grid-template-columns:auto 1fr;gap:10px}.innovation-grid header span{font:9px ui-monospace,monospace}.innovation-grid header b{font-size:13px;font-weight:500}.innovation-grid header small{grid-column:2;color:#999c95;font:8px ui-monospace,monospace;text-transform:uppercase}.innovation-art{position:relative;min-height:255px;display:grid;place-items:center;margin:35px 0;overflow:hidden;border:1px solid #ffffff26;background:#ffffff08}.innovation-art span{position:relative;z-index:2;font-size:53px}.innovation-art i{position:absolute;width:160px;height:160px;border:1px solid #ffffff38;border-radius:50%;animation:pulse 6s ease-in-out infinite}.innovation-art i:nth-of-type(2){width:225px;height:95px;transform:rotate(35deg);animation-delay:-2s}.innovation-art i:nth-of-type(3){width:260px;height:260px;animation-delay:-4s}.innovation-grid h3{margin:auto 0 17px;font-size:clamp(30px,3vw,47px);font-weight:430;letter-spacing:-.055em;line-height:1}.innovation-grid article>p{color:#adafa9;font-size:12px;line-height:1.7}.innovation-grid footer{display:flex;gap:6px;flex-wrap:wrap;margin-top:22px}.innovation-grid footer span{border:1px solid #ffffff2d;border-radius:99px;padding:6px 9px;color:#b9bbb4;font:7px ui-monospace,monospace}.innovation-grid article:nth-child(2) .innovation-art span{color:#9db9a6}
.function-grid{display:grid;grid-template-columns:repeat(4,1fr);max-width:1400px;margin:auto;border-top:1px solid var(--black);border-left:1px solid var(--line)}.function-grid article{min-height:190px;display:grid;grid-template-columns:1fr auto;padding:20px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}.function-grid span{font:8px ui-monospace,monospace}.function-grid h3{align-self:end;margin:0;font-size:24px;font-weight:470}.function-grid i{font-style:normal}.function-copy{max-width:1400px;margin:38px auto 0;display:flex;justify-content:space-between;align-items:flex-end}.function-copy p{max-width:720px;margin:0;color:var(--muted);font-size:16px;line-height:1.6}
.outcomes{display:grid;grid-template-columns:.8fr 1.2fr;gap:7vw;padding:130px 24px;background:var(--paper)}.outcome-copy h2{margin:25px 0 0;font-size:clamp(50px,5.4vw,86px);font-weight:430;letter-spacing:-.065em;line-height:.94}.outcome-sequence{border-top:1px solid var(--black)}.outcome-sequence article{display:grid;grid-template-columns:50px 190px 1fr;gap:20px;padding:27px 0;border-bottom:1px solid #bfc0b9}.outcome-sequence span{font:8px ui-monospace,monospace}.outcome-sequence h3{margin:0;font-size:21px;font-weight:500}.outcome-sequence p{margin:0;color:var(--muted);font-size:11px;line-height:1.65}
.security{display:grid;grid-template-columns:1fr 1fr;gap:8vw;align-items:center;padding:140px 8vw;background:#d9d8d1}.security h2{margin:27px 0;font-size:clamp(52px,5.5vw,88px);font-weight:430;letter-spacing:-.065em;line-height:.94}.security>div>p:last-of-type{max-width:600px;color:#555750;font-size:14px;line-height:1.7}.security button{margin-top:35px;border:1px solid var(--black);background:transparent}.security-board{border:1px solid #a8aaa2;background:var(--white)}.security-board header,.security-board article{display:flex;justify-content:space-between;padding:18px 20px;border-bottom:1px solid var(--line)}.security-board header{font:8px ui-monospace,monospace}.security-board header b{color:var(--green)}.security-board header i{display:inline-block;width:6px;height:6px;margin-right:6px;border-radius:50%;background:var(--green)}.security-board article span{color:#656760;font-size:11px}.security-board article b{font-size:12px}.security-board footer{padding:50px 20px 20px;font-size:28px;letter-spacing:-.04em}
.closing{min-height:720px;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:80px 24px;background:var(--white);text-align:center}.closing h2{margin:25px 0 42px;font-size:clamp(65px,8vw,126px);font-weight:430;letter-spacing:-.075em;line-height:.86}.closing button{border:1px solid var(--black);background:var(--black);color:#fff}.footer{display:grid;grid-template-columns:1fr 1fr 1fr;gap:30px;align-items:end;padding:55px 24px;background:var(--black);color:#fff}.footer-wordmark{color:#fff;text-decoration:none;font-size:31px;font-weight:550}.footer p{max-width:360px;margin:0;color:#a9aba4;font-size:11px;line-height:1.6}.footer nav{justify-self:end;display:flex;gap:22px;flex-wrap:wrap;justify-content:flex-end}.footer nav a,.footer nav span{color:#a9aba4;text-decoration:none;font-size:9px}
.overlay{position:fixed;z-index:100;inset:0;display:grid;place-items:center;padding:20px;background:#000b;backdrop-filter:blur(12px)}.modal{width:min(780px,100%);display:grid;grid-template-columns:230px 1fr;background:var(--white);box-shadow:0 30px 100px #0008}.modal>header{display:flex;flex-direction:column;justify-content:space-between;padding:25px;background:var(--black);color:#fff}.modal>header b{letter-spacing:.08em}.modal>header button{align-self:flex-start;border:0;background:transparent;color:#fff;font-size:30px;cursor:pointer}.modal>div{padding:55px}.modal h2{margin:18px 0 13px;font-size:53px;font-weight:450;letter-spacing:-.065em}.modal>div>span{color:var(--muted);font-size:12px}.modal form{margin-top:38px}.modal label{display:flex;justify-content:space-between;margin-bottom:8px;font-size:10px}.modal label small{color:#777}.modal input{width:100%;border:1px solid #bbbdb5;background:#fff;padding:14px;font:12px ui-monospace,monospace;outline:none}.modal form button{width:100%;display:flex;justify-content:space-between;margin-top:10px;border:0;background:var(--black);padding:15px;color:#fff;cursor:pointer}.modal form button:disabled{opacity:.5}.modal form i{font-style:normal}.error{color:#8c2828!important;font-size:11px!important}
.landing .section-heading h2,.landing .outcome-copy h2,.landing .security h2,.landing .closing h2{color:var(--black)}.landing .section-heading.inverse h2{color:#fff}
@keyframes orbit{to{transform:translate(-50%,-50%) rotate(360deg)}}@keyframes float{50%{transform:translateY(-12px)}}@keyframes pulse{50%{opacity:.3;transform:scale(1.1)}}
@media(max-width:950px){.nav nav{display:none}.hero h1{font-size:clamp(58px,12vw,95px)}.system-layout,.outcomes,.security{grid-template-columns:1fr}.system-visual{min-height:540px}.innovation-grid{grid-template-columns:1fr}.innovation-grid article{min-height:560px}.function-grid{grid-template-columns:repeat(2,1fr)}.section-heading{grid-template-columns:1fr}.trust-strip{grid-template-columns:1fr;gap:20px}.trust-strip div{grid-template-columns:repeat(3,1fr);gap:15px}.footer{grid-template-columns:1fr}.footer nav{justify-self:start;justify-content:flex-start}}
@media(max-width:650px){.announcement{padding:0 12px;font-size:9px}.announcement a{display:none}.nav{grid-template-columns:1fr auto;top:42px}.wordmark{grid-column:1}.nav-right{grid-column:2}.nav-right .login{display:none}.hero{min-height:810px}.hero-copy{bottom:55px}.hero h1{font-size:58px}.hero-bottom{align-items:flex-start;flex-direction:column}.hero-bottom button{width:100%}.scroll-cue,.hero-signal{display:none}.monolith{height:280px;width:110px}.system-section,.functions-section,.innovations{padding:90px 16px}.section-heading{margin-bottom:45px}.section-heading h2{font-size:48px}.system-visual{min-height:430px}.ring-two{width:360px;height:360px}.ring-one{width:240px;height:240px}.node{padding:7px;font-size:7px}.layer-list button{min-height:140px;padding:20px}.system-footer,.function-copy{align-items:flex-start;flex-direction:column}.function-grid{grid-template-columns:1fr}.function-grid article{min-height:135px}.outcomes{padding:90px 16px}.outcome-copy h2{font-size:50px}.outcome-sequence article{grid-template-columns:36px 1fr}.outcome-sequence p{grid-column:2}.security{padding:90px 16px}.security h2{font-size:49px}.closing{min-height:600px}.closing h2{font-size:60px}.modal{grid-template-columns:1fr}.modal>header{flex-direction:row}.modal>div{padding:35px 24px}.modal h2{font-size:44px}}
@media(prefers-reduced-motion:reduce){.landing *{animation:none!important;scroll-behavior:auto!important}}
</style>
