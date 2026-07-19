import test from 'node:test'
import assert from 'node:assert/strict'
import { guideAction } from '../src/fleetAdmin/guidance.ts'

test('pre-action guidance rewards quantified reversible improvements', () => {
  const result = guideAction({ product: 'orchestrator', domain: 'infra', actionType: 'ui:improve', intent: 'Improve task discovery', reversibility: 'reversible', blastRadius: 'small', confidence: .9, affectedUsers: 5000, expectedRevenueUsd: 30000, expectedErrorReductionPct: 25, expectedUxLiftPct: 20, estimatedCostUsd: 500, evidence: [{ source: 'experiment', confidence: .9 }] })
  assert.ok(result.expectedValue > 50)
  assert.ok(result.successProbability > .6)
  assert.notEqual(result.recommendation, 'do_not_proceed')
  assert.ok(result.proofRequirements.length >= 3)
})

test('pre-action guidance blocks irreversible fleet-wide low-confidence actions', () => {
  const result = guideAction({ product: 'orchestrator', domain: 'users_access', actionType: 'access:bulk_change', intent: 'Change all user access', reversibility: 'irreversible', blastRadius: 'fleet', confidence: .2 })
  assert.equal(result.recommendation, 'do_not_proceed')
  assert.ok(result.riskScore >= 75)
  assert.ok(result.missingEvidence.length >= 2)
})

test('historical concentrated exposure is included in risk', () => {
  const candidate = { product: 'orchestrator', domain: 'billing' as const, actionType: 'billing:change', intent: 'Change billing', reversibility: 'hard_to_reverse' as const, blastRadius: 'large' as const, confidence: .8, evidence: [{ source: 'ledger', confidence: .8 }] }
  const low = guideAction(candidate)
  const concentrated = guideAction(candidate, [{ product: 'apparently', amountUsd: 6000, at: '2026-07-01T00:00:00Z' }])
  assert.ok(concentrated.riskScore > low.riskScore)
  assert.equal(concentrated.blast.recommendation, 'high_blast')
})
