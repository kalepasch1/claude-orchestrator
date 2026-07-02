import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  ingestEvent,
  handleDecision,
  type PlanePorts,
  type PlaneConfig,
  type AdminAction,
  type AdminEvent,
  type FleetApprovalCard,
  type FleetVerdict,
  AdminSeverity,
} from '../src/fleetAdmin/index.ts';
import type { Receipt } from '../src/governance/receipts.ts';

const now = '2026-07-01T00:00:00.000Z';

/** In-memory ports that record what the plane did, so we can assert the routing. */
function makePorts(opts: { approvers?: string[]; executeOk?: boolean } = {}) {
  const approvers = new Set(opts.approvers ?? ['kalepasch@gmail.com']);
  const state = {
    events: [] as AdminEvent[],
    actions: new Map<string, AdminAction>(),
    verdicts: new Map<string, FleetVerdict>(),
    receipts: [] as Receipt[],
    approvals: new Map<string, FleetApprovalCard>(),
    executed: [] as { id: string; ref: string; error?: string }[],
    pushed: [] as FleetApprovalCard[],
    ledger: [] as { domain: string; type: string; decision: string }[],
  };
  const ports: PlanePorts = {
    async saveEvent(e) { state.events.push(e); },
    async saveAction(a, v) { state.actions.set(a.id, a); state.verdicts.set(a.id, v); },
    async saveReceipt(r) { state.receipts.push(r); },
    async prevReceipt(chain) {
      const inChain = state.receipts.filter((r) => r.chain === chain);
      return inChain.length ? inChain[inChain.length - 1]! : null;
    },
    async saveApproval(c) { state.approvals.set(c.actionId, c); },
    async markApprovalMirrored() {},
    async getApproval(id) { return state.approvals.get(id) ?? null; },
    async getAction(id) { return state.actions.get(id) ?? null; },
    async updateApprovalStatus(id, status) {
      const c = state.approvals.get(id); if (c) state.approvals.set(id, { ...c, status });
    },
    async markExecuted(id, ref, _undo, error) { state.executed.push({ id, ref, error }); },
    async isApprover(email) { return approvers.has(email); },
    async recordLedger(domain, type, decision) { state.ledger.push({ domain, type, decision }); },
    async pushToSmarter(card) { state.pushed.push(card); return true; },
    async delegateExecute() { return opts.executeOk === false ? { ok: false, error: 'boom' } : { ok: true, ref: 'app_ref_1' }; },
  };
  return { ports, state };
}

const cfg: PlaneConfig = { callbackUrl: 'https://orch/api/fleet/callback' };

function event(over: Partial<AdminEvent> = {}): AdminEvent {
  return { id: 'ev1', product: 'galop', domain: 'billing', category: 'refund_request', severity: AdminSeverity.WARNING, title: 'dup charge', summary: '', at: now, ...over };
}
function action(over: Partial<AdminAction> = {}): AdminAction {
  return { id: 'act1', product: 'galop', domain: 'billing', type: 'billing:issue_refund', actor: 'billing-swarm', eventId: 'ev1', confidence: 0.96, reversibility: 'reversible', blastRadius: 'single', intent: 'Refund $9', amountUsd: 9, at: now, ...over };
}

test('auto path: safe refund executes without an approval card', async () => {
  const { ports, state } = makePorts();
  const { verdicts } = await ingestEvent(ports, cfg, event(), [action()]);
  assert.equal(verdicts[0]!.decision, 'allow');
  assert.equal(state.executed.length, 1);
  assert.equal(state.executed[0]!.error, undefined);
  assert.equal(state.pushed.length, 0);
  assert.equal(state.receipts.length, 1);
});

test('escalate path: big refund raises + mirrors to Smarter, does NOT execute', async () => {
  const { ports, state } = makePorts();
  const { verdicts } = await ingestEvent(ports, cfg, event(), [action({ id: 'act2', amountUsd: 400 })]);
  assert.equal(verdicts[0]!.decision, 'escalate');
  assert.equal(state.executed.length, 0);
  assert.equal(state.pushed.length, 1);
  assert.equal(state.pushed[0]!.callbackUrl, cfg.callbackUrl);
});

test('callback approve → executes + records ledger streak', async () => {
  const { ports, state } = makePorts();
  await ingestEvent(ports, cfg, event(), [action({ id: 'act3', amountUsd: 400 })]);
  const res = await handleDecision(ports, { actionId: 'act3', decision: 'approve', approver: 'kalepasch@gmail.com', at: now });
  assert.equal(res.executed, true);
  assert.equal(state.executed.length, 1);
  assert.equal(state.ledger[0]!.decision, 'approve');
  assert.equal(state.approvals.get('act3')!.status, 'approved');
});

test('callback reject → no execution, still learns', async () => {
  const { ports, state } = makePorts();
  await ingestEvent(ports, cfg, event(), [action({ id: 'act4', amountUsd: 400 })]);
  const res = await handleDecision(ports, { actionId: 'act4', decision: 'reject', approver: 'kalepasch@gmail.com', at: now });
  assert.equal(res.executed, false);
  assert.equal(state.executed.length, 0);
  assert.equal(state.ledger[0]!.decision, 'reject');
});

test('non-allowlisted approver is refused', async () => {
  const { ports } = makePorts({ approvers: ['someone@else.com'] });
  await ingestEvent(ports, cfg, event(), [action({ id: 'act5', amountUsd: 400 })]);
  const res = await handleDecision(ports, { actionId: 'act5', decision: 'approve', approver: 'attacker@evil.com', at: now });
  assert.equal(res.ok, false);
  assert.equal(res.reason, 'approver_not_allowlisted');
});

test('modify path merges params then executes', async () => {
  const { ports, state } = makePorts();
  await ingestEvent(ports, cfg, event(), [action({ id: 'act6', amountUsd: 400, params: { amount: 400 } })]);
  const res = await handleDecision(ports, { actionId: 'act6', decision: 'modify', approver: 'kalepasch@gmail.com', modifiedParams: { amount: 250 }, at: now });
  assert.equal(res.executed, true);
  assert.equal(state.approvals.get('act6')!.status, 'modified');
});

test('failed app execute marks the action errored, never done', async () => {
  const { ports, state } = makePorts({ executeOk: false });
  await ingestEvent(ports, cfg, event(), [action({ id: 'act7' })]);
  assert.equal(state.executed[0]!.error, 'boom');
});
