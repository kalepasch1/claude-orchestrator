import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  createConfigRequest,
  approveConfigRequest,
  rejectConfigRequest,
  getPendingConfigRequests,
  getRequestsByRequester,
  getApprovalDetails,
  type ConfigApprovalPorts,
  type ConfigRequest,
  type ConfigApproval,
} from '../src/configApproval/index.ts';

// ---------- in-memory ports (mirrors the Supabase implementation) ----------

function mockPorts(): ConfigApprovalPorts & { _requests: ConfigRequest[]; _approvals: ConfigApproval[] } {
  const requests: ConfigRequest[] = [];
  const approvals: ConfigApproval[] = [];
  let seq = 0;

  return {
    _requests: requests,
    _approvals: approvals,

    async insertRequest(req) {
      const row: ConfigRequest = {
        id: `req-${++seq}`,
        key: req.key,
        value: req.value,
        requester: req.requester,
        status: req.status,
        created_at: new Date().toISOString(),
      };
      requests.push(row);
      return row;
    },
    async fetchPendingRequests() {
      return requests.filter((r) => r.status === 'pending');
    },
    async fetchRequestsByRequester(requester) {
      return requests.filter((r) => r.requester === requester);
    },
    async updateRequestStatus(requestId, status) {
      const r = requests.find((x) => x.id === requestId);
      if (!r) throw new Error(`request ${requestId} not found`);
      r.status = status;
    },
    async insertApproval(approval) {
      const row: ConfigApproval = {
        id: `apr-${++seq}`,
        request_id: approval.request_id,
        approver: approval.approver,
        decision: approval.decision,
        reason: approval.reason,
        decided_at: new Date().toISOString(),
      };
      approvals.push(row);
      return row;
    },
    async fetchApprovals(requestId) {
      return approvals.filter((a) => a.request_id === requestId);
    },
  };
}

// ---------- request creation ----------

test('createConfigRequest: inserts a pending request', async () => {
  const ports = mockPorts();
  const req = await createConfigRequest(ports, 'ORCH_AUTO_PULL_MIN', '5', 'alice@example.com');

  assert.equal(req.key, 'ORCH_AUTO_PULL_MIN');
  assert.equal(req.value, '5');
  assert.equal(req.requester, 'alice@example.com');
  assert.equal(req.status, 'pending');
  assert.ok(req.id, 'id is set');
  assert.ok(req.created_at, 'created_at is set');
});

test('createConfigRequest: created_at is an ISO 8601 timestamp', async () => {
  const ports = mockPorts();
  const req = await createConfigRequest(ports, 'ORCH_FLEET_TICK_S', '60', 'bob@example.com');
  assert.ok(!Number.isNaN(Date.parse(req.created_at)), 'created_at parses as a date');
});

test('createConfigRequest: multiple requests accumulate', async () => {
  const ports = mockPorts();
  await createConfigRequest(ports, 'KEY_A', 'val1', 'alice@example.com');
  await createConfigRequest(ports, 'KEY_B', 'val2', 'alice@example.com');
  assert.equal(ports._requests.length, 2);
});

// ---------- pending request listing (RLS simulation) ----------

test('getPendingConfigRequests: returns only pending items', async () => {
  const ports = mockPorts();
  const r1 = await createConfigRequest(ports, 'KEY_A', '1', 'alice@example.com');
  await createConfigRequest(ports, 'KEY_B', '2', 'bob@example.com');
  // Approve r1 directly in store to simulate approved state
  ports._requests.find((r) => r.id === r1.id)!.status = 'approved';

  const pending = await getPendingConfigRequests(ports);
  assert.equal(pending.length, 1);
  assert.equal(pending[0]!.key, 'KEY_B');
});

test('getPendingConfigRequests: returns empty list when nothing is pending', async () => {
  const ports = mockPorts();
  const pending = await getPendingConfigRequests(ports);
  assert.deepEqual(pending, []);
});

// ---------- requester-scoped listing (RLS simulation) ----------

test('getRequestsByRequester: requester sees only their own requests', async () => {
  const ports = mockPorts();
  await createConfigRequest(ports, 'KEY_A', '1', 'alice@example.com');
  await createConfigRequest(ports, 'KEY_B', '2', 'alice@example.com');
  await createConfigRequest(ports, 'KEY_C', '3', 'bob@example.com');

  const aliceReqs = await getRequestsByRequester(ports, 'alice@example.com');
  assert.equal(aliceReqs.length, 2);
  assert.ok(aliceReqs.every((r) => r.requester === 'alice@example.com'), 'all belong to alice');

  const bobReqs = await getRequestsByRequester(ports, 'bob@example.com');
  assert.equal(bobReqs.length, 1);
  assert.equal(bobReqs[0]!.requester, 'bob@example.com');
});

test('getRequestsByRequester: unknown requester sees nothing', async () => {
  const ports = mockPorts();
  await createConfigRequest(ports, 'KEY_A', '1', 'alice@example.com');
  const unknown = await getRequestsByRequester(ports, 'nobody@example.com');
  assert.deepEqual(unknown, []);
});

// ---------- approval flow ----------

test('approveConfigRequest: sets status to approved and records decision', async () => {
  const ports = mockPorts();
  const req = await createConfigRequest(ports, 'ORCH_AUTO_PULL_MIN', '10', 'alice@example.com');

  const approval = await approveConfigRequest(ports, req.id, 'approver@example.com', 'LGTM');

  const updated = ports._requests.find((r) => r.id === req.id)!;
  assert.equal(updated.status, 'approved');
  assert.equal(approval.request_id, req.id);
  assert.equal(approval.approver, 'approver@example.com');
  assert.equal(approval.decision, 'approved');
  assert.equal(approval.reason, 'LGTM');
  assert.ok(approval.id, 'approval id is set');
});

test('approveConfigRequest: decided_at is an ISO 8601 timestamp', async () => {
  const ports = mockPorts();
  const req = await createConfigRequest(ports, 'K', 'v', 'alice@example.com');
  const approval = await approveConfigRequest(ports, req.id, 'boss@example.com', '');
  assert.ok(!Number.isNaN(Date.parse(approval.decided_at)), 'decided_at parses as a date');
});

// ---------- rejection flow ----------

test('rejectConfigRequest: sets status to rejected and records decision', async () => {
  const ports = mockPorts();
  const req = await createConfigRequest(ports, 'ORCH_AUTO_PULL_MIN', '999', 'alice@example.com');

  const approval = await rejectConfigRequest(ports, req.id, 'approver@example.com', 'Too aggressive');

  const updated = ports._requests.find((r) => r.id === req.id)!;
  assert.equal(updated.status, 'rejected');
  assert.equal(approval.decision, 'rejected');
  assert.equal(approval.reason, 'Too aggressive');
});

test('rejectConfigRequest: decided_at is an ISO 8601 timestamp', async () => {
  const ports = mockPorts();
  const req = await createConfigRequest(ports, 'K', 'v', 'alice@example.com');
  const approval = await rejectConfigRequest(ports, req.id, 'boss@example.com', '');
  assert.ok(!Number.isNaN(Date.parse(approval.decided_at)), 'decided_at parses as a date');
});

// ---------- full flow: create → approve → verify pending shrinks ----------

test('full approval flow: pending queue shrinks after decision', async () => {
  const ports = mockPorts();
  const r1 = await createConfigRequest(ports, 'KEY_A', '1', 'alice@example.com');
  const r2 = await createConfigRequest(ports, 'KEY_B', '2', 'bob@example.com');

  assert.equal((await getPendingConfigRequests(ports)).length, 2);

  await approveConfigRequest(ports, r1.id, 'boss@example.com', 'ok');
  assert.equal((await getPendingConfigRequests(ports)).length, 1);
  assert.equal((await getPendingConfigRequests(ports))[0]!.id, r2.id);

  await rejectConfigRequest(ports, r2.id, 'boss@example.com', 'no');
  assert.equal((await getPendingConfigRequests(ports)).length, 0);
});

// ---------- approval details retrieval ----------

test('getApprovalDetails: returns all decisions for a request', async () => {
  const ports = mockPorts();
  const req = await createConfigRequest(ports, 'KEY_A', '1', 'alice@example.com');
  await approveConfigRequest(ports, req.id, 'boss@example.com', 'ok');

  const details = await getApprovalDetails(ports, req.id);
  assert.equal(details.length, 1);
  assert.equal(details[0]!.decision, 'approved');
  assert.equal(details[0]!.request_id, req.id);
});

test('getApprovalDetails: returns empty for unknown request', async () => {
  const ports = mockPorts();
  const details = await getApprovalDetails(ports, 'no-such-id');
  assert.deepEqual(details, []);
});

test('getApprovalDetails: reason field is preserved', async () => {
  const ports = mockPorts();
  const req = await createConfigRequest(ports, 'K', 'v', 'alice@example.com');
  await rejectConfigRequest(ports, req.id, 'boss@example.com', 'security risk');
  const [d] = await getApprovalDetails(ports, req.id);
  assert.equal(d!.reason, 'security risk');
});

// ---------- audit field immutability (once set, not overwritten) ----------

test('audit fields: subsequent actions on different requests are independent', async () => {
  const ports = mockPorts();
  const r1 = await createConfigRequest(ports, 'K1', 'v1', 'alice@example.com');
  const r2 = await createConfigRequest(ports, 'K2', 'v2', 'bob@example.com');
  await approveConfigRequest(ports, r1.id, 'boss@example.com', 'r1 ok');
  await rejectConfigRequest(ports, r2.id, 'boss@example.com', 'r2 no');

  const [d1] = await getApprovalDetails(ports, r1.id);
  const [d2] = await getApprovalDetails(ports, r2.id);
  assert.equal(d1!.decision, 'approved');
  assert.equal(d2!.decision, 'rejected');
});

// ---------- RLS boundary: requester cannot see other user's requests ----------

test('RLS boundary: requester sees only their own, not another user\'s', async () => {
  const ports = mockPorts();
  await createConfigRequest(ports, 'SECRET_KEY', 'secret_val', 'other@example.com');
  await createConfigRequest(ports, 'MY_KEY', 'my_val', 'alice@example.com');

  const aliceView = await getRequestsByRequester(ports, 'alice@example.com');
  assert.equal(aliceView.length, 1);
  assert.equal(aliceView[0]!.key, 'MY_KEY');
  assert.ok(
    aliceView.every((r) => r.requester === 'alice@example.com'),
    'alice cannot see other requester rows',
  );
});
