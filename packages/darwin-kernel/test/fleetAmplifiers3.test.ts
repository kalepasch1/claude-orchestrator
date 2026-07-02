import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  dryRunChange,
  buildFederatedPrecedent,
  seedFromFederated,
  optimizeDial,
  buildDecisionProof,
  verifyDecisionProof,
  compileNlControl,
  preprocessAdminNl,
  assessAdapterHealth,
  detectEventDrift,
  governFleetAction,
  fleetAdminConstitution,
  DEFAULT_DOMAIN_POLICIES,
  type AdminAction,
  type AppTypeStat,
  type TypeCostInput,
  type ExecutionOutcome,
} from '../src/fleetAdmin/index.ts';

const now = '2026-07-01T00:00:00.000Z';
function action(over: Partial<AdminAction> = {}): AdminAction {
  return { id: 'a1', product: 'galop', domain: 'billing', type: 'billing:issue_refund', actor: 'swarm', confidence: 0.97, reversibility: 'reversible', blastRadius: 'single', intent: 'Refund $9', amountUsd: 9, at: now, ...over };
}

// ---------- digital twin ----------
test('twin: a stricter constitution tightens decisions with no side effects', () => {
  const actions = [action({ id: 'a1' }), action({ id: 'a2', amountUsd: 20 })];
  const before = fleetAdminConstitution();
  // "after": remove the small-refund allow → refunds now escalate (tighter)
  const after = { ...before, rules: before.rules.filter((r) => r.id !== 'allow-refund-small') };
  const res = dryRunChange({ actions, after: { constitution: after }, before: { constitution: before } });
  assert.ok(res.changed >= 1);
  assert.equal(res.loosened, 0);
  assert.ok(res.tightened >= 1);
  assert.equal(res.regressions, 0);
});
test('twin: flags a regression when a change would auto-run a rejected action', () => {
  const a = action({ id: 'ax', amountUsd: 9 });
  // before: normal fleet law (refund auto). Feed an outcome saying the human rejected it.
  const res = dryRunChange({
    actions: [a],
    before: { constitution: { ...fleetAdminConstitution(), rules: fleetAdminConstitution().rules.filter((r) => r.id !== 'allow-refund-small') } },
    after: { constitution: fleetAdminConstitution() },
    outcomes: { ax: 'reject' },
  });
  assert.equal(res.loosened, 1);
  assert.equal(res.regressions, 1);
});

// ---------- federated precedent ----------
test('federated precedent aggregates across apps + suppresses tiny cohorts', () => {
  const stats: AppTypeStat[] = [
    { product: 'galop', domain: 'billing', actionType: 'billing:issue_refund', total: 100, cleanApprovals: 99 },
    { product: 'pareto', domain: 'billing', actionType: 'billing:issue_refund', total: 80, cleanApprovals: 78 },
    { product: 'apparently', domain: 'billing', actionType: 'billing:issue_refund', total: 60, cleanApprovals: 59 },
    { product: 'galop', domain: 'infra', actionType: 'infra:rare', total: 5, cleanApprovals: 5 }, // cohort of 1 → suppressed
  ];
  const fed = buildFederatedPrecedent(stats, { k: 3, epsilon: 0.5 }, 42);
  const refund = fed.find((f) => f.actionType === 'billing:issue_refund')!;
  assert.equal(refund.cohortSize, 3);
  assert.equal(refund.suppressed, false);
  assert.ok(refund.privatizedCleanRate! > 0.8);
  const rare = fed.find((f) => f.actionType === 'infra:rare')!;
  assert.equal(rare.suppressed, true);
  const seed = seedFromFederated(fed);
  assert.ok('billing::billing:issue_refund' in seed);
  assert.ok(!('infra::infra:rare' in seed)); // suppressed → not seeded (fail-closed)
});

// ---------- economic autopilot ----------
test('economic autopilot recommends auto only when cheaper + within FP tolerance + ceiling ok', () => {
  const inputs: TypeCostInput[] = [
    { domain: 'billing', actionType: 'billing:issue_refund', volume: 1000, cleanRate: 0.99, avgAmountUsd: 10 }, // cheap, low fp → auto
    { domain: 'billing', actionType: 'billing:messy', volume: 1000, cleanRate: 0.5, avgAmountUsd: 200 }, // high fp → keep human
    { domain: 'infra', actionType: 'infra:rollback', volume: 1000, cleanRate: 0.99 }, // ceiling co_pilot → keep human
  ];
  const dial = optimizeDial(inputs, (d) => DEFAULT_DOMAIN_POLICIES[d].ceiling);
  const byType = Object.fromEntries(dial.perType.map((r) => [r.actionType, r.recommend]));
  assert.equal(byType['billing:issue_refund'], 'auto');
  assert.equal(byType['billing:messy'], 'keep_human');
  assert.equal(byType['infra:rollback'], 'keep_human');
  assert.ok(dial.totalExpectedSavingUsd > 0);
});

// ---------- proof pack ----------
test('decision proof is stateless-verifiable and tamper-evident', () => {
  const v = governFleetAction({ action: action(), constitution: fleetAdminConstitution() });
  const proof = buildDecisionProof({ action: action(), verdict: v, constitutionVersion: 1, deliberation: undefined });
  assert.equal(verifyDecisionProof(proof).valid, true);
  // tamper with the decision → digest mismatch
  const tampered = { ...proof, decision: 'deny' as const };
  assert.equal(verifyDecisionProof(tampered).valid, false);
  assert.equal(verifyDecisionProof(tampered).digestOk, false);
});

// ---------- NL control plane ----------
test('NL: "stop auto-refunding" normalizes + compiles to an approval rule', () => {
  const lines = preprocessAdminNl('stop auto-refunding new accounts');
  assert.ok(lines[0]!.toLowerCase().startsWith('require approval for refund'));
  const res = compileNlControl({ text: 'stop auto-refunding new accounts' });
  assert.ok(res.addedRuleCount >= 1);
});
test('NL: compiled control dry-runs against history', () => {
  const res = compileNlControl({
    text: 'require approval for issue_refund',
    history: [action({ id: 'h1', type: 'issue_refund' })],
  });
  assert.ok(res.dryRun);
  assert.equal(typeof res.dryRun!.changed, 'number');
});

// ---------- self-healing adapters ----------
test('adapter health flags a failing adapter + drafts a code-fix task', () => {
  const outcomes: ExecutionOutcome[] = [
    ...Array.from({ length: 7 }, () => ({ product: 'galop', ok: false, error: 'app_execute_500', at: now })),
    ...Array.from({ length: 3 }, () => ({ product: 'galop', ok: true, at: now })),
    ...Array.from({ length: 10 }, () => ({ product: 'apparently', ok: true, at: now })),
  ];
  const reports = assessAdapterHealth(outcomes);
  const galop = reports.find((r) => r.product === 'galop')!;
  assert.equal(galop.status, 'failing');
  assert.ok(galop.incident);
  assert.equal(galop.incident!.domain, 'infra');
  assert.ok(galop.proposedFix!.slug.includes('galop'));
  const apparently = reports.find((r) => r.product === 'apparently')!;
  assert.equal(apparently.status, 'healthy');
});
test('event drift detection catches missing required fields', () => {
  assert.deepEqual(detectEventDrift({ id: 'x', product: 'galop', domain: 'billing', category: 'refund_request', severity: 30, title: 't', at: now }), []);
  assert.ok(detectEventDrift({ id: 'x' }).includes('product'));
});
