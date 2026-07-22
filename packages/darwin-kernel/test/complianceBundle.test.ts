import { test } from 'node:test';
import assert from 'node:assert/strict';

import { PolicyService } from '../src/governance/policyService.ts';
import { attest } from '../src/attestation/attestation.ts';
import { assembleBundle, verifyBundle } from '../src/governance/complianceBundle.ts';
import type { AgentAction } from '../src/types.ts';

const POLICY_TEXT = `
1. Allow trade actions for product tomorrow.
2. Deny any action with capability "delete".
`;

function makeAction(capability = 'trade'): AgentAction {
  return {
    product: 'tomorrow',
    capability,
    subjectId: 'user-1',
    at: new Date().toISOString(),
  } as AgentAction;
}

test('assembleBundle produces a valid, verifiable bundle', () => {
  const svc = PolicyService.fromText({ product: 'tomorrow', text: POLICY_TEXT });
  svc.govern(makeAction('trade'));
  svc.govern(makeAction('trade'));
  const pack = svc.exportPack();

  const att1 = attest({ kind: 'tomorrow:trigger_rating', issuer: 'tomorrow', about: 'trigger-1', payload: { rating: 'AAA' } });
  const att2 = attest({ kind: 'tomorrow:clause_at_market', issuer: 'tomorrow', about: 'clause-42', payload: { spread: 0.02 } });

  const bundle = assembleBundle({ product: 'tomorrow', compliancePack: pack, attestations: [att1, att2] });

  assert.equal(bundle.product, 'tomorrow');
  assert.ok(bundle.digest);
  assert.ok(bundle.signature);
  assert.equal(bundle.attestations.length, 2);

  const result = verifyBundle(bundle);
  assert.equal(result.ok, true);
  assert.equal(result.signatureValid, true);
  assert.equal(result.packValid, true);
  assert.equal(result.attestationResults.length, 2);
  assert.equal(result.issues.length, 0);
});

test('verifyBundle detects tampered bundle', () => {
  const svc = PolicyService.fromText({ product: 'tomorrow', text: POLICY_TEXT });
  svc.govern(makeAction('trade'));
  const pack = svc.exportPack();
  const att = attest({ kind: 'tomorrow:trigger_rating', issuer: 'tomorrow', about: 'trigger-1', payload: { rating: 'AAA' } });

  const bundle = assembleBundle({ product: 'tomorrow', compliancePack: pack, attestations: [att] });

  // Tamper with the product field
  const tampered = { ...bundle, product: 'hacked' };
  const result = verifyBundle(tampered);
  assert.equal(result.ok, false);
  assert.equal(result.signatureValid, false);
  assert.ok(result.issues.length > 0);
});

test('verifyBundle with no attestations', () => {
  const svc = PolicyService.fromText({ product: 'tomorrow', text: POLICY_TEXT });
  svc.govern(makeAction('trade'));
  const pack = svc.exportPack();

  const bundle = assembleBundle({ product: 'tomorrow', compliancePack: pack, attestations: [] });
  const result = verifyBundle(bundle);
  assert.equal(result.ok, true);
  assert.equal(result.attestationResults.length, 0);
});
