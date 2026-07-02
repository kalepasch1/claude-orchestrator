/**
 * Adversarial co-evolution — a learning adversary searches for the highest-harm action the
 * current dial will AUTO-run, while a defender tightens the policy to close each gap it
 * finds. Iterating to a fixed point yields the provably-largest SAFE autonomy envelope,
 * re-found automatically whenever the world changes. Pure + zero-dep.
 */
import { fleetAdminConstitution } from './constitution.ts';
import { DEFAULT_DOMAIN_POLICIES, type DomainAutonomyPolicy } from './autonomy.ts';
import { governFleetAction } from './govern.ts';
import type { AdminAction, AdminDomain, Reversibility, BlastRadius } from './types.ts';
import { ALL_ADMIN_DOMAINS } from './types.ts';
import { fleetHarmScore as harm } from './shared.ts';

/** Adversary: the worst (highest-harm) action in a domain that still auto-runs, if any. */
function worstAutoInDomain(domain: AdminDomain, policies: Record<AdminDomain, DomainAutonomyPolicy>): { action: AdminAction; harm: number } | null {
  const constitution = fleetAdminConstitution();
  const revs: Reversibility[] = ['reversible', 'hard_to_reverse', 'irreversible'];
  const blasts: BlastRadius[] = ['single', 'small', 'large', 'fleet'];
  const amounts = [0, (policies[domain].autoMaxUsd ?? 100)]; // $0 tests non-money ceilings
  let worst: { action: AdminAction; harm: number } | null = null;
  for (const reversibility of revs)
    for (const blastRadius of blasts)
      for (const amountUsd of amounts) {
        const action: AdminAction = {
          id: `adv_${domain}_${reversibility}_${blastRadius}_${amountUsd}`,
          product: 'orchestrator', domain, type: `${domain}:__adv_probe`, actor: 'adversary',
          confidence: 0.99, reversibility, blastRadius, intent: 'adversarial probe', amountUsd,
          at: '2026-07-01T00:00:00.000Z',
        };
        const v = governFleetAction({ action, constitution, policies });
        if (v.decision === 'allow' && v.tier === 'auto') {
          const h = harm(action);
          if (!worst || h > worst.harm) worst = { action, harm: h };
        }
      }
  return worst;
}

/** Defender: tighten a domain policy to remove its current worst-auto gap. */
function tighten(policy: DomainAutonomyPolicy, worst: AdminAction): { policy: DomainAutonomyPolicy; change: string } {
  const p = structuredClone(policy);
  if (worst.reversibility !== 'reversible' && p.autoReversibility.length > 1) {
    p.autoReversibility = ['reversible'];
    return { policy: p, change: `${p.domain}: auto now requires reversible` };
  }
  if (worst.blastRadius === 'fleet' || worst.blastRadius === 'large') {
    p.autoMaxBlast = 'small';
    return { policy: p, change: `${p.domain}: auto blast capped at small` };
  }
  if ((worst.amountUsd ?? 0) > 0) {
    p.autoMaxUsd = Math.max(0, Math.floor((worst.amountUsd ?? 0) / 2));
    return { policy: p, change: `${p.domain}: auto money cap lowered to $${p.autoMaxUsd}` };
  }
  p.ceiling = 'co_pilot';
  return { policy: p, change: `${p.domain}: ceiling lowered to co_pilot` };
}

export interface CoevolutionResult {
  rounds: number;
  tightenings: string[];
  /** the highest harm that STILL auto-runs after co-evolution settles (the safe envelope) */
  residualHarm: number;
  hardenedPolicies: Record<AdminDomain, DomainAutonomyPolicy>;
}

/** Run adversary↔defender to a fixed point (or maxRounds). Returns the hardened envelope. */
export function coEvolve(
  policies: Record<AdminDomain, DomainAutonomyPolicy> = DEFAULT_DOMAIN_POLICIES,
  harmThreshold = 0.3,
  maxRounds = 12,
): CoevolutionResult {
  let current = structuredClone(policies);
  const tightenings: string[] = [];
  let rounds = 0;
  for (; rounds < maxRounds; rounds++) {
    let tightenedThisRound = false;
    for (const domain of ALL_ADMIN_DOMAINS) {
      const worst = worstAutoInDomain(domain, current);
      if (worst && worst.harm >= harmThreshold) {
        const { policy, change } = tighten(current[domain], worst.action);
        current[domain] = policy;
        tightenings.push(change);
        tightenedThisRound = true;
      }
    }
    if (!tightenedThisRound) break;
  }
  // Residual: worst harm that still auto-runs anywhere after hardening.
  let residualHarm = 0;
  for (const domain of ALL_ADMIN_DOMAINS) {
    const worst = worstAutoInDomain(domain, current);
    if (worst) residualHarm = Math.max(residualHarm, worst.harm);
  }
  return { rounds: rounds + 1, tightenings, residualHarm, hardenedPolicies: current };
}
