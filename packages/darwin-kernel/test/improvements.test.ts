import { test } from 'node:test';
import assert from 'node:assert/strict';

import { compileConstitution, evaluateConstitution } from '../src/governance/index.ts';
import {
  buildUsageRecord,
  verifyUsageRecord,
  settleUsage,
  priceUsage,
  MeteredRegistry,
  type PriceBook,
} from '../src/orchestratorClient/index.ts';
import { CapabilityRegistry, defineCapability, memoryTransport } from '../src/orchestratorClient/index.ts';
import { attest, verifyAttestation, liveAttestations } from '../src/attestation/index.ts';
import { runCoopRound } from '../src/dataCoop/index.ts';
import { householdRollup, entityRollup, type IdentityEdge, type RollupNode } from '../src/identity/index.ts';
import type { ConsentGrant } from '../src/identity/index.ts';

// ---------- #1 NL constitution compiler ----------
test('compiles plain-English policy into enforceable rules', () => {
  const { constitution, unmapped, rejected } = compileConstitution({
    product: 'tomorrow',
    text: `
      Escalate any action above $1,000,000.
      Never reveal_winner_pre_lock.
      Allow place_trade under $250k.
      Require approval for novate.
    `,
    alwaysEscalate: ['money_move'],
    lockedDimensions: ['reveal_winner'],
  });
  // cap rule escalates a big trade
  assert.equal(evaluateConstitution({ product: 'tomorrow', type: 'place_trade', actor: 'b', amountUsd: 2_000_000 }, constitution).decision, 'escalate');
  // allow under 250k
  assert.equal(evaluateConstitution({ product: 'tomorrow', type: 'place_trade', actor: 'b', amountUsd: 1_000 }, constitution).decision, 'allow');
  // deny rule fired
  assert.equal(evaluateConstitution({ product: 'tomorrow', type: 'reveal_winner_pre_lock', actor: 'b' }, constitution).decision, 'deny');
  assert.equal(Array.isArray(unmapped), true);
  assert.equal(rejected.length, 0);
});

test('compiler refuses to allow a locked dimension (fail-closed)', () => {
  const { rejected, constitution } = compileConstitution({
    product: 'hisanta',
    text: `Allow charge_child under $5.`,
    lockedDimensions: ['charge_child'],
  });
  assert.equal(rejected.length, 1);
  assert.equal(constitution.rules.length, 0); // the dangerous rule was not compiled
});

test('compiler parses $2.5m shorthand on both bounds', () => {
  const { constitution } = compileConstitution({
    product: 'pareto',
    text: 'Escalate any action above $2.5m.\nAllow trade under $2.5m.',
  });
  // above 2.5m escalates; below 2.5m matches the allow rule
  assert.equal(evaluateConstitution({ product: 'pareto', type: 'trade', actor: 'b', amountUsd: 3_000_000 }, constitution).decision, 'escalate');
  assert.equal(evaluateConstitution({ product: 'pareto', type: 'trade', actor: 'b', amountUsd: 2_000_000 }, constitution).decision, 'allow');
});

// ---------- #2 metering / internal API economy ----------
test('usage record is signed, priced, and verifiable; tamper detected', () => {
  const book: PriceBook = { perUnitCents: { 'cap_x': 5 }, fallbackPerUnitCents: 1 };
  assert.equal(priceUsage('cap_x', 10, book), 50);
  const rec = buildUsageRecord({ capabilityId: 'cap_x', caller: 'tomorrow', owner: 'pareto', latencyMs: 12, units: 10, book });
  assert.equal(rec.amountCents, 50);
  assert.equal(verifyUsageRecord(rec), true);
  assert.equal(verifyUsageRecord({ ...rec, amountCents: 999 }), false);
});

test('settleUsage rolls transfer pricing per owner<=caller and ignores tampered', () => {
  const book: PriceBook = { perUnitCents: {}, fallbackPerUnitCents: 2 };
  const r1 = buildUsageRecord({ capabilityId: 'mc', caller: 'tomorrow', owner: 'pareto', latencyMs: 1, units: 3, book });
  const r2 = buildUsageRecord({ capabilityId: 'mc', caller: 'tomorrow', owner: 'pareto', latencyMs: 1, units: 2, book });
  const bad = { ...buildUsageRecord({ capabilityId: 'mc', caller: 'smarter', owner: 'pareto', latencyMs: 1, units: 100, book }), amountCents: 1 };
  const settle = settleUsage([r1, r2, bad as any]);
  const paretoFromTomorrow = settle.find((s) => s.owner === 'pareto' && s.caller === 'tomorrow')!;
  assert.equal(paretoFromTomorrow.calls, 2);
  assert.equal(paretoFromTomorrow.amountCents, 10); // (3+2)*2
  assert.ok(!settle.some((s) => s.caller === 'smarter')); // tampered excluded
});

test('MeteredRegistry times + meters a cross-product capability call', async () => {
  const cap = defineCapability({ name: 'monte_carlo', owner: 'pareto', version: '1.0.0', description: 'mc', input: {}, output: {}, tags: ['finance'], endpoint: '/x' });
  const reg = new CapabilityRegistry(memoryTransport({ [cap.id]: (i) => ({ p50: (i.balance as number) * 1.5 }) }));
  await reg.publish(cap);
  let captured: any = null;
  const metered = new MeteredRegistry({ registry: reg, caller: 'tomorrow', onUsage: (u) => (captured = u) });
  let t = 1000;
  const { output, usage } = await metered.invoke({ capabilityId: cap.id, owner: 'pareto', input: { balance: 100 }, units: 1, now: () => (t += 5) });
  assert.equal((output as any).p50, 150);
  assert.equal(usage.caller, 'tomorrow');
  assert.equal(usage.owner, 'pareto');
  assert.ok(usage.latencyMs >= 0);
  assert.equal(captured.id, usage.id);
});

// ---------- #3 attestation bus ----------
test('arbitrary attestation verifies offline + expires + tamper detected', () => {
  const a = attest({ kind: 'tomorrow:trigger_rating', issuer: 'tomorrow', about: 'trigger_42', payload: { grade: 'AAA' }, ttlDays: 30, issuedAt: new Date('2026-01-01') });
  assert.equal(verifyAttestation(a, new Date('2026-01-15')).valid, true);
  assert.equal(verifyAttestation(a, new Date('2026-03-01')).valid, false); // expired
  const tampered = { ...a, payload: { grade: 'D' } };
  assert.equal(verifyAttestation(tampered).valid, false);
});

test('liveAttestations filters by kind/about and validity', () => {
  const good = attest({ kind: 'barks:shelter_verified', issuer: 'orchestrator', about: 'shelter_9', payload: { ein: '123' }, ttlDays: 365 });
  const other = attest({ kind: 'smarter:clause_at_market', issuer: 'smarter', about: 'clause_3', payload: { atMarket: true }, ttlDays: 365 });
  const live = liveAttestations([good, other], { kind: 'barks:shelter_verified' });
  assert.equal(live.length, 1);
  assert.equal(live[0]!.about, 'shelter_9');
});

// ---------- #4 consent data-cooperative ----------
test('coop pays consented contributors above k-floor, suppresses below, blocks non-consenters', () => {
  const consent: ConsentGrant[] = ['a', 'b', 'c', 'd'].map((s) => ({
    subject: s, from: 'pareto', to: 'tomorrow', scopes: ['financial_profile'], grantedAt: '2026-01-01T00:00:00Z',
  }));
  const contributions = ['a', 'b', 'c', 'd', 'e'].map((s) => ({
    subject: s, from: 'pareto' as const, to: 'tomorrow' as const, scope: 'financial_profile' as const, value: 1,
  }));
  const res = runCoopRound({
    contributions, consent,
    schedule: { currency: 'galop_coins', perContributor: 100 },
    privacy: { k: 3, epsilon: 1 }, sensitivity: 1, rng: () => 0.5,
  });
  // 'e' had no consent -> rejected; 4 accepted >= k=3 -> not suppressed -> 4 rewards
  assert.equal(res.rejected.some((r) => r.subject === 'e'), true);
  assert.equal(res.cohortSize, 4);
  assert.equal(res.suppressed, false);
  assert.equal(res.rewards.length, 4);
  assert.equal(res.rewards[0]!.currency, 'galop_coins');
});

test('coop suppresses + pays nothing when cohort below k', () => {
  const consent: ConsentGrant[] = [{ subject: 'a', from: 'pareto', to: 'tomorrow', scopes: ['financial_profile'], grantedAt: '2026-01-01T00:00:00Z' }];
  const res = runCoopRound({
    contributions: [{ subject: 'a', from: 'pareto', to: 'tomorrow', scope: 'financial_profile', value: 5 }],
    consent, schedule: { currency: 'hisanta_sparks', perContributor: 10 }, privacy: { k: 3, epsilon: 1 },
  });
  assert.equal(res.suppressed, true);
  assert.equal(res.rewards.length, 0);
  assert.equal(res.sharedValue, null);
});

// ---------- #5 identity rollups ----------
test('household rollup unions products across guardian/spouse edges', () => {
  const nodes: RollupNode[] = [
    { subject: 'parent', products: ['hisanta', 'pareto'] },
    { subject: 'child', products: ['hisanta'] },
    { subject: 'spouse', products: ['tomorrow'] },
    { subject: 'stranger', products: ['galop'] },
  ];
  const edges: IdentityEdge[] = [
    { from: 'parent', to: 'child', kind: 'guardian_of' },
    { from: 'parent', to: 'spouse', kind: 'spouse_of' },
    { from: 'stranger', to: 'child', kind: 'advises' }, // not a household edge
  ];
  const r = householdRollup('parent', nodes, edges);
  assert.deepEqual(new Set(r.members), new Set(['parent', 'child', 'spouse']));
  assert.deepEqual(new Set(r.products), new Set(['hisanta', 'pareto', 'tomorrow']));
  assert.equal(r.breadth, 3);
  assert.ok(!r.members.includes('stranger'));
});

test('entity rollup follows controls/advises only', () => {
  const nodes: RollupNode[] = [
    { subject: 'fund', products: ['tomorrow'] },
    { subject: 'sub', products: ['apparently'] },
    { subject: 'family', products: ['hisanta'] },
  ];
  const edges: IdentityEdge[] = [
    { from: 'fund', to: 'sub', kind: 'controls' },
    { from: 'fund', to: 'family', kind: 'spouse_of' }, // not an entity edge
  ];
  const r = entityRollup('fund', nodes, edges);
  assert.deepEqual(new Set(r.members), new Set(['fund', 'sub']));
  assert.equal(r.breadth, 2);
});
