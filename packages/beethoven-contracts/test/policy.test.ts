import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  DEFAULT_RELEASE_TRAIN_CONFIG,
  MERGE_CANDIDATE_STATES,
  PolicyError,
  RELEASE_MAX_HOLD_SECONDS,
  RELEASE_MIN_BATCH_RECOVERY,
  RELEASE_MIN_BATCH_STEADY,
  RELEASE_TRAIN_STATES,
  ROUTE_DECISIONS,
  ROUTE_MIN_MERGE_RATE,
  ROUTE_MIN_SAMPLES,
  coderQualityMetricSchema,
  effectiveBatchFloor,
  mergeCandidateSchema,
  mergeWindowSchema,
  releaseTrainBatchSchema,
  releaseTrainConfigSchema,
  routeScoreSchema,
  type CoderQualityMetric,
  type MergeCandidate,
  type ReleaseTrainBatch,
  type ReleaseTrainConfig,
  type RouteScore,
  type RoutingPolicy,
} from '../src/policy.ts';
import { CONTRACT_VERSION, type AuditFields } from '../src/domain.ts';

/* ------------------------------------------------------------------ *
 * Fixtures
 * ------------------------------------------------------------------ */

const audit: AuditFields = {
  observedAt: 1_700_000_000_000,
  observedBy: 'release-train',
  reason: 'batch floor met',
  contractVer: CONTRACT_VERSION,
  source: 'db',
};

const candidate: MergeCandidate = {
  candidateId: 'c-1',
  taskId: 't-1',
  branch: 'agent/some-slug',
  baseBranch: 'master',
  state: 'eligible',
  waitingSeconds: 120,
  changedFiles: 3,
};

const metric: CoderQualityMetric = {
  route: 'claude:claude-haiku-4-5-20251001',
  taskClass: 'legal',
  samples: 12,
  merged: 0,
  testPassed: 1,
  mergeRate: 0,
  costUsd: 0.01,
};

const routeScore: RouteScore = {
  route: metric.route,
  taskClass: 'legal',
  score: 0.05,
  decision: 'demote',
  reason: '0/12 merged on legal-class tasks, below ROUTE_MIN_MERGE_RATE',
  metric,
};

const batch: ReleaseTrainBatch = {
  batchId: 'b-1',
  state: 'accumulating',
  candidates: [candidate],
  config: DEFAULT_RELEASE_TRAIN_CONFIG,
  audit,
};

/* ------------------------------------------------------------------ *
 * (1) the default config fixture validates against its schema
 * ------------------------------------------------------------------ */

test('the default config validates against its schema', () => {
  assert.equal(releaseTrainConfigSchema.is(DEFAULT_RELEASE_TRAIN_CONFIG), true);
  assert.deepEqual(releaseTrainConfigSchema.parse(DEFAULT_RELEASE_TRAIN_CONFIG),
                   DEFAULT_RELEASE_TRAIN_CONFIG);
});

test('the default config encodes the recovery-mode floor and the age override', () => {
  assert.equal(DEFAULT_RELEASE_TRAIN_CONFIG.recoveryMode, true);
  assert.equal(DEFAULT_RELEASE_TRAIN_CONFIG.batchFloor, RELEASE_MIN_BATCH_RECOVERY);
  assert.equal(RELEASE_MIN_BATCH_RECOVERY, 1, 'diagnosis 6: a floor of 10 held small merges');
  assert.equal(DEFAULT_RELEASE_TRAIN_CONFIG.maxHoldSeconds, RELEASE_MAX_HOLD_SECONDS);
  assert.equal(DEFAULT_RELEASE_TRAIN_CONFIG.contractVer, CONTRACT_VERSION);
});

test('effectiveBatchFloor honours recovery mode', () => {
  const steady: ReleaseTrainConfig = { ...DEFAULT_RELEASE_TRAIN_CONFIG, recoveryMode: false, batchFloor: RELEASE_MIN_BATCH_STEADY };
  assert.equal(effectiveBatchFloor(steady), RELEASE_MIN_BATCH_STEADY);
  assert.equal(effectiveBatchFloor({ ...steady, recoveryMode: true }), RELEASE_MIN_BATCH_RECOVERY);
});

/* ------------------------------------------------------------------ *
 * (2) a sample batch and a RoutingPolicy stub compile
 * ------------------------------------------------------------------ */

test('a sample batch of MergeCandidates validates', () => {
  assert.equal(releaseTrainBatchSchema.is(batch), true);
  assert.equal(mergeCandidateSchema.is(candidate), true);
  assert.equal(routeScoreSchema.is(routeScore), true);
  assert.equal(coderQualityMetricSchema.is(metric), true);
});

test('a RoutingPolicy stub satisfies the interface and stays pure', () => {
  const stub: RoutingPolicy = {
    name: 'stub',
    minSamples: ROUTE_MIN_SAMPLES,
    minMergeRate: ROUTE_MIN_MERGE_RATE,
    score(m: CoderQualityMetric): RouteScore {
      const enoughEvidence = m.samples >= ROUTE_MIN_SAMPLES;
      const weak = m.mergeRate < ROUTE_MIN_MERGE_RATE;
      return {
        route: m.route,
        taskClass: m.taskClass,
        score: m.mergeRate,
        decision: enoughEvidence && weak ? 'demote' : 'keep',
        reason: enoughEvidence
          ? `${m.merged}/${m.samples} merged`
          : `only ${m.samples} sample(s); below ROUTE_MIN_SAMPLES`,
        metric: m,
      };
    },
    select(taskClass, metrics) {
      const scored = metrics.filter(m => m.taskClass === taskClass).map(m => this.score(m));
      const kept = scored.filter(s => s.decision === 'keep');
      return kept.length ? kept.reduce((a, b) => (b.score > a.score ? b : a)) : null;
    },
  };

  const demoted = stub.score(metric);
  assert.equal(demoted.decision, 'demote');
  assert.equal(routeScoreSchema.is(demoted), true);

  // same input, same output — no clock, no randomness
  assert.deepEqual(stub.score(metric), demoted);
});

test('a route without enough samples is not demoted on one unlucky batch', () => {
  const thin: CoderQualityMetric = { ...metric, samples: 2, merged: 0, mergeRate: 0 };
  const stub: Pick<RoutingPolicy, 'score'> = {
    score: (m) => ({
      route: m.route, taskClass: m.taskClass, score: m.mergeRate,
      decision: m.samples >= ROUTE_MIN_SAMPLES && m.mergeRate < ROUTE_MIN_MERGE_RATE ? 'demote' : 'keep',
      reason: 'evidence bar', metric: m,
    }),
  };
  assert.equal(stub.score(thin).decision, 'keep');
});

test('select returns null when no route clears the bar', () => {
  const policy: Pick<RoutingPolicy, 'select'> = { select: () => null };
  assert.equal(policy.select('legal', []), null);
});

/* ------------------------------------------------------------------ *
 * (3) invalid policy values are rejected
 * ------------------------------------------------------------------ */

test('a negative batch floor is rejected', () => {
  const bad = { ...DEFAULT_RELEASE_TRAIN_CONFIG, batchFloor: -1 };
  const result = releaseTrainConfigSchema.safeParse(bad);
  assert.equal(result.success, false);
  if (!result.success) {
    assert.equal(result.issues.some(i => i.path === 'batchFloor' && /must be >= 0/.test(i.message)), true);
  }
  assert.throws(() => releaseTrainConfigSchema.parse(bad), PolicyError);
});

test('a fractional batch floor and a negative hold are rejected', () => {
  assert.equal(releaseTrainConfigSchema.is({ ...DEFAULT_RELEASE_TRAIN_CONFIG, batchFloor: 1.5 }), false);
  assert.equal(releaseTrainConfigSchema.is({ ...DEFAULT_RELEASE_TRAIN_CONFIG, maxHoldSeconds: -1 }), false);
});

test('recoveryMode must be a boolean, not a truthy string', () => {
  assert.equal(releaseTrainConfigSchema.is({ ...DEFAULT_RELEASE_TRAIN_CONFIG, recoveryMode: 'true' }), false);
});

test('an out-of-range merge window is rejected', () => {
  assert.equal(mergeWindowSchema.is({ opensAtMinute: 1440, durationMinutes: 0 }), false);
  assert.equal(mergeWindowSchema.is({ opensAtMinute: -1, durationMinutes: 0 }), false);
  assert.equal(mergeWindowSchema.is({ opensAtMinute: 0, durationMinutes: 1441 }), false);
  assert.equal(mergeWindowSchema.is({ opensAtMinute: 1439, durationMinutes: 1440 }), true);
});

test('an unknown MergeCandidate state is rejected', () => {
  assert.equal(mergeCandidateSchema.is({ ...candidate, state: 'sorta-merged' }), false);
});

test('an unknown RouteDecision is rejected', () => {
  assert.equal(routeScoreSchema.is({ ...routeScore, decision: 'maybe' }), false);
});

test('a merge rate outside 0..1 is rejected', () => {
  assert.equal(coderQualityMetricSchema.is({ ...metric, mergeRate: 1.5 }), false);
  assert.equal(coderQualityMetricSchema.is({ ...metric, mergeRate: -0.1 }), false);
  assert.equal(coderQualityMetricSchema.is({ ...metric, costUsd: -1 }), false);
});

test('an empty decision reason is rejected — nothing is demoted without a reason', () => {
  assert.equal(routeScoreSchema.is({ ...routeScore, reason: '' }), false);
});

test('a bad candidate inside a batch is reported with its index', () => {
  const result = releaseTrainBatchSchema.safeParse({
    ...batch,
    candidates: [candidate, { ...candidate, waitingSeconds: -5 }],
  });
  assert.equal(result.success, false);
  if (!result.success) {
    assert.equal(result.issues.some(i => i.path === 'candidates[1].waitingSeconds'), true);
  }
});

test('candidates must be an array', () => {
  assert.equal(releaseTrainBatchSchema.is({ ...batch, candidates: 'one' }), false);
});

test('non-objects and missing fields are rejected without throwing', () => {
  for (const bad of [null, undefined, 7, 'config', [], true]) {
    assert.equal(releaseTrainConfigSchema.safeParse(bad).success, false, String(bad));
  }
  const { batchFloor: _dropped, ...withoutFloor } = DEFAULT_RELEASE_TRAIN_CONFIG;
  const result = releaseTrainConfigSchema.safeParse(withoutFloor);
  assert.equal(result.success, false);
  if (!result.success) {
    assert.equal(result.issues.some(i => i.path === 'batchFloor' && i.message === 'is required'), true);
  }
});

/* ------------------------------------------------------------------ *
 * Enumerations
 * ------------------------------------------------------------------ */

test('enumerations expose the documented members', () => {
  assert.deepEqual([...RELEASE_TRAIN_STATES], ['idle', 'accumulating', 'holding', 'releasing', 'blocked']);
  assert.deepEqual([...MERGE_CANDIDATE_STATES], ['pending', 'eligible', 'held', 'merged', 'rejected']);
  assert.deepEqual([...ROUTE_DECISIONS], ['promote', 'keep', 'demote', 'hold', 'block']);
});

test('the routing evidence bar matches the documented thresholds', () => {
  assert.equal(ROUTE_MIN_SAMPLES, 6);
  assert.equal(ROUTE_MIN_MERGE_RATE, 0.15);
});
