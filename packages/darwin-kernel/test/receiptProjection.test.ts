import { test } from 'node:test';
import assert from 'node:assert/strict';

import { buildReceipt, verifyChain } from '../src/governance/receipts.ts';
import { projectChain } from '../src/governance/receiptProjection.ts';
import type { AgentAction } from '../src/types.ts';
import type { ConstitutionDecision } from '../src/governance/constitution.ts';

function makeAction(overrides: Partial<AgentAction> = {}): AgentAction {
  return {
    product: 'test-product',
    capability: 'trade',
    subjectId: 'user-1',
    at: new Date().toISOString(),
    ...overrides,
  } as AgentAction;
}

function makeVerdict(decision: string = 'allow', ruleId: string | null = 'r1'): ConstitutionDecision {
  return { decision, ruleId, reason: 'test', materiality: null } as ConstitutionDecision;
}

function buildChain(count: number): import('../src/governance/receipts.ts').Receipt[] {
  const chain: import('../src/governance/receipts.ts').Receipt[] = [];
  for (let i = 0; i < count; i++) {
    const action = makeAction();
    const verdict = makeVerdict(i % 3 === 0 ? 'deny' : 'allow', i % 2 === 0 ? 'r1' : 'r2');
    chain.push(buildReceipt({ chain: 'test:user-1', action, verdict, prev: chain[i - 1] ?? null }));
  }
  return chain;
}

test('projectChain replays a valid chain to derived state', () => {
  const receipts = buildChain(5);
  const result = projectChain(receipts);

  assert.equal(result.ok, true);
  assert.equal(result.brokenAt, null);
  assert.equal(result.state.totalReceipts, 5);
  assert.equal(result.state.chain, 'test:user-1');
  assert.equal(result.state.headSeq, 4);
  assert.equal(result.state.headDigest, receipts[4]!.digest);
  assert.ok(result.state.firstAt !== null);
  assert.ok(result.state.lastAt !== null);
  // decisions: index 0,3 = deny (2), index 1,2,4 = allow (3)
  assert.equal(result.state.decisionCounts['deny'], 2);
  assert.equal(result.state.decisionCounts['allow'], 3);
  // rules: even indices r1 (0,2,4=3), odd indices r2 (1,3=2)
  assert.equal(result.state.ruleCounts['r1'], 3);
  assert.equal(result.state.ruleCounts['r2'], 2);
});

test('projectChain detects a broken/reordered chain', () => {
  const receipts = buildChain(4);
  const broken = [receipts[0]!, receipts[1]!, receipts[3]!, receipts[2]!];
  const result = projectChain(broken);

  assert.equal(result.ok, false);
  assert.notEqual(result.brokenAt, null);
  assert.ok(result.state.totalReceipts < 4);
});

test('projectChain handles empty chain', () => {
  const result = projectChain([]);
  assert.equal(result.ok, true);
  assert.equal(result.brokenAt, null);
  assert.equal(result.state.totalReceipts, 0);
  assert.equal(result.state.chain, '');
  assert.equal(result.state.firstAt, null);
  assert.equal(result.state.lastAt, null);
  assert.equal(result.state.headDigest, null);
  assert.equal(result.state.headSeq, -1);
});

test('projectChain single receipt', () => {
  const receipts = buildChain(1);
  const result = projectChain(receipts);
  assert.equal(result.ok, true);
  assert.equal(result.state.totalReceipts, 1);
  assert.equal(result.state.headSeq, 0);
  assert.equal(result.state.firstAt, result.state.lastAt);
});

test('projectChain integrity matches verifyChain', () => {
  const receipts = buildChain(6);
  const projection = projectChain(receipts);
  const verification = verifyChain(receipts);
  assert.equal(projection.ok, verification.ok);
  assert.equal(projection.brokenAt, verification.brokenAt);
});
