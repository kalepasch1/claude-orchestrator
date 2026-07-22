import { test } from 'node:test';
import assert from 'node:assert/strict';
import { transitionAction } from '../agentLedger.js';
import { verifyReceipt } from '../darwin/govern.ts';

test('non-gated state bypasses govern and returns state-only', async () => {
  const result = await transitionAction(
    { type: 'send_notification', actor: 'a1', userId: 'u1' },
    'pending',
    null,
  );
  assert.deepEqual(result, { state: 'pending' });
});

test('awaiting_approval transition returns decision, receipt, and state', async () => {
  const result = await transitionAction(
    { type: 'send_notification', actor: 'a2', userId: 'u2' },
    'awaiting_approval',
    null,
  );
  assert.equal(result.state, 'awaiting_approval');
  assert.ok(
    ['allow', 'escalate', 'deny'].includes(result.decision),
    `unexpected decision: ${result.decision}`,
  );
  assert.ok(result.receipt, 'receipt must be present');
  assert.equal(verifyReceipt(result.receipt), true, 'receipt signature must verify');
});

test('approved and executing states are gated', async () => {
  for (const state of ['approved', 'executing'] as const) {
    const r = await transitionAction(
      { type: 'execute_task', actor: `a-${state}`, userId: 'u0' },
      state,
      null,
    );
    assert.equal(r.state, state);
    assert.ok(r.receipt, `receipt missing for state=${state}`);
    assert.equal(verifyReceipt(r.receipt), true);
  }
});

test('receipts chain across consecutive transitions for the same actor+userId', async () => {
  const action = { type: 'queue_task', actor: 'chain-agent', userId: 'chain-user' };
  const first = await transitionAction(action, 'awaiting_approval', null);
  const second = await transitionAction(action, 'approved', null);
  assert.equal(second.receipt.seq, first.receipt.seq + 1, 'seq must increment');
  assert.equal(second.receipt.prevHash, first.receipt.digest, 'prevHash must equal prior digest');
  assert.equal(verifyReceipt(second.receipt), true, 'chained receipt must verify');
});

test('supabase.insert is called on gated transition', async () => {
  let inserted: unknown = null;
  const sb = {
    from: () => ({
      insert: (data: unknown) => {
        inserted = data;
        return Promise.resolve({});
      },
    }),
  };
  await transitionAction(
    { type: 'send_notification', actor: 'sb-a', userId: 'sb-u' },
    'executing',
    sb,
  );
  assert.ok(inserted !== null, 'supabase.insert must be called');
  const row = inserted as Record<string, unknown>;
  assert.equal(row.actor, 'sb-a');
  assert.equal(row.action_type, 'send_notification');
});

test('supabase failure does not throw (fail-soft)', async () => {
  const badSb = {
    from: () => ({
      insert: () => Promise.reject(new Error('DB unavailable')),
    }),
  };
  await assert.doesNotReject(
    () => transitionAction(
      { type: 'approve_action', actor: 'fs-a', userId: 'fs-u' },
      'awaiting_approval',
      badSb,
    ),
    'supabase failure must not propagate',
  );
});
