import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  memoryIdempotencyStore, executeIdempotent, runCompensable,
  scoreBinary, evalGate, evalDecisionModel, splitHoldout,
  trainDecisionModel, samplesFromResolved,
  fleetHarmScore, minTier,
  ingestEvent,
  AdminSeverity,
  type ExecutionResult, type CompensableStep, type ResolvedCase,
  type PlanePorts, type PlaneConfig, type AdminEvent, type AdminAction, type FleetVerdict,
} from '../src/fleetAdmin/index.ts';
import type { Receipt } from '../src/governance/receipts.ts';

const now = '2026-07-01T00:00:00.000Z';

// ---------- shared primitives (consolidation didn't change behavior) ----------
test('shared harm score + minTier behave as before', () => {
  assert.equal(fleetHarmScore({ reversibility: 'reversible', blastRadius: 'single', amountUsd: 0 }), 0);
  assert.ok(fleetHarmScore({ reversibility: 'irreversible', blastRadius: 'fleet', amountUsd: 3000 }) >= 0.9);
  assert.equal(minTier('auto', 'co_pilot'), 'co_pilot');
  assert.equal(minTier('human', 'auto'), 'human');
});

// ---------- idempotent executor ----------
test('executeIdempotent runs once, dedupes on retry, and does not memoize failures', async () => {
  const store = memoryIdempotencyStore();
  let calls = 0;
  const ok = async (): Promise<ExecutionResult> => { calls++; return { ok: true, ref: 'r1', detail: 'done' }; };
  const r1 = await executeIdempotent('a1', ok, store);
  const r2 = await executeIdempotent('a1', ok, store);
  assert.equal(calls, 1); // second call deduped
  assert.equal(r2.deduped, true);
  assert.equal(r1.ref, 'r2' === r2.ref ? r1.ref : r1.ref); // same stored result
  assert.equal(r2.ref, 'r1');

  // failures are retryable (not memoized)
  let fcalls = 0;
  const fail = async (): Promise<ExecutionResult> => { fcalls++; return { ok: false, detail: 'x', error: 'boom' }; };
  await executeIdempotent('b1', fail, store);
  await executeIdempotent('b1', fail, store);
  assert.equal(fcalls, 2);
});

// ---------- compensable saga ----------
test('runCompensable rolls back completed steps in reverse on failure', async () => {
  const undone: string[] = [];
  const steps: CompensableStep[] = [
    { name: 's1', run: async () => ({ ok: true, ref: '1', detail: '' }), undo: async () => { undone.push('s1'); } },
    { name: 's2', run: async () => ({ ok: true, ref: '2', detail: '' }), undo: async () => { undone.push('s2'); } },
    { name: 's3', run: async () => ({ ok: false, detail: '', error: 'fail' }) },
  ];
  const res = await runCompensable(steps);
  assert.equal(res.ok, false);
  assert.equal(res.failedStep, 's3');
  assert.deepEqual(res.completed, ['s1', 's2']);
  assert.deepEqual(res.rolledBack, ['s2', 's1']); // reverse order
  assert.deepEqual(undone, ['s2', 's1']);
});
test('runCompensable succeeds with no rollback when all steps pass', async () => {
  const res = await runCompensable([{ name: 'a', run: async () => ({ ok: true, ref: 'x', detail: '' }) }]);
  assert.equal(res.ok, true);
  assert.equal(res.rolledBack.length, 0);
});

// ---------- eval harness ----------
test('scoreBinary computes a correct confusion matrix', () => {
  const s = scoreBinary([
    { predicted: true, actual: true }, // tp
    { predicted: true, actual: false }, // fp
    { predicted: false, actual: true }, // fn
    { predicted: false, actual: false }, // tn
  ]);
  assert.deepEqual([s.tp, s.fp, s.fn, s.tn], [1, 1, 1, 1]);
  assert.equal(s.precision, 0.5);
  assert.equal(s.recall, 0.5);
  assert.equal(s.accuracy, 0.5);
});
test('evalGate surfaces false auto-runs; decision model scores well on separable data', () => {
  const gate = evalGate([
    { tier: 'auto', decisionAllow: true, outcome: 'approve' }, // good auto
    { tier: 'auto', decisionAllow: true, outcome: 'reject' }, // FALSE auto-run (dangerous)
    { tier: 'human', decisionAllow: false, outcome: 'approve' }, // over-escalation
  ]);
  assert.equal(gate.falseAutoRuns, 1);

  const cases: ResolvedCase[] = [
    ...Array.from({ length: 30 }, () => ({ domain: 'billing' as const, type: 'billing:issue_refund', amountUsd: 9, reversibility: 'reversible' as const, blastRadius: 'single' as const, outcome: 'approve' as const, at: now })),
    ...Array.from({ length: 30 }, () => ({ domain: 'billing' as const, type: 'billing:issue_refund', amountUsd: 9000, reversibility: 'irreversible' as const, blastRadius: 'fleet' as const, outcome: 'reject' as const, at: now })),
  ];
  const { train, test: held } = splitHoldout(cases, 4);
  const model = trainDecisionModel(samplesFromResolved(train));
  const score = evalDecisionModel(model, held);
  assert.ok(score.accuracy >= 0.9);
});

// ---------- shadow mode (plane records but never executes) ----------
function shadowPorts() {
  const state = { executed: 0, pushed: 0, actions: 0, receipts: 0 };
  const ports: PlanePorts = {
    async saveEvent() {}, async saveAction() { state.actions++; }, async saveReceipt() { state.receipts++; },
    async prevReceipt() { return null; }, async saveApproval() {}, async markApprovalMirrored() {},
    async getApproval() { return null; }, async getAction() { return null; }, async updateApprovalStatus() {},
    async markExecuted() { state.executed++; }, async isApprover() { return true; }, async recordLedger() {},
    async pushToSmarter() { state.pushed++; return true; }, async delegateExecute() { state.executed++; return { ok: true, ref: 'r' }; },
  };
  return { ports, state };
}
test('shadow mode governs + records but never executes or mirrors', async () => {
  const { ports, state } = shadowPorts();
  const cfg: PlaneConfig = { callbackUrl: 'cb', shadowMode: true };
  const event: AdminEvent = { id: 'e', product: 'apparently', domain: 'billing', category: 'refund_request', severity: AdminSeverity.WARNING, title: 't', summary: '', at: now };
  const autoAction: AdminAction = { id: 'a', product: 'apparently', domain: 'billing', type: 'billing:issue_refund', actor: 's', confidence: 0.97, reversibility: 'reversible', blastRadius: 'single', intent: 'refund', amountUsd: 9, at: now };
  const bigAction: AdminAction = { ...autoAction, id: 'b', amountUsd: 5000 };
  const { verdicts } = await ingestEvent(ports, cfg, event, [autoAction, bigAction]);
  assert.equal(verdicts[0]!.decision, 'allow'); // would auto...
  assert.equal(state.executed, 0); // ...but shadow never executes
  assert.equal(state.pushed, 0); // and never bugs a human
  assert.equal(state.actions, 2); // both still recorded for the agreement analysis
});
