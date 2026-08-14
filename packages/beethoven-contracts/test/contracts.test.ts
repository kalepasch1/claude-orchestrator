import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  ASSIGNMENT_STATES,
  AUTHORITATIVE_SOURCE,
  CAPACITY_STATES,
  CONTRACT_VERSION,
  HEALTH_LEVELS,
  LANE_STATES,
  RUNNER_STATUSES,
  SchemaError,
  WORKER_STATES,
  auditFieldsSchema,
  auditNow,
  capacityStateSchema,
  claimCapacitySchema,
  healthLevelSchema,
  jobAssignmentSchema,
  laneIdentitySchema,
  laneSnapshotSchema,
  laneStateSchema,
  runnerIdentitySchema,
  runnerSnapshotSchema,
  runnerStatusSchema,
  timestampsSchema,
  workerIdentitySchema,
  workerSnapshotSchema,
  workerStateSchema,
  type AuditFields,
  type ClaimCapacity,
  type JobAssignment,
  type LaneIdentity,
  type LaneSnapshot,
  type RunnerIdentity,
  type RunnerSnapshot,
  type Timestamps,
  type WorkerIdentity,
  type WorkerSnapshot,
} from '../src/index.ts';

/* ------------------------------------------------------------------ *
 * Fixtures — each is annotated with its interface, so a drift between a
 * type and its schema is a compile error before it is a test failure.
 * ------------------------------------------------------------------ */

const timestamps: Timestamps = { createdAt: 1_000, updatedAt: 2_000, lastHeartbeatAt: 2_000 };
const audit: AuditFields = {
  observedAt: 2_000,
  observedBy: 'immune-sweep',
  reason: 'lane age exceeded ORCH_LANE_ZOMBIE_AFTER_S',
  contractVer: CONTRACT_VERSION,
  source: AUTHORITATIVE_SOURCE,
};
const laneIdentity: LaneIdentity = { laneId: 'lane-1', host: 'mac-2', workerId: 'worker-1' };
const workerIdentity: WorkerIdentity = { workerId: 'worker-1', host: 'mac-2', pid: 4242, role: 'coder' };
const runnerIdentity: RunnerIdentity = { runnerId: 'runner-1', host: 'mac-2', version: '59de85f2' };
const capacity: ClaimCapacity = { subject: 'beethoven', state: 'held', claimable: 803, claiming: 0, limit: 12 };
const laneSnapshot: LaneSnapshot = { identity: laneIdentity, state: 'zombie', health: 'critical', ageSeconds: 4_100, timestamps };
const workerSnapshot: WorkerSnapshot = { identity: workerIdentity, state: 'leaked', health: 'degraded', activeLanes: 14, timestamps };
const runnerSnapshot: RunnerSnapshot = { identity: runnerIdentity, status: 'down', health: 'critical', heartbeatAgeSeconds: null, timestamps };
const assignment: JobAssignment = {
  assignmentId: 'a-1',
  taskId: 't-1',
  lane: laneIdentity,
  worker: workerIdentity,
  state: 'running',
  attempt: 1,
  timestamps,
  audit,
};

const OBJECT_CASES = [
  ['Timestamps', timestampsSchema, timestamps],
  ['AuditFields', auditFieldsSchema, audit],
  ['LaneIdentity', laneIdentitySchema, laneIdentity],
  ['WorkerIdentity', workerIdentitySchema, workerIdentity],
  ['RunnerIdentity', runnerIdentitySchema, runnerIdentity],
  ['ClaimCapacity', claimCapacitySchema, capacity],
  ['LaneSnapshot', laneSnapshotSchema, laneSnapshot],
  ['WorkerSnapshot', workerSnapshotSchema, workerSnapshot],
  ['RunnerSnapshot', runnerSnapshotSchema, runnerSnapshot],
  ['JobAssignment', jobAssignmentSchema, assignment],
] as const;

/* ------------------------------------------------------------------ *
 * Accepts valid fixtures
 * ------------------------------------------------------------------ */

for (const [name, schema, fixture] of OBJECT_CASES) {
  test(`${name}: accepts a valid fixture`, () => {
    assert.equal(schema.safeParse(fixture).success, true);
    assert.deepEqual(schema.parse(fixture), fixture);
    assert.equal(schema.is(fixture), true);
  });
}

test('every declared enum member is accepted by its schema', () => {
  for (const v of LANE_STATES) assert.equal(laneStateSchema.is(v), true, v);
  for (const v of WORKER_STATES) assert.equal(workerStateSchema.is(v), true, v);
  for (const v of RUNNER_STATUSES) assert.equal(runnerStatusSchema.is(v), true, v);
  for (const v of HEALTH_LEVELS) assert.equal(healthLevelSchema.is(v), true, v);
  for (const v of CAPACITY_STATES) assert.equal(capacityStateSchema.is(v), true, v);
  for (const v of ASSIGNMENT_STATES) assert.equal(ASSIGNMENT_STATES.includes(v), true, v);
});

/* ------------------------------------------------------------------ *
 * Rejects invalid values — the reason the schemas exist
 * ------------------------------------------------------------------ */

test('an unknown LaneState is rejected, not passed through', () => {
  assert.equal(laneStateSchema.is('wedged'), false);
  const result = laneStateSchema.safeParse('wedged');
  assert.equal(result.success, false);
  assert.throws(() => laneStateSchema.parse('wedged'), SchemaError);
});

test('an unknown RunnerStatus is rejected', () => {
  assert.equal(runnerStatusSchema.is('probably-fine'), false);
  assert.equal(runnerStatusSchema.is('unknown'), true, '"unknown" is a real state, not a rejection');
});

test('an unknown nested enum fails the whole snapshot with a path', () => {
  const result = laneSnapshotSchema.safeParse({ ...laneSnapshot, state: 'wedged' });
  assert.equal(result.success, false);
  if (!result.success) {
    assert.equal(result.issues.some(i => i.path === 'state'), true);
  }
});

test('a missing required field is reported by name', () => {
  const { reason: _dropped, ...withoutReason } = audit;
  const result = auditFieldsSchema.safeParse(withoutReason);
  assert.equal(result.success, false);
  if (!result.success) {
    assert.deepEqual(result.issues, [{ path: 'reason', message: 'is required' }]);
  }
});

test('an empty reason is rejected — nothing is held or reaped without one', () => {
  assert.equal(auditFieldsSchema.is({ ...audit, reason: '' }), false);
});

test('nested issues carry a dotted path', () => {
  const result = jobAssignmentSchema.safeParse({ ...assignment, worker: { ...workerIdentity, pid: 0 } });
  assert.equal(result.success, false);
  if (!result.success) {
    assert.equal(result.issues.some(i => i.path === 'worker.pid'), true);
  }
});

test('non-objects and nullish input are rejected without throwing', () => {
  for (const bad of [null, undefined, 42, 'lane', [], true]) {
    const result = laneSnapshotSchema.safeParse(bad);
    assert.equal(result.success, false, String(bad));
  }
});

test('NaN and Infinity are not finite numbers', () => {
  assert.equal(timestampsSchema.is({ ...timestamps, createdAt: NaN }), false);
  assert.equal(timestampsSchema.is({ ...timestamps, updatedAt: Infinity }), false);
});

test('a null heartbeat is valid, a string heartbeat is not', () => {
  assert.equal(timestampsSchema.is({ ...timestamps, lastHeartbeatAt: null }), true);
  assert.equal(timestampsSchema.is({ ...timestamps, lastHeartbeatAt: '2026-08-11' }), false);
  assert.equal(runnerSnapshotSchema.is({ ...runnerSnapshot, heartbeatAgeSeconds: null }), true);
});

test('an unclaimed lane may have a null workerId', () => {
  assert.equal(laneIdentitySchema.is({ ...laneIdentity, workerId: null }), true);
  assert.equal(laneIdentitySchema.is({ ...laneIdentity, workerId: '' }), false);
});

test('counts must be non-negative integers', () => {
  assert.equal(claimCapacitySchema.is({ ...capacity, claimable: -1 }), false);
  assert.equal(claimCapacitySchema.is({ ...capacity, claiming: 1.5 }), false);
  assert.equal(claimCapacitySchema.is({ ...capacity, claimable: 0 }), true);
});

test('an unrecognised audit source is rejected', () => {
  assert.equal(auditFieldsSchema.is({ ...audit, source: 'guess' }), false);
  assert.equal(auditFieldsSchema.is({ ...audit, source: 'file' }), true);
});

/* ------------------------------------------------------------------ *
 * Helpers and versioning
 * ------------------------------------------------------------------ */

test('auditNow stamps the current contract version and the authoritative source', () => {
  const stamped = auditNow('sweep', 'lane zombie', 1234);
  assert.equal(stamped.contractVer, CONTRACT_VERSION);
  assert.equal(stamped.source, AUTHORITATIVE_SOURCE);
  assert.equal(stamped.observedAt, 1234);
  assert.equal(auditFieldsSchema.is(stamped), true);
});

test('the authoritative source is the database, not a file mirror', () => {
  assert.equal(AUTHORITATIVE_SOURCE, 'db');
});

test('SchemaError names the schema and lists every issue', () => {
  try {
    laneSnapshotSchema.parse({});
    assert.fail('expected a throw');
  } catch (err) {
    assert.ok(err instanceof SchemaError);
    assert.match(err.message, /LaneSnapshot/);
    assert.ok(err.issues.length >= 5);
  }
});
