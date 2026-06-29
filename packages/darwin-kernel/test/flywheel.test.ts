import { test } from 'node:test';
import assert from 'node:assert/strict';

import { buildPassport } from '../src/passport/index.ts';
import { deriveSubject, type ConsentGrant } from '../src/identity/index.ts';
import { runFlywheel } from '../src/flywheel.ts';
import { evaluateConstitution } from '../src/governance/index.ts';
import { defineCapability, CapabilityRegistry, memoryTransport } from '../src/orchestratorClient/index.ts';
import * as galop from '../src/products/galop.ts';
import * as pareto from '../src/products/pareto.ts';
import * as tomorrow from '../src/products/tomorrow.ts';
import * as hisanta from '../src/products/hisanta.ts';
import { constitutionFor, allCapabilities } from '../src/products/index.ts';

// ---------- product wiring sanity ----------
test('each product yields a constitution + capabilities', () => {
  for (const p of ['tomorrow', 'pareto', 'smarter', 'galop', 'hisanta', 'apparently'] as const) {
    const c = constitutionFor(p);
    assert.ok(c, `${p} has a constitution`);
    assert.equal(c!.product, p);
  }
  assert.ok(allCapabilities().length >= 15);
});

test("product constitutions keep their non-negotiables (deny holds)", () => {
  // Galop must never reveal a winner pre-lock
  assert.equal(
    evaluateConstitution({ product: 'galop', type: 'reveal_winner_pre_lock', actor: 'bot' }, galop.galopConstitution()).decision,
    'deny',
  );
  // Hisanta must never charge a child, and any AI message to a child escalates to parent
  assert.equal(
    evaluateConstitution({ product: 'hisanta', type: 'charge_child', actor: 'bot' }, hisanta.hisantaConstitution()).decision,
    'deny',
  );
  assert.equal(
    evaluateConstitution({ product: 'hisanta', type: 'deliver_ai_message', actor: 'bot' }, hisanta.hisantaConstitution()).decision,
    'escalate',
  );
});

// ---------- THE FLYWHEEL: KYC once (Galop) -> instant underwrite + route (Tomorrow) ----------
test('Galop KYC + Pareto financial profile → Tomorrow instant-underwrites with consent', () => {
  const subject = deriveSubject('jane@example.com');

  // Galop verified her identity + geo when she played.
  const galopPassport = buildPassport({ subject, claims: galop.galopKycClaims({ geoRegion: 'US-NY', sanctionsClear: true }) });
  // Pareto knows her financial strength.
  const paretoPassport = buildPassport({
    subject,
    claims: [pareto.paretoFinancialProfileClaim(0.82, { netWorthBand: '1-5M', liquidityBand: '100-500k' })],
  });

  // She consented to share KYC (galop→tomorrow) and financial_profile (pareto→tomorrow).
  const consent: ConsentGrant[] = [
    { subject, from: 'galop', to: 'tomorrow', scopes: ['kyc_verified', 'geo_allowed', 'sanctions_clear'], grantedAt: '2026-01-01T00:00:00Z' },
    { subject, from: 'pareto', to: 'tomorrow', scopes: ['financial_profile'], grantedAt: '2026-01-01T00:00:00Z' },
  ];

  const { prefill, crossSell } = runFlywheel({
    subject,
    asking: 'tomorrow',
    passports: [galopPassport, paretoPassport],
    consent,
    alreadyOn: ['galop', 'pareto'],
  });

  assert.equal(prefill.kycVerified, true);
  assert.equal(prefill.sanctionsClear, true);
  assert.equal(prefill.financialStrength, 0.82);
  assert.equal(prefill.canInstantUnderwrite, true); // Risk Studio underwrites with zero new intake
  // already on galop+pareto, so cross-sell should not re-suggest them
  assert.ok(!crossSell.some((r) => r.to === 'galop' || r.to === 'pareto'));
});

test('without consent, claims do NOT cross to the asking product (privacy holds)', () => {
  const subject = deriveSubject('bob@example.com');
  const galopPassport = buildPassport({ subject, claims: galop.galopKycClaims({ geoRegion: 'US-CA' }) });
  const { prefill } = runFlywheel({
    subject,
    asking: 'tomorrow',
    passports: [galopPassport],
    consent: [], // no consent granted
    alreadyOn: ['galop'],
  });
  assert.equal(prefill.kycVerified, false); // galop's KYC is NOT usable by tomorrow
  assert.equal(prefill.canInstantUnderwrite, false);
});

test('a product can always use its OWN claims without a consent grant', () => {
  const subject = deriveSubject('carol@example.com');
  const passport = buildPassport({ subject, claims: [tomorrow.tomorrowEcpClaim(), tomorrow.tomorrowCreditClaim(0.9)] });
  const { prefill } = runFlywheel({
    subject,
    asking: 'tomorrow',
    passports: [passport],
    consent: [],
    alreadyOn: ['tomorrow'],
  });
  assert.equal(prefill.ecpEligible, true);
  assert.equal(prefill.financialStrength, 0.9); // credit_quality used as financial signal
});

// ---------- capability instantiation across products (Pareto engine run by Tomorrow) ----------
test('Tomorrow instantiates Pareto monte_carlo via the registry, no code copy', async () => {
  const caps = pareto.paretoCapabilities('https://pareto.app');
  const mc = caps.find((c) => c.name === 'monte_carlo')!;
  const reg = new CapabilityRegistry(
    memoryTransport({ [mc.id]: (input) => ({ p50: (input.balance as number) * 1.4 }) }),
  );
  await reg.publish(mc);
  const found = await reg.discover('retirement', ['finance']);
  assert.ok(found.some((c) => c.name === 'monte_carlo'));
  const out = (await reg.instantiate(mc.id, { balance: 2000 })) as { p50: number };
  assert.equal(out.p50, 2800);
});
