import assert from 'node:assert/strict';
import test from 'node:test';
import { FractalCausalGraph, HIVEMIND_APPS, HivemindV15, ZeroCopyHolographicRing, canonicalApp, fractalKey } from '../src/hivemindV15/index.ts';

test('exports adapters for all ten applications', async () => {
  const runtime = new HivemindV15();
  assert.equal(HIVEMIND_APPS.length, 10);
  assert.equal(canonicalApp('beethoven'), 'orchestrator');
  for (const app of HIVEMIND_APPS) {
    const result = await runtime.adapter(app).query({ app }, { default: query => query.app });
    assert.equal(result.result, app);
  }
});

test('exact memory short-circuits but same-shaped values do not stale replay', async () => {
  const runtime = new HivemindV15(); let calls = 0;
  const adapter = runtime.adapter('predictions'); const paths = { primary: (q: { x: number }) => { calls++; return q.x + 1; } };
  assert.equal((await adapter.query({ x: 1 }, paths)).result, 2);
  assert.equal((await adapter.query({ x: 1 }, paths)).source, 'memory');
  assert.equal((await adapter.query({ x: 8 }, paths)).result, 9);
  assert.equal(calls, 2);
});

test('spike resting, error curriculum, anomaly curriculum and fractal keys are live', () => {
  const runtime = new HivemindV15(); const app = runtime.adapter('vigil');
  assert.equal(runtime.budget.signal('idle', .1), 0);
  for (let i = 0; i < 8; i++) app.channelOutcome('galop', true);
  assert.equal(app.channelOutcome('galop', true), 3);
  assert.equal(app.anomalyBatch([1, 2, 3], 4).length, 4);
  assert.ok(fractalKey([1, 2, 4, 8, 16, 32]).length > 0);
  const ring = new ZeroCopyHolographicRing(2, 6);
  assert.equal(ring.publish(fractalKey([1, 2, 4, 8])).buffer, ring.publish(fractalKey([2, 4, 8, 16])).buffer);
  const causal = new FractalCausalGraph([1, 4]);
  for (let i = 0; i < 40; i++) causal.observe({ driver: i, target: Math.max(0, i - 1) });
  assert.ok(causal.predict('target', ['driver']).causes.length > 0);
});
