import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  signListing, verifyListing, GovernanceMarketplace, memoryMarketTransport,
  composeIntentPlan,
  selectPortfolioConfig, generateDialCandidates,
  counterfactualReview, buildApproverProfile,
  runBountyRound, evaluateSubmission,
  counterSign, verifyCounterSignature, verifyTrustPassport, buildAutonomyAttestation,
  governIntent,
  DEFAULT_DOMAIN_POLICIES,
  type TypeCostInput, type AdminAction, type PlanExemplar, type GapSubmission,
  type ApproverDecisionRecord, type AutoDecisionRef, type AdminDomain,
  type MarketListing,
} from '../src/fleetAdmin/index.ts';

const now = '2026-07-01T00:00:00.000Z';
const ceilingOf = (d: AdminDomain) => DEFAULT_DOMAIN_POLICIES[d].ceiling;

// ---------- marketplace ----------
test('marketplace: signed listings publish, verify, discover, and install', async () => {
  const listing = signListing({ id: 'l1', kind: 'constitution', title: 'Lean refund policy', owner: 'acme', version: '1.0.0', tags: ['billing', 'refund'], payload: { rules: ['allow refund under 50'] }, publishedAt: now });
  assert.equal(verifyListing(listing), true);
  const market = new GovernanceMarketplace(memoryMarketTransport());
  await market.publish(listing);
  const found = await market.discover('refund', 'constitution');
  assert.equal(found.length, 1);
  const installed = await market.install('l1');
  assert.deepEqual(installed.payload, { rules: ['allow refund under 50'] });
});
test('marketplace: a tampered listing is rejected on publish + install', async () => {
  const listing = signListing({ id: 'l2', kind: 'playbook', title: 'x', owner: 'a', version: '1', tags: [], payload: { a: 1 }, publishedAt: now });
  const tampered: MarketListing = { ...listing, payload: { a: 999 } };
  assert.equal(verifyListing(tampered), false);
  const market = new GovernanceMarketplace(memoryMarketTransport());
  await assert.rejects(market.publish(tampered));
});

// ---------- learned intent planner ----------
test('intent planner reuses a similar successful exemplar, else falls back to template', () => {
  const exemplars: PlanExemplar[] = [{
    goal: 'keep churn risk customer happy',
    success: 0.9,
    steps: [
      { id: 's1', product: 'galop', domain: 'billing', type: 'billing:issue_refund', actor: 'x', confidence: 0.9, reversibility: 'reversible', blastRadius: 'single', intent: 'refund', amountUsd: 10, at: now },
      { id: 's2', product: 'galop', domain: 'trust_safety', type: 'trust_safety:send_apology', actor: 'x', confidence: 0.9, reversibility: 'reversible', blastRadius: 'single', intent: 'apology', at: now },
    ],
  }];
  const matched = composeIntentPlan({ goal: 'keep this churn risk customer happy', product: 'galop', subjectId: 'u1', exemplars });
  assert.equal(matched.source, 'exemplar');
  assert.equal(matched.plan.steps.length, 2);
  // and the composed plan is still governable as ONE decision
  assert.ok(['allow', 'escalate', 'deny'].includes(governIntent({ plan: matched.plan }).decision));

  const novel = composeIntentPlan({ goal: 'totally unrelated objective xyz', product: 'galop', exemplars });
  assert.equal(novel.source, 'template');
});

// ---------- portfolio objective ----------
test('portfolio objective picks the best feasible dial under a risk cap', () => {
  const inputs: TypeCostInput[] = [
    { domain: 'billing', actionType: 'billing:issue_refund', volume: 1000, cleanRate: 0.99, avgAmountUsd: 10 },
    { domain: 'users_access', actionType: 'users_access:reset_password', volume: 500, cleanRate: 0.98 },
  ];
  const candidates = generateDialCandidates(inputs, ceilingOf);
  const maxAuto = selectPortfolioConfig(candidates, { goal: 'max_autonomy' });
  assert.ok(maxAuto.chosen);
  const capped = selectPortfolioConfig(candidates, { goal: 'max_autonomy', constraints: { maxRisk: 0 } });
  // maxRisk 0 forbids any auto money type → the fp=0 / no-auto candidate is chosen
  assert.ok(capped.chosen);
  assert.ok(capped.chosen!.objectives.risk <= (maxAuto.chosen!.objectives.risk));
  const infeasible = selectPortfolioConfig(candidates, { goal: 'min_cost', constraints: { maxCost: -1 } });
  assert.equal(infeasible.chosen, null);
});

// ---------- counterfactual human model ----------
test('counterfactual flags auto-runs the human would likely have rejected', () => {
  const records: ApproverDecisionRecord[] = Array.from({ length: 6 }, () => ({ domain: 'billing' as const, actionType: 'billing:issue_refund', outcome: 'reject' as const, at: now }));
  const profile = buildApproverProfile(records);
  const autos: AutoDecisionRef[] = [
    { actionId: 'a1', domain: 'billing', actionType: 'billing:issue_refund' }, // human rejects these → divergence
    { actionId: 'a2', domain: 'infra', actionType: 'infra:unknown' }, // no history → uncertain, no flag
  ];
  const report = counterfactualReview(autos, profile);
  assert.equal(report.divergences, 1);
  assert.equal(report.flags[0]!.actionId, 'a1');
  assert.ok(report.divergenceRate > 0);
});

// ---------- bounty market ----------
test('bounty: a real auto-run gap is accepted, paid, and drafts an amendment; a gated probe is not', () => {
  // Loosen billing so a harmful probe auto-runs.
  const reckless = structuredClone(DEFAULT_DOMAIN_POLICIES);
  reckless.billing.autoReversibility = ['reversible', 'hard_to_reverse', 'irreversible'];
  reckless.billing.autoMaxBlast = 'fleet';
  const subs: GapSubmission[] = [
    { id: 'g1', finder: 'red1', domain: 'billing', actionType: 'billing:__probe', amountUsd: 0, reversibility: 'irreversible', blastRadius: 'fleet', confidence: 0.99 },
  ];
  const round = runBountyRound(subs, reckless);
  assert.equal(round.accepted.length, 1);
  assert.ok(round.totalPayoutUsd > 0);
  assert.equal(round.amendments.length, 1);
  assert.equal(round.leaderboard[0]!.finder, 'red1');
  // under the SAFE default dial, the same probe is gated → not a gap
  assert.equal(evaluateSubmission(subs[0]!).accepted, false);
});

// ---------- trust web ----------
test('trust web: counter-signatures build a verifiable passport; wrong-digest cosigners rejected', () => {
  const att = buildAutonomyAttestation({ issuedAt: now, periodDays: 30, answeredFromPlaneRate: 0.85, totalDecisions: 4000, regressions: 0, redTeamResidualHarm: 0.1, receiptsChainVerified: true });
  const good = counterSign(att.digest, 'PartnerCo', now);
  assert.equal(verifyCounterSignature(good), true);
  const wrong = counterSign('some-other-digest', 'ImposterCo', now);
  const check = verifyTrustPassport({ attestation: att, counterSignatures: [good, wrong] });
  assert.equal(check.attestationValid, true);
  assert.ok(check.validCosigners.includes('PartnerCo'));
  assert.ok(check.invalidCosigners.includes('ImposterCo'));
  assert.equal(check.valid, false); // an invalid cosigner present → passport not fully valid
  const clean = verifyTrustPassport({ attestation: att, counterSignatures: [good] });
  assert.equal(clean.valid, true);
});
