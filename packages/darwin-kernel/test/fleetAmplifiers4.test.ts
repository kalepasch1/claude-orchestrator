import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  generateDialCandidates,
  paretoFrontier,
  learnCausalGraph,
  rootCause,
  factionVariants,
  runRuleMarket,
  coEvolve,
  buildTreasury,
  bundleQueue,
  precedenceRank,
  DEFAULT_DOMAIN_POLICIES,
  AdminSeverity,
  type TypeCostInput,
  type AdminEvent,
  type AdminAction,
  type SettledDecision,
  type PendingDecision,
  type DomainAutonomyPolicy,
  type AdminDomain,
} from '../src/fleetAdmin/index.ts';

const now = '2026-07-01T00:00:00.000Z';
const ceilingOf = (d: AdminDomain) => DEFAULT_DOMAIN_POLICIES[d].ceiling;

// ---------- pareto tuning ----------
test('pareto: frontier is non-dominated and includes extreme candidates', () => {
  const inputs: TypeCostInput[] = [
    { domain: 'billing', actionType: 'billing:issue_refund', volume: 1000, cleanRate: 0.99, avgAmountUsd: 10 },
    { domain: 'billing', actionType: 'billing:messy', volume: 500, cleanRate: 0.7, avgAmountUsd: 100 },
    { domain: 'users_access', actionType: 'users_access:reset_password', volume: 800, cleanRate: 0.98 },
  ];
  const candidates = generateDialCandidates(inputs, ceilingOf);
  const { frontier, dominated } = paretoFrontier(candidates);
  assert.ok(frontier.length >= 1);
  assert.equal(frontier.length + dominated.length, candidates.length);
  // no frontier point is dominated by another candidate
  for (const f of frontier) {
    assert.ok(!candidates.some((o) => o.id !== f.id &&
      o.objectives.cost <= f.objectives.cost && o.objectives.risk <= f.objectives.risk &&
      o.objectives.approverLoad <= f.objectives.approverLoad && o.objectives.latency <= f.objectives.latency &&
      (o.objectives.cost < f.objectives.cost || o.objectives.risk < f.objectives.risk || o.objectives.approverLoad < f.objectives.approverLoad || o.objectives.latency < f.objectives.latency)));
  }
});

// ---------- causal model ----------
test('causal: learns A→B when A reliably precedes B, and finds the root cause', () => {
  const base = Date.parse(now);
  const events: AdminEvent[] = [];
  // 6 episodes: outage (A) then error_spike (B) 1 min later; plus noise
  for (let i = 0; i < 6; i++) {
    events.push({ id: `a${i}`, product: 'galop', domain: 'infra', category: 'outage', severity: AdminSeverity.URGENT, title: 'o', summary: '', at: new Date(base + i * 3600000).toISOString() });
    events.push({ id: `b${i}`, product: 'galop', domain: 'infra', category: 'error_spike', severity: AdminSeverity.WARNING, title: 'e', summary: '', at: new Date(base + i * 3600000 + 60000).toISOString() });
  }
  const graph = learnCausalGraph(events);
  const edge = graph.find((e) => e.from === 'outage' && e.to === 'error_spike');
  assert.ok(edge);
  assert.ok(edge!.lift >= 1.5);
  const incident = [events[0]!, events[1]!]; // outage + error_spike
  assert.equal(rootCause(incident, graph)!.category, 'outage');
});

// ---------- rule market ----------
test('rule market: tight faction wins when history is full of rejections', () => {
  const history: AdminAction[] = Array.from({ length: 12 }, (_, i) => ({
    id: `m${i}`, product: 'galop', domain: 'billing', type: 'billing:issue_refund', actor: 's',
    confidence: 0.97, reversibility: 'reversible', blastRadius: 'single', intent: 'refund', amountUsd: 9, at: now,
  }));
  // Human rejected almost all → the faction that escalates (tight) should score best.
  const outcomes = Object.fromEntries(history.map((a, i) => [a.id, i < 10 ? 'reject' : 'approve'] as const));
  const res = runRuleMarket(factionVariants(), history, outcomes as any);
  assert.equal(res.winner, 'tight');
  assert.ok(res.ranked[0]!.fitness >= res.ranked[1]!.fitness);
});

// ---------- co-evolution ----------
test('co-evolution: default dial has a small safe envelope; reckless dial gets hardened', () => {
  const clean = coEvolve(); // defaults are already safe → few/no tightenings
  assert.ok(clean.residualHarm < 0.3);

  const reckless = structuredClone(DEFAULT_DOMAIN_POLICIES) as Record<AdminDomain, DomainAutonomyPolicy>;
  reckless.billing.autoReversibility = ['reversible', 'hard_to_reverse', 'irreversible'];
  reckless.billing.autoMaxBlast = 'fleet';
  const hardened = coEvolve(reckless);
  assert.ok(hardened.tightenings.length > 0);
  assert.ok(hardened.residualHarm < 0.3); // adversary can no longer find a harmful auto
});

// ---------- treasury ----------
test('treasury: nets approver savings + avoided loss against escalation cost', () => {
  const decisions: SettledDecision[] = [
    ...Array.from({ length: 100 }, () => ({ domain: 'billing' as const, tier: 'auto' as const, decision: 'allow' as const })),
    { domain: 'billing', tier: 'human', decision: 'escalate', outcome: 'reject', amountUsd: 500 },
    { domain: 'billing', tier: 'human', decision: 'escalate', outcome: 'approve' },
  ];
  const t = buildTreasury(decisions);
  assert.ok(t.savingsUsd > 0);
  assert.ok(t.netUsd > 0);
  assert.ok(t.byDomain[0]!.autonomous === 100);
});

// ---------- dependency queue ----------
test('dependency queue: termination supersedes refund on the same subject', () => {
  assert.ok(precedenceRank('users_access:terminate_account') > precedenceRank('billing:issue_refund'));
  const pending: PendingDecision[] = [
    { actionId: 'p1', subjectId: 'user_9', domain: 'billing', type: 'billing:issue_refund', priority: 30 },
    { actionId: 'p2', subjectId: 'user_9', domain: 'trust_safety', type: 'trust_safety:terminate_account', priority: 60 },
    { actionId: 'p3', subjectId: 'user_5', domain: 'billing', type: 'billing:issue_refund', priority: 20 },
  ];
  const { bundles, standalone } = bundleQueue(pending);
  assert.equal(bundles.length, 1);
  assert.equal(bundles[0]!.primary.type, 'trust_safety:terminate_account');
  assert.equal(bundles[0]!.subsumed.length, 1);
  assert.equal(standalone.length, 1); // user_5's lone refund
});
