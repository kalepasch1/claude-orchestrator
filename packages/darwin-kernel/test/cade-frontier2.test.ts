import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  toDeterminationCredential,
  verifyDeterminationCredential,
  determinationSignature,
  matchTemplate,
  federatedDetermination,
  screenOracleSources,
  propagateFinality,
  precedentPricingAdjustmentBps,
  optimizeCapitalTreatment,
  mineDoctrineUpdates,
  type Determination,
  type OptimalityCertificate,
  type IssueSpec,
  type DeterminationTemplate,
} from '../src/cade/index.ts';

function fakeDet(confidence: number, value?: number): Determination {
  const certificate: OptimalityCertificate = {
    rosterComplete: true, consideredCount: 100, seatedCount: 12, marginalValueBound: 0.03,
    confidence, saturated: true, adversariallyComplete: true, statement: 's',
  };
  return {
    issueId: 'i1', position: 'enforceable', value, confidence, dissent: [], factions: [], certificate,
    unsettled: false,
    proof: { id: 'cade_xyz', issueId: 'i1', digest: 'feed', record: {} as never },
  };
}

// #1/#9 credential + passport (content-addressed, verifiable)
test('determination credential is content-addressed and verifies offline', () => {
  const cred = toDeterminationCredential(fakeDet(0.9, 0.1), { issuedBy: 'apparently', at: '2026-07-12T00:00:00Z' });
  assert.match(cred.id, /^cred_[0-9a-f]{40}$/);
  assert.equal(verifyDeterminationCredential(cred), true);
  // tamper → fails
  const tampered = { ...cred, confidence: 0.1 };
  assert.equal(verifyDeterminationCredential(tampered), false);
});

// #2 template reuse (marketplace liquidity / self-precedent)
test('matchTemplate reuses a template with a similar signature', () => {
  const issue: IssueSpec = { id: 'i', text: 't', kind: 'legal', rosterClass: 'scotus', materiality: 0.5, requiredCompetence: { conflict_of_laws: 1, contracts: 1 } };
  const tmpl: DeterminationTemplate = {
    templateId: 'tpl1',
    signature: determinationSignature(issue),
    credential: toDeterminationCredential(fakeDet(0.9), { issuedBy: 'apparently', at: 'now' }),
  };
  assert.ok(matchTemplate(issue, [tmpl], 0.85));
  const different: IssueSpec = { ...issue, kind: 'financial', requiredCompetence: { derivatives_pricing: 1 } };
  assert.equal(matchTemplate(different, [tmpl], 0.85), undefined);
});

// #3 federated determination (k-anon suppression)
test('federatedDetermination suppresses sub-k cohorts and blends the rest', () => {
  const r = federatedDetermination([
    { nodeId: 'n1', stance: 0.8, confidence: 0.9, cohortSize: 10 },
    { nodeId: 'n2', stance: 0.6, confidence: 0.8, cohortSize: 5 },
    { nodeId: 'n3', stance: -0.9, confidence: 0.9, cohortSize: 1 }, // suppressed
  ], { minCohort: 3 });
  assert.deepEqual(r.suppressed, ['n3']);
  assert.equal(r.contributors, 2);
  assert.ok(r.stance > 0); // outlier n3 was suppressed
});

// #6 adversarial oracle screening
test('screenOracleSources rejects stale, outlier, and colluding sources', () => {
  const s = screenOracleSources([
    { id: 'a', value: 100, ageMs: 1000, cluster: 'x' },
    { id: 'b', value: 101, ageMs: 1000, cluster: 'y' },
    { id: 'c', value: 100, ageMs: 1000, cluster: 'z' },
    { id: 'stale', value: 100, ageMs: 999_999 },
    { id: 'wild', value: 10_000, ageMs: 1000, cluster: 'w' },
  ], { maxAgeMs: 60_000, outlierZ: 3, maxPerCluster: 5 });
  assert.ok(s.rejected.some((r) => r.id === 'stale' && r.reason === 'stale'));
  assert.ok(s.rejected.some((r) => r.id === 'wild' && r.reason === 'outlier'));
  assert.ok(s.admitted.length >= 3);
});

// #4 determination-finality DAG
test('propagateFinality cascades finality and flags cycles', () => {
  const r = propagateFinality([
    { id: 'd2', dependsOn: [], final: true },
    { id: 'd1', dependsOn: ['d2'], final: false }, // becomes final
    { id: 'c1', dependsOn: ['c2'], final: false },
    { id: 'c2', dependsOn: ['c1'], final: false }, // cycle
  ]);
  assert.ok(r.finalIds.includes('d1'));
  assert.ok(r.newlyFinal.includes('d1'));
  assert.ok(r.cyclic.includes('c1') && r.cyclic.includes('c2'));
});

// #5 precedent-weighted pricing
test('precedentPricingAdjustmentBps widens with concentration and unreliability', () => {
  const safe = precedentPricingAdjustmentBps(0.1, 0.95);
  const fragile = precedentPricingAdjustmentBps(0.9, 0.4);
  assert.ok(fragile > safe);
  assert.ok(safe >= 0);
});

// #7 capital optimization
test('optimizeCapitalTreatment frees margin as certified haircut falls', () => {
  const r = optimizeCapitalTreatment([
    { positionId: 'p1', baselineImUsd: 1000, haircutMultiplier: 0.6 },
    { positionId: 'p2', baselineImUsd: 500, haircutMultiplier: 1.0 },
  ]);
  assert.equal(r.freedUsd, 400); // 1000*(1-0.6) + 0
  assert.equal(r.optimizedImUsd, 1100);
});

// #8 self-closing doctrine loop
test('mineDoctrineUpdates surfaces high-overturn patterns ranked by impact', () => {
  const proposals = mineDoctrineUpdates([
    { pattern: 'noncompete:CA', overturned: true },
    { pattern: 'noncompete:CA', overturned: true },
    { pattern: 'noncompete:CA', overturned: true },
    { pattern: 'choice_of_law:NY', overturned: false },
    { pattern: 'choice_of_law:NY', overturned: false },
    { pattern: 'choice_of_law:NY', overturned: false },
  ], { minCount: 3, failRate: 0.5 });
  assert.equal(proposals.length, 1);
  assert.equal(proposals[0]?.pattern, 'noncompete:CA');
  assert.equal(proposals[0]?.overturnRate, 1);
});
