/**
 * approvalCentral.ts — Centralized approval process stub.
 */
export type ApprovalState = 'pending' | 'approved' | 'rejected' | 'expired'

export interface ApprovalRequest {
  id: string
  taskId: string
  state: ApprovalState
  createdAt: number
  expiresAt: number
}

export function isExpired(req: ApprovalRequest, nowMs?: number): boolean {
  return (nowMs ?? Date.now()) > req.expiresAt
}

export function resolveState(req: ApprovalRequest, nowMs?: number): ApprovalState {
  if (req.state === 'pending' && isExpired(req, nowMs)) return 'expired'
  return req.state
}
