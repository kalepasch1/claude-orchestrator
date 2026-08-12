/**
 * Passport digest canonicalization + fail-closed expiry.
 *
 * Two defects this pins:
 *
 * 1. The digest and content id were computed over the claims array as
 *    supplied, so the same credential presented with its claims in a
 *    different order produced a different id and digest. Claim order is not
 *    semantic — [a, b] and [b, a] are the same passport — so this made
 *    content-addressing unreliable and could reject a legitimate passport as
 *    a digest mismatch.
 *
 * 2. Expiry was evaluated only against `asOf`. Passing a backdated `asOf`
 *    could resurrect a claim that was already expired when the passport was
 *    minted. Expiry is now fail-closed: a claim must be live at `asOf` AND at
 *    the passport's own issue time.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  buildPassport,
  verifyPassport,
  claim,
  type Claim,
} from '../src/passport/passport.ts';

function claimsOf(): Claim[] {
  return [
    claim('kyc_verified', 'galop', 1, 90),
    claim('accredited', 'pareto', 1, 180),
    claim('sanctions_clear', 'tomorrow', 1, 30),
  ];
}

test('passport: digest is independent of claim order', () => {
  const claims = claimsOf();
  const forward = buildPassport({ subject: 'entity_1', claims, issuedAt: '2026-01-01T00:00:00.000Z' });
  const reversed = buildPassport({
    subject: 'entity_1',
    claims: [...claims].reverse(),
    issuedAt: '2026-01-01T00:00:00.000Z',
  });

  assert.equal(forward.digest, reversed.digest, 'digest must not depend on claim order');
});

test('passport: content id is independent of claim order', () => {
  const claims = claimsOf();
  const forward = buildPassport({ subject: 'entity_1', claims, issuedAt: '2026-01-01T00:00:00.000Z' });
  const reversed = buildPassport({
    subject: 'entity_1',
    claims: [...claims].reverse(),
    issuedAt: '2026-01-01T00:00:00.000Z',
  });

  assert.equal(forward.id, reversed.id, 'content id must not depend on claim order');
});

test('passport: supplied claim order is preserved on the passport itself', () => {
  const claims = claimsOf();
  const passport = buildPassport({ subject: 'entity_1', claims });

  assert.deepEqual(
    passport.claims.map((c) => c.kind),
    claims.map((c) => c.kind),
    'canonicalization is for the digest only; the passport keeps caller order',
  );
});

test('passport: reordered claims still verify', () => {
  const passport = buildPassport({ subject: 'entity_1', claims: claimsOf() });
  const shuffled = { ...passport, claims: [...passport.claims].reverse() };

  assert.equal(verifyPassport(shuffled).valid, true, 'reordering must not break verification');
});

test('passport: a different claim set still changes the digest', () => {
  const base = buildPassport({
    subject: 'entity_1',
    claims: claimsOf(),
    issuedAt: '2026-01-01T00:00:00.000Z',
  });
  const tampered = buildPassport({
    subject: 'entity_1',
    claims: [...claimsOf(), claim('accredited', 'attacker', 1, 365)],
    issuedAt: '2026-01-01T00:00:00.000Z',
  });

  assert.notEqual(base.digest, tampered.digest, 'canonicalization must not mask tampering');
});

test('passport: tampered claim value is still detected', () => {
  const passport = buildPassport({ subject: 'entity_1', claims: claimsOf() });
  const tampered = {
    ...passport,
    claims: passport.claims.map((c, i) => (i === 0 ? { ...c, value: c.value + 1 } : c)),
  };

  const result = verifyPassport(tampered);
  assert.equal(result.valid, false);
  assert.equal(result.reason, 'digest_mismatch');
});

test('passport: backdated asOf cannot resurrect a claim expired at mint time', () => {
  // Claim expires before the passport is even issued.
  const dead: Claim = {
    ...claim('kyc_verified', 'galop', 1, 1),
    issuedAt: '2020-01-01T00:00:00.000Z',
    expiresAt: '2020-01-02T00:00:00.000Z',
  };
  const passport = buildPassport({
    subject: 'entity_1',
    claims: [dead],
    issuedAt: '2026-01-01T00:00:00.000Z',
  });

  const backdated = verifyPassport(passport, new Date('2020-01-01T12:00:00.000Z'));
  assert.equal(
    backdated.liveClaims.length,
    0,
    'a claim already dead at mint time must never be live',
  );
});

test('passport: normally-live claim is unaffected by fail-closed expiry', () => {
  const passport = buildPassport({ subject: 'entity_1', claims: claimsOf() });

  const result = verifyPassport(passport);
  assert.equal(result.valid, true);
  assert.equal(result.liveClaims.length, 3, 'valid claims must still be returned');
});

test('passport: claim expiring after mint but before asOf is not live', () => {
  const shortLived: Claim = {
    ...claim('sanctions_clear', 'tomorrow', 1, 1),
    issuedAt: '2026-01-01T00:00:00.000Z',
    expiresAt: '2026-01-02T00:00:00.000Z',
  };
  const passport = buildPassport({
    subject: 'entity_1',
    claims: [shortLived],
    issuedAt: '2026-01-01T00:00:00.000Z',
  });

  assert.equal(verifyPassport(passport, new Date('2026-01-01T12:00:00.000Z')).liveClaims.length, 1);
  assert.equal(verifyPassport(passport, new Date('2026-06-01T00:00:00.000Z')).liveClaims.length, 0);
});
