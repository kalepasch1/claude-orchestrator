/**
 * The approval bridge — the shape the Orchestrator pushes into Smarter so Bear can
 * approve every fleet admin decision from his Smarter account, and the decision
 * Smarter posts back. Pure + transport-agnostic: the Orchestrator's push endpoint
 * and Smarter's inbox both speak this vocabulary.
 *
 * Round-trip:
 *   Orchestrator  --FleetApprovalCard-->  Smarter inbox (Now/Approve)
 *   Smarter       --ApprovalDecision  -->  Orchestrator callback  --> executor
 */
import type { ProductId } from '../types.ts';
import type { AdminAction, AdminDomain, AutonomyTier } from './types.ts';
import type { FleetVerdict } from './govern.ts';
import { deliberate, type Deliberation } from './deliberation.ts';

export interface FleetApprovalCard {
  /** stable id == the action id it gates */
  id: string;
  actionId: string;
  product: ProductId;
  domain: AdminDomain;
  tier: AutonomyTier;
  /** ranking inputs so the inbox can sort by (impact × urgency × irreversibility) */
  priority: number;
  title: string;
  /** the four fields the Orchestrator UI already renders, filled from the action + dial */
  why: string;
  value: string;
  risk: string;
  alternatives: string[];
  /** exactly what will happen if approved */
  intent: string;
  /** what happens if NOT approved (the counterfactual) */
  ifNotDone?: string;
  amountUsd?: number;
  /** deep link back into the originating app */
  sourceUrl?: string;
  /** the signed receipt digest pinning what was evaluated (tamper-evident) */
  receiptDigest: string;
  /** CADE pre-pass: the strongest case + strongest objection, so the human decides fast */
  deliberation?: Deliberation;
  /** where Smarter POSTs the decision back to */
  callbackUrl: string;
  status: 'pending' | 'approved' | 'modified' | 'rejected';
  createdAt: string;
}

export interface ApprovalDecision {
  actionId: string;
  decision: 'approve' | 'modify' | 'reject';
  /** approver identity — e.g. kalepasch@gmail.com */
  approver: string;
  /** if 'modify', the edited params the executor should use instead */
  modifiedParams?: Record<string, unknown>;
  note?: string;
  at: string;
}

/** Rank a card 0..100 so the single queue surfaces the most consequential first. */
export function priorityOf(action: AdminAction): number {
  const rev = action.reversibility === 'irreversible' ? 40 : action.reversibility === 'hard_to_reverse' ? 25 : 5;
  const blast = { single: 5, small: 15, large: 30, fleet: 45 }[action.blastRadius];
  const money = Math.min(15, (action.amountUsd ?? 0) / 100);
  return Math.round(Math.min(100, rev + blast + money + (1 - action.confidence) * 15));
}

/** Build the card the Orchestrator pushes to Smarter from a governed action. */
export function buildApprovalCard(params: {
  action: AdminAction;
  verdict: FleetVerdict;
  callbackUrl: string;
  /** skip the CADE pre-pass (e.g. when the caller ran full runDetermination already) */
  skipDeliberation?: boolean;
}): FleetApprovalCard {
  const { action, verdict, callbackUrl } = params;
  // Human-tier cards get the CADE adversarial pre-pass so Bear sees case + objection.
  const deliberation =
    params.skipDeliberation ? undefined : deliberate(action, verdict.precedent);
  return {
    id: action.id,
    actionId: action.id,
    product: action.product,
    domain: action.domain,
    tier: verdict.tier,
    priority: priorityOf(action),
    title: `${action.product} · ${action.domain} · ${action.type}`,
    why: action.intent,
    value: action.ifNotDone ? `Avoids: ${action.ifNotDone}` : verdict.summary,
    risk: `${action.reversibility}, blast=${action.blastRadius}, conf=${action.confidence.toFixed(2)} — ${verdict.autonomy.reasons.join('; ')}`,
    alternatives: ['Approve as proposed', 'Modify parameters, then approve', 'Reject (take no action)'],
    intent: action.intent,
    ifNotDone: action.ifNotDone,
    amountUsd: action.amountUsd,
    sourceUrl: (action.params?.sourceUrl as string | undefined) ?? undefined,
    receiptDigest: verdict.receipt.digest,
    deliberation,
    callbackUrl,
    status: 'pending',
    createdAt: action.at,
  };
}

/** Apply a returned decision to a card (pure — the caller persists the result). */
export function applyDecision(card: FleetApprovalCard, decision: ApprovalDecision): FleetApprovalCard {
  const status =
    decision.decision === 'approve' ? 'approved' : decision.decision === 'modify' ? 'modified' : 'rejected';
  return { ...card, status };
}
