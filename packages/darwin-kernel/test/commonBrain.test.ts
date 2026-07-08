import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  buildBrainRecipe,
  buildBrainReceipt,
  cadePatternFor,
  commonBrainCapabilities,
} from '../src/commonBrain/index.ts';

test('common brain builds a reusable orchestrator recipe with CADE + agent market + proof', () => {
  const recipe = buildBrainRecipe({
    product: 'orchestrator',
    surface: 'merge-train-release-gate',
    domain: 'autonomous code orchestration',
    objective: 'increase rollback-free deployed improvements per dollar-minute',
    materiality: 0.8,
    sensitivity: 'confidential',
  });

  assert.equal(recipe.cade.proofLabel, 'deployed-diff proof pack');
  assert.match(recipe.settlement, /deployed improvement/);
  assert.ok(recipe.primitives.some((p) => p.id === 'cade_consensus'));
  assert.ok(recipe.primitives.some((p) => p.id === 'agent_market'));
  assert.ok(recipe.stages.some((s) => s.id === 'verify'));
  assert.match(recipe.deploymentPrompt, /red build/);
});

test('CADE pattern changes by product while preserving the same determination structure', () => {
  const tomorrow = cadePatternFor('tomorrow');
  const apparently = cadePatternFor('apparently');
  const smarter = cadePatternFor('smarter');

  assert.match(tomorrow.target, /trade path/);
  assert.match(apparently.target, /regulatory fact/);
  assert.match(smarter.target, /legal work product/);
  assert.ok(tomorrow.issueKinds.includes('negotiation'));
  assert.ok(apparently.issueKinds.includes('legal'));
  assert.ok(smarter.issueKinds.includes('legal'));
});

test('regulated and money-moving surfaces add the right guardrails', () => {
  const recipe = buildBrainRecipe({
    product: 'tomorrow',
    surface: 'execution-router',
    domain: 'OTC exchange',
    objective: 'route orders to compliant best execution or safe no-trade',
    regulated: true,
    moneyMovement: true,
    materiality: 0.9,
  });
  const ids = recipe.primitives.map((p) => p.id);

  assert.ok(ids.includes('disclosure_guardrail'));
  assert.ok(ids.includes('no_custody_payments'));
  assert.ok(ids.includes('zero_touch_autopilot'));
  assert.ok(recipe.guardrails.some((g) => /never custody principal/.test(g)));
});

test('brain receipt is deterministic and capability specs are deployable', () => {
  const recipe = buildBrainRecipe({
    product: 'apparently',
    surface: 'regulatory-hive',
    domain: 'regulatory intelligence',
    objective: 'turn verified regulatory facts into accepted filings',
    regulated: true,
  });
  const a = buildBrainReceipt(recipe);
  const b = buildBrainReceipt(recipe);
  const caps = commonBrainCapabilities('https://orchestrator.example');

  assert.equal(a.digest, b.digest);
  assert.match(a.digest, /^[0-9a-f]{64}$/);
  assert.equal(caps.length, 2);
  assert.ok(caps.every((c) => c.tags.includes('brain')));
  assert.match(caps[0]!.endpoint ?? '', /common-brain\/recipe/);
});
