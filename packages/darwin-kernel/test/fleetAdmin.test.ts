import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  evaluateAutonomy,
  governFleetAction,
  fleetAdminConstitution,
  buildApprovalCard,
  applyDecision,
  priorityOf,
  FleetAutonomyLedger,
  FleetAdapterRegistry,
  memoryAdapter,
  domainOfCategory,
  DEFAULT_DOMAIN_POLICIES,
  AdminSeverity,
  type AdminAction,
  type AdminEvent,
} from '../src/fleetAdmin/index.ts';

const now = '2026-07-01T00:00:00.000Z';

function action(over: Partial<AdminAction> = {}): AdminAction {
  return {
    id: 'act_1',
    product: 'apparently',
    domain: 'billing',
    type: 'billing:issue_refund',
    actor: 'billing-swarm',
    confidence: 0.95,
    reversibility: 'reversible',
    blastRadius: 'single',
    intent: 'Refund $12 duplicate charge',
    amountUsd: 12,
    at: now,
    ...over,
  };
}

// ---------- category → domain mapping ----------
test('category maps to its domain, unknown fails closed to infra', () => {
  assert.equal(domainOfCategory('refund_request'), 'billing');
  assert.equal(domainOfCategory('kyc_identity'), 'users_access');
  assert.equal(domainOfCategory('security_alert'), 'infra');
  assert.equal(domainOfCategory('totally_unknown'), 'infra');
});

// ---------- autonomy dial ----------
test('small reversible high-confidence refund is auto', () => {
  const d = evaluateAutonomy(action());
  assert.equal(d.tier, 'auto');
  assert.equal(d.requiresHuman, false);
});

test('refund over the money cap forces human', () => {
  const d = evaluateAutonomy(action({ amountUsd: 500 }));
  assert.equal(d.tier, 'human');
});

test('low confidence drops to co_pilot, very low to human', () => {
  assert.equal(evaluateAutonomy(action({ confidence: 0.7 })).tier, 'co_pilot');
  assert.equal(evaluateAutonomy(action({ confidence: 0.2 })).tier, 'human');
});

test('always-human verb is never auto even at full confidence', () => {
  const d = evaluateAutonomy(
    action({ type: 'billing:dispute_chargeback', confidence: 1, amountUsd: 0 }),
  );
  assert.equal(d.tier, 'human');
});

test('infra ceiling clamps auto down to co_pilot', () => {
  const d = evaluateAutonomy(
    action({ domain: 'infra', type: 'infra:rollback_deploy', amountUsd: 0, confidence: 0.99 }),
  );
  assert.equal(d.ceiling, 'co_pilot');
  assert.equal(d.tier, 'co_pilot');
});

test('irreversible fleet-wide action forces human', () => {
  const d = evaluateAutonomy(
    action({ domain: 'users_access', type: 'users_access:reset_password', reversibility: 'irreversible', blastRadius: 'fleet', amountUsd: 0 }),
  );
  assert.equal(d.tier, 'human');
});

test('unknown domain fails closed to human', () => {
  // @ts-expect-error deliberately invalid domain
  const d = evaluateAutonomy(action({ domain: 'nonsense' }));
  assert.equal(d.tier, 'human');
});

// ---------- composition with the constitution ----------
const constitution = fleetAdminConstitution();

test('governFleetAction: auto refund allowed + receipt minted', () => {
  const v = governFleetAction({ action: action(), constitution });
  assert.equal(v.decision, 'allow');
  assert.equal(v.tier, 'auto');
  assert.ok(v.receipt.digest.length > 0);
});

test('governFleetAction: always-escalate verb never auto-allows', () => {
  const v = governFleetAction({
    action: action({ type: 'users_access:delete_account', domain: 'users_access', amountUsd: 0 }),
    constitution,
  });
  assert.notEqual(v.decision, 'allow');
  assert.equal(v.tier === 'auto', false);
});

test('governFleetAction never upgrades a constitution escalate into allow', () => {
  // 'billing:move_funds' is always-escalate in the constitution, but its autonomy
  // inputs (reversible, single, high-confidence, $0) would otherwise compute 'auto'.
  // Composition must keep it escalated — the dial can only ever lower autonomy.
  const a = action({ type: 'billing:move_funds', amountUsd: 0, confidence: 1, reversibility: 'reversible', blastRadius: 'single' });
  assert.equal(evaluateAutonomy(a).tier, 'auto');
  const v = governFleetAction({ action: a, constitution });
  assert.equal(v.decision, 'escalate');
  assert.notEqual(v.tier, 'auto');
});

// ---------- approval bridge ----------
test('approval card carries the four fields + receipt digest + callback', () => {
  const v = governFleetAction({ action: action({ amountUsd: 500 }), constitution });
  const card = buildApprovalCard({ action: action({ amountUsd: 500 }), verdict: v, callbackUrl: 'https://orch/api/fleet/callback' });
  assert.equal(card.status, 'pending');
  assert.ok(card.why && card.risk && card.alternatives.length === 3);
  assert.equal(card.receiptDigest, v.receipt.digest);
  assert.equal(card.callbackUrl, 'https://orch/api/fleet/callback');
  const decided = applyDecision(card, { actionId: card.actionId, decision: 'approve', approver: 'kalepasch@gmail.com', at: now });
  assert.equal(decided.status, 'approved');
});

test('priority ranks irreversible fleet-wide money highest', () => {
  const low = priorityOf(action());
  const high = priorityOf(action({ reversibility: 'irreversible', blastRadius: 'fleet', amountUsd: 2000, confidence: 0.4 }));
  assert.ok(high > low);
});

// ---------- flywheel ----------
test('ledger streaks, promotion candidates, and autonomy rate', () => {
  const ledger = new FleetAutonomyLedger();
  for (let i = 0; i < 20; i++) ledger.record({ domain: 'billing', actionType: 'billing:issue_refund', decision: 'approve' });
  const cands = ledger.promotionCandidates((d) => DEFAULT_DOMAIN_POLICIES[d].ceiling);
  assert.equal(cands.length, 1);
  assert.equal(cands[0]!.recommendTier, 'auto');
  // an edit resets the streak
  ledger.record({ domain: 'billing', actionType: 'billing:issue_refund', decision: 'modify' });
  assert.equal(ledger.promotionCandidates((d) => DEFAULT_DOMAIN_POLICIES[d].ceiling).length, 0);
  assert.ok(ledger.autonomyRate().rate > 0.9);
});

// ---------- adapter registry ----------
test('adapter registry polls all apps and isolates failures', async () => {
  const reg = new FleetAdapterRegistry();
  const ev: AdminEvent = {
    id: 'ev1', product: 'galop', domain: 'billing', category: 'refund_request',
    severity: AdminSeverity.WARNING, title: 'refund', summary: 'dup charge', at: '2026-07-01T01:00:00.000Z',
  };
  reg.register(memoryAdapter('galop', { events: [ev] }));
  reg.register(memoryAdapter('hisanta'));
  const res = await reg.pollAll('2026-07-01T00:00:00.000Z');
  const galop = res.find((r) => r.product === 'galop')!;
  assert.equal(galop.events.length, 1);
});
