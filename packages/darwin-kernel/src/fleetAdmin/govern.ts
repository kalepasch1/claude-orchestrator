/**
 * governFleetAction — the ONE call the control plane makes before any admin
 * remediation runs. It composes three things that already exist in the kernel:
 *
 *   1. the Policy Constitution      (evaluateConstitution — fail-closed law)
 *   2. the four-domain autonomy dial (evaluateAutonomy — the 5/95 ceiling)
 *   3. a signed, hash-chained receipt (buildReceipt — tamper-evident audit)
 *
 * Composition rule (strictly restrictive):
 *   - constitution 'deny'      => deny  (never runs; logged)
 *   - constitution 'escalate'  => escalate to a human, autonomy can only lower it
 *   - constitution 'allow' + autonomy 'auto'     => allow (runs unattended)
 *   - constitution 'allow' + autonomy co_pilot/human => escalate (approval card)
 *
 * The autonomy dial can only ever REDUCE autonomy; it can never upgrade a
 * constitution verdict into an allow. That is what makes the system safe to run
 * across the whole fleet from one control plane.
 */
import type { AgentAction, Decision } from '../types.ts';
import {
  evaluateConstitution,
  type Constitution,
  type ConstitutionDecision,
} from '../governance/constitution.ts';
import { buildReceipt, type Receipt } from '../governance/receipts.ts';
import type { AdminAction, AutonomyTier } from './types.ts';
import {
  evaluateAutonomy,
  type AutonomyDecision,
  type DomainAutonomyPolicy,
} from './autonomy.ts';
import type { AdminDomain } from './types.ts';
import { applyPrecedent, type PrecedentAdvice } from './precedent.ts';

/** Lower an AdminAction into the kernel's generic AgentAction (so it reuses receipts + rules). */
export function toAgentAction(action: AdminAction): AgentAction {
  return {
    product: action.product,
    type: action.type,
    actor: action.actor,
    subjectId: action.subjectId,
    amountUsd: action.amountUsd,
    at: action.at,
    metadata: {
      domain: action.domain,
      eventId: action.eventId,
      confidence: action.confidence,
      reversibility: action.reversibility,
      blastRadius: action.blastRadius,
      intent: action.intent,
      ...(action.params ?? {}),
    },
  };
}

export interface FleetVerdict {
  /** the enforced decision the executor obeys */
  decision: Decision; // 'allow' => run now; 'escalate' => approval card; 'deny' => refuse
  /** the autonomy tier that would apply if allowed */
  tier: AutonomyTier;
  constitution: ConstitutionDecision;
  autonomy: AutonomyDecision;
  /** the precedent advice applied (if any) — case-based autonomy */
  precedent?: PrecedentAdvice;
  /** signed, chain-linkable receipt to persist append-only */
  receipt: Receipt;
  /** one-line human summary for logs + the approval card header */
  summary: string;
}

function combine(
  constitution: ConstitutionDecision,
  autonomy: AutonomyDecision,
): { decision: Decision; tier: AutonomyTier } {
  if (constitution.decision === 'deny') return { decision: 'deny', tier: 'human' };
  if (constitution.decision === 'escalate') {
    // Constitution demands a human; autonomy can only keep it human/co-pilot.
    return { decision: 'escalate', tier: autonomy.tier === 'auto' ? 'co_pilot' : autonomy.tier };
  }
  // constitution allow: autonomy decides whether it runs or waits for approval.
  if (autonomy.tier === 'auto') return { decision: 'allow', tier: 'auto' };
  return { decision: 'escalate', tier: autonomy.tier };
}

/**
 * Evaluate an admin action against the constitution + autonomy matrix and mint a
 * receipt in one step. `prevReceipt`/`chain` maintain the per-subject hash chain.
 */
export function governFleetAction(params: {
  action: AdminAction;
  constitution: Constitution | null | undefined;
  policies?: Record<AdminDomain, DomainAutonomyPolicy>;
  /** optional case-based advice — can only HOLD or LOWER the tier, never raise it */
  precedent?: PrecedentAdvice;
  prevReceipt?: Receipt | null;
  chain?: string;
}): FleetVerdict {
  const agentAction = toAgentAction(params.action);
  const constitution = evaluateConstitution(agentAction, params.constitution);
  const autonomy = evaluateAutonomy(params.action, params.policies);
  let { decision, tier } = combine(constitution, autonomy);

  // Case-based autonomy: if precedent supports LESS autonomy than the dial granted,
  // clamp down (and if an auto action is clamped below auto, it must now escalate).
  if (params.precedent && decision === 'allow') {
    const clamped = applyPrecedent(tier, params.precedent);
    if (clamped !== tier) {
      tier = clamped;
      if (tier !== 'auto') decision = 'escalate';
    }
  }

  const chain =
    params.chain ??
    `${params.action.product}:${params.action.domain}:${params.action.subjectId ?? 'global'}`;

  const receipt = buildReceipt({
    chain,
    action: agentAction,
    verdict: { decision, ruleId: constitution.ruleId, reason: constitution.reason },
    prev: params.prevReceipt ?? null,
    at: params.action.at,
  });

  const verb = decision === 'allow' ? `auto-run (${tier})` : decision === 'deny' ? 'DENIED' : `needs human (${tier})`;
  const summary = `${params.action.product}/${params.action.domain} · ${params.action.type} → ${verb} · ${autonomy.reasons[0] ?? constitution.reason}`;

  return { decision, tier, constitution, autonomy, precedent: params.precedent, receipt, summary };
}
