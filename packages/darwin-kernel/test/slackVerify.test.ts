import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';

// Mirrors the verify() function in supabase/functions/slack-interactions/index.ts.
// Keep in sync with that file; the test proves the fail-closed invariant.
function verify(signing: string, ts: string, sig: string, raw: string): boolean {
  if (!signing) return false; // fail-closed: missing secret rejects all requests
  if (Math.abs(Date.now() / 1000 - Number(ts)) > 300) return false;
  const mac = 'v0=' + createHmac('sha256', signing).update(`v0:${ts}:${raw}`).digest('hex');
  return mac === sig;
}

function makeSignature(secret: string, ts: string, body: string): string {
  return 'v0=' + createHmac('sha256', secret).update(`v0:${ts}:${body}`).digest('hex');
}

const SECRET = 'test-signing-secret';
const BODY = 'payload=%7B%22type%22%3A%22block_actions%22%7D';
const TS = String(Math.floor(Date.now() / 1000));

test('missing signing secret rejects request (fail-closed)', () => {
  const sig = makeSignature(SECRET, TS, BODY);
  assert.equal(verify('', TS, sig, BODY), false);
});

test('valid signature and recent timestamp is accepted', () => {
  const sig = makeSignature(SECRET, TS, BODY);
  assert.equal(verify(SECRET, TS, sig, BODY), true);
});

test('wrong signature is rejected', () => {
  const sig = makeSignature('wrong-secret', TS, BODY);
  assert.equal(verify(SECRET, TS, sig, BODY), false);
});

test('stale timestamp is rejected', () => {
  const staleTs = String(Math.floor(Date.now() / 1000) - 301);
  const sig = makeSignature(SECRET, staleTs, BODY);
  assert.equal(verify(SECRET, staleTs, sig, BODY), false);
});
