/**
 * Shadow Decisions — calibration system that compares AI policy decisions
 * against actual human decisions to measure alignment before going live.
 */

export type AiDecision = 'auto_approve' | 'auto_deny' | 'escalate'
export type HumanDecision = 'approved' | 'denied' | 'modified'

export interface ShadowDecision {
  id: string
  eventId: string
  app: string
  domain: string
  policyId?: string
  aiDecision: AiDecision
  humanDecision?: HumanDecision
  aligned: boolean | null
  aiConfidence: number
  createdAt: string
  decidedAt?: string
  details: any
}

export interface CalibrationReport {
  totalShadow: number
  humanDecided: number
  alignmentRate: number
  falseApproves: number
  falseEscalates: number
  confidenceByBucket: { bucket: string; count: number; alignmentRate: number }[]
  readyToPromote: boolean
}

const decisions: ShadowDecision[] = []

function makeId(): string {
  return `sdec_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

function computeAlignment(ai: AiDecision, human: HumanDecision): boolean {
  if (ai === 'auto_approve' && human === 'approved') return true
  if (ai === 'auto_deny' && human === 'denied') return true
  if (ai === 'escalate' && human === 'modified') return true
  return false
}

export function recordShadowDecision(
  eventId: string,
  app: string,
  domain: string,
  aiDecision: AiDecision,
  confidence: number,
  policyId?: string,
  details?: any,
): ShadowDecision {
  const decision: ShadowDecision = {
    id: makeId(),
    eventId,
    app,
    domain,
    policyId,
    aiDecision,
    humanDecision: undefined,
    aligned: null,
    aiConfidence: Math.max(0, Math.min(1, confidence)),
    createdAt: new Date().toISOString(),
    details: details || {},
  }
  decisions.unshift(decision)
  if (decisions.length > 1000) decisions.length = 1000
  return decision
}

export function recordHumanDecision(eventId: string, humanDecision: HumanDecision): ShadowDecision | null {
  const decision = decisions.find(d => d.eventId === eventId)
  if (!decision) return null

  decision.humanDecision = humanDecision
  decision.decidedAt = new Date().toISOString()
  decision.aligned = computeAlignment(decision.aiDecision, humanDecision)
  return decision
}

export function getCalibrationReport(): CalibrationReport {
  const decided = decisions.filter(d => d.humanDecision != null)
  const aligned = decided.filter(d => d.aligned === true)

  const falseApproves = decided.filter(
    d => d.aiDecision === 'auto_approve' && d.humanDecision === 'denied',
  ).length

  const falseEscalates = decided.filter(
    d => d.aiDecision === 'escalate' && d.humanDecision === 'approved',
  ).length

  const buckets = [
    { bucket: '0.0 - 0.5', min: 0, max: 0.5 },
    { bucket: '0.5 - 0.8', min: 0.5, max: 0.8 },
    { bucket: '0.8 - 1.0', min: 0.8, max: 1.01 },
  ]

  const confidenceByBucket = buckets.map(b => {
    const inBucket = decided.filter(d => d.aiConfidence >= b.min && d.aiConfidence < b.max)
    const alignedInBucket = inBucket.filter(d => d.aligned === true)
    return {
      bucket: b.bucket,
      count: inBucket.length,
      alignmentRate: inBucket.length > 0 ? alignedInBucket.length / inBucket.length : 0,
    }
  })

  const alignmentRate = decided.length > 0 ? aligned.length / decided.length : 0

  return {
    totalShadow: decisions.length,
    humanDecided: decided.length,
    alignmentRate,
    falseApproves,
    falseEscalates,
    confidenceByBucket,
    readyToPromote: alignmentRate > 0.95 && decided.length > 50,
  }
}

export function getShadowDecisions(limit = 50): ShadowDecision[] {
  return decisions.slice(0, limit)
}

export function getPromotionCandidates(): { policyId: string; count: number; alignmentRate: number }[] {
  const byPolicy = new Map<string, ShadowDecision[]>()
  for (const d of decisions) {
    if (!d.policyId || d.humanDecision == null) continue
    const list = byPolicy.get(d.policyId) || []
    list.push(d)
    byPolicy.set(d.policyId, list)
  }

  const candidates: { policyId: string; count: number; alignmentRate: number }[] = []
  for (const [policyId, list] of byPolicy) {
    if (list.length < 50) continue
    const aligned = list.filter(d => d.aligned === true).length
    const rate = aligned / list.length
    if (rate > 0.95) {
      candidates.push({ policyId, count: list.length, alignmentRate: rate })
    }
  }

  return candidates.sort((a, b) => b.alignmentRate - a.alignmentRate)
}
