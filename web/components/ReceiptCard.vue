<script setup lang="ts">
/**
 * ReceiptCard — what the operator sees after an autonomous action.
 *
 * Two things must ALWAYS be visible, and the component is built around them:
 *
 *   1. The undo control. When an action cannot be reversed the button is not
 *      hidden — it is shown DISABLED with the reason. Hiding it would leave the
 *      operator unsure whether reversal was impossible or merely unimplemented,
 *      and that ambiguity is resolved at the worst possible moment.
 *   2. The counterfactual cost. Without it the operator sees only the price of
 *      acting and never the price of NOT acting, so every autonomous action
 *      reads as pure expense.
 */
import { computed } from 'vue'

interface UndoPlan {
  available: boolean
  method?: string
  reason?: string
}

interface Receipt {
  action: string
  explanation: string
  cost_usd: number
  counterfactual_cost_usd: number
  undo: UndoPlan
  actor?: string
  at?: string | null
  net_benefit_usd?: number
}

const props = defineProps<{ receipt: Receipt }>()
const emit = defineEmits<{ (e: 'undo', action: string): void }>()

const money = (n: unknown) => {
  const value = typeof n === 'number' && Number.isFinite(n) ? n : 0
  return `$${value.toFixed(2)}`
}

const canUndo = computed(() => props.receipt?.undo?.available === true)

const undoTitle = computed(() =>
  canUndo.value
    ? props.receipt.undo.method || 'Undo this action'
    : props.receipt?.undo?.reason || 'This action cannot be undone',
)

const netBenefit = computed(() => {
  const r = props.receipt
  if (typeof r?.net_benefit_usd === 'number') return r.net_benefit_usd
  return (r?.counterfactual_cost_usd ?? 0) - (r?.cost_usd ?? 0)
})
</script>

<template>
  <section class="receipt-card" data-testid="receipt-card">
    <header>
      <h3 data-testid="receipt-action">{{ receipt.action }}</h3>
      <p data-testid="receipt-explanation">{{ receipt.explanation }}</p>
    </header>

    <dl class="receipt-costs">
      <div>
        <dt>Cost of acting</dt>
        <dd data-testid="receipt-cost">{{ money(receipt.cost_usd) }}</dd>
      </div>
      <div>
        <!-- The price of doing nothing. Always rendered. -->
        <dt>Counterfactual cost</dt>
        <dd data-testid="receipt-counterfactual-cost">
          {{ money(receipt.counterfactual_cost_usd) }}
        </dd>
      </div>
      <div>
        <dt>Net benefit</dt>
        <dd data-testid="receipt-net-benefit">{{ money(netBenefit) }}</dd>
      </div>
    </dl>

    <!--
      Rendered whether or not undo is possible. A disabled button with a reason
      tells the operator something; a missing button tells them nothing.
    -->
    <button
      type="button"
      class="receipt-undo"
      data-testid="receipt-undo-button"
      :disabled="!canUndo"
      :title="undoTitle"
      @click="canUndo && emit('undo', receipt.action)"
    >
      Undo
    </button>
    <p v-if="!canUndo" class="receipt-undo-reason" data-testid="receipt-undo-reason">
      {{ undoTitle }}
    </p>
  </section>
</template>
