/**
 * Pareto/2080 wiring — personal finance / retirement / autonomous money agent.
 *
 * Adoption: wrap the Tier-A/B/C agent spine in `governAction` (Tier-C money moves
 * already escalate via §1a), publish the ~60 pure engines as capabilities so
 * Tomorrow's bank vertical and Smarter can instantiate them, and emit a
 * financial_profile passport claim that drives cross-product underwriting + routing.
 */
import type { Constitution } from '../governance/constitution.ts';
import { rule } from '../governance/constitution.ts';
import { defineCapability, type CapabilitySpec } from '../orchestratorClient/capabilityRegistry.ts';
import { claim, type Claim } from '../passport/passport.ts';

export const PARETO_LOCKED_DIMENSIONS = [
  'tier_c_requires_signed_token',
  'no_autonomous_money_above_cap',
  'explainability_contract', // every financial engine emits makeExplanation()
] as const;

export function paretoConstitution(version = 1, approvalCapUsd = 2_500): Constitution {
  return {
    product: 'pareto',
    version,
    alwaysEscalate: ['money_move', 'live_money_move', 'capital_draw'],
    rules: [
      // Tier-A outreach is allowed; Tier-B non-money commit allowed under cap; Tier-C escalates.
      rule.allowUnder('tier-a-outreach', 'send_outreach', Number.MAX_SAFE_INTEGER, 30),
      rule.allowUnder('tier-b-commit', 'non_money_commit', approvalCapUsd, 40),
      rule.notionalCap('approval-cap', approvalCapUsd, 110),
    ],
  };
}

/** Pareto's pure engines, published once, runnable by any product. */
export function paretoCapabilities(baseUrl = ''): CapabilitySpec[] {
  return [
    defineCapability({
      name: 'monte_carlo',
      owner: 'pareto',
      version: '1.0.0',
      description: 'Probabilistic retirement simulation (P10/P50/P90, success probability)',
      input: { balance: 'number', annualContribution: 'number', horizonYears: 'number' },
      output: { p10: 'number', p50: 'number', p90: 'number', successProb: 'number' },
      tags: ['finance', 'simulation', 'retirement'],
      endpoint: `${baseUrl}/api/personal/retirement/montecarlo`,
    }),
    defineCapability({
      name: 'allocator',
      owner: 'pareto',
      version: '1.0.0',
      description: 'Unified loop allocator (invest vs spend-now vs later) + luxury frontier',
      input: { cashUsd: 'number', goals: 'array' },
      output: { allocations: 'array' },
      tags: ['finance', 'optimization'],
      endpoint: `${baseUrl}/api/finance/allocator/proposal`,
    }),
    defineCapability({
      name: 'deduction_optimizer',
      owner: 'pareto',
      version: '1.0.0',
      description: 'Standard-vs-itemized, caps + reroute, above-the-line steering',
      input: { income: 'number', deductions: 'array' },
      output: { plan: 'object', savingsUsd: 'number' },
      tags: ['finance', 'tax'],
      endpoint: `${baseUrl}/api/finance/deductions`,
    }),
    defineCapability({
      name: 'geo_arbitrage',
      owner: 'pareto',
      version: '1.0.0',
      description: 'Retirement-city ranking (cost/safety/climate/tax/visa/health access)',
      input: { profile: 'object' },
      output: { ranked: 'array' },
      tags: ['finance', 'geo', 'lifestyle'],
      endpoint: `${baseUrl}/api/reos/compare`,
    }),
  ];
}

/**
 * Pareto issues a financial_profile claim (0..1 = net-worth/liquidity band) — the
 * key that lets Tomorrow pre-underwrite hedges/parametric products with no new data.
 */
export function paretoFinancialProfileClaim(
  band: number,
  detail?: { netWorthBand?: string; liquidityBand?: string },
  ttlDays = 90,
): Claim {
  return claim('financial_profile', 'pareto', Math.max(0, Math.min(1, band)), ttlDays, detail);
}

/** Pareto can also vouch accreditation once detected from holdings/income. */
export function paretoAccreditedClaim(ttlDays = 365): Claim {
  return claim('accredited', 'pareto', 1, ttlDays);
}
