import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  settleMarket,
  trainDecisionModel, samplesFromResolved, predictApprove,
  verifyConstitutionInvariants, fleetAdminConstitution, DEFAULT_DOMAIN_POLICIES,
  mergeFederatedThreats, planesToWarn,
  differenceInDifferences,
  regulatorQuery, parseRegulatorQuery,
  type StakePosition, type InstallOutcome, type ResolvedCase, type FederatedSignal,
  type Observation, type DecisionRecord, type AdminDomain, type DomainAutonomyPolicy,
} from '../src/fleetAdmin/index.ts';

const now = '2026-07-01T00:00:00.000Z';

// ---------- market economics ----------
test('market settles revenue on good installs and slashes on bad ones', () => {
  const stakes: StakePosition[] = [
    { listingId: 'l1', publisher: 'good', stakeUsd: 1000, reputation: 0.5 },
    { listingId: 'l2', publisher: 'bad', stakeUsd: 1000, reputation: 0.5 },
  ];
  const outcomes: InstallOutcome[] = [
    { listingId: 'l1', installer: 'x', revenueUsd: 1000, performedWell: true, observedRegretRate: 0 },
    { listingId: 'l2', installer: 'y', revenueUsd: 1000, performedWell: false, observedRegretRate: 0.5 },
  ];
  const { settlements, ranking } = settleMarket(stakes, outcomes);
  const good = settlements.find((s) => s.publisher === 'good')!;
  const bad = settlements.find((s) => s.publisher === 'bad')!;
  assert.ok(good.earningsUsd > 0 && good.reputation > 0.5);
  assert.ok(bad.slashedUsd > 0 && bad.reputation < 0.5);
  assert.equal(ranking[0]!.publisher, 'good');
});

// ---------- decision model ----------
test('decision model learns approve vs reject from the corpus', () => {
  const cases: ResolvedCase[] = [
    ...Array.from({ length: 40 }, () => ({ domain: 'billing' as const, type: 'billing:issue_refund', amountUsd: 9, reversibility: 'reversible' as const, blastRadius: 'single' as const, outcome: 'approve' as const, at: now })),
    ...Array.from({ length: 40 }, () => ({ domain: 'billing' as const, type: 'billing:issue_refund', amountUsd: 5000, reversibility: 'irreversible' as const, blastRadius: 'fleet' as const, outcome: 'reject' as const, at: now })),
  ];
  const model = trainDecisionModel(samplesFromResolved(cases));
  const pSmall = predictApprove(model, { domain: 'billing', type: 'billing:issue_refund', amountUsd: 9, reversibility: 'reversible', blastRadius: 'single' });
  const pBig = predictApprove(model, { domain: 'billing', type: 'billing:issue_refund', amountUsd: 5000, reversibility: 'irreversible', blastRadius: 'fleet' });
  assert.ok(pSmall > 0.7);
  assert.ok(pBig < 0.3);
});

// ---------- constitution verifier ----------
test('default constitution + dial pass all locked-dimension invariants', () => {
  const res = verifyConstitutionInvariants();
  assert.equal(res.ok, true);
  assert.equal(res.violations.length, 0);
  assert.ok(res.checked > 100);
});
test('verifier catches a breach if the dial is loosened to auto a locked verb path', () => {
  const reckless = structuredClone(DEFAULT_DOMAIN_POLICIES) as Record<AdminDomain, DomainAutonomyPolicy>;
  // Remove the always-human list for infra so a "never auto" verb could slip through.
  reckless.infra.alwaysHuman = [];
  reckless.infra.ceiling = 'auto';
  reckless.infra.autoReversibility = ['reversible', 'hard_to_reverse', 'irreversible'];
  reckless.infra.autoMaxBlast = 'fleet';
  const res = verifyConstitutionInvariants(fleetAdminConstitution(), reckless);
  // constitution's always-escalate still catches these verbs → invariant holds even so
  assert.equal(res.ok, true);
});

// ---------- federation ----------
test('federation elevates a threat seen on >=2 planes and lists planes to warn', () => {
  const signals: FederatedSignal[] = [
    { planeId: 'orgA', signalKey: 'fraud_ring_42', severity: 60, subjectId: 'u1', at: now },
    { planeId: 'orgB', signalKey: 'fraud_ring_42', severity: 100, subjectId: 'u1', at: now },
    { planeId: 'orgA', signalKey: 'lonely_signal', severity: 30, at: now },
  ];
  const threats = mergeFederatedThreats(signals);
  const ring = threats.find((t) => t.signalKey === 'fraud_ring_42')!;
  assert.equal(ring.elevated, true);
  assert.equal(ring.planeCount, 2);
  assert.equal(ring.maxSeverity, 100);
  assert.deepEqual(planesToWarn(ring, ['orgA', 'orgB', 'orgC']), ['orgC']);
  assert.equal(threats.find((t) => t.signalKey === 'lonely_signal')!.elevated, false);
});

// ---------- treatment effect ----------
test('difference-in-differences estimates a promotion causing lower regret', () => {
  // treated regret drops from 0.2 to 0.05; control stays ~0.1 → DiD ≈ -0.15
  const obs: Observation[] = [
    ...Array.from({ length: 10 }, () => ({ metric: 0.2, treated: true, period: 'pre' as const })),
    ...Array.from({ length: 10 }, () => ({ metric: 0.05, treated: true, period: 'post' as const })),
    ...Array.from({ length: 10 }, () => ({ metric: 0.1, treated: false, period: 'pre' as const })),
    ...Array.from({ length: 10 }, () => ({ metric: 0.1, treated: false, period: 'post' as const })),
  ];
  const did = differenceInDifferences(obs);
  assert.ok(did.estimate < 0);
  assert.ok(Math.abs(did.estimate - -0.15) < 0.001);
  assert.match(did.interpretation, /reduction/);
});

// ---------- regulator lens ----------
test('regulator lens filters, redacts PII, and attaches proof digests', () => {
  const f = parseRegulatorQuery('show every auto-approved action over $500 in Q2 2026');
  assert.equal(f.minAmountUsd, 500);
  assert.equal(f.autoOnly, true);
  assert.equal(f.fromIso, '2026-04-01');

  const records: DecisionRecord[] = [
    { actionId: 'a1', product: 'galop', domain: 'billing', type: 'billing:issue_refund', tier: 'auto', decision: 'allow', amountUsd: 800, subjectId: 'real-user-123', at: '2026-05-10T00:00:00Z', receiptDigest: 'dig1' },
    { actionId: 'a2', product: 'galop', domain: 'billing', type: 'billing:issue_refund', tier: 'human', decision: 'escalate', amountUsd: 900, subjectId: 'real-user-456', at: '2026-05-10T00:00:00Z', receiptDigest: 'dig2' },
  ];
  const ans = regulatorQuery('auto-approved over $500 in Q2 2026', records);
  assert.equal(ans.count, 1);
  assert.equal(ans.matches[0]!.actionId, 'a1');
  assert.match(ans.matches[0]!.subject!, /^subj_/); // PII redacted
  assert.ok(!JSON.stringify(ans.matches).includes('real-user-123'));
  assert.deepEqual(ans.proofDigests, ['dig1']);
});
