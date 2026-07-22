import { test } from 'node:test';
import assert from 'node:assert/strict';

import { RewardLedgerWriter, runDataCoopProductRound, type DataCoopPoolConfig } from '../src/dataCoop/dataCoopProduct.ts';
import type { ConsentGrant } from '../src/identity/graph.ts';

const pool: DataCoopPoolConfig = {
  from: 'tomorrow',
  to: 'smarter',
  scope: 'credit_quality',
  schedule: { currency: 'apparently_points', perContributor: 100 },
  sensitivity: 1,
};

function makeConsent(subject: string): ConsentGrant {
  return {
    subject,
    from: 'tomorrow',
    to: 'smarter',
    scopes: ['credit_quality'],
    grantedAt: '2026-01-01T00:00:00Z',
  };
}

test('runDataCoopProductRound pays reward-ledger entry and respects k-floor', () => {
  const ledger = new RewardLedgerWriter();

  // 5 contributors with consent (default k=5 should pass)
  const contributions = [
    { subject: 'u1', value: 0.8 },
    { subject: 'u2', value: 0.7 },
    { subject: 'u3', value: 0.6 },
    { subject: 'u4', value: 0.9 },
    { subject: 'u5', value: 0.75 },
  ];
  const consent = contributions.map((c) => makeConsent(c.subject));

  const result = runDataCoopProductRound({
    pool,
    contributions,
    consent,
    ledger,
    rng: () => 0.5, // deterministic noise
  });

  assert.equal(result.suppressed, false);
  assert.ok(result.totalDividendCents > 0);
  assert.equal(ledger.all().length, 5);
  // Each entry should be 100 apparently_points
  for (const entry of ledger.all()) {
    assert.equal(entry.currency, 'apparently_points');
    assert.equal(entry.amount, 100);
  }
});

test('suppression below k-floor means no rewards', () => {
  const ledger = new RewardLedgerWriter();

  // Only 2 contributors — below default k=5
  const contributions = [
    { subject: 'u1', value: 0.8 },
    { subject: 'u2', value: 0.7 },
  ];
  const consent = contributions.map((c) => makeConsent(c.subject));

  const result = runDataCoopProductRound({
    pool,
    contributions,
    consent,
    ledger,
    rng: () => 0.5,
  });

  assert.equal(result.suppressed, true);
  assert.equal(result.totalDividendCents, 0);
  assert.equal(ledger.all().length, 0);
});

test('no consent means rejection, not reward', () => {
  const ledger = new RewardLedgerWriter();

  const contributions = [
    { subject: 'u1', value: 0.8 },
    { subject: 'u2', value: 0.7 },
    { subject: 'u3', value: 0.6 },
    { subject: 'u4', value: 0.9 },
    { subject: 'u5', value: 0.75 },
  ];
  // Only u1 has consent
  const consent = [makeConsent('u1')];

  const result = runDataCoopProductRound({
    pool,
    contributions,
    consent,
    ledger,
    rng: () => 0.5,
  });

  // Only 1 consented → below k-floor → suppressed
  assert.equal(result.round.rejected.length, 4);
  assert.equal(result.suppressed, true);
  assert.equal(ledger.all().length, 0);
});

test('RewardLedgerWriter tracks per-subject and normalized totals', () => {
  const ledger = new RewardLedgerWriter();
  ledger.append({ subject: 'u1', currency: 'apparently_points', amount: 100, reason: 'test' });
  ledger.append({ subject: 'u2', currency: 'hisanta_sparks', amount: 200, reason: 'test' });
  ledger.append({ subject: 'u1', currency: 'galop_coins', amount: 50, reason: 'test2' });

  assert.equal(ledger.all().length, 3);
  assert.equal(ledger.forSubject('u1').length, 2);
  assert.equal(ledger.forSubject('u2').length, 1);
  // 100*1 + 200*0.5 + 50*0.25 = 100 + 100 + 12.5 = 212.5
  assert.equal(ledger.totalNormalizedCents(), 212.5);
});
