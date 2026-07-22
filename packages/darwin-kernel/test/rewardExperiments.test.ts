import { test } from 'node:test';
import assert from 'node:assert/strict';

import { runExperiment } from '../src/dataCoop/rewardExperiments.ts';
import { DEFAULT_RATES } from '../src/dataCoop/exchange.ts';

test('runExperiment produces normalized-currency deltas and significance', () => {
  const result = runExperiment({
    experimentId: 'cross-product-1',
    arms: [
      { name: 'control', earnCurrency: 'apparently_points', redeemCurrency: 'apparently_points', rewardPerAction: 10 },
      { name: 'treatment', earnCurrency: 'hisanta_sparks', redeemCurrency: 'galop_coins', rewardPerAction: 20 },
    ],
    assignments: [
      { subject: 'u1', arm: 'control', actionsCompleted: 5 },
      { subject: 'u2', arm: 'control', actionsCompleted: 3 },
      { subject: 'u3', arm: 'control', actionsCompleted: 4 },
      { subject: 'u4', arm: 'treatment', actionsCompleted: 6 },
      { subject: 'u5', arm: 'treatment', actionsCompleted: 8 },
      { subject: 'u6', arm: 'treatment', actionsCompleted: 7 },
    ],
  });

  assert.equal(result.experimentId, 'cross-product-1');
  assert.equal(result.arms.length, 2);

  const ctrl = result.arms[0]!;
  assert.equal(ctrl.arm, 'control');
  assert.equal(ctrl.n, 3);
  assert.equal(ctrl.totalActions, 12);
  assert.ok(ctrl.totalNormalizedCents > 0);
  assert.equal(ctrl.ledgerEntries.length, 3);

  const treat = result.arms[1]!;
  assert.equal(treat.arm, 'treatment');
  assert.equal(treat.n, 3);
  assert.ok(treat.totalNormalizedCents > 0);

  // Significance should be a number (not NaN with 3 subjects per arm)
  assert.ok(!isNaN(result.significance));
  assert.ok(result.significance >= 0 && result.significance <= 1);
});

test('runExperiment with single arm returns NaN significance', () => {
  const result = runExperiment({
    experimentId: 'single-arm',
    arms: [
      { name: 'only', earnCurrency: 'galop_coins', redeemCurrency: 'galop_coins', rewardPerAction: 5 },
    ],
    assignments: [
      { subject: 'u1', arm: 'only', actionsCompleted: 10 },
    ],
  });

  assert.equal(result.arms.length, 1);
  assert.ok(isNaN(result.significance));
});

test('ledger entries use normalized cross-product currency', () => {
  const result = runExperiment({
    experimentId: 'cross-redeem',
    arms: [
      { name: 'earn-sparks-redeem-coins', earnCurrency: 'hisanta_sparks', redeemCurrency: 'galop_coins', rewardPerAction: 10 },
    ],
    assignments: [
      { subject: 'u1', arm: 'earn-sparks-redeem-coins', actionsCompleted: 4 },
    ],
  });

  const entry = result.arms[0]!.ledgerEntries[0]!;
  assert.equal(entry.currency, 'galop_coins');
  // 4 actions * 10 sparks = 40 sparks earned
  // 40 sparks * (0.5 cents/spark) / (0.25 cents/coin) = 80 coins
  assert.equal(entry.amount, 80);
  // Normalized: 40 sparks * 0.5 = 20 cents
  assert.equal(result.arms[0]!.totalNormalizedCents, 20);
});
