<template>
  <div class="mc">
    <header class="mc-head">
      <h1>Fleet Admin — Mission Control</h1>
      <button :disabled="busy" @click="refreshAll">↻ Refresh</button>
    </header>

    <section class="kpis">
      <div class="kpi">
        <div class="kpi-label">Answered from plane</div>
        <div class="kpi-value">{{ pct(kpi?.answeredFromPlaneRate) }}</div>
        <div class="kpi-sub" v-if="kpi?.trend">Δ {{ kpi.trend.deltaPct }}% vs prior</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Pending approvals</div>
        <div class="kpi-value">{{ approvals.length }}</div>
        <div class="kpi-sub">across all apps</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Net treasury</div>
        <div class="kpi-value">${{ treasury?.netUsd ?? '—' }}</div>
        <div class="kpi-sub">saved − cost</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Safe promotions</div>
        <div class="kpi-value">{{ promo?.recommended?.length ?? 0 }}</div>
        <div class="kpi-sub">{{ promo?.safeToAcceptAll ? 'accept-all ready' : 'review' }}</div>
      </div>
    </section>

    <div class="cols">
      <section class="panel">
        <h2>Human queue <span class="dim">(ranked by attention)</span></h2>
        <p v-if="!approvals.length" class="dim">Nothing waiting — swarms handling the routine.</p>
        <ul class="rows">
          <li v-for="a in approvals" :key="a.action_id || a.actionId">
            <span class="badge" :data-domain="a.domain">{{ a.domain }}</span>
            <span class="row-title">{{ a.title }}</span>
            <span class="chip">{{ a.tier }}</span>
            <span class="chip" v-if="a.amount_usd">${{ a.amount_usd }}</span>
          </li>
        </ul>
      </section>

      <section class="panel">
        <h2>Cross-app incidents</h2>
        <p v-if="!incidents.length" class="dim">No correlated incidents.</p>
        <ul class="rows">
          <li v-for="i in incidents" :key="i.id">
            <span class="badge" data-domain="infra">{{ i.products?.join(', ') }}</span>
            <span class="row-title">{{ i.summary }}</span>
          </li>
        </ul>
      </section>
    </div>

    <section class="panel">
      <h2>Autonomy attestation</h2>
      <p v-if="attestation">
        Rate <b>{{ pct(attestation.answeredFromPlaneRate) }}</b> · regressions
        <b>{{ attestation.regressions }}</b> · red-team envelope <b>{{ attestation.redTeamResidualHarm }}</b>
        · <span :class="attMeets ? 'ok' : 'warn'">{{ attMeets ? 'meets trust bar' : 'below bar' }}</span>
      </p>
      <p class="dim mono" v-if="attestation">digest {{ (attestation.digest || '').slice(0,24) }}…</p>
    </section>
  </div>
</template>

<script setup lang="ts">
const supabase = useSupabaseClient<any>()
const busy = ref(false)
const kpi = ref<any>(null)
const approvals = ref<any[]>([])
const treasury = ref<any>(null)
const promo = ref<any>(null)
const incidents = ref<any[]>([])
const attestation = ref<any>(null)
const attMeets = ref(false)

function pct(x: number | undefined) { return x === undefined ? '—' : Math.round(x * 100) + '%' }
async function safe<T>(p: Promise<T>, fallback: T): Promise<T> { try { return await p } catch { return fallback } }

async function refreshAll() {
  busy.value = true
  try {
    const [k, a, t, p, inc, att] = await Promise.all([
      safe($fetch<any>('/api/fleet/kpi'), null),
      safe($fetch<any>('/api/fleet/approvals?status=pending'), { items: [] }),
      safe($fetch<any>('/api/fleet/treasury'), null),
      safe($fetch<any>('/api/fleet/self-promotion'), null),
      safe($fetch<any>('/api/fleet/incidents'), { incidents: [] }),
      safe($fetch<any>('/api/fleet/attestation'), null),
    ])
    kpi.value = k
    approvals.value = a?.items ?? []
    treasury.value = t
    promo.value = p
    incidents.value = inc?.incidents ?? []
    attestation.value = att?.attestation ?? null
    attMeets.value = att?.verification?.meetsBar ?? false
  } finally { busy.value = false }
}

onMounted(() => {
  refreshAll()
  supabase.channel('fleet')
    .on('postgres_changes', { event: '*', schema: 'public', table: 'fleet_approvals' }, refreshAll)
    .subscribe()
})
</script>

<style scoped>
.mc { font-family: 'JetBrains Mono', monospace; max-width: 1100px; margin: 0 auto; padding: 24px; color: #e7e7ea; }
.mc-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.mc-head h1 { font-size: 20px; font-weight: 700; }
.mc-head button { background: #2b2b31; color: #e7e7ea; border: 1px solid #3a3a42; border-radius: 6px; padding: 6px 12px; cursor: pointer; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
.kpi { background: #17171b; border: 1px solid #2a2a30; border-radius: 10px; padding: 14px; }
.kpi-label { font-size: 11px; color: #9a9aa2; text-transform: uppercase; letter-spacing: .04em; }
.kpi-value { font-size: 26px; font-weight: 700; margin: 4px 0; }
.kpi-sub { font-size: 11px; color: #7a7a82; }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.panel { background: #17171b; border: 1px solid #2a2a30; border-radius: 10px; padding: 14px; margin-bottom: 12px; }
.panel h2 { font-size: 13px; margin-bottom: 10px; }
.dim { color: #7a7a82; font-size: 12px; }
.mono { font-size: 11px; }
.rows { list-style: none; display: flex; flex-direction: column; gap: 6px; }
.rows li { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.row-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.badge { font-size: 10px; padding: 2px 6px; border-radius: 4px; background: #26313f; color: #7fb0ff; }
.badge[data-domain='billing'] { background: #123227; color: #5fe0a0; }
.badge[data-domain='trust_safety'] { background: #2b2340; color: #b79cff; }
.badge[data-domain='infra'] { background: #33291a; color: #f0b060; }
.chip { font-size: 10px; padding: 2px 6px; border-radius: 4px; background: #26262c; color: #b5b5bd; }
.ok { color: #5fe0a0; } .warn { color: #f0b060; }
</style>
