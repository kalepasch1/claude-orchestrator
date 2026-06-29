/**
 * Policy Constitution — the single, declarative, versioned enforcement boundary
 * every bot in every product provably obeys. Generalized from Tomorrow's P1.
 *
 * Design invariants (do not weaken):
 *   - FAIL CLOSED. Any error, missing constitution, or unrecognized high-risk
 *     action => 'escalate' (never 'allow').
 *   - LOCKED DIMENSIONS can never be loosened by a compiled rule. Each product
 *     contributes its own non-negotiables (e.g. tomorrow: ECP gate; hisanta:
 *     no-real-money-to-child; galop: server-authoritative settlement).
 *   - §1a-style override: a configurable set of action types ALWAYS escalates
 *     regardless of rules (money movement, novation, irreversible/child-facing).
 */
import type { AgentAction, Decision, ProductId } from '../types.ts';

export interface ConstitutionRule {
  id: string;
  /** human-authored intent, retained for the audit trail */
  text: string;
  /** action types this rule applies to ('*' = all) */
  appliesTo: string[];
  /** a pure predicate; true => the rule's effect fires */
  when: (action: AgentAction) => boolean;
  effect: Decision;
  /** higher wins on conflict */
  priority: number;
}

export interface Constitution {
  product: ProductId;
  version: number;
  rules: ConstitutionRule[];
  /** action types that ALWAYS escalate (the §1a hard override) */
  alwaysEscalate: string[];
  /** if true, every evaluation short-circuits to deny (master kill switch) */
  killSwitch?: boolean;
}

export interface ConstitutionDecision {
  decision: Decision;
  ruleId: string | null;
  reason: string;
}

/** Default hard-override set. Products extend, never shrink, this. */
export const DEFAULT_ALWAYS_ESCALATE = [
  'money_move',
  'live_money_move',
  'capital_draw',
  'novate',
];

/**
 * Evaluate an action against a constitution. Pure and fail-closed.
 * Resolution order: killSwitch > §1a override > highest-priority matching
 * deny > highest-priority matching escalate > highest-priority matching allow >
 * default escalate.
 */
export function evaluateConstitution(
  action: AgentAction,
  constitution: Constitution | null | undefined,
): ConstitutionDecision {
  try {
    if (!constitution) {
      return { decision: 'escalate', ruleId: null, reason: 'no_constitution' };
    }
    if (constitution.killSwitch) {
      return { decision: 'deny', ruleId: null, reason: 'kill_switch' };
    }
    const overrides = constitution.alwaysEscalate.length
      ? constitution.alwaysEscalate
      : DEFAULT_ALWAYS_ESCALATE;
    if (overrides.includes(action.type)) {
      return { decision: 'escalate', ruleId: null, reason: 'always_escalate_override' };
    }

    const matches = constitution.rules
      .filter((r) => (r.appliesTo.includes('*') || r.appliesTo.includes(action.type)))
      .filter((r) => safePredicate(r, action))
      .sort((a, b) => b.priority - a.priority);

    const deny = matches.find((r) => r.effect === 'deny');
    if (deny) return { decision: 'deny', ruleId: deny.id, reason: deny.text };

    const escalate = matches.find((r) => r.effect === 'escalate');
    if (escalate) return { decision: 'escalate', ruleId: escalate.id, reason: escalate.text };

    const allow = matches.find((r) => r.effect === 'allow');
    if (allow) return { decision: 'allow', ruleId: allow.id, reason: allow.text };

    // Nothing matched. Allow only low-risk, explicitly non-money actions; else escalate.
    if (action.amountUsd && action.amountUsd > 0) {
      return { decision: 'escalate', ruleId: null, reason: 'unmatched_money_action' };
    }
    return { decision: 'allow', ruleId: null, reason: 'no_rule_matched_nonmoney' };
  } catch (err) {
    return { decision: 'escalate', ruleId: null, reason: `evaluation_error:${String(err)}` };
  }
}

function safePredicate(rule: ConstitutionRule, action: AgentAction): boolean {
  try {
    return rule.when(action);
  } catch {
    // A throwing predicate must never silently pass an action.
    return false;
  }
}

/** Convenience builders for the most common rule shapes (NL compiler lands later). */
export const rule = {
  notionalCap(id: string, maxUsd: number, priority = 100): ConstitutionRule {
    return {
      id,
      text: `Escalate any action above $${maxUsd.toLocaleString()}`,
      appliesTo: ['*'],
      when: (a) => (a.amountUsd ?? 0) > maxUsd,
      effect: 'escalate',
      priority,
    };
  },
  denyActionType(id: string, type: string, priority = 200): ConstitutionRule {
    return {
      id,
      text: `Deny action type ${type}`,
      appliesTo: [type],
      when: () => true,
      effect: 'deny',
      priority,
    };
  },
  allowUnder(id: string, type: string, maxUsd: number, priority = 50): ConstitutionRule {
    return {
      id,
      text: `Allow ${type} under $${maxUsd.toLocaleString()}`,
      appliesTo: [type],
      when: (a) => (a.amountUsd ?? 0) <= maxUsd,
      effect: 'allow',
      priority,
    };
  },
};
