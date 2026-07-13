import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  toOracleReading,
  impliedOverturnProbability,
  proposeEventCompression,
  marginHaircutMultiplier,
  machineCheck,
  updateReliabilityFromOutcome,
  precedentConcentration,
  propagateAuthorityChange,
  mineInstrumentGaps,
  priceDeterminationService,
  type Determination,
  type OptimalityCertificate,
} from '../src/cade/index.ts';

function fakeDet(confidence: number, value?: number): Determination {
  const certificate: OptimalityCertificate = {
    rosterComplete: true, consideredCount: 100, seatedCount: 12, marginalValueBound: 0.03,
    confidence, saturated: true, adversariallyComplete: true, statement: 's',
  };
  return {
    issueId: 'i1', position: 'p', value, confidence, dissent: [], factions: [], certificate,
    unsettled: false,
    proof: { id: 'cade_abc', issueId: 'i1', digest: 'deadbeef', record: {} as never },
  };
}

// #1 oracle bridge
test('toOracleReading exposes a Determination as an attested oracle source', () => {
  const r = toOracleReading(fakeDet(0.9, 0.12), { ageMs: 500, provedTier: 'panel' });
  assert.equal(r.sourceId, 'cade:cade_abc');
  assert.equal(r.value, 0.12);
  assert.equal(r.confidence, 0.9);
  assert.equal(r.evidenceDigest, 'deadbeef');
  assert.equal(r.precedentId, 'cade_abc');
});

// #5 challenge legs
test('impliedOverturnProbability blends engine confidence with money-weighted market', () => {
  const base = impliedOverturnProbability(0.9, []);
  assert.ok(Math.abs(base - 0.1) < 1e-9); // no legs → engine's own P(overturn)
  const withMarket = impliedOverturnProbability(0.9, [
    { participantId: 'a', side: 'overturn', notionalUsd: 1_000_000, price: 0.6 },
    { participantId: 'b', side: 'uphold', notionalUsd: 0, price: 0.1 },
  ], 0.5);
  assert.ok(withMarket > base); // market says overturn more likely → prob rises
  assert.ok(withMarket >= 0 && withMarket <= 1);
});

// #7 bilateral event compression (never a pool)
test('proposeEventCompression matches opposing sides into named bilateral legs', () => {
  const res = proposeEventCompression([
    { participantId: 'A', eventId: 'e1', notionalUsd: 100, side: 1 },
    { participantId: 'B', eventId: 'e1', notionalUsd: 70, side: -1 },
    { participantId: 'C', eventId: 'e1', notionalUsd: 40, side: -1 },
  ]);
  assert.equal(res.compressedUsd, 100); // 70 + 30
  assert.equal(res.legs.length, 2);
  for (const leg of res.legs) { assert.ok(leg.a && leg.b); assert.notEqual(leg.a, leg.b); } // bilateral
});

// #8 margin haircut
test('marginHaircutMultiplier falls as certified confidence rises, bounded by floor', () => {
  const hi = marginHaircutMultiplier(fakeDet(0.95).certificate, { floor: 0.5, sensitivity: 1 });
  const lo = marginHaircutMultiplier(fakeDet(0.1).certificate, { floor: 0.5, sensitivity: 1 });
  assert.ok(hi < lo);
  assert.ok(hi >= 0.5 && lo <= 1);
});

// #2 L0 machine-proved tier
test('machineCheck proves inconsistency when a proposition is required and forbidden', () => {
  const ok = machineCheck([{ id: 'c1', requires: ['delivery'] }, { id: 'c2', requires: ['payment'] }]);
  assert.equal(ok.consistent, true);
  assert.equal(ok.tier, 'L0');
  const bad = machineCheck([{ id: 'c1', requires: ['exclusivity'] }, { id: 'c2', forbids: ['exclusivity'] }]);
  assert.equal(bad.consistent, false);
  assert.equal(bad.conflicts[0]?.proposition, 'exclusivity');
});

// #6 reliability calibration
test('updateReliabilityFromOutcome moves toward 0 on overturn, toward 1 on correct', () => {
  assert.ok(updateReliabilityFromOutcome(0.8, { overturned: true, weight: 0.5 }) < 0.8);
  assert.ok(updateReliabilityFromOutcome(0.8, { overturned: false, weight: 0.5 }) > 0.8);
});

// #4 precedent concentration
test('precedentConcentration reports HHI + the most-exposed precedent', () => {
  const c = precedentConcentration([
    { precedentId: 'p1', contractId: 'x', notionalUsd: 900 },
    { precedentId: 'p2', contractId: 'y', notionalUsd: 100 },
  ]);
  assert.ok(c.hhi > 0.8); // heavily concentrated in p1
  assert.equal(c.mostConcentrated?.precedentId, 'p1');
});

// #3 living loop
test('propagateAuthorityChange finds affected determinations + legs to re-strike', () => {
  const r = propagateAuthorityChange([
    { id: 'd1', citedAuthorityIds: ['scotus:X'], legId: 'leg1' },
    { id: 'd2', citedAuthorityIds: ['scotus:Y'] },
  ], ['scotus:X']);
  assert.deepEqual(r.affectedDeterminationIds, ['d1']);
  assert.deepEqual(r.legsToRestrike, ['leg1']);
});

// #9 instrument gap mining
test('mineInstrumentGaps proposes instruments for unhedged legal-event losses', () => {
  const gaps = mineInstrumentGaps(
    [{ eventType: 'clause_struck', lossUsd: 500 }, { eventType: 'reg_action', lossUsd: 200 }, { eventType: 'clause_struck', lossUsd: 300 }],
    [{ coversEventType: 'reg_action' }],
  );
  assert.equal(gaps.length, 1);
  assert.equal(gaps[0]?.eventType, 'clause_struck');
  assert.equal(gaps[0]?.unhedgedLossUsd, 800);
  assert.equal(gaps[0]?.candidate.kind, 'parametric_event');
});

// #10 certified RaaS tier
test('priceDeterminationService meters by tier × difficulty; certified attaches the certificate', () => {
  const cheap = priceDeterminationService(0, 'oracle');
  const certified = priceDeterminationService(1, 'certified');
  assert.ok(certified.priceUsd > cheap.priceUsd);
  assert.equal(certified.includesCertificate, true);
  assert.equal(cheap.includesCertificate, false);
});
