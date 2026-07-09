import { test } from 'node:test';
import assert from 'node:assert/strict';
import { govern, verifyReceipt } from '../govern.ts';

const VALID_DECISIONS = new Set(['allow', 'escalate', 'deny']);

test('govern Tier-B action returns a valid decision', () => {
  const result = govern({
    type: 'send_notification',
    actor: 'agent-001',
    userId: 'user-123',
    amountUsd: 0,
    metadata: { tier: 'B', channel: 'email' },
  });

  assert.ok(
    VALID_DECISIONS.has(result.decision),
    `decision must be allow|escalate|deny, got: ${result.decision}`,
  );
});

test('govern receipt passes verifyReceipt', () => {
  const result = govern({
    type: 'approve_action',
    actor: 'agent-002',
    userId: 'user-456',
    metadata: { tier: 'B' },
  });

  assert.equal(
    verifyReceipt(result.receipt),
    true,
    'receipt signature must verify',
  );
});

test('govern chains receipts correctly', () => {
  const first = govern({ type: 'queue_task', actor: 'agent-003' });
  const second = govern({ type: 'execute_task', actor: 'agent-003' }, first.receipt);

  assert.equal(second.receipt.seq, first.receipt.seq + 1);
  assert.equal(second.receipt.prevHash, first.receipt.digest);
  assert.equal(verifyReceipt(second.receipt), true);
});
