import { simulateBlast, type ExposureRecord } from './blastSimulator.ts'
import { governFleetAction } from './govern.ts'
import type { AdminAction, AdminDomain, BlastRadius, Reversibility } from './types.ts'

export interface GuidanceCandidate {
  id?: string
  product: string
  domain: AdminDomain
  actionType: string
  intent: string
  amountUsd?: number
  reversibility: Reversibility
  blastRadius: BlastRadius
  confidence?: number
  affectedUsers?: number
  affectedApps?: number
  expectedRevenueUsd?: number
  expectedErrorReductionPct?: number
  expectedUxLiftPct?: number
  estimatedCostUsd?: number
  evidence?: Array<{ source: string; confidence?: number }>
  ifNotDone?: string
}

export interface PreActionGuidance {
  recommendation: 'proceed' | 'proceed_with_guardrails' | 'review' | 'do_not_proceed'
  expectedValue: number
  successProbability: number
  confidence: number
  riskScore: number
  governance: ReturnType<typeof governFleetAction>
  blast: ReturnType<typeof simulateBlast>
  outcome: { headline: string; expectedUpside: string; ifNotDone: string }
  guardrails: string[]
  alternatives: string[]
  missingEvidence: string[]
  proofRequirements: string[]
  signals: Array<{ name: string; value: number; contribution: string }>
  summary: string
}

const REVERSIBILITY_RISK: Record<Reversibility, number> = { reversible: 8, hard_to_reverse: 24, irreversible: 42 }
const BLAST_RISK: Record<BlastRadius, number> = { single: 4, small: 12, large: 28, fleet: 45 }

export function guideAction(candidate: GuidanceCandidate, exposure: ExposureRecord[] = []): PreActionGuidance {
  const evidence = candidate.evidence ?? []
  const evidenceConfidence = evidence.length ? evidence.reduce((sum, item) => sum + (item.confidence ?? .65), 0) / evidence.length : .25
  const confidence = Math.max(.1, Math.min(1, ((candidate.confidence ?? .5) + evidenceConfidence) / 2))
  const revenueValue = Math.min(35, Math.max(0, (candidate.expectedRevenueUsd ?? 0) / 3000))
  const reliabilityValue = Math.min(35, Math.max(0, candidate.expectedErrorReductionPct ?? 0) * .35)
  const uxValue = Math.min(20, Math.max(0, candidate.expectedUxLiftPct ?? 0) * .4)
  const reachValue = Math.min(10, Math.log10(Math.max(1, candidate.affectedUsers ?? 1)) * 2)
  const costPenalty = Math.min(25, Math.max(0, candidate.estimatedCostUsd ?? 0) / 400)
  const expectedValue = Math.round(Math.max(0, Math.min(100, revenueValue + reliabilityValue + uxValue + reachValue + 20 - costPenalty)))
  const blast = simulateBlast({ domain: candidate.domain, actionType: candidate.actionType }, exposure)
  const concentrationRisk = blast.recommendation === 'high_blast' ? 25 : blast.recommendation === 'concentrated_blast' ? 14 : 0
  const riskScore = Math.round(Math.min(100, REVERSIBILITY_RISK[candidate.reversibility] + BLAST_RISK[candidate.blastRadius] + concentrationRisk + (1 - confidence) * 25))
  const successProbability = Math.round(Math.max(5, Math.min(95, (confidence * .65 + (1 - riskScore / 100) * .35) * 100))) / 100
  const action: AdminAction = { id: candidate.id ?? `guidance:${candidate.actionType}`, product: candidate.product as any, domain: candidate.domain, type: candidate.actionType, actor: 'operator-guidance', confidence, reversibility: candidate.reversibility, blastRadius: candidate.blastRadius, intent: candidate.intent, amountUsd: candidate.amountUsd, ifNotDone: candidate.ifNotDone, at: new Date().toISOString() }
  const governance = governFleetAction({ action })
  const missingEvidence: string[] = []
  if (!candidate.expectedRevenueUsd && !candidate.expectedErrorReductionPct && !candidate.expectedUxLiftPct) missingEvidence.push('No quantified outcome signal')
  if (!evidence.length) missingEvidence.push('No supporting evidence attached')
  if (!exposure.length) missingEvidence.push('No historical exposure for this action type')
  if (!candidate.affectedUsers && !candidate.affectedApps) missingEvidence.push('Reach is not quantified')
  let recommendation: PreActionGuidance['recommendation'] = 'proceed'
  if (governance.decision !== 'allow' || riskScore >= 75) recommendation = candidate.reversibility === 'irreversible' ? 'do_not_proceed' : 'review'
  else if (riskScore >= 45 || confidence < .65 || missingEvidence.length >= 2) recommendation = 'proceed_with_guardrails'
  const guardrails = [candidate.reversibility !== 'reversible' ? 'Require explicit human confirmation' : 'Capture rollback checkpoint', candidate.blastRadius === 'fleet' || candidate.blastRadius === 'large' ? 'Canary on one application before widening' : 'Monitor the affected scope', riskScore >= 45 ? 'Stop automatically if the primary success metric declines' : 'Record realized outcome for CADE learning'].filter(Boolean)
  const alternatives = [riskScore >= 45 ? 'Reduce blast radius and stage the change' : 'Run the current plan with monitoring', candidate.reversibility !== 'reversible' ? 'Choose a reversible proxy action first' : 'Run a shadow simulation before execution', confidence < .65 ? 'Collect one additional independent signal' : 'Compare against doing nothing']
  const proofRequirements = ['Before/after primary outcome', 'Execution receipt and actor', candidate.reversibility === 'reversible' ? 'Rollback verification' : 'Explicit approval record', 'Realized cost and affected scope']
  const expectedUpside = expectedValue >= 70 ? 'High modeled value' : expectedValue >= 40 ? 'Moderate modeled value' : 'Limited modeled value'
  const summary = `${recommendation.replaceAll('_', ' ')} · value ${expectedValue}/100 · ${Math.round(successProbability * 100)}% modeled success · risk ${riskScore}/100 · ${Math.round(confidence * 100)}% confidence.`
  return { recommendation, expectedValue, successProbability, confidence: Math.round(confidence * 100) / 100, riskScore, governance, blast, outcome: { headline: `${expectedUpside} for ${candidate.product}`, expectedUpside, ifNotDone: candidate.ifNotDone || 'The current state remains unchanged; opportunity cost is not quantified.' }, guardrails, alternatives, missingEvidence, proofRequirements, signals: [{ name: 'Revenue', value: Math.round(revenueValue), contribution: 'expected upside' }, { name: 'Reliability', value: Math.round(reliabilityValue), contribution: 'error reduction' }, { name: 'Experience', value: Math.round(uxValue), contribution: 'user outcome' }, { name: 'Cost', value: Math.round(costPenalty), contribution: 'value penalty' }, { name: 'Risk', value: riskScore, contribution: 'execution downside' }], summary }
}
