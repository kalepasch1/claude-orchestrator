/**
 * Fleet Admin — canonical cross-product admin vocabulary.
 *
 * Promoted from Apparently's `admin-board.ts` (severity ladder + categories) into
 * the shared kernel so EVERY product (tomorrow, smarter, apparently, pareto,
 * galop, hisanta, Sustainable Barks, darwn, + any new app) emits and accepts the
 * SAME admin object. Adding a new app becomes: implement one adapter against this
 * contract — not a bespoke integration.
 *
 * An `AdminEvent` is "something happened that may need attention." An `AdminAction`
 * is "the remediation an agent proposes (or takes)." Both are governed by the
 * kernel constitution + the four-domain autonomy matrix and leave a signed receipt.
 */
import type { ProductId } from '../types.ts';

/** The four highest-stakes runtime admin domains, each with its own autonomy ceiling. */
export type AdminDomain =
  | 'users_access' // account creation, roles/permissions, suspensions, bans, KYC/identity
  | 'billing' // refunds, chargebacks, failed payments, plan changes, dunning
  | 'trust_safety' // content flags, abuse/fraud, moderation, appeals, terminations
  | 'infra'; // outages, error spikes, security alerts, data/DB remediation

export const ALL_ADMIN_DOMAINS: AdminDomain[] = [
  'users_access',
  'billing',
  'trust_safety',
  'infra',
];

/**
 * Severity ladder (kept numeric so it sorts + thresholds cleanly). Mirrors
 * Apparently's board, but as a const-object rather than a TS `enum` so it runs
 * under the kernel's `--experimental-strip-types` test runner (no enum support).
 */
export const AdminSeverity = {
  INFO: 0,
  NOTICE: 10,
  WARNING: 30,
  URGENT: 60,
  BLOCKING: 100,
} as const;
export type AdminSeverity = (typeof AdminSeverity)[keyof typeof AdminSeverity];

/**
 * Canonical event categories across the fleet. A superset of Apparently's board
 * categories, grouped so every category maps to exactly one domain (see
 * `DOMAIN_OF_CATEGORY`). Products may pass a `rawCategory` string too.
 */
export type AdminEventCategory =
  // users_access
  | 'access_request'
  | 'role_change'
  | 'account_suspension'
  | 'kyc_identity'
  // billing
  | 'refund_request'
  | 'chargeback'
  | 'failed_payment'
  | 'plan_change'
  | 'dunning'
  // trust_safety
  | 'content_flag'
  | 'abuse_report'
  | 'fraud_signal'
  | 'moderation_appeal'
  // infra
  | 'outage'
  | 'error_spike'
  | 'security_alert'
  | 'data_remediation'
  | 'portal_url_broken'
  // cross-cutting
  | 'compliance_alert'
  | 'system_error'
  | 'other';

/** Which domain owns each category. Fail-closed: unknown category => the safest domain. */
export const DOMAIN_OF_CATEGORY: Record<AdminEventCategory, AdminDomain> = {
  access_request: 'users_access',
  role_change: 'users_access',
  account_suspension: 'users_access',
  kyc_identity: 'users_access',
  refund_request: 'billing',
  chargeback: 'billing',
  failed_payment: 'billing',
  plan_change: 'billing',
  dunning: 'billing',
  content_flag: 'trust_safety',
  abuse_report: 'trust_safety',
  fraud_signal: 'trust_safety',
  moderation_appeal: 'trust_safety',
  outage: 'infra',
  error_spike: 'infra',
  security_alert: 'infra',
  data_remediation: 'infra',
  portal_url_broken: 'infra',
  compliance_alert: 'trust_safety',
  system_error: 'infra',
  other: 'infra',
};

/** How hard the action is to walk back — a primary input to the autonomy dial. */
export type Reversibility = 'reversible' | 'hard_to_reverse' | 'irreversible';

/** How many users/dollars/systems the action touches. */
export type BlastRadius = 'single' | 'small' | 'large' | 'fleet';

export const BLAST_ORDER: Record<BlastRadius, number> = {
  single: 0,
  small: 1,
  large: 2,
  fleet: 3,
};

/** Autonomy tiers. `auto` runs unattended; `co_pilot` drafts for approval; `human` requires a decision. */
export type AutonomyTier = 'auto' | 'co_pilot' | 'human';

/** A normalized "something happened" record every app emits. */
export interface AdminEvent {
  /** stable id (content-addressed by the emitter or the kernel) */
  id: string;
  product: ProductId;
  domain: AdminDomain;
  category: AdminEventCategory;
  /** the emitter's own category string, retained for the audit trail */
  rawCategory?: string;
  severity: AdminSeverity;
  title: string;
  summary: string;
  /** the subject the event concerns (user id, account id, deploy id, invoice id, ...) */
  subjectId?: string;
  /** money magnitude in USD if relevant (drives billing thresholds) */
  amountUsd?: number;
  /** free-form structured payload used by remediation agents + rule predicates */
  details?: Record<string, unknown>;
  /** deep link back into the originating app so a human can inspect in context */
  sourceUrl?: string;
  /** ISO timestamp */
  at: string;
}

/** A remediation an agent proposes (or, when autonomy=auto, takes). */
export interface AdminAction {
  id: string;
  product: ProductId;
  domain: AdminDomain;
  /** colon/dot-namespaced verb, e.g. 'billing:issue_refund', 'users_access:suspend_account' */
  type: string;
  /** the agent/swarm proposing the action */
  actor: string;
  /** the event this action responds to */
  eventId?: string;
  subjectId?: string;
  amountUsd?: number;
  /** the agent's self-assessed confidence in this remediation, 0..1 */
  confidence: number;
  reversibility: Reversibility;
  blastRadius: BlastRadius;
  /** human-readable description of exactly what will happen */
  intent: string;
  /** structured params the app's admin API needs to execute the action */
  params?: Record<string, unknown>;
  /** the counterfactual: what happens if this is NOT done */
  ifNotDone?: string;
  at: string;
}

/** Resolve the domain for a category, fail-closed to infra (highest-caution executor path). */
export function domainOfCategory(category: AdminEventCategory | string): AdminDomain {
  return (DOMAIN_OF_CATEGORY as Record<string, AdminDomain>)[category] ?? 'infra';
}
