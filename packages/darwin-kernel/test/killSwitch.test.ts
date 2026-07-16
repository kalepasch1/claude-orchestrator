import { test } from 'node:test';
import assert from 'node:assert/strict';

import { KillSwitchController } from '../src/governance/killSwitch.ts';
import { verifyReceipt } from '../src/governance/receipts.ts';
import { evaluateConstitution } from '../src/governance/constitution.ts';
import { constitutionFor } from '../src/products/index.ts';
import type { AgentAction } from '../src/types.ts';

function makeAction(product: string): AgentAction {
  return { product: product as any, type: 'trade', actor: 'bot-1', subjectId: 'deal-1', at: new Date().toISOString() };
}

test('engage halts all registered products and produces receipts', () => {
  const ctrl = new KillSwitchController();
  const tConst = constitutionFor('tomorrow')!;
  const sConst = constitutionFor('smarter')!;
  ctrl.register('tomorrow', tConst);
  ctrl.register('smarter', sConst);

  const result = ctrl.engage();
  assert.equal(result.engaged, true);
  assert.equal(result.products.length, 2);

  // All products should be engaged
  assert.equal(ctrl.isEngaged('tomorrow'), true);
  assert.equal(ctrl.isEngaged('smarter'), true);

  // Every receipt should be valid
  for (const ps of result.products) {
    assert.equal(ps.engaged, true);
    assert.ok(verifyReceipt(ps.receipt));
  }

  // Constitution evaluation should deny everything
  const tDecision = evaluateConstitution(makeAction('tomorrow'), tConst);
  assert.equal(tDecision.decision, 'deny');
  assert.equal(tDecision.reason, 'kill_switch');
});

test('disengage restores all products', () => {
  const ctrl = new KillSwitchController();
  const tConst = constitutionFor('tomorrow')!;
  ctrl.register('tomorrow', tConst);

  ctrl.engage();
  assert.equal(ctrl.isEngaged('tomorrow'), true);

  const result = ctrl.disengage();
  assert.equal(result.engaged, false);
  assert.equal(ctrl.isEngaged('tomorrow'), false);

  // Should no longer deny
  const decision = evaluateConstitution(makeAction('tomorrow'), tConst);
  assert.notEqual(decision.reason, 'kill_switch');
});

test('propagation reaches all registered products', () => {
  const ctrl = new KillSwitchController();
  const products = ['tomorrow', 'smarter', 'apparently', 'pareto', 'galop'] as const;
  for (const p of products) {
    ctrl.register(p, constitutionFor(p)!);
  }

  const start = Date.now();
  const result = ctrl.engage();
  const elapsed = Date.now() - start;

  // All products reached
  assert.equal(result.products.length, products.length);
  for (const p of products) {
    assert.equal(ctrl.isEngaged(p), true);
  }
  // Should complete in < 5s (it's synchronous, so near-instant)
  assert.ok(elapsed < 5000, `Propagation took ${elapsed}ms, expected < 5000ms`);

  // Every receipt is verifiable
  for (const ps of result.products) {
    assert.ok(verifyReceipt(ps.receipt));
  }
});

test('receipt chain is maintained across multiple flips', () => {
  const ctrl = new KillSwitchController();
  ctrl.register('tomorrow', constitutionFor('tomorrow')!);

  ctrl.engage();
  ctrl.disengage();
  ctrl.engage();

  const receipts = ctrl.receiptsFor('tomorrow');
  assert.equal(receipts.length, 3);
  // Chain linkage: each receipt's prevHash matches prior digest
  assert.equal(receipts[0]!.prevHash, null);
  assert.equal(receipts[1]!.prevHash, receipts[0]!.digest);
  assert.equal(receipts[2]!.prevHash, receipts[1]!.digest);
});
