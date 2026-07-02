/**
 * Intent-level autonomy — promote INTENTS, not just action-types. "Keep this churn-risk
 * user happy" becomes a multi-step remediation (refund + apology + priority support) that the
 * plane composes and governs as ONE decision, with the constitution bounding the WHOLE plan
 * rather than each step in isolation. Deciding once, safely, across steps is how 2/98 becomes
 * 1/99. Pure + zero-dep.
 */
import type { Constitution } from '../governance/constitution.ts';
import { buildReceipt, type Receipt } from '../governance/receipts.ts';
import type { AgentAction, Decision } from '../types.ts';
import { governFleetAction, type FleetVerdict } from './govern.ts';
import { DEFAULT_DOMAIN_POLICIES, type DomainAutonomyPolicy } from './autonomy.ts';
import { fleetAdminConstitution } from './constitution.ts';
import type { AdminAction, AdminDomain, AutonomyTier } from './types.ts';

export interface IntentPlan {
  intentId: string;
  goal: string;
  subjectId?: string;
  product: AdminAction['product'];
  steps: AdminAction[];
}

/** Deterministic planner: common goals → a bounded, ordered remediation plan. */
export function planIntent(params: {
  goal: string;
  subjectId?: string;
  product: AdminAction['product'];
  amountUsd?: number;
  at?: string;
}): IntentPlan {
  const at = params.at ?? new Date().toISOString();
  const mk = (over: Partial<AdminAction> & Pick<AdminAction, 'domain' | 'type' | 'intent'>): AdminAction => ({
    id: `${params.goal}:${over.type}:${params.subjectId ?? 'global'}`,
    product: params.product, actor: 'intent-planner', subjectId: params.subjectId,
    confidence: 0.9, reversibility: 'reversible', blastRadius: 'single', at, ...over,
  });

  let steps: AdminAction[];
  switch (params.goal) {
    case 'retain_churn_risk':
      steps = [
        mk({ domain: 'billing', type: 'billing:issue_refund', intent: 'Goodwill refund', amountUsd: Math.min(params.amountUsd ?? 20, 20) }),
        mk({ domain: 'trust_safety', type: 'trust_safety:send_apology', intent: 'Personalized apology' }),
        mk({ domain: 'users_access', type: 'users_access:grant_priority_support', intent: 'Grant priority support for 30 days' }),
      ];
      break;
    case 'offboard_bad_actor':
      steps = [
        mk({ domain: 'trust_safety', type: 'trust_safety:terminate_account', intent: 'Terminate the account', reversibility: 'hard_to_reverse' }),
        mk({ domain: 'billing', type: 'billing:hold_payouts', intent: 'Freeze outstanding payouts' }),
        mk({ domain: 'users_access', type: 'users_access:revoke_sessions', intent: 'Revoke active sessions' }),
      ];
      break;
    default:
      steps = [mk({ domain: 'users_access', type: `custom:${params.goal}`, intent: params.goal })];
  }
  return { intentId: `intent_${params.goal}_${params.subjectId ?? 'global'}`, goal: params.goal, subjectId: params.subjectId, product: params.product, steps };
}

const TIER_ORDER: Record<AutonomyTier, number> = { human: 0, co_pilot: 1, auto: 2 };

export interface IntentVerdict {
  intentId: string;
  goal: string;
  /** the ONE enforced decision for the whole plan */
  decision: Decision;
  /** the least-autonomous tier across all steps (the plan is only as auto as its weakest step) */
  tier: AutonomyTier;
  stepVerdicts: { type: string; decision: Decision; tier: AutonomyTier }[];
  /** a single signed receipt over the whole intent */
  receipt: Receipt;
  summary: string;
}

/**
 * Govern a whole intent as one decision: DENY if any step denies; ESCALATE if any step
 * escalates; otherwise ALLOW. The plan's tier is the minimum across steps. One receipt.
 */
export function governIntent(params: {
  plan: IntentPlan;
  constitution?: Constitution | null;
  policies?: Record<AdminDomain, DomainAutonomyPolicy>;
  prevReceipt?: Receipt | null;
}): IntentVerdict {
  const constitution = params.constitution ?? fleetAdminConstitution();
  const policies = params.policies ?? DEFAULT_DOMAIN_POLICIES;
  const stepVerdicts: FleetVerdict[] = params.plan.steps.map((a) => governFleetAction({ action: a, constitution, policies }));

  const anyDeny = stepVerdicts.some((v) => v.decision === 'deny');
  const anyEscalate = stepVerdicts.some((v) => v.decision === 'escalate');
  const decision: Decision = anyDeny ? 'deny' : anyEscalate ? 'escalate' : 'allow';
  const tier: AutonomyTier = stepVerdicts.reduce<AutonomyTier>(
    (min, v) => (TIER_ORDER[v.tier] < TIER_ORDER[min] ? v.tier : min),
    'auto',
  );

  const agentAction: AgentAction = {
    product: params.plan.product,
    type: `intent:${params.plan.goal}`,
    actor: 'intent-planner',
    subjectId: params.plan.subjectId,
    metadata: { steps: params.plan.steps.map((s) => s.type) },
    at: params.plan.steps[0]?.at,
  };
  const receipt = buildReceipt({
    chain: `${params.plan.product}:intent:${params.plan.subjectId ?? 'global'}`,
    action: agentAction,
    verdict: { decision, ruleId: null, reason: `intent(${params.plan.goal}) over ${params.plan.steps.length} steps` },
    prev: params.prevReceipt ?? null,
    at: agentAction.at,
  });

  return {
    intentId: params.plan.intentId,
    goal: params.plan.goal,
    decision,
    tier,
    stepVerdicts: stepVerdicts.map((v, i) => ({ type: params.plan.steps[i]!.type, decision: v.decision, tier: v.tier })),
    receipt,
    summary: `intent '${params.plan.goal}' (${params.plan.steps.length} steps) → ${decision}/${tier} — bounded by the constitution over the whole plan`,
  };
}
