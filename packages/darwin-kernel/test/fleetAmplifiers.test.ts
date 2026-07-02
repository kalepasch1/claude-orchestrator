import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  precedentAdvice,
  applyPrecedent,
  caseSimilarity,
  governFleetAction,
  fleetAdminConstitution,
  buildApprovalCard,
  deliberate,
  forecastFromEvents,
  correlateEvents,
  quantifyPromotion,
  auctionBoard,
  computeNorthStar,
  DEFAULT_DOMAIN_POLICIES,
  AdminSeverity,
  type AdminAction,
  type AdminEvent,
  type ResolvedCase,
  type LedgerEntry,
  type RoutedActionSummary,
} from '../src/fleetAdmin/index.ts';

const now = '2026-07-01T00:00:00.000Z';
function action(over: Partial<AdminAction> = {}): AdminAction {
  return {
    id: 'a1', product: 'galop', domain: 'billing', type: 'billing:issue_refund', actor: 'swarm',
    confidence: 0.97, reversibility: 'reversible', blastRadius: 'single', intent: 'Refund $9', amountUsd: 9, at: now, ...over,
  };
}
function cases(outcome: ResolvedCase['outcome'], n: number): ResolvedCase[] {
  return Array.from({ length: n }, () => ({ domain: 'billing', type: 'billing:issue_refund', amountUsd: 9, reversibility: 'reversible', blastRadius: 'single', outcome, at: now }));
}

// ---------- precedent (case-based autonomy) ----------
test('similar clean-approved precedent supports auto; rejections force human', () => {
  assert.equal(precedentAdvice(action(), cases('approve', 20)).suggestedTier, 'auto');
  assert.equal(precedentAdvice(action(), cases('reject', 20)).suggestedTier, 'human');
});
test('sparse precedent is not trusted', () => {
  const adv = precedentAdvice(action(), cases('approve', 2));
  assert.equal(adv.suggestedTier, 'human');
  assert.equal(adv.reason, 'insufficient_precedent');
});
test('precedent only lowers, never raises', () => {
  assert.equal(applyPrecedent('co_pilot', { suggestedTier: 'auto', cleanRate: 1, sampleSize: 20, reason: '' }), 'co_pilot');
  assert.equal(applyPrecedent('auto', { suggestedTier: 'human', cleanRate: 0, sampleSize: 20, reason: '' }), 'human');
});
test('governFleetAction: bad precedent turns an auto refund into an escalation', () => {
  const c = fleetAdminConstitution();
  const clean = governFleetAction({ action: action(), constitution: c });
  assert.equal(clean.decision, 'allow');
  const withBadPrecedent = governFleetAction({ action: action(), constitution: c, precedent: precedentAdvice(action(), cases('reject', 20)) });
  assert.equal(withBadPrecedent.decision, 'escalate');
});
test('caseSimilarity: same verb+domain beats different', () => {
  assert.ok(caseSimilarity(action(), cases('approve', 1)[0]!) > 0.9);
});

// ---------- forecast (predictive admin) ----------
test('forecast flags an overdue recurring stream', () => {
  const evs: AdminEvent[] = [0, 1, 2, 3].map((d) => ({
    id: `e${d}`, product: 'pareto', domain: 'billing', category: 'failed_payment',
    severity: AdminSeverity.WARNING, title: 'fail', summary: '', at: new Date(Date.parse('2026-06-01') + d * 86400000).toISOString(),
  }));
  const out = forecastFromEvents(evs, '2026-06-10T00:00:00.000Z', 0.5);
  assert.ok(out.length === 1);
  assert.ok(out[0]!.risk >= 0.5);
  assert.ok(out[0]!.etaIso);
});

// ---------- deliberation (CADE pre-pass) ----------
test('deliberation surfaces case + objection and measures dissent', () => {
  const d = deliberate(action({ reversibility: 'irreversible', amountUsd: 5000, blastRadius: 'large', confidence: 0.4 }));
  assert.ok(d.strongestObjection.length > 0);
  assert.ok(d.dissent >= 0 && d.dissent <= 1);
  assert.equal(d.recommendation, 'reject'); // adversary out-confident on a scary action
});
test('approval card carries the deliberation', () => {
  const v = governFleetAction({ action: action({ amountUsd: 500 }), constitution: fleetAdminConstitution() });
  const card = buildApprovalCard({ action: action({ amountUsd: 500 }), verdict: v, callbackUrl: 'cb' });
  assert.ok(card.deliberation);
  assert.equal(card.deliberation!.viewpoints.length, 3);
});

// ---------- correlate (cross-app incidents) ----------
test('correlates events across apps that share a signal in a window', () => {
  const base = Date.parse(now);
  const evs: AdminEvent[] = [
    { id: 'x1', product: 'apparently', domain: 'infra', category: 'error_spike', severity: 60, title: 'db', summary: '', at: new Date(base).toISOString(), details: { provider: 'supabase-east' } },
    { id: 'x2', product: 'pareto', domain: 'billing', category: 'failed_payment', severity: 30, title: 'pay', summary: '', at: new Date(base + 60000).toISOString(), details: { provider: 'supabase-east' } },
    { id: 'x3', product: 'galop', domain: 'infra', category: 'outage', severity: 100, title: 'out', summary: '', at: new Date(base + 5 * 86400000).toISOString(), details: { provider: 'cloudflare' } },
  ];
  const incidents = correlateEvents(evs);
  assert.equal(incidents.length, 1);
  assert.deepEqual(incidents[0]!.events.sort(), ['x1', 'x2']);
  assert.ok(incidents[0]!.products.includes('apparently') && incidents[0]!.products.includes('pareto'));
});

// ---------- promotion value (reverse auction) ----------
function ledgerEntry(over: Partial<LedgerEntry> = {}): LedgerEntry {
  return { actionType: 'billing:retry_payment', domain: 'billing', streak: 25, total: 25, cleanApprovals: 25, edits: 0, rejections: 0, updatedAt: now, ...over };
}
test('quantifies a promotion with dollars + approvals saved', () => {
  const v = quantifyPromotion(ledgerEntry(), (d) => DEFAULT_DOMAIN_POLICIES[d].ceiling);
  assert.ok(v);
  assert.equal(v!.approvalsSaved, 25);
  assert.ok(v!.dollarsAtRiskAvoided > 0);
  assert.match(v!.recommendation, /Promote/);
});
test('no offer for short streaks; board ranks by value', () => {
  assert.equal(quantifyPromotion(ledgerEntry({ streak: 3, total: 3, cleanApprovals: 3 }), (d) => DEFAULT_DOMAIN_POLICIES[d].ceiling), null);
  const board = auctionBoard([ledgerEntry(), ledgerEntry({ actionType: 'users_access:reset_password', domain: 'users_access' })], (d) => DEFAULT_DOMAIN_POLICIES[d].ceiling);
  assert.equal(board.length, 2);
  assert.ok(board[0]!.dollarsAtRiskAvoided >= board[1]!.dollarsAtRiskAvoided);
});

// ---------- KPI (north-star) ----------
test('answered-from-plane rate + trend', () => {
  const acts: RoutedActionSummary[] = [
    { domain: 'billing', decision: 'allow', tier: 'auto', at: '2026-06-01T00:00:00Z' },
    { domain: 'billing', decision: 'escalate', tier: 'human', at: '2026-06-02T00:00:00Z' },
    { domain: 'billing', decision: 'allow', tier: 'auto', at: '2026-06-20T00:00:00Z' },
    { domain: 'billing', decision: 'allow', tier: 'auto', at: '2026-06-21T00:00:00Z' },
    { domain: 'infra', decision: 'deny', tier: 'human', at: '2026-06-21T00:00:00Z' },
  ];
  const ns = computeNorthStar(acts, '2026-06-15T00:00:00Z');
  assert.equal(ns.autonomous, 3);
  assert.equal(ns.escalated, 1);
  assert.equal(ns.denied, 1);
  assert.ok(ns.answeredFromPlaneRate > 0.7);
  assert.ok(ns.trend!.current > ns.trend!.previous); // autonomy improved over time
});
