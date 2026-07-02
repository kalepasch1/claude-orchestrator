/**
 * Constitution verifier — the law is load-bearing across many orgs, so prove its invariants
 * hold rather than just test them. This model-checks a bounded action space against the composed
 * gate (constitution + autonomy) and asserts the locked dimensions can NEVER be violated: money
 * movement never auto-allows, identity/termination actions never auto-run, prod-data mutation +
 * secret rotation never auto. An amendment that would breach one is caught here, provably, before
 * it ships. Pure + zero-dep.
 */
import type { Constitution } from '../governance/constitution.ts';
import { fleetAdminConstitution, FLEET_ADMIN_ALWAYS_ESCALATE } from './constitution.ts';
import { DEFAULT_DOMAIN_POLICIES, type DomainAutonomyPolicy } from './autonomy.ts';
import { governFleetAction } from './govern.ts';
import type { AdminAction, AdminDomain, Reversibility, BlastRadius } from './types.ts';

export interface InvariantViolation {
  invariant: string;
  verb: string;
  domain: AdminDomain;
  decision: string;
  tier: string;
  probe: { amountUsd: number; reversibility: Reversibility; blastRadius: BlastRadius };
}

/** Verbs that must never AUTO-run (identity + destructive infra), by domain. */
const NEVER_AUTO: { domain: AdminDomain; verb: string }[] = [
  { domain: 'users_access', verb: 'users_access:delete_account' },
  { domain: 'users_access', verb: 'users_access:reject_kyc' },
  { domain: 'users_access', verb: 'users_access:grant_admin_role' },
  { domain: 'trust_safety', verb: 'trust_safety:terminate_account' },
  { domain: 'infra', verb: 'infra:mutate_production_data' },
  { domain: 'infra', verb: 'infra:apply_schema_migration' },
  { domain: 'infra', verb: 'infra:rotate_secret' },
];

const REVS: Reversibility[] = ['reversible', 'hard_to_reverse', 'irreversible'];
const BLASTS: BlastRadius[] = ['single', 'small', 'large', 'fleet'];
const AMOUNTS = [0, 1, 100, 100000];

function probe(domain: AdminDomain, verb: string, amountUsd: number, reversibility: Reversibility, blastRadius: BlastRadius): AdminAction {
  return { id: `verify_${verb}_${amountUsd}_${reversibility}_${blastRadius}`, product: 'orchestrator', domain, type: verb, actor: 'verifier', confidence: 1, reversibility, blastRadius, intent: 'invariant probe', amountUsd, at: '2026-07-01T00:00:00.000Z' };
}

export interface VerificationResult {
  ok: boolean;
  checked: number;
  violations: InvariantViolation[];
}

/**
 * Exhaustively probe the invariant surface. `confidence` is held at 1 (the most permissive case)
 * so if a violation exists at all, it surfaces. Returns every breach found.
 */
export function verifyConstitutionInvariants(
  constitution: Constitution = fleetAdminConstitution(),
  policies: Record<AdminDomain, DomainAutonomyPolicy> = DEFAULT_DOMAIN_POLICIES,
): VerificationResult {
  const violations: InvariantViolation[] = [];
  let checked = 0;

  const run = (domain: AdminDomain, verb: string) => {
    for (const amt of AMOUNTS) for (const rev of REVS) for (const blast of BLASTS) {
      checked++;
      const v = governFleetAction({ action: probe(domain, verb, amt, rev, blast), constitution, policies });
      const auto = v.decision === 'allow' && v.tier === 'auto';
      const p = { amountUsd: amt, reversibility: rev, blastRadius: blast };
      if (FLEET_ADMIN_ALWAYS_ESCALATE.includes(verb) && v.decision === 'allow')
        violations.push({ invariant: 'always_escalate_never_allows', verb, domain, decision: v.decision, tier: v.tier, probe: p });
      if (NEVER_AUTO.some((n) => n.verb === verb) && auto)
        violations.push({ invariant: 'locked_verb_never_auto', verb, domain, decision: v.decision, tier: v.tier, probe: p });
    }
  };

  for (const verb of FLEET_ADMIN_ALWAYS_ESCALATE) run(inferDomain(verb), verb);
  for (const n of NEVER_AUTO) run(n.domain, n.verb);

  return { ok: violations.length === 0, checked, violations };
}

function inferDomain(verb: string): AdminDomain {
  const d = verb.split(':')[0];
  return (['users_access', 'billing', 'trust_safety', 'infra'] as AdminDomain[]).includes(d as AdminDomain) ? (d as AdminDomain) : 'billing';
}
