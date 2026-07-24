import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  buildPassport,
  verifyPassport,
  hasClaim,
  claim,
  type Passport,
  type Claim,
  type ClaimKind,
} from '../src/passport/passport.ts';

test('passport: builds passport with valid structure', () => {
  const claims = [
    claim('kyc_verified', 'galop', 1, 90),
    claim('accredited', 'pareto', 1, 180),
  ];

  const passport = buildPassport({
    subject: 'entity_abc123',
    claims,
  });

  assert.equal(passport.subject, 'entity_abc123');
  assert.equal(passport.version, 1);
  assert.equal(passport.claims.length, 2);
  assert.ok(passport.id.startsWith('pass_'));
  assert.ok(passport.digest);
  assert.equal(passport.signature.algorithm, 'ed25519');
  assert.ok(passport.signature.value);
  assert.ok(passport.signature.publicKeyPem);
});

test('passport: ID is content-addressed (deterministic)', () => {
  const claims = [claim('kyc_verified', 'galop', 1)];
  const iso = new Date('2026-07-23T00:00:00Z').toISOString();

  const p1 = buildPassport({ subject: 'user_1', claims, issuedAt: iso });
  const p2 = buildPassport({ subject: 'user_1', claims, issuedAt: iso });

  assert.equal(p1.id, p2.id);
  assert.equal(p1.digest, p2.digest);
});

test('passport: different subjects produce different IDs', () => {
  const claims = [claim('kyc_verified', 'galop', 1)];
  const iso = new Date().toISOString();

  const p1 = buildPassport({ subject: 'user_1', claims, issuedAt: iso });
  const p2 = buildPassport({ subject: 'user_2', claims, issuedAt: iso });

  assert.notEqual(p1.id, p2.id);
  assert.notEqual(p1.digest, p2.digest);
});

test('passport: claim ordering does not affect digest', () => {
  const iso = new Date().toISOString();
  const c1 = claim('kyc_verified', 'galop', 1, 90, {}, new Date(iso));
  const c2 = claim('accredited', 'pareto', 1, 180, {}, new Date(iso));

  const p1 = buildPassport({ subject: 'user_1', claims: [c1, c2], issuedAt: iso });
  const p2 = buildPassport({ subject: 'user_1', claims: [c2, c1], issuedAt: iso });

  assert.equal(p1.digest, p2.digest);
  assert.equal(p1.id, p2.id);
});

test('passport: verify accepts valid passport', () => {
  const claims = [claim('kyc_verified', 'galop', 1)];
  const passport = buildPassport({ subject: 'user_1', claims });

  const result = verifyPassport(passport);

  assert.equal(result.valid, true);
  assert.equal(result.reason, 'ok');
  assert.equal(result.liveClaims.length, 1);
});

test('passport: verify rejects passport with tampered digest', () => {
  const claims = [claim('kyc_verified', 'galop', 1)];
  const passport = buildPassport({ subject: 'user_1', claims });

  const tampered: Passport = { ...passport, digest: 'deadbeef'.repeat(8) };
  const result = verifyPassport(tampered);

  assert.equal(result.valid, false);
  assert.equal(result.reason, 'digest_mismatch');
  assert.equal(result.liveClaims.length, 0);
});

test('passport: verify rejects passport with invalid signature', () => {
  const claims = [claim('kyc_verified', 'galop', 1)];
  const passport = buildPassport({ subject: 'user_1', claims });

  const tampered: Passport = {
    ...passport,
    signature: { ...passport.signature, value: 'invalid_signature_base64' },
  };
  const result = verifyPassport(tampered);

  assert.equal(result.valid, false);
  assert.equal(result.reason, 'signature_invalid');
});

test('passport: verify rejects all-expired passport', () => {
  const past = new Date('2020-01-01');
  const expiredClaim: Claim = {
    kind: 'kyc_verified',
    issuer: 'galop',
    value: 1,
    issuedAt: '2020-01-01T00:00:00Z',
    expiresAt: '2020-01-02T00:00:00Z',
  };

  const passport = buildPassport({ subject: 'user_1', claims: [expiredClaim] });
  const result = verifyPassport(passport, past);

  assert.equal(result.valid, false);
  assert.equal(result.reason, 'all_claims_expired');
});

test('passport: verify filters to only live claims', () => {
  const now = new Date('2026-07-23T00:00:00Z');
  const past = new Date(now.getTime() - 1000 * 60 * 60 * 24); // 1 day ago

  const liveClaim: Claim = {
    kind: 'kyc_verified',
    issuer: 'galop',
    value: 1,
    issuedAt: now.toISOString(),
    expiresAt: new Date(now.getTime() + 1000 * 60 * 60 * 24 * 90).toISOString(),
  };

  const expiredClaim: Claim = {
    kind: 'accredited',
    issuer: 'pareto',
    value: 1,
    issuedAt: past.toISOString(),
    expiresAt: new Date(past.getTime() + 1000 * 60 * 60 * 24).toISOString(),
  };

  const passport = buildPassport({
    subject: 'user_1',
    claims: [liveClaim, expiredClaim],
  });

  const result = verifyPassport(passport, now);

  assert.equal(result.valid, true);
  assert.equal(result.liveClaims.length, 1);
  assert.equal(result.liveClaims[0]!.kind, 'kyc_verified');
});

test('passport: hasClaim returns true for live claim meeting minimum value', () => {
  const passport = buildPassport({
    subject: 'user_1',
    claims: [
      claim('credit_quality', 'tomorrow', 0.85, 90),
      claim('kyc_verified', 'galop', 1, 90),
    ],
  });

  assert.equal(hasClaim(passport, 'credit_quality', 0.8), true);
  assert.equal(hasClaim(passport, 'credit_quality', 0.85), true);
  assert.equal(hasClaim(passport, 'credit_quality', 0.9), false);
});

test('passport: hasClaim returns false for missing claim kind', () => {
  const passport = buildPassport({
    subject: 'user_1',
    claims: [claim('kyc_verified', 'galop', 1)],
  });

  assert.equal(hasClaim(passport, 'accredited'), false);
  assert.equal(hasClaim(passport, 'credit_quality'), false);
});

test('passport: hasClaim returns false for expired claim', () => {
  const past = new Date('2020-01-01');
  const expiredClaim: Claim = {
    kind: 'kyc_verified',
    issuer: 'galop',
    value: 1,
    issuedAt: '2020-01-01T00:00:00Z',
    expiresAt: '2020-01-02T00:00:00Z',
  };

  const passport = buildPassport({ subject: 'user_1', claims: [expiredClaim] });

  assert.equal(hasClaim(passport, 'kyc_verified', 0, past), false);
});

test('passport: hasClaim is case-sensitive on claim kind', () => {
  const passport = buildPassport({
    subject: 'user_1',
    claims: [claim('kyc_verified', 'galop', 1)],
  });

  assert.equal(hasClaim(passport, 'kyc_verified' as ClaimKind), true);
  assert.equal(hasClaim(passport, 'KYC_VERIFIED' as ClaimKind), false);
});

test('passport: claim helper creates claim with correct TTL', () => {
  const issuedAt = new Date('2026-07-23T00:00:00Z');
  const c = claim('kyc_verified', 'galop', 1, 90, {}, issuedAt);

  assert.equal(c.kind, 'kyc_verified');
  assert.equal(c.issuer, 'galop');
  assert.equal(c.value, 1);
  assert.equal(c.issuedAt, issuedAt.toISOString());

  const expiryDate = new Date(c.expiresAt);
  const expectedExpiry = new Date(issuedAt.getTime() + 90 * 24 * 60 * 60 * 1000);
  assert.equal(expiryDate.getTime(), expectedExpiry.getTime());
});

test('passport: claim with TTL=0 expires immediately', () => {
  const issuedAt = new Date('2026-07-23T00:00:00Z');
  const c = claim('kyc_verified', 'galop', 1, 0, {}, issuedAt);

  const now = new Date(issuedAt.getTime() + 1000);
  const passport = buildPassport({ subject: 'user_1', claims: [c] });
  const result = verifyPassport(passport, now);

  assert.equal(result.valid, false);
  assert.equal(result.liveClaims.length, 0);
});

test('passport: claim with optional detail preserves structure', () => {
  const detail = { band: 'high', tier: 'premium', sources: ['tomorrow', 'pareto'] };
  const c = claim('financial_profile', 'pareto', 1, 90, detail);

  assert.deepEqual(c.detail, detail);
  assert.equal(c.detail.band, 'high');
});

test('passport: multiple claim kinds in single passport', () => {
  const passport = buildPassport({
    subject: 'entity_xyz',
    claims: [
      claim('kyc_verified', 'galop', 1, 90),
      claim('ecp_eligible', 'tomorrow', 1, 180),
      claim('accredited', 'pareto', 1, 365),
      claim('geo_allowed', 'galop', 1, 90),
      claim('credit_quality', 'tomorrow', 0.92, 90),
      claim('financial_profile', 'pareto', 1, 180),
      claim('reliability', 'smarter', 0.95, 120),
      claim('sanctions_clear', 'galop', 1, 90),
    ],
  });

  const result = verifyPassport(passport);

  assert.equal(result.valid, true);
  assert.equal(result.liveClaims.length, 8);
});

test('passport: verifyPassport with custom asOf date', () => {
  const baseDate = new Date('2026-07-23T00:00:00Z');
  const futureDate = new Date(baseDate.getTime() + 1000 * 60 * 60 * 24 * 365); // 1 year later

  const passport = buildPassport({
    subject: 'user_1',
    claims: [claim('kyc_verified', 'galop', 1, 90, {}, baseDate)],
  });

  const resultNow = verifyPassport(passport, baseDate);
  assert.equal(resultNow.valid, true);

  const resultFuture = verifyPassport(passport, futureDate);
  assert.equal(resultFuture.valid, false);
  assert.equal(resultFuture.reason, 'all_claims_expired');
});

test('passport: default TTL is 90 days', () => {
  const issuedAt = new Date('2026-07-23T00:00:00Z');
  const c = claim('kyc_verified', 'galop', 1, undefined, {}, issuedAt);

  const expiryDate = new Date(c.expiresAt);
  const expectedExpiry = new Date(issuedAt.getTime() + 90 * 24 * 60 * 60 * 1000);

  assert.equal(expiryDate.getTime(), expectedExpiry.getTime());
});

test('passport: claim value can be zero (for numeric scores)', () => {
  const c = claim('credit_quality', 'tomorrow', 0, 90);

  assert.equal(c.value, 0);

  const passport = buildPassport({ subject: 'user_1', claims: [c] });
  assert.equal(hasClaim(passport, 'credit_quality', 0), true);
  assert.equal(hasClaim(passport, 'credit_quality', 0.1), false);
});

test('passport: claim value can be fractional', () => {
  const c = claim('reliability', 'smarter', 0.573, 90);

  assert.equal(c.value, 0.573);

  const passport = buildPassport({ subject: 'user_1', claims: [c] });
  assert.equal(hasClaim(passport, 'reliability', 0.57), true);
  assert.equal(hasClaim(passport, 'reliability', 0.574), false);
});

test('passport: empty claims list is valid (but no live claims)', () => {
  const passport = buildPassport({ subject: 'user_1', claims: [] });

  const result = verifyPassport(passport);

  assert.equal(result.valid, false);
  assert.equal(result.reason, 'all_claims_expired');
  assert.equal(result.liveClaims.length, 0);
});

test('passport: large batch of claims processes correctly', () => {
  const claims: Claim[] = [];
  for (let i = 0; i < 100; i++) {
    claims.push(claim('kyc_verified', 'galop', 1, 90));
  }

  const passport = buildPassport({ subject: 'user_1', claims });

  const result = verifyPassport(passport);

  assert.equal(result.valid, true);
  assert.equal(result.liveClaims.length, 100);
  assert.ok(
    result.liveClaims.every((c) => c.kind === 'kyc_verified' && c.issuer === 'galop'),
  );
});

test('passport: claim expiry is checked at exact boundary', () => {
  const baseDate = new Date('2026-07-23T00:00:00Z');
  const expiryDate = new Date(baseDate.getTime() + 90 * 24 * 60 * 60 * 1000);
  const justBeforeExpiry = new Date(expiryDate.getTime() - 1);
  const justAfterExpiry = new Date(expiryDate.getTime() + 1);

  const c: Claim = {
    kind: 'kyc_verified',
    issuer: 'galop',
    value: 1,
    issuedAt: baseDate.toISOString(),
    expiresAt: expiryDate.toISOString(),
  };

  const passport = buildPassport({ subject: 'user_1', claims: [c] });

  const resultBefore = verifyPassport(passport, justBeforeExpiry);
  assert.equal(resultBefore.valid, true);
  assert.equal(resultBefore.liveClaims.length, 1);

  const resultAfter = verifyPassport(passport, justAfterExpiry);
  assert.equal(resultAfter.valid, false);
});

test('passport: issuer field is arbitrary string', () => {
  const claims = [
    claim('kyc_verified', 'custom_provider_xyz', 1),
    claim('accredited', 'another-issuer-123', 1),
  ];

  const passport = buildPassport({ subject: 'user_1', claims });

  assert.equal(hasClaim(passport, 'kyc_verified'), true);
  assert.equal(hasClaim(passport, 'accredited'), true);
  assert.equal(passport.claims[0]!.issuer, 'custom_provider_xyz');
  assert.equal(passport.claims[1]!.issuer, 'another-issuer-123');
});

test('passport: subject is preserved exactly', () => {
  const subjects = [
    'user_abc123',
    'entity_with-dashes',
    'org.domain.code',
    'id/with/slashes',
    '12345',
  ];

  for (const subject of subjects) {
    const passport = buildPassport({
      subject,
      claims: [claim('kyc_verified', 'galop', 1)],
    });

    assert.equal(passport.subject, subject);
  }
});
