/**
 * The Fleet Admin Constitution — the portfolio-wide law for runtime admin actions,
 * layered on top of each product's own constitution. This is the single source of
 * the non-negotiables that apply to admin ops REGARDLESS of which app raised them.
 *
 * It reuses the exact `Constitution` shape from governance/constitution.ts, so the
 * same `evaluateConstitution` / `governAction` machinery (and the same signed
 * receipts) apply. `governFleetAction` runs this alongside the autonomy matrix.
 */
import type { Constitution, ConstitutionRule } from '../governance/constitution.ts';
import { rule } from '../governance/constitution.ts';

/** Non-negotiables that no compiled rule and no confidence score can loosen. */
export const FLEET_ADMIN_LOCKED_DIMENSIONS = [
  'money_movement_requires_human', // no fund movement / payout runs unattended
  'identity_actions_require_human', // account deletion, KYC rejection, admin-role grant
  'prod_data_mutation_requires_human', // no unattended writes to production data/schema
  'security_incident_requires_human', // security response is never auto
  'every_action_leaves_a_signed_receipt',
  'single_control_plane_default_deny_rls',
] as const;

/**
 * The always-escalate hard override for admin ops. These verbs ALWAYS route to a
 * human no matter what any rule says (mirrors the constitution's §1a override).
 */
export const FLEET_ADMIN_ALWAYS_ESCALATE = [
  // money
  'billing:issue_refund_over_cap',
  'billing:dispute_chargeback',
  'billing:issue_exception_credit',
  'billing:move_funds',
  'money_move',
  // identity / access
  'users_access:delete_account',
  'users_access:reject_kyc',
  'users_access:grant_admin_role',
  // trust & safety
  'trust_safety:terminate_account',
  'trust_safety:report_to_authority',
  // infra
  'infra:mutate_production_data',
  'infra:apply_schema_migration',
  'infra:rotate_secret',
  'infra:security_incident_response',
];

/**
 * Build the fleet admin constitution. Product constitutions still apply first via
 * their own `governAction`; this is the shared admin overlay the control plane runs.
 */
export function fleetAdminConstitution(version = 1): Constitution {
  const rules: ConstitutionRule[] = [
    // Deny outright anything that tries to bypass the audit trail.
    rule.denyActionType('no-unlogged-action', 'admin:bypass_receipt'),
    // Small reversible refunds are allowed by law up to a cap; above the cap no
    // allow matches, so the base constitution escalates ('unmatched_money_action').
    // The autonomy dial still applies its own (lower) per-domain money ceiling.
    rule.allowUnder('allow-refund-small', 'billing:issue_refund', 50, 40),
    // Explicit safe allows for the routine, reversible 95%.
    rule.allowUnder('allow-password-reset', 'users_access:reset_password', Number.MAX_SAFE_INTEGER, 40),
    rule.allowUnder('allow-role-grant-in-policy', 'users_access:grant_role_in_policy', Number.MAX_SAFE_INTEGER, 40),
    rule.allowUnder('allow-retry-payment', 'billing:retry_payment', Number.MAX_SAFE_INTEGER, 40),
    rule.allowUnder('allow-dunning', 'billing:send_dunning', Number.MAX_SAFE_INTEGER, 40),
    rule.allowUnder('allow-rate-limit', 'trust_safety:rate_limit', Number.MAX_SAFE_INTEGER, 40),
    rule.allowUnder('allow-remove-spam', 'trust_safety:remove_spam', Number.MAX_SAFE_INTEGER, 40),
    rule.allowUnder('allow-rollback', 'infra:rollback_deploy', Number.MAX_SAFE_INTEGER, 40),
    rule.allowUnder('allow-scale', 'infra:scale_service', Number.MAX_SAFE_INTEGER, 40),
    rule.allowUnder('allow-runbook', 'infra:apply_runbook', Number.MAX_SAFE_INTEGER, 40),
  ];

  return {
    product: 'orchestrator',
    version,
    alwaysEscalate: FLEET_ADMIN_ALWAYS_ESCALATE,
    rules,
  };
}
