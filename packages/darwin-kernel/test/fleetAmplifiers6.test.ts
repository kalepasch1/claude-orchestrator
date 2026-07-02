import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  fleetAdminCapabilities,
  fleetGovernCapabilityId,
  planIntent,
  governIntent,
  runShadowAB,
  regretAsOutcomes,
  regretToResolvedCases,
  regretReport,
  buildComplianceReport,
  renderComplianceReportMarkdown,
  buildAutonomyAttestation,
  buildDecisionProof,
  governFleetAction,
  fleetAdminConstitution,
  precedentAdvice,
  type AdminAction,
  type RegretSignal,
  type AutoRunRecord,
  type ResolvedCase,
} from '../src/fleetAdmin/index.ts';
import { CapabilityRegistry, memoryTransport } from '../src/orchestratorClient/index.ts';

const now = '2026-07-01T00:00:00.000Z';

// ---------- capability publication ----------
test('the plane publishes as capabilities discoverable + instantiable on the registry', async () => {
  const caps = fleetAdminCapabilities('https://orch.example');
  assert.ok(caps.length >= 4);
  const governCap = caps[0]!;
  assert.equal(governCap.name, 'admin_govern_action');
  assert.equal(fleetGovernCapabilityId('https://orch.example'), governCap.id);

  const transport = memoryTransport({ [governCap.id]: () => ({ decision: 'allow', tier: 'auto' }) });
  const reg = new CapabilityRegistry(transport);
  for (const c of caps) await reg.publish(c);
  const found = await reg.discover('admin', ['governance']);
  assert.ok(found.some((c) => c.name === 'admin_govern_action'));
  const out = await reg.instantiate(governCap.id, { product: 'newco', domain: 'billing', type: 'billing:issue_refund' });
  assert.deepEqual(out, { decision: 'allow', tier: 'auto' });
});

// ---------- intent-level autonomy ----------
test('intent plan composes steps and is governed as ONE decision', () => {
  const plan = planIntent({ goal: 'retain_churn_risk', subjectId: 'u1', product: 'galop', amountUsd: 15 });
  assert.equal(plan.steps.length, 3);
  const v = governIntent({ plan });
  assert.equal(v.stepVerdicts.length, 3);
  // one receipt for the whole intent
  assert.ok(v.receipt.digest.length > 0);
  // plan tier is the least-autonomous across steps
  assert.ok(['human', 'co_pilot', 'auto'].includes(v.tier));
});
test('an intent with a terminate step never auto-runs the whole plan', () => {
  const plan = planIntent({ goal: 'offboard_bad_actor', subjectId: 'u2', product: 'galop' });
  const v = governIntent({ plan });
  assert.notEqual(v.decision, 'allow'); // termination forces the whole intent to escalate
  assert.notEqual(v.tier, 'auto');
});

// ---------- shadow A/B ----------
test('shadow A/B promotes a challenger that fits history better', () => {
  const history: AdminAction[] = Array.from({ length: 40 }, (_, i) => ({
    id: `s${i}`, product: 'galop', domain: 'billing', type: 'billing:issue_refund', actor: 's',
    confidence: 0.97, reversibility: 'reversible', blastRadius: 'single', intent: 'r', amountUsd: 9, at: now,
  }));
  // Humans rejected most refunds → a champion that auto-allows them regresses; a tighter
  // challenger (strips the refund allow) escalates instead and wins.
  const outcomes = Object.fromEntries(history.map((a, i) => [a.id, i < 34 ? 'reject' : 'approve'] as const));
  const base = fleetAdminConstitution();
  const champion = { name: 'champion', constitution: base };
  const challenger = { name: 'challenger', constitution: { ...base, rules: base.rules.filter((r) => r.id !== 'allow-refund-small') } };
  const res = runShadowAB({ champion, challenger, history, outcomes: outcomes as any });
  assert.equal(res.recommendation, 'promote_challenger');
});
test('shadow A/B needs enough sample', () => {
  const base = fleetAdminConstitution();
  const res = runShadowAB({ champion: { name: 'c', constitution: base }, challenger: { name: 'x', constitution: base }, history: [], outcomes: {} });
  assert.equal(res.recommendation, 'insufficient_sample');
});

// ---------- regret ledger ----------
test('regret turns auto mistakes into reject-precedent + a per-type rate', () => {
  const autos: AutoRunRecord[] = [
    { id: 'x1', domain: 'billing', type: 'billing:issue_refund', amountUsd: 9, reversibility: 'reversible', blastRadius: 'single', at: now },
    { id: 'x2', domain: 'billing', type: 'billing:issue_refund', amountUsd: 9, reversibility: 'reversible', blastRadius: 'single', at: now },
    { id: 'x3', domain: 'billing', type: 'billing:issue_refund', amountUsd: 9, reversibility: 'reversible', blastRadius: 'single', at: now },
  ];
  const signals: RegretSignal[] = [{ actionId: 'x1', kind: 'reversed_charge', at: now }];
  assert.deepEqual(regretAsOutcomes(signals), { x1: 'reject' });
  const rej = regretToResolvedCases(autos, signals);
  assert.equal(rej.length, 1);
  assert.equal(rej[0]!.outcome, 'reject');
  const rep = regretReport(autos, signals);
  assert.equal(rep.totalRegrets, 1);
  assert.ok(Math.abs(rep.overallRegretRate - 0.333) < 0.01);

  // regret feeds precedent: enough reject-cases lower the suggested tier
  const history: ResolvedCase[] = [...Array.from({ length: 10 }, () => rej[0]!)];
  assert.equal(precedentAdvice(autos[0] as any, history).suggestedTier, 'human');
});

// ---------- compliance SKU ----------
test('compliance report bundles a verifiable attestation + proofs and renders markdown', () => {
  const att = buildAutonomyAttestation({ issuedAt: now, periodDays: 30, answeredFromPlaneRate: 0.82, totalDecisions: 5000, regressions: 0, redTeamResidualHarm: 0.1, receiptsChainVerified: true });
  const action: AdminAction = { id: 'a1', product: 'galop', domain: 'billing', type: 'billing:issue_refund', actor: 's', confidence: 0.97, reversibility: 'reversible', blastRadius: 'single', intent: 'r', amountUsd: 9, at: now };
  const proof = buildDecisionProof({ action, verdict: governFleetAction({ action, constitution: fleetAdminConstitution() }), constitutionVersion: 1 });
  const report = buildComplianceReport({ orgName: 'Acme', attestation: att, sampleProofs: [proof] });
  assert.equal(report.attestationValid, true);
  assert.equal(report.sampleAllValid, true);
  assert.equal(report.attestationMeetsBar, true);
  const md = renderComplianceReportMarkdown(report);
  assert.match(md, /Provably-Governed AI Operations — Acme/);
  assert.match(md, /Answered-from-plane rate/);
});
