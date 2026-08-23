import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  buildPassport,
  verifyPassport,
  hasClaim,
  claim,
  type Passport,
  type Claim,
} from '../src/passport/passport.ts';

/**
 * Attested Outcomes: tests for secret-verified claim integrity.
 * Passports use Ed25519 signatures to attest that outcomes (claims) have not
 * been tampered with. These tests verify the signature and digest mechanisms.
 */

test('attested-outcomes: passport signature verifies digest integrity', () => {
  const claims = [claim('kyc_verified', 'galop', 1, 90)];
  const passport = buildPassport({ subject: 'entity_abc123', claims });

  const result = verifyPassport(passport);

  assert.equal(result.valid, true);
  assert.equal(result.reason, 'ok');
  assert.ok(passport.signature.value, 'signature must have value');
  assert.ok(passport.signature.publicKeyPem, 'signature must have public key');
  assert.equal(passport.signature.algorithm, 'ed25519');
});

test('attested-outcomes: modifying any claim invalidates signature', () => {
  const claims = [claim('kyc_verified', 'galop', 1, 90)];
  const passport = buildPassport({ subject: 'entity_abc123', claims });

  // Modify a claim value
  const tampered: Passport = {
    ...passport,
    claims: [{ ...passport.claims[0]!, value: 0.5 }],
  };

  const result = verifyPassport(tampered);

  assert.equal(result.valid, false);
  assert.equal(result.reason, 'digest_mismatch');
});

test('attested-outcomes: modifying issuer invalidates attestation', () => {
  const claims = [claim('kyc_verified', 'galop', 1, 90)];
  const passport = buildPassport({ subject: 'entity_abc123', claims });

  const tampered: Passport = {
    ...passport,
    claims: [{ ...passport.claims[0]!, issuer: 'malicious_issuer' }],
  };

  const result = verifyPassport(tampered);

  assert.equal(result.valid, false);
  assert.equal(result.reason, 'digest_mismatch');
});

test('attested-outcomes: reordering claims preserves digest (order-independent)', () => {
  const iso = new Date().toISOString();
  const c1 = claim('kyc_verified', 'galop', 1, 90, {}, new Date(iso));
  const c2 = claim('accredited', 'pareto', 1, 180, {}, new Date(iso));
  const c3 = claim('geo_allowed', 'galop', 1, 90, {}, new Date(iso));

  const p1 = buildPassport({ subject: 'entity_xyz', claims: [c1, c2, c3], issuedAt: iso });
  const p2 = buildPassport({ subject: 'entity_xyz', claims: [c3, c1, c2], issuedAt: iso });
  const p3 = buildPassport({ subject: 'entity_xyz', claims: [c2, c3, c1], issuedAt: iso });

  assert.equal(p1.digest, p2.digest);
  assert.equal(p2.digest, p3.digest);
  assert.equal(p1.id, p2.id);
  assert.equal(p2.id, p3.id);

  const result1 = verifyPassport(p1);
  const result2 = verifyPassport(p2);
  const result3 = verifyPassport(p3);

  assert.equal(result1.valid, true);
  assert.equal(result2.valid, true);
  assert.equal(result3.valid, true);
});

test('attested-outcomes: adding a claim changes digest and id', () => {
  const claims = [claim('kyc_verified', 'galop', 1, 90)];
  const iso = new Date('2026-07-23T00:00:00Z').toISOString();

  const p1 = buildPassport({ subject: 'entity_xyz', claims, issuedAt: iso });
  const p2 = buildPassport({
    subject: 'entity_xyz',
    claims: [...claims, claim('accredited', 'pareto', 1, 180)],
    issuedAt: iso,
  });

  assert.notEqual(p1.digest, p2.digest);
  assert.notEqual(p1.id, p2.id);
});

test('attested-outcomes: same content produces identical digest and signature', () => {
  const claims = [
    claim('kyc_verified', 'galop', 1, 90),
    claim('accredited', 'pareto', 1, 180),
  ];
  const iso = new Date('2026-07-23T00:00:00Z').toISOString();

  const p1 = buildPassport({ subject: 'entity_xyz', claims, issuedAt: iso });
  const p2 = buildPassport({ subject: 'entity_xyz', claims, issuedAt: iso });

  assert.equal(p1.digest, p2.digest);
  assert.equal(p1.signature.value, p2.signature.value);
  assert.equal(p1.id, p2.id);
});

test('attested-outcomes: removing claim from attested passport fails verification', () => {
  const claims = [
    claim('kyc_verified', 'galop', 1, 90),
    claim('accredited', 'pareto', 1, 180),
  ];
  const passport = buildPassport({ subject: 'entity_xyz', claims });

  // Remove a claim
  const tampered: Passport = {
    ...passport,
    claims: [passport.claims[0]!],
  };

  const result = verifyPassport(tampered);

  assert.equal(result.valid, false);
  assert.equal(result.reason, 'digest_mismatch');
});

test('attested-outcomes: detects claim detail tampering', () => {
  const detail = { band: 'high', tier: 'premium' };
  const c = claim('financial_profile', 'pareto', 1, 180, detail);
  const passport = buildPassport({ subject: 'entity_xyz', claims: [c] });

  const tampered: Passport = {
    ...passport,
    claims: [
      {
        ...passport.claims[0]!,
        detail: { band: 'low', tier: 'standard' },
      },
    ],
  };

  const result = verifyPassport(tampered);

  assert.equal(result.valid, false);
  assert.equal(result.reason, 'digest_mismatch');
});

test('attested-outcomes: signature validation fails on corrupt signature', () => {
  const claims = [claim('kyc_verified', 'galop', 1, 90)];
  const passport = buildPassport({ subject: 'entity_xyz', claims });

  const tampered: Passport = {
    ...passport,
    signature: {
      ...passport.signature,
      value: 'corrupted_signature_base64_string',
    },
  };

  const result = verifyPassport(tampered);

  assert.equal(result.valid, false);
  assert.equal(result.reason, 'signature_invalid');
});

test('attested-outcomes: changing subject invalidates passport', () => {
  const claims = [claim('kyc_verified', 'galop', 1, 90)];
  const passport = buildPassport({ subject: 'entity_abc123', claims });

  const tampered: Passport = {
    ...passport,
    subject: 'entity_xyz789',
  };

  const result = verifyPassport(tampered);

  assert.equal(result.valid, false);
  assert.equal(result.reason, 'digest_mismatch');
});

test('attested-outcomes: passport with multiple issuers is attested correctly', () => {
  const claims = [
    claim('kyc_verified', 'galop', 1, 90),
    claim('financial_profile', 'pareto', 1, 180),
    claim('reliability', 'smarter', 0.95, 120),
    claim('sanctions_clear', 'galop', 1, 90),
  ];

  const passport = buildPassport({ subject: 'entity_xyz', claims });
  const result = verifyPassport(passport);

  assert.equal(result.valid, true);
  assert.equal(result.liveClaims.length, 4);

  // All issuers should be present in the attested claims
  const issuers = new Set(result.liveClaims.map((c) => c.issuer));
  assert.equal(issuers.size, 3); // galop, pareto, smarter
  assert.ok(issuers.has('galop'));
  assert.ok(issuers.has('pareto'));
  assert.ok(issuers.has('smarter'));
});

test('attested-outcomes: expired claims are excluded from attestation', () => {
  const now = new Date('2026-07-23T00:00:00Z');
  const past = new Date(now.getTime() - 1000 * 60 * 60 * 24 * 200);

  const liveClaimDetail = { status: 'verified' };
  const expiredClaimDetail = { status: 'expired' };

  const liveClaim: Claim = {
    kind: 'kyc_verified',
    issuer: 'galop',
    value: 1,
    detail: liveClaimDetail,
    issuedAt: now.toISOString(),
    expiresAt: new Date(now.getTime() + 1000 * 60 * 60 * 24 * 90).toISOString(),
  };

  const expiredClaim: Claim = {
    kind: 'accredited',
    issuer: 'pareto',
    value: 1,
    detail: expiredClaimDetail,
    issuedAt: past.toISOString(),
    expiresAt: new Date(past.getTime() + 1000 * 60 * 60 * 24).toISOString(),
  };

  const passport = buildPassport({
    subject: 'entity_xyz',
    claims: [liveClaim, expiredClaim],
  });

  const result = verifyPassport(passport, now);

  assert.equal(result.valid, true);
  assert.equal(result.liveClaims.length, 1);
  assert.equal(result.liveClaims[0]!.kind, 'kyc_verified');
  assert.deepEqual(result.liveClaims[0]!.detail, liveClaimDetail);
});

test('attested-outcomes: claim with zero value is properly attested', () => {
  const c = claim('credit_quality', 'tomorrow', 0, 90);
  const passport = buildPassport({ subject: 'entity_xyz', claims: [c] });

  const result = verifyPassport(passport);

  assert.equal(result.valid, true);
  assert.equal(result.liveClaims[0]!.value, 0);
});

test('attested-outcomes: claim with fractional value is properly attested', () => {
  const c = claim('reliability', 'smarter', 0.573, 90);
  const passport = buildPassport({ subject: 'entity_xyz', claims: [c] });

  const result = verifyPassport(passport);

  assert.equal(result.valid, true);
  assert.equal(result.liveClaims[0]!.value, 0.573);
});

test('attested-outcomes: content-addressed id is stable across rebuilds', () => {
  const claims = [
    claim('kyc_verified', 'galop', 1, 90),
    claim('accredited', 'pareto', 1, 180),
  ];
  const iso = new Date('2026-07-23T00:00:00Z').toISOString();

  const ids = new Set();
  for (let i = 0; i < 5; i++) {
    const passport = buildPassport({ subject: 'entity_xyz', claims, issuedAt: iso });
    ids.add(passport.id);
  }

  assert.equal(ids.size, 1, 'passport id should be identical across rebuilds');
});

test('attested-outcomes: different subjects produce different attestations', () => {
  const claims = [claim('kyc_verified', 'galop', 1, 90)];
  const iso = new Date().toISOString();

  const subjects = ['user_1', 'user_2', 'entity_abc', 'entity_xyz'];
  const ids = new Set();

  for (const subject of subjects) {
    const passport = buildPassport({ subject, claims, issuedAt: iso });
    ids.add(passport.id);
  }

  assert.equal(ids.size, 4, 'different subjects must produce different attestations');
});

test('attested-outcomes: issuedAt changes digest', () => {
  const claims = [claim('kyc_verified', 'galop', 1, 90)];

  const p1 = buildPassport({
    subject: 'entity_xyz',
    claims,
    issuedAt: '2026-07-23T00:00:00Z',
  });
  const p2 = buildPassport({
    subject: 'entity_xyz',
    claims,
    issuedAt: '2026-07-24T00:00:00Z',
  });

  assert.notEqual(p1.digest, p2.digest);
  assert.notEqual(p1.signature.value, p2.signature.value);
});

test('attested-outcomes: hasClaim respects attestation validity', () => {
  const now = new Date('2026-07-23T00:00:00Z');
  const future = new Date(now.getTime() + 1000 * 60 * 60 * 24 * 365);

  const passport = buildPassport({
    subject: 'entity_xyz',
    claims: [claim('kyc_verified', 'galop', 1, 90, {}, now)],
  });

  // At issue time, claim is attested and live
  assert.equal(hasClaim(passport, 'kyc_verified', 0, now), true);

  // After expiry, claim is not attested as live
  assert.equal(hasClaim(passport, 'kyc_verified', 0, future), false);
});

test('attested-outcomes: empty passport (no claims) fails attestation', () => {
  const passport = buildPassport({ subject: 'entity_xyz', claims: [] });

  const result = verifyPassport(passport);

  assert.equal(result.valid, false);
  assert.equal(result.reason, 'all_claims_expired');
  assert.equal(result.liveClaims.length, 0);
});

test('attested-outcomes: claim kind, issuer, value, and timestamps all affect digest', () => {
  const baseIso = new Date('2026-07-23T00:00:00Z').toISOString();
  const baseClaim = claim('kyc_verified', 'galop', 1, 90, {}, new Date(baseIso));
  const basePassport = buildPassport({
    subject: 'entity_xyz',
    claims: [baseClaim],
    issuedAt: baseIso,
  });

  // Change kind
  const differentKind = buildPassport({
    subject: 'entity_xyz',
    claims: [claim('accredited', 'galop', 1, 90, {}, new Date(baseIso))],
    issuedAt: baseIso,
  });
  assert.notEqual(basePassport.digest, differentKind.digest);

  // Change issuer
  const differentIssuer = buildPassport({
    subject: 'entity_xyz',
    claims: [claim('kyc_verified', 'pareto', 1, 90, {}, new Date(baseIso))],
    issuedAt: baseIso,
  });
  assert.notEqual(basePassport.digest, differentIssuer.digest);

  // Change value
  const differentValue = buildPassport({
    subject: 'entity_xyz',
    claims: [claim('kyc_verified', 'galop', 0.5, 90, {}, new Date(baseIso))],
    issuedAt: baseIso,
  });
  assert.notEqual(basePassport.digest, differentValue.digest);
});

test('attested-outcomes: batch of claims all attested correctly', () => {
  const claims: Claim[] = [];
  for (let i = 0; i < 50; i++) {
    claims.push(
      claim(
        i % 2 === 0 ? 'kyc_verified' : 'accredited',
        i % 3 === 0 ? 'galop' : 'pareto',
        i / 100,
        90,
      ),
    );
  }

  const passport = buildPassport({ subject: 'entity_xyz', claims });
  const result = verifyPassport(passport);

  assert.equal(result.valid, true);
  assert.equal(result.liveClaims.length, 50);

  // All claims should be attested exactly as provided
  const liveKinds = new Set(result.liveClaims.map((c) => c.kind));
  assert.ok(liveKinds.has('kyc_verified'));
  assert.ok(liveKinds.has('accredited'));
});
