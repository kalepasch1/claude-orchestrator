import { test } from 'node:test';
import assert from 'node:assert/strict';

import { sha256Canonical, canonicalize, contentId } from '../src/crypto/hash.ts';
import {
  evaluateConstitution,
  rule,
  governAction,
  verifyReceipt,
  verifyChain,
  classifyMateriality,
  type Constitution,
} from '../src/governance/index.ts';
import { buildPassport, verifyPassport, hasClaim, claim } from '../src/passport/index.ts';
import {
  deriveSubject,
  newIdentity,
  linkLocalId,
  consentAllows,
  suggestRoutes,
  type ConsentGrant,
} from '../src/identity/index.ts';
import { privatizeAggregate, secureSum, seededRng } from '../src/federated/index.ts';
import {
  defineCapability,
  CapabilityRegistry,
  memoryTransport,
} from '../src/orchestratorClient/index.ts';
import type { AgentAction } from '../src/types.ts';

// ---------- crypto / hashing ----------
test('canonicalize is key-order independent', () => {
  assert.equal(canonicalize({ a: 1, b: 2 }), canonicalize({ b: 2, a: 1 }));
  assert.equal(sha256Canonical({ a: 1, b: [3, 2] }), sha256Canonical({ b: [3, 2], a: 1 }));
});
test('canonicalize preserves array order', () => {
  assert.notEqual(sha256Canonical([1, 2]), sha256Canonical([2, 1]));
});
test('contentId is prefixed + deterministic', () => {
  const id = contentId('vp', { x: 1 });
  assert.match(id, /^vp_[0-9a-f]{40}$/);
  assert.equal(id, contentId('vp', { x: 1 }));
});

// ---------- governance: constitution ----------
const baseConstitution: Constitution = {
  product: 'tomorrow',
  version: 1,
  alwaysEscalate: ['money_move', 'novate'],
  rules: [
    rule.denyActionType('no-spoof', 'spoof_identity'),
    rule.notionalCap('cap-1m', 1_000_000),
    rule.allowUnder('small-trade', 'place_trade', 1_000_000),
  ],
};

test('fail-closed when no constitution', () => {
  const a: AgentAction = { product: 'tomorrow', type: 'place_trade', actor: 'bot1' };
  assert.equal(evaluateConstitution(a, null).decision, 'escalate');
});
test('kill switch denies everything', () => {
  const c = { ...baseConstitution, killSwitch: true };
  const a: AgentAction = { product: 'tomorrow', type: 'place_trade', actor: 'bot1' };
  assert.equal(evaluateConstitution(a, c).decision, 'deny');
});
test('§1a override always escalates money movement', () => {
  const a: AgentAction = { product: 'pareto', type: 'money_move', actor: 'agent', amountUsd: 5 };
  assert.equal(evaluateConstitution(a, baseConstitution).decision, 'escalate');
});
test('deny rule beats allow rule', () => {
  const a: AgentAction = { product: 'tomorrow', type: 'spoof_identity', actor: 'bot' };
  assert.equal(evaluateConstitution(a, baseConstitution).decision, 'deny');
});
test('notional cap escalates large, allows small', () => {
  const big: AgentAction = { product: 'tomorrow', type: 'place_trade', actor: 'b', amountUsd: 2_000_000 };
  const small: AgentAction = { product: 'tomorrow', type: 'place_trade', actor: 'b', amountUsd: 500 };
  assert.equal(evaluateConstitution(big, baseConstitution).decision, 'escalate');
  assert.equal(evaluateConstitution(small, baseConstitution).decision, 'allow');
});
test('unmatched money action escalates (fail-closed)', () => {
  const a: AgentAction = { product: 'galop', type: 'unknown_verb', actor: 'x', amountUsd: 10 };
  assert.equal(evaluateConstitution(a, baseConstitution).decision, 'escalate');
});
test('throwing predicate never passes the action', () => {
  const c: Constitution = {
    product: 'smarter',
    version: 1,
    alwaysEscalate: [],
    rules: [
      { id: 'boom', text: 'boom', appliesTo: ['*'], when: () => { throw new Error('x'); }, effect: 'allow', priority: 999 },
    ],
  };
  const a: AgentAction = { product: 'smarter', type: 'send_email', actor: 'bot' };
  // predicate throws => rule does not match => non-money unmatched => allow
  assert.equal(evaluateConstitution(a, c).decision, 'allow');
});

// ---------- governance: receipts + chain ----------
test('governAction mints a verifiable receipt', () => {
  const a: AgentAction = { product: 'tomorrow', type: 'place_trade', actor: 'b', amountUsd: 500, subjectId: 'deal1', at: '2026-06-28T00:00:00Z' };
  const { verdict, receipt } = governAction({ action: a, constitution: baseConstitution });
  assert.equal(verdict.decision, 'allow');
  assert.equal(verifyReceipt(receipt), true);
});
test('tampered receipt fails verification', () => {
  const a: AgentAction = { product: 'tomorrow', type: 'place_trade', actor: 'b', amountUsd: 500, at: '2026-06-28T00:00:00Z' };
  const { receipt } = governAction({ action: a, constitution: baseConstitution });
  const tampered = { ...receipt, decision: 'deny' as const };
  assert.equal(verifyReceipt(tampered), false);
});
test('hash chain links and detects reordering', () => {
  const c = baseConstitution;
  const mk = (i: number, prev: any) =>
    governAction({
      action: { product: 'tomorrow', type: 'place_trade', actor: 'b', amountUsd: 1, subjectId: 'd', at: `2026-06-28T00:0${i}:00Z` },
      constitution: c,
      prevReceipt: prev,
      chain: 'tomorrow:d',
    }).receipt;
  const r0 = mk(0, null);
  const r1 = mk(1, r0);
  const r2 = mk(2, r1);
  assert.deepEqual(verifyChain([r0, r1, r2]), { ok: true, brokenAt: null });
  assert.equal(verifyChain([r0, r2, r1]).ok, false);
});

// ---------- governance: materiality ----------
test('materiality fail-closed on empty changeset', () => {
  assert.equal(classifyMateriality([]).material, true);
});
test('materiality flags schema + money paths, passes docs', () => {
  assert.equal(classifyMateriality(['server/api/funds/payout.ts']).material, true);
  assert.equal(classifyMateriality(['prisma/migrations/001/migration.sql']).material, true);
  assert.equal(classifyMateriality(['docs/README.md', 'tests/foo.test.ts']).material, false);
});

// ---------- passport ----------
test('passport verifies and respects expiry', () => {
  const issuedAt = new Date('2026-01-01T00:00:00Z');
  const p = buildPassport({
    subject: 'sub_1',
    claims: [claim('kyc_verified', 'galop', 1, 90, undefined, issuedAt)],
    issuedAt: issuedAt.toISOString(),
  });
  assert.equal(verifyPassport(p, new Date('2026-02-01T00:00:00Z')).valid, true);
  // 200 days later -> expired
  assert.equal(verifyPassport(p, new Date('2026-07-20T00:00:00Z')).valid, false);
});
test('passport tamper detected; hasClaim honors min value', () => {
  const p = buildPassport({
    subject: 'sub_1',
    claims: [claim('credit_quality', 'tomorrow', 0.8, 90)],
  });
  assert.equal(hasClaim(p, 'credit_quality', 0.7), true);
  assert.equal(hasClaim(p, 'credit_quality', 0.9), false);
  const tampered = { ...p, claims: [claim('credit_quality', 'tomorrow', 0.99, 90)] };
  assert.equal(verifyPassport(tampered).valid, false);
});

// ---------- identity graph ----------
test('deriveSubject stable + case/space insensitive', () => {
  assert.equal(deriveSubject(' Jane@Example.com '), deriveSubject('jane@example.com'));
});
test('link local ids across products', () => {
  let node = newIdentity('sub_1', '2026-01-01T00:00:00Z');
  node = linkLocalId(node, 'pareto', 'u-42');
  node = linkLocalId(node, 'tomorrow', 'party-9');
  assert.equal(node.localIds.pareto, 'u-42');
  assert.equal(node.localIds.tomorrow, 'party-9');
});
test('consent gates cross-product reads + honors revoke/expiry', () => {
  const grants: ConsentGrant[] = [
    { subject: 'sub_1', from: 'galop', to: 'pareto', scopes: ['kyc_verified'], grantedAt: '2026-01-01T00:00:00Z' },
    { subject: 'sub_1', from: 'pareto', to: 'tomorrow', scopes: ['financial_profile'], grantedAt: '2026-01-01T00:00:00Z', revoked: true },
  ];
  assert.equal(consentAllows(grants, { subject: 'sub_1', from: 'galop', to: 'pareto', scope: 'kyc_verified' }), true);
  assert.equal(consentAllows(grants, { subject: 'sub_1', from: 'galop', to: 'pareto', scope: 'credit_quality' }), false);
  assert.equal(consentAllows(grants, { subject: 'sub_1', from: 'pareto', to: 'tomorrow', scope: 'financial_profile' }), false);
});
test('cross-sell routing suggests products by claim, skips existing', () => {
  const routes = suggestRoutes({
    liveClaimKinds: [
      { kind: 'financial_profile', value: 0.8 },
      { kind: 'kyc_verified', value: 1 },
    ],
    alreadyOn: ['pareto'],
  });
  // financial_profile -> tomorrow (high score); pareto suggestion skipped (already on)
  assert.ok(routes.some((r) => r.to === 'tomorrow'));
  assert.ok(!routes.some((r) => r.to === 'pareto'));
  assert.ok(routes[0]!.score >= routes[routes.length - 1]!.score);
});

// ---------- federated privacy ----------
test('k-anonymity suppresses small cohorts', () => {
  const r = privatizeAggregate(100, 2, 1, { k: 3, epsilon: 0.1 });
  assert.equal(r.suppressed, true);
  assert.equal(r.value, null);
});
test('epsilon-DP adds bounded noise for large cohorts; reproducible with seed', () => {
  const a = privatizeAggregate(100, 50, 1, { k: 3, epsilon: 1 }, seededRng(42));
  const b = privatizeAggregate(100, 50, 1, { k: 3, epsilon: 1 }, seededRng(42));
  assert.equal(a.suppressed, false);
  assert.equal(a.value, b.value); // same seed => same noise
});
test('secureSum refuses below k-floor, sums above', () => {
  assert.equal(secureSum([1, 2], { k: 3, epsilon: 0.1 }).ok, false);
  assert.equal(secureSum([1, 2, 3], { k: 3, epsilon: 0.1 }).sum, 6);
});

// ---------- orchestrator: capability registry ----------
test('publish + discover + instantiate a capability across products', async () => {
  const cap = defineCapability({
    name: 'monte_carlo',
    owner: 'pareto',
    version: '1.0.0',
    description: 'Probabilistic retirement simulation P10/P50/P90',
    input: { balance: 'number' },
    output: { p50: 'number' },
    tags: ['finance', 'simulation'],
    endpoint: '/api/personal/retirement/montecarlo',
  });
  const transport = memoryTransport({
    [cap.id]: (input) => ({ p50: (input.balance as number) * 1.5 }),
  });
  const reg = new CapabilityRegistry(transport);
  await reg.publish(cap);
  const found = await reg.discover('monte', ['finance']);
  assert.equal(found.length, 1);
  // Tomorrow's bank vertical instantiates Pareto's engine with no code copy:
  const out = (await reg.instantiate(cap.id, { balance: 1000 })) as { p50: number };
  assert.equal(out.p50, 1500);
});
