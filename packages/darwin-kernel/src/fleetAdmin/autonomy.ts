/**
 * The four-domain autonomy matrix — the operational core of the 5/95 principle.
 *
 * Autonomy is NOT a fixed ratio. It is a dial computed per action from four
 * attributes — domain, confidence, reversibility, blast radius (+ money) — clamped
 * by a per-domain ceiling. This is what lets the fleet auto-resolve the routine 95%
 * while routing only genuinely-hard decisions to the single human queue.
 *
 * Design invariants (do not weaken):
 *   - FAIL CLOSED. Unknown domain / missing inputs / any error => 'human'.
 *   - Each domain has a hard CEILING the dial can never exceed, regardless of how
 *     confident an agent is. Money movement, identity, termination, and prod data
 *     mutation are gated hardest — mirroring Smarter's `canAutoSubmit()` default.
 *   - The matrix only ever RESTRICTS. It cannot turn a constitution 'deny'/'escalate'
 *     into an 'allow' — composition happens in `governFleetAction`.
 */
import type {
  AdminAction,
  AdminDomain,
  AutonomyTier,
  BlastRadius,
  Reversibility,
} from './types.ts';
import { BLAST_ORDER } from './types.ts';
import { TIER_ORDER } from './shared.ts';

export interface DomainAutonomyPolicy {
  domain: AdminDomain;
  /** the highest tier this domain may EVER reach (hard clamp) */
  ceiling: AutonomyTier;
  /** minimum agent confidence to run unattended */
  autoConfidenceMin: number;
  /** minimum confidence to draft-for-approval; below this => human from scratch */
  coPilotConfidenceMin: number;
  /** reversibility classes eligible for `auto` (everything else caps at co_pilot) */
  autoReversibility: Reversibility[];
  /** the largest blast radius eligible for `auto` */
  autoMaxBlast: BlastRadius;
  /** money ceiling for `auto` (undefined => money is not a factor for this domain) */
  autoMaxUsd?: number;
  /** action verbs (or `event.category`) that ALWAYS require a human, full stop */
  alwaysHuman: string[];
}

/**
 * Portfolio defaults. Tuned to the four domains' real blast radii. These are the
 * STARTING ceilings; the flywheel (see ledger.ts) proposes promotions from evidence,
 * but a human still confirms any ceiling change (that change is itself material).
 */
export const DEFAULT_DOMAIN_POLICIES: Record<AdminDomain, DomainAutonomyPolicy> = {
  // Reversible account ops can auto; identity + destructive account ops never do.
  users_access: {
    domain: 'users_access',
    ceiling: 'auto',
    autoConfidenceMin: 0.85,
    coPilotConfidenceMin: 0.5,
    autoReversibility: ['reversible'],
    autoMaxBlast: 'small',
    alwaysHuman: [
      'users_access:suspend_account',
      'users_access:ban_account',
      'users_access:delete_account',
      'users_access:reject_kyc',
      'users_access:grant_admin_role',
      'account_suspension',
      'kyc_identity',
    ],
  },
  // Small reversible refunds/retries auto; money above the cap or disputes go to a human.
  billing: {
    domain: 'billing',
    ceiling: 'auto',
    autoConfidenceMin: 0.9,
    coPilotConfidenceMin: 0.6,
    autoReversibility: ['reversible'],
    autoMaxBlast: 'small',
    autoMaxUsd: 50,
    alwaysHuman: [
      'billing:dispute_chargeback',
      'billing:issue_exception_credit',
      'billing:change_price',
      'chargeback',
    ],
  },
  // Obvious spam/rate-limit auto; termination, appeals, and legal-exposure to a human.
  trust_safety: {
    domain: 'trust_safety',
    ceiling: 'auto',
    autoConfidenceMin: 0.92,
    coPilotConfidenceMin: 0.6,
    autoReversibility: ['reversible'],
    autoMaxBlast: 'small',
    alwaysHuman: [
      'trust_safety:terminate_account',
      'trust_safety:resolve_appeal',
      'trust_safety:report_to_authority',
      'moderation_appeal',
    ],
  },
  // Rollbacks/scaling/runbook auto; data mutation, schema, and security incidents to a human.
  // Ceiling is co_pilot: infra defaults to proposing, never silently acting on prod.
  infra: {
    domain: 'infra',
    ceiling: 'co_pilot',
    autoConfidenceMin: 0.95,
    coPilotConfidenceMin: 0.5,
    autoReversibility: ['reversible'],
    autoMaxBlast: 'small',
    alwaysHuman: [
      'infra:mutate_production_data',
      'infra:apply_schema_migration',
      'infra:rotate_secret',
      'infra:security_incident_response',
      'data_remediation',
      'security_alert',
    ],
  },
};

export interface AutonomyDecision {
  tier: AutonomyTier;
  /** true unless tier === 'auto' */
  requiresHuman: boolean;
  /** the domain ceiling that applied */
  ceiling: AutonomyTier;
  /** ordered, human-readable reasons — shown on the approval card */
  reasons: string[];
}

function clampTier(tier: AutonomyTier, ceiling: AutonomyTier): AutonomyTier {
  return TIER_ORDER[tier] <= TIER_ORDER[ceiling] ? tier : ceiling;
}

/**
 * Compute the autonomy tier for a single admin action. Pure + fail-closed.
 * Returns the LEAST-autonomous tier consistent with every constraint.
 */
export function evaluateAutonomy(
  action: AdminAction,
  policies: Record<AdminDomain, DomainAutonomyPolicy> = DEFAULT_DOMAIN_POLICIES,
): AutonomyDecision {
  try {
    const policy = policies[action.domain];
    if (!policy) {
      return {
        tier: 'human',
        requiresHuman: true,
        ceiling: 'human',
        reasons: [`unknown_domain:${String(action.domain)} (fail-closed)`],
      };
    }

    const reasons: string[] = [];

    // 1. Hard always-human list (verb or category) — non-negotiable.
    if (policy.alwaysHuman.includes(action.type)) {
      return {
        tier: 'human',
        requiresHuman: true,
        ceiling: policy.ceiling,
        reasons: [`'${action.type}' is always-human for ${policy.domain}`],
      };
    }

    // 2. Confidence floor: below the co-pilot floor, a human starts from scratch.
    const conf = Number.isFinite(action.confidence) ? action.confidence : 0;
    if (conf < policy.coPilotConfidenceMin) {
      return {
        tier: 'human',
        requiresHuman: true,
        ceiling: policy.ceiling,
        reasons: [`confidence ${conf.toFixed(2)} < co-pilot floor ${policy.coPilotConfidenceMin}`],
      };
    }

    // 3. Start optimistic at the ceiling, then restrict on each failed auto-gate.
    let tier: AutonomyTier = 'auto';

    if (conf < policy.autoConfidenceMin) {
      tier = 'co_pilot';
      reasons.push(`confidence ${conf.toFixed(2)} < auto floor ${policy.autoConfidenceMin}`);
    }
    if (!policy.autoReversibility.includes(action.reversibility)) {
      tier = 'co_pilot';
      reasons.push(`reversibility '${action.reversibility}' not auto-eligible`);
    }
    if (BLAST_ORDER[action.blastRadius] > BLAST_ORDER[policy.autoMaxBlast]) {
      // Fleet-wide blast is severe enough to demand a human, not just co-pilot.
      tier = action.blastRadius === 'fleet' ? 'human' : 'co_pilot';
      reasons.push(`blast '${action.blastRadius}' > auto max '${policy.autoMaxBlast}'`);
    }
    if (
      policy.autoMaxUsd !== undefined &&
      (action.amountUsd ?? 0) > policy.autoMaxUsd
    ) {
      tier = 'human';
      reasons.push(`amount $${action.amountUsd} > auto cap $${policy.autoMaxUsd}`);
    }

    // 4. Clamp to the domain ceiling (e.g. infra can never be 'auto').
    const clamped = clampTier(tier, policy.ceiling);
    if (clamped !== tier) reasons.push(`clamped to ${policy.domain} ceiling '${policy.ceiling}'`);
    if (reasons.length === 0) reasons.push('all auto-gates passed');

    return {
      tier: clamped,
      requiresHuman: clamped !== 'auto',
      ceiling: policy.ceiling,
      reasons,
    };
  } catch (err) {
    return {
      tier: 'human',
      requiresHuman: true,
      ceiling: 'human',
      reasons: [`autonomy_error:${String(err)} (fail-closed)`],
    };
  }
}
