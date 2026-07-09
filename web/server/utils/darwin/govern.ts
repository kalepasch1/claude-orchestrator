import {
  governAction,
  verifyReceipt,
  type Receipt,
} from '../../../../packages/darwin-kernel/src/governance/index.ts';
import type { AgentAction } from '../../../../packages/darwin-kernel/src/types.ts';

export type { Receipt };
export { verifyReceipt };

export interface Governable {
  type: string;
  actor: string;
  userId?: string;
  amountUsd?: number;
  metadata?: Record<string, unknown>;
}

export interface GoverResult {
  decision: 'allow' | 'escalate' | 'deny';
  receipt: Receipt;
}

/**
 * Thin adapter over @darwin/kernel governAction. Called before any agent
 * action transitions to awaiting_approval / approved / executing. Fail-closed:
 * missing constitution => escalate (never allow).
 */
export function govern(action: Governable, prevReceipt?: Receipt | null): GoverResult {
  const agentAction: AgentAction = {
    product: 'orchestrator',
    type: action.type,
    actor: action.actor,
    subjectId: action.userId,
    amountUsd: action.amountUsd,
    metadata: action.metadata,
  };
  const { verdict, receipt } = governAction({
    action: agentAction,
    constitution: null, // fail-closed: no constitution => escalate
    prevReceipt: prevReceipt ?? null,
  });
  return { decision: verdict.decision, receipt };
}
