/**
 * ReceiptCard renders the undo button and the counterfactual cost.
 *
 * Rendered with Vue's own server renderer rather than @vue/test-utils + jsdom,
 * because neither is installed in web/ and adding two dependencies to assert on
 * markup would be a larger change than the feature. renderToString exercises
 * the real SFC through @vitejs/plugin-vue, so the assertions are against actual
 * component output, not a stub.
 */
import { describe, expect, it } from 'vitest'
import { renderToString } from 'vue/server-renderer'
import { createSSRApp } from 'vue'

import ReceiptCard from '../ReceiptCard.vue'

const undoableReceipt = {
  action: 'config_changed',
  explanation: 'raised MAX_PARALLEL from 10 to 24',
  cost_usd: 0.1,
  counterfactual_cost_usd: 5,
  net_benefit_usd: 4.9,
  undo: { available: true, method: 'restore prior fleet_config value', reason: '' },
  actor: 'governor',
  at: '2026-08-06T00:00:00Z',
}

const irreversibleReceipt = {
  ...undoableReceipt,
  action: 'money_moved',
  undo: { available: false, method: '', reason: "'money_moved' is irreversible once taken" },
}

const render = (receipt: unknown) =>
  renderToString(createSSRApp(ReceiptCard, { receipt } as never))

describe('ReceiptCard', () => {
  it('renders the undo button', async () => {
    const html = await render(undoableReceipt)

    expect(html).toContain('data-testid="receipt-undo-button"')
    expect(html).toContain('Undo')
  })

  it('renders the counterfactual cost', async () => {
    const html = await render(undoableReceipt)

    expect(html).toContain('data-testid="receipt-counterfactual-cost"')
    expect(html).toContain('Counterfactual cost')
    expect(html).toContain('$5.00')
  })

  it('renders the undo button ENABLED when the action is reversible', async () => {
    const html = await render(undoableReceipt)

    expect(html).not.toMatch(/receipt-undo-button[^>]*disabled/)
    expect(html).toContain('restore prior fleet_config value')
  })

  it('still renders the undo button when the action cannot be undone', async () => {
    // Hiding it would leave the operator unsure whether reversal was impossible
    // or merely unimplemented.
    const html = await render(irreversibleReceipt)

    expect(html).toContain('data-testid="receipt-undo-button"')
    expect(html).toMatch(/disabled/)
  })

  it('states WHY an action cannot be undone', async () => {
    const html = await render(irreversibleReceipt)

    expect(html).toContain('data-testid="receipt-undo-reason"')
    expect(html).toContain('irreversible once taken')
  })

  it('shows the cost of acting alongside the counterfactual', async () => {
    const html = await render(undoableReceipt)

    expect(html).toContain('Cost of acting')
    expect(html).toContain('$0.10')
  })

  it('renders the net benefit', async () => {
    const html = await render(undoableReceipt)

    expect(html).toContain('data-testid="receipt-net-benefit"')
    expect(html).toContain('$4.90')
  })

  it('derives the net benefit when the receipt does not carry one', async () => {
    const { net_benefit_usd: _omitted, ...withoutNet } = undoableReceipt
    const html = await render(withoutNet)

    expect(html).toContain('$4.90')
  })

  it('renders a zero counterfactual rather than omitting it', async () => {
    // An unstated counterfactual reads as "acting saved nothing" — a claim,
    // not an absence — so it must still appear.
    const html = await render({ ...undoableReceipt, counterfactual_cost_usd: 0 })

    expect(html).toContain('Counterfactual cost')
    expect(html).toContain('$0.00')
  })

  it('does not crash on malformed cost values', async () => {
    const html = await render({
      ...undoableReceipt,
      cost_usd: null,
      counterfactual_cost_usd: undefined,
      net_benefit_usd: undefined,
    })

    expect(html).toContain('data-testid="receipt-undo-button"')
    expect(html).toContain('$0.00')
  })
})
