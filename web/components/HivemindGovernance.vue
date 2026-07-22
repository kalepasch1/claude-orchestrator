<script setup lang="ts">
type Goal = 'earn' | 'adopt' | 'protect' | 'govern'

const supabase = useSupabaseClient<any>()
const state = ref<any>(null)
const active = ref<Goal>('earn')
const busy = ref('')
const message = ref('')

const goals: Array<{ id: Goal; label: string; promise: string }> = [
  { id: 'earn', label: 'Earn', promise: 'Value returned to you' },
  { id: 'adopt', label: 'Adopt', promise: 'Verified advantages ready' },
  { id: 'protect', label: 'Protect', promise: 'Risk already contained' },
  { id: 'govern', label: 'Govern', promise: 'Decisions needing your voice' },
]

async function authed<T>(url: string, options: any = {}) {
  const { data: { session } } = await supabase.auth.getSession()
  return $fetch<T>(url, {
    ...options,
    headers: session?.access_token ? { authorization: `Bearer ${session.access_token}` } : {},
  })
}

const dollars = (cents: any) => new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
}).format(Number(cents || 0) / 100)

const relative = (value: string) => {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60_000))
  if (minutes < 2) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  if (minutes < 1_440) return `${Math.round(minutes / 60)}h ago`
  return `${Math.round(minutes / 1_440)}d ago`
}

async function load() {
  try {
    state.value = await authed('/api/hivemind/outcomes')
  } catch (error: any) {
    message.value = error?.data?.message || error?.message || 'The Hivemind outcome view is temporarily unavailable.'
  }
}

async function act(key: string, url: string, body: any) {
  busy.value = key
  message.value = ''
  try {
    await authed(url, { method: 'POST', body })
    message.value = key === 'refresh'
      ? 'Your portfolio protections, credits, and opportunities are current.'
      : 'Your decision was recorded with its safeguards.'
    await load()
  } catch (error: any) {
    message.value = error?.data?.message || error?.data?.data?.message || error?.message || 'That action could not be completed safely.'
  } finally {
    busy.value = ''
  }
}

const prepare = (opportunity: any) => act(
  `bundle:${opportunity.id}`,
  '/api/hivemind/governance',
  { action: 'bundle', opportunity_id: opportunity.id, objective: opportunity.title },
)
const vote = (proposal: any, decision: 'support' | 'oppose') => act(
  `vote:${proposal.id}`,
  '/api/hivemind/governance',
  { action: 'vote', proposal_id: proposal.id, vote: decision },
)
const discloseConflict = (proposal: any) => act(
  `conflict:${proposal.id}`,
  '/api/hivemind/outcomes',
  { action: 'conflict', proposal_id: proposal.id, relationship_class: 'material_beneficiary', material_interest: true },
)

onMounted(() => {
  load()
  const timer = setInterval(load, 60_000)
  onUnmounted(() => clearInterval(timer))
})
</script>

<template>
  <section class="cockpit" aria-labelledby="hivemind-outcomes-title">
    <header class="hero">
      <div>
        <span class="eyebrow">MADEUS HIVEMIND</span>
        <h1 id="hivemind-outcomes-title">The network works.<br><em>You steer the outcomes.</em></h1>
      </div>
      <div class="hero-copy">
        <p>Madeus quietly compounds what works across your portfolio, contains what does not, and returns the value to the people who created it.</p>
        <div class="pulse" :class="{ attention: state?.attention?.length }">
          <i />
          <span v-if="state?.attention?.length">{{ state.attention.length }} outcome{{ state.attention.length === 1 ? '' : 's' }} need your attention</span>
          <span v-else>Portfolio protected · no action needed</span>
          <button :disabled="busy === 'refresh'" @click="act('refresh', '/api/hivemind/outcomes', { action: 'refresh' })">Check now</button>
        </div>
      </div>
    </header>

    <div v-if="!state" class="loading">Preparing your outcomes…</div>
    <template v-else>
      <aside v-if="state.attention.length" class="attention" aria-label="Needs attention">
        <div v-for="item in state.attention" :key="`${item.title}:${item.outcome}`">
          <span>{{ item.severity || 'Review' }}</span>
          <b>{{ item.title }}</b>
          <p>{{ item.outcome }}</p>
        </div>
      </aside>

      <nav class="goals" aria-label="Hivemind outcomes">
        <button
          v-for="goal in goals"
          :key="goal.id"
          :class="{ active: active === goal.id }"
          :aria-current="active === goal.id ? 'page' : undefined"
          @click="active = goal.id"
        >
          <b>{{ goal.label }}</b>
          <span>{{ goal.promise }}</span>
        </button>
      </nav>

      <section v-if="active === 'earn'" class="view" aria-labelledby="earn-title">
        <div class="view-heading">
          <div><span>YOUR SHARE OF NETWORK VALUE</span><h2 id="earn-title">{{ dollars(state.account.available_cents) }} ready</h2></div>
          <p>Credits are automatically attributed, risk-adjusted, and cleared. Available value is applied according to your subscription preference.</p>
        </div>
        <div class="money-grid">
          <article><span>Lifetime earned</span><b>{{ dollars(state.account.lifetime_earned_cents) }}</b><small>From verified reuse and useful learning</small></article>
          <article><span>Clearing</span><b>{{ dollars(state.account.pending_settlement_cents) }}</b><small>Becomes available after outcome verification</small></article>
          <article><span>Protected reserve</span><b>{{ dollars(state.account.reserved_cents) }}</b><small>Held against reversals and warranty risk</small></article>
        </div>
        <div class="feed">
          <div v-for="outcome in state.outcomes.filter((x: any) => ['earnings', 'learning'].includes(x.kind))" :key="outcome.title">
            <i class="good" /><b>{{ outcome.title }}</b><strong v-if="outcome.amount_cents">{{ dollars(outcome.amount_cents) }}</strong>
          </div>
          <div v-if="!state.outcomes.some((x: any) => ['earnings', 'learning'].includes(x.kind))" class="empty">Nothing new to reconcile. Earnings continue to update automatically.</div>
        </div>
        <details class="receipt">
          <summary>View accounting receipt</summary>
          <div v-if="state.earn.clearing[0]">
            <span>Current period</span><b>{{ dollars(state.earn.clearing[0].net_available_cents) }} net available</b>
            <small>Reserve {{ dollars(state.earn.clearing[0].reserve_cents) }} · receipt {{ state.earn.clearing[0].clearing_digest.slice(0, 12) }}</small>
          </div>
          <p v-else>Your first accounting receipt will appear after value is earned.</p>
        </details>
      </section>

      <section v-else-if="active === 'adopt'" class="view" aria-labelledby="adopt-title">
        <div class="view-heading">
          <div><span>VERIFIED ADVANTAGE</span><h2 id="adopt-title">{{ state.adopt.opportunities.length }} next-best move{{ state.adopt.opportunities.length === 1 ? '' : 's' }}</h2></div>
          <p>Madeus finds improvements proven elsewhere, adapts them locally, and keeps material execution behind your approval boundary.</p>
        </div>
        <div class="opportunities">
          <article v-for="opportunity in state.adopt.opportunities" :key="opportunity.id">
            <div><span>{{ Math.round(Number(opportunity.confidence) * 100) }}% confidence</span><h3>{{ opportunity.title }}</h3><p>{{ opportunity.explanation }}</p></div>
            <div class="value"><b>{{ opportunity.predicted_value_cents ? dollars(opportunity.predicted_value_cents) : 'Compounding value' }}</b><small>predicted portfolio value</small></div>
            <button :disabled="busy === `bundle:${opportunity.id}`" @click="prepare(opportunity)">Prepare safely</button>
          </article>
          <div v-if="!state.adopt.opportunities.length" class="empty">No verified advantage is waiting. Madeus will surface one when evidence clears your thresholds.</div>
        </div>
        <div v-if="state.adopt.bundles.length" class="prepared">
          <span>PREPARED FOR YOU</span>
          <div v-for="bundle in state.adopt.bundles.slice(0, 4)" :key="bundle.id">
            <b>{{ bundle.objective }}</b><small>{{ bundle.status.replaceAll('_', ' ') }}</small>
          </div>
        </div>
      </section>

      <section v-else-if="active === 'protect'" class="view" aria-labelledby="protect-title">
        <div class="view-heading">
          <div><span>PORTFOLIO IMMUNE SYSTEM</span><h2 id="protect-title">{{ state.attention.length ? 'Contained. Review when ready.' : 'Protected by default.' }}</h2></div>
          <p>Permissions, privacy, failures, and shared dependencies are monitored continuously. Affected scope is contained while healthy services stay on the last verified version.</p>
        </div>
        <div class="protection-grid">
          <article><i class="good" /><b>{{ state.protect.proofs.filter((x: any) => x.verdict === 'verified').length }} verified executions</b><p>Policy compliance confirmed without storing execution payloads.</p></article>
          <article><i :class="state.protect.licenses.some((x: any) => x.status === 'suspended') ? 'warn' : 'good'" /><b>{{ state.protect.licenses.filter((x: any) => x.status === 'active').length }} active permissions</b><p>{{ state.protect.licenses.filter((x: any) => x.status === 'suspended').length }} safely suspended.</p></article>
          <article><i class="good" /><b>{{ state.earn.failures.length }} reusable failure insight{{ state.earn.failures.length === 1 ? '' : 's' }}</b><p>Context mismatches are separated from genuinely portable failures.</p></article>
          <article><i class="good" /><b>No private payload pooling</b><p>Only bounded commitments, aggregate outcomes, and signed receipts cross the network plane.</p></article>
        </div>
        <div v-if="state.protect.immune.length" class="feed">
          <div v-for="item in state.protect.immune" :key="item.id"><i class="good" /><b>{{ item.customer_impact }}</b><small>{{ relative(item.created_at) }}</small></div>
        </div>
        <details class="receipt">
          <summary>How protection works</summary>
          <p>Madeus checks granted scope, usage limits, prohibited uses, expiry, proof freshness, dependency health, and rollback readiness. It stores hashes and policy receipts—not your code, prompts, customer data, model inputs, or outputs.</p>
        </details>
      </section>

      <section v-else class="view" aria-labelledby="govern-title">
        <div class="view-heading">
          <div><span>FOUNDER CONSTITUTION</span><h2 id="govern-title">{{ state.govern.proposals.length }} decision{{ state.govern.proposals.length === 1 ? '' : 's' }} open</h2></div>
          <p>Every change is simulated against different member types before voting. One organization gets one vote; rights-sensitive changes need a stronger majority.</p>
        </div>
        <div class="proposals">
          <article v-for="proposal in state.govern.proposals" :key="proposal.id">
            <div class="proposal-main">
              <span>{{ proposal.policy_domain.replaceAll('_', ' ') }}</span>
              <h3>{{ proposal.title }}</h3>
              <p>{{ proposal.rationale }}</p>
              <div v-if="proposal.simulation" class="simulation">
                <b>{{ proposal.simulation.recommendation === 'proceed' ? 'Safe to decide' : 'Revision recommended' }}</b>
                <span>Rights impact {{ proposal.simulation.rights_impact.score }}/100</span>
                <span>Capture risk {{ proposal.simulation.capture_risk.score }}/100</span>
              </div>
            </div>
            <div v-if="proposal.status === 'open'" class="decision">
              <button :disabled="!proposal.simulation || proposal.simulation.recommendation !== 'proceed' || busy === `vote:${proposal.id}`" @click="vote(proposal, 'support')">Support</button>
              <button class="secondary" :disabled="busy === `vote:${proposal.id}`" @click="vote(proposal, 'oppose')">Oppose</button>
              <button class="link" :disabled="busy === `conflict:${proposal.id}`" @click="discloseConflict(proposal)">I have a material interest</button>
            </div>
            <b v-else class="status">{{ proposal.status }}</b>
          </article>
          <div v-if="!state.govern.proposals.length" class="empty">No network decisions need your voice.</div>
        </div>
      </section>

      <p v-if="message" class="notice" role="status">{{ message }}</p>
    </template>
  </section>
</template>

<style scoped>
.cockpit{min-height:100vh;padding:104px clamp(18px,4vw,64px);background:#f2f2ee;color:#111}.hero,.view,.goals,.attention{max-width:1220px;margin:auto}.hero{display:grid;grid-template-columns:1.35fr .65fr;gap:8vw;align-items:end}.eyebrow,.view-heading span,.prepared>span,.proposal-main>span{font:750 9px/1.2 JetBrains Mono,monospace;letter-spacing:.15em;color:#27704e}.hero h1{margin:18px 0 0;font-size:clamp(54px,7vw,104px);line-height:.91;letter-spacing:-.07em;font-weight:480}.hero h1 em{font-style:normal;color:#85857e}.hero-copy>p,.view-heading>p{color:#666761;font-size:13px;line-height:1.75}.pulse{margin-top:20px;display:flex;align-items:center;gap:9px;border-top:1px solid #d5d5cf;padding-top:15px;font:700 9px/1.2 JetBrains Mono,monospace}.pulse i,.protection-grid i,.feed i{width:8px;height:8px;border-radius:50%;background:#43a06b;box-shadow:0 0 0 4px #dcece2}.pulse.attention i,.protection-grid i.warn{background:#cf8c37;box-shadow:0 0 0 4px #f2e5d4}.pulse button{margin-left:auto;border:0;background:transparent;text-decoration:underline;font:inherit}.loading{max-width:1220px;margin:50px auto;padding:30px;border-top:1px solid #d4d4ce;color:#777}.attention{margin-top:34px;display:grid;gap:8px}.attention div{display:grid;grid-template-columns:auto .6fr 1fr;gap:18px;align-items:center;padding:14px 18px;background:#211f1b;color:#fff;border-radius:12px}.attention span{color:#e8b66e;font:700 9px JetBrains Mono,monospace;text-transform:uppercase}.attention p{margin:0;color:#c7c6c2;font-size:11px}.goals{display:grid;grid-template-columns:repeat(4,1fr);margin-top:52px;border:1px solid #d3d3cd;border-radius:15px;overflow:hidden;background:#e8e8e3}.goals button{display:grid;gap:5px;padding:17px 19px;text-align:left;border:0;border-right:1px solid #d3d3cd;background:transparent;color:#64645f}.goals button:last-child{border-right:0}.goals button.active{background:#111;color:#fff}.goals b{font-size:15px}.goals span{font-size:9px}.view{margin-top:10px;padding:34px;border:1px solid #d3d3cd;border-radius:15px;background:#fff;min-height:520px}.view-heading{display:grid;grid-template-columns:1fr .65fr;gap:8vw;align-items:end}.view h2{margin:6px 0 0;font-size:clamp(38px,5vw,70px);line-height:.96;letter-spacing:-.06em}.money-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:32px}.money-grid article,.protection-grid article{padding:19px;border:1px solid #deded8;border-radius:11px;background:#f8f8f5}.money-grid span,.money-grid small{display:block;color:#72736d;font-size:9px}.money-grid b{display:block;margin:8px 0;font-size:28px;letter-spacing:-.04em}.feed,.prepared{margin-top:20px;border-top:1px solid #deded8}.feed>div,.prepared>div{display:flex;align-items:center;gap:12px;padding:13px 4px;border-bottom:1px solid #ededE8;font-size:10px}.feed strong,.feed small,.prepared small{margin-left:auto;color:#6e6f68}.feed i.good{background:#43a06b}.receipt{margin-top:22px;border-radius:10px;background:#f0f4f1;padding:14px 17px;font-size:10px}.receipt summary{cursor:pointer;font-weight:750}.receipt div{display:grid;gap:5px;margin-top:12px}.receipt p{color:#626660;line-height:1.65}.opportunities,.proposals{display:grid;gap:9px;margin-top:30px}.opportunities article{display:grid;grid-template-columns:1fr auto auto;gap:24px;align-items:center;padding:20px;border:1px solid #deded8;border-radius:12px}.opportunities h3,.proposals h3{margin:5px 0;font-size:19px;letter-spacing:-.03em}.opportunities p,.proposals p,.protection-grid p{margin:0;color:#70716b;font-size:10px;line-height:1.55}.opportunities span{font:700 8px JetBrains Mono,monospace;color:#27704e}.value{min-width:130px}.value b,.value small{display:block}.value small{font-size:8px;color:#777}.opportunities button,.decision button{border:0;border-radius:8px;background:#111;color:#fff;padding:11px 14px;font-size:9px;font-weight:750}.prepared{padding-top:16px}.prepared>span{display:block;margin-bottom:8px}.protection-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:9px;margin-top:30px}.protection-grid article{display:grid;grid-template-columns:auto 1fr;gap:8px 12px}.protection-grid i{margin-top:4px}.protection-grid p{grid-column:2}.proposals article{display:grid;grid-template-columns:1fr auto;gap:24px;align-items:center;padding:20px;border:1px solid #deded8;border-radius:12px}.simulation{display:flex;gap:12px;margin-top:13px;font-size:8px}.simulation b{color:#27704e}.simulation span{color:#797a73}.decision{display:grid;grid-template-columns:1fr 1fr;gap:6px}.decision .secondary{background:#e8e8e3;color:#111}.decision .link{grid-column:1/-1;background:transparent;color:#777;padding:5px;text-decoration:underline}.status{text-transform:capitalize}.empty{padding:28px;border:1px dashed #d0d0ca;border-radius:11px;color:#777;font-size:11px}.notice{position:sticky;bottom:16px;z-index:5;max-width:700px;margin:18px auto 0;padding:13px 16px;border-radius:10px;background:#111;color:#fff;font-size:10px}@media(max-width:800px){.cockpit{padding-top:76px}.hero,.view-heading{grid-template-columns:1fr;gap:22px}.goals{grid-template-columns:1fr 1fr}.goals button:nth-child(2){border-right:0}.goals button:nth-child(-n+2){border-bottom:1px solid #d3d3cd}.view{padding:20px}.money-grid,.protection-grid{grid-template-columns:1fr}.opportunities article,.proposals article{grid-template-columns:1fr}.attention div{grid-template-columns:1fr}.value{min-width:0}.simulation{flex-wrap:wrap}}
</style>
