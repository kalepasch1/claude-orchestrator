<script setup lang="ts">
/**
 * The one screen that answers "what do all my products/entities need from me
 * right now".
 *
 * Rendered in BOTH modes from the same component: `private_cockpit` for the
 * operator's own madeus.cc, `apparently_embedded` for in-house teams. The mode
 * is passed through to the API, which decides what comes back; this component
 * simply renders what it is given, so the two surfaces cannot drift apart.
 *
 * The inbox comes pre-ranked by urgency with a human-readable rationale on each
 * row. Both matter: an unranked inbox is a list, and a ranked one whose order
 * nobody can explain gets scrolled past.
 */
const props = withDefaults(defineProps<{
  tenantId?: string
  mode?: 'private_cockpit' | 'apparently_embedded'
}>(), { tenantId: 'founding', mode: 'private_cockpit' })

type Card = {
  entityId: string; displayName: string
  fleet: { running: number; queued: number }
  pendingApprovalCount: number
  nextWave: { waveId: string; label: string; etaMs: number | null } | null
  compliance: { state: string; headline: string }
  latestShipped: { label: string; at: number } | null
  needsYou: boolean
}
type InboxItem = {
  approvalId: string; entityId: string; summary: string
  waitingHours: number; urgency: number; rationale: string
}

const { data, pending } = await useFetch<{
  ok: boolean; entities: Card[]; inbox: InboxItem[]
  totals: { entities: number; running: number; queued: number; pendingApprovals: number }
  operatorTools?: { manageTenants: string; fleetControl: string }
}>('/api/portfolio/dashboard', {
  query: { tenantId: props.tenantId, mode: props.mode },
  default: () => ({ ok: false, entities: [], inbox: [], totals: { entities: 0, running: 0, queued: 0, pendingApprovals: 0 } }),
})

const fmtEta = (ms: number | null) => {
  if (!ms) return 'no ETA'
  const h = Math.round((ms - Date.now()) / 3_600_000)
  if (h < 0) return 'overdue'
  return h < 24 ? `${h}h` : `${Math.round(h / 24)}d`
}
</script>

<template>
  <div class="portfolio">
    <p v-if="pending" class="muted">Loading portfolio…</p>

    <header class="totals">
      <span><strong>{{ data?.totals.entities }}</strong> entities</span>
      <span><strong>{{ data?.totals.running }}</strong> running</span>
      <span><strong>{{ data?.totals.queued }}</strong> queued</span>
      <span><strong>{{ data?.totals.pendingApprovals }}</strong> awaiting you</span>
    </header>

    <!-- The inbox comes FIRST: it is the answer to the question the screen exists
         to ask, and burying it under cards would defeat the point. -->
    <section aria-label="What needs you now">
      <h2>Needs you now</h2>
      <p v-if="!data?.inbox?.length" class="muted">Nothing is waiting on you.</p>
      <ol v-else class="inbox">
        <li v-for="item in data.inbox" :key="item.approvalId">
          <span class="entity">{{ item.entityId }}</span>
          <span class="summary">{{ item.summary }}</span>
          <span class="why">{{ item.rationale }}</span>
        </li>
      </ol>
    </section>

    <section aria-label="Entities">
      <h2>Entities</h2>
      <div class="cards">
        <article
          v-for="card in (data?.entities || [])"
          :key="card.entityId"
          class="card"
          :class="{ 'card--needs-you': card.needsYou }"
        >
          <h3>{{ card.displayName }}</h3>
          <p class="line">{{ card.fleet.running }} running · {{ card.fleet.queued }} queued</p>
          <p class="line">{{ card.pendingApprovalCount }} pending approval{{ card.pendingApprovalCount === 1 ? '' : 's' }}</p>
          <p class="line">
            Next wave:
            <template v-if="card.nextWave">{{ card.nextWave.label }} ({{ fmtEta(card.nextWave.etaMs) }})</template>
            <template v-else>none scheduled</template>
          </p>
          <p class="line muted">{{ card.compliance.headline }}</p>
          <p v-if="card.latestShipped" class="line muted">Last shipped: {{ card.latestShipped.label }}</p>
        </article>
      </div>
    </section>

    <!-- Present only in the private cockpit; the embedded bundle never receives it. -->
    <nav v-if="data?.operatorTools" class="operator" aria-label="Operator tools">
      <a :href="data.operatorTools.manageTenants">Tenants</a>
      <a :href="data.operatorTools.fleetControl">Fleet control</a>
    </nav>
  </div>
</template>

<style scoped>
.portfolio { font-family: system-ui, sans-serif; }
.totals { display: flex; gap: 20px; font-size: 13px; color: #52525b; margin-bottom: 16px; }
h2 { font-size: 14px; text-transform: uppercase; letter-spacing: 0.04em; color: #52525b; margin: 16px 0 8px; }
.inbox { margin: 0; padding-left: 18px; display: grid; gap: 6px; }
.inbox li { display: grid; grid-template-columns: 120px 1fr auto; gap: 10px; align-items: baseline; font-size: 14px; }
.entity { color: #71717a; font-size: 12px; }
.why { color: #71717a; font-size: 12px; }
.cards { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
.card { border: 1px solid #e4e4e7; border-radius: 12px; padding: 12px; }
.card--needs-you { border-color: #f59e0b; }
.card h3 { margin: 0 0 6px; font-size: 15px; }
.line { margin: 2px 0; font-size: 13px; }
.muted { color: #71717a; font-size: 12px; }
.operator { display: flex; gap: 12px; margin-top: 20px; font-size: 13px; }
</style>
