<script setup lang="ts">
/**
 * The four organs a managed startup's workspace grows: Coordination,
 * Interception, Compliance, Risk.
 *
 * Deliberately dumb. All of the judgement — which slots are connected, what to
 * say when they are not, what to link to — lives in
 * server/utils/integrationSlots.ts, which never throws and always returns four
 * views. This component renders whatever it is handed.
 *
 * That split is why the not-connected states are trustworthy: they are unit
 * tested from fixtures rather than depending on a live Apparently, a live
 * Smarter and a live Tomorrow all being up at once.
 */
type SlotView = {
  kind: 'coordination' | 'interception' | 'compliance' | 'risk'
  state: 'connected' | 'not_connected' | 'disabled' | 'degraded'
  headline: string
  href?: string
  detail?: Record<string, unknown>
  reason?: string
}

const props = defineProps<{ tenantId?: string }>()

const { data, pending } = await useFetch<{ ok: boolean; slots: SlotView[] }>(
  '/api/workspace/slots',
  { query: { tenantId: props.tenantId || 'founding' }, default: () => ({ ok: false, slots: [] }) },
)

const LABELS: Record<SlotView['kind'], string> = {
  coordination: 'Coordination',
  interception: 'Legal interception',
  compliance: 'Compliance',
  risk: 'Risk',
}
</script>

<template>
  <section class="slots" aria-label="Workspace integrations">
    <p v-if="pending" class="slot-muted">Loading integrations…</p>

    <article
      v-for="slot in (data?.slots || [])"
      :key="slot.kind"
      class="slot"
      :class="`slot--${slot.state}`"
    >
      <header>
        <h3>{{ LABELS[slot.kind] }}</h3>
        <span class="badge">{{ slot.state.replace('_', ' ') }}</span>
      </header>

      <p class="headline">{{ slot.headline }}</p>

      <!-- A reason is shown, not hidden: "not connected" with no explanation is
           the state operators cannot act on. -->
      <p v-if="slot.reason" class="slot-muted">{{ slot.reason }}</p>

      <a v-if="slot.href" :href="slot.href" class="slot-link">Open</a>
    </article>
  </section>
</template>

<style scoped>
.slots { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
.slot { border: 1px solid #e4e4e7; border-radius: 12px; padding: 12px; }
.slot header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.slot h3 { font-size: 13px; margin: 0; text-transform: uppercase; letter-spacing: 0.04em; color: #52525b; }
.badge { font-size: 11px; padding: 2px 8px; border-radius: 999px; background: #f4f4f5; color: #52525b; }
.slot--connected .badge { background: #dcfce7; color: #166534; }
.slot--not_connected .badge { background: #fef9c3; color: #854d0e; }
.slot--disabled { opacity: 0.6; }
.headline { margin: 8px 0 0; font-size: 14px; }
.slot-muted { color: #71717a; font-size: 12px; margin: 6px 0 0; }
.slot-link { display: inline-block; margin-top: 8px; font-size: 13px; }
</style>
