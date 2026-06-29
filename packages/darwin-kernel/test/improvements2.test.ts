import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  buildUsageRecord,
  capabilityEconomics,
  productEconomics,
  type CostModel,
} from '../src/orchestratorClient/index.ts';
import { PolicyService, verifyCompliancePack } from '../src/governance/index.ts';
import { attest } from '../src/attestation/attestation.ts';
import { AttestationFeed, memoryFeedTransport } from '../src/attestation/feed.ts';
import { convert, toUsdCents, normalizeBalance } from '../src/dataCoop/exchange.ts';
import { householdRollup, relationshipPnl, type AttributedUsage } from '../src/identity/index.ts';
import type { RewardLedgerEntry } from '../src/dataCoop/dataCoop.ts';
import type { RollupNode, IdentityEdge } from '../src/identity/rollups.ts';

const book = { perUnitCents: {}, fallbackPerUnitCents: 10 };

// ---------- #1 unit-economics ledger ----------
test('capability + product economics compute margin and net transfer P&L', () => {
  const recs = [
    buildUsageRecord({ capabilityId: 'monte_carlo', caller: 'tomorrow', owner: 'pareto', latencyMs: 8, units: 1, book }),
    buildUsageRecord({ capabilityId: 'monte_carlo', caller: 'smarter', owner: 'pareto', latencyMs: 12, units: 2, book }),
    buildUsageRecord({ capabilityId: 'price_swap', caller: 'pareto', owner: 'tomorrow', latencyMs: 5, units: 1, book }),
  ];
  const cost: CostModel = { costPerUnitCents: { monte_carlo: 4, price_swap: 3 }, fallbackCostPerUnitCents: 0 };
  const caps = capabilityEconomics(recs, cost);
  const mc = caps.find((c) => c.capabilityId === 'monte_carlo')!;
  // revenue = (1+2)*10 = 30; cost = (1+2)*4 = 12; margin 18; pct 0.6
  assert.equal(mc.revenueCents, 30);
  assert.equal(mc.costCents, 12);
  assert.equal(mc.marginCents, 18);
  assert.ok(Math.abs(mc.marginPct - 0.6) < 1e-9);

  const prods = productEconomics(recs, cost);
  const pareto = prods.find((p) => p.product === 'pareto')!;
  // pareto earns 30 as owner, spends 10 as caller of price_swap => net 20
  assert.equal(pareto.revenueCents, 30);
  assert.equal(pareto.spendCents, 10);
  assert.equal(pareto.netCents, 20);
});

test('tampered usage records are excluded from economics', () => {
  const good = buildUsageRecord({ capabilityId: 'x', caller: 'tomorrow', owner: 'pareto', latencyMs: 1, units: 1, book });
  const bad = { ...good, amountCents: 9999 };
  const caps = capabilityEconomics([good, bad as any]);
  assert.equal(caps.length, 1);
  assert.equal(caps[0]!.revenueCents, 10);
});

// ---------- #2 policy-as-a-product ----------
test('PolicyService compiles NL, governs a stream, and exports a verifiable pack', () => {
  const svc = PolicyService.fromText({
    product: 'tomorrow',
    text: 'Escalate any action above $1,000,000.\nNever spoof_identity.\nAllow place_trade under $1,000,000.',
  });
  svc.govern({ product: 'tomorrow', type: 'place_trade', actor: 'b', amountUsd: 500, at: '2026-06-29T00:00:00Z' });
  svc.govern({ product: 'tomorrow', type: 'place_trade', actor: 'b', amountUsd: 5_000_000, at: '2026-06-29T00:01:00Z' });
  svc.govern({ product: 'tomorrow', type: 'spoof_identity', actor: 'b', at: '2026-06-29T00:02:00Z' });
  const pack = svc.exportPack();
  assert.equal(pack.receipts.length, 3);
  assert.equal(pack.receipts[0]!.decision, 'allow');
  assert.equal(pack.receipts[1]!.decision, 'escalate');
  assert.equal(pack.receipts[2]!.decision, 'deny');
  const v = verifyCompliancePack(pack);
  assert.equal(v.valid, true);
  assert.equal(v.chainOk, true);
});

test('tampered compliance pack fails offline verification', () => {
  const svc = PolicyService.fromText({ product: 'pareto', text: 'Allow x under $10.' });
  svc.govern({ product: 'pareto', type: 'x', actor: 'a', amountUsd: 5 });
  const pack = svc.exportPack();
  // tamper a receipt decision after the fact
  const tampered = { ...pack, receipts: [{ ...pack.receipts[0]!, decision: 'deny' as const }] };
  assert.equal(verifyCompliancePack(tampered as any).valid, false);
});

// ---------- #3 attestation feed ----------
test('attestation feed publishes (owner-gated) and serves verified, metered reads', async () => {
  const manifest = { id: 'tomorrow:trigger_rating', owner: 'tomorrow' as const, kind: 'tomorrow:trigger_rating', title: 'Trigger ratings', description: 'AAA-D parametric trigger grades', pricePerReadCents: 5 };
  let lastRead: any = null;
  const feed = new AttestationFeed({ transport: memoryFeedTransport(), manifest, onRead: (r) => (lastRead = r) });

  const good = attest({ kind: 'tomorrow:trigger_rating', issuer: 'tomorrow', about: 'trig_1', payload: { grade: 'AAA' }, ttlDays: 30 });
  const wrongIssuer = attest({ kind: 'tomorrow:trigger_rating', issuer: 'smarter', about: 'trig_2', payload: { grade: 'A' }, ttlDays: 30 });
  assert.equal((await feed.publish(good)).ok, true);
  assert.equal((await feed.publish(wrongIssuer)).ok, false); // only owner may publish

  const res = await feed.read({ limit: 10 });
  assert.equal(res.attestations.length, 1);
  assert.equal(res.billableReads, 1);
  assert.equal(res.priceCents, 5);
  assert.equal(lastRead.priceCents, 5);
});

// ---------- #4 rewards currency exchange ----------
test('currencies are fungible via USD-cent anchors', () => {
  assert.equal(toUsdCents(100, 'apparently_points'), 100);
  assert.equal(toUsdCents(100, 'galop_coins'), 25);
  // 100 points (=100c) -> coins at 0.25c each = 400 coins
  assert.equal(convert(100, 'apparently_points', 'galop_coins'), 400);
});

test('normalizeBalance rolls a mixed reward ledger into one fungible balance', () => {
  const entries: RewardLedgerEntry[] = [
    { subject: 's', currency: 'apparently_points', amount: 100, reason: 'r1' }, // 100c
    { subject: 's', currency: 'galop_coins', amount: 200, reason: 'r2' }, // 50c
    { subject: 's', currency: 'hisanta_sparks', amount: 100, reason: 'r3' }, // 50c
  ];
  const bal = normalizeBalance(entries, 'apparently_points');
  assert.equal(bal.totalUsdCents, 200);
  assert.equal(bal.inCurrency.amount, 200); // 200c in 1c points
  assert.equal(bal.byCurrency.galop_coins, 200);
});

// ---------- #5 relationship P&L ----------
test('relationship P&L aggregates revenue, cost, rewards across a household', () => {
  const nodes: RollupNode[] = [
    { subject: 'parent', products: ['hisanta', 'pareto'] },
    { subject: 'child', products: ['hisanta'] },
  ];
  const edges: IdentityEdge[] = [{ from: 'parent', to: 'child', kind: 'guardian_of' }];
  const roll = householdRollup('parent', nodes, edges);

  const usage: AttributedUsage[] = [
    { subject: 'parent', record: buildUsageRecord({ capabilityId: 'monte_carlo', caller: 'pareto', owner: 'pareto', latencyMs: 5, units: 1, book }) }, // 10c
    { subject: 'stranger', record: buildUsageRecord({ capabilityId: 'monte_carlo', caller: 'pareto', owner: 'pareto', latencyMs: 5, units: 5, book }) }, // excluded (not a member)
  ];
  const rewards = [{ subject: 'parent', entry: { subject: 'parent', currency: 'galop_coins' as const, amount: 40, reason: 'coop' } }]; // 10c

  const pnl = relationshipPnl({
    rollup: roll,
    usage,
    rewards,
    costModel: { costPerUnitCents: { monte_carlo: 4 }, fallbackCostPerUnitCents: 0 },
  });
  assert.equal(pnl.revenueCents, 10); // only parent's call counts
  assert.equal(pnl.costCents, 4);
  assert.equal(pnl.rewardsPaidCents, 10); // 40 coins * 0.25c
  assert.equal(pnl.netContributionCents, 10 - 4 - 10); // -4
  assert.equal(pnl.breadth, 2);
  assert.equal(pnl.ltvProxyCents, -4 * 2);
});
