/**
 * Tomorrow wiring — OTC derivatives / risk fabric / war room / risk studio.
 *
 * Tomorrow already has a P1 Constitution + C1 Ed25519 proof layer. Adoption here
 * means: delegate `evaluateConstitution` to the kernel (so receipts are
 * portfolio-readable), publish its pricing/risk/war-room engines as capabilities,
 * and emit credit/ECP passport claims other products consume.
 *
 * Locked dimensions = Tomorrow's non-negotiables that NO compiled rule may loosen:
 * ECP gate, swap-only allowlist, bilateral-only (no DCO/CCP), operator-disinterested.
 */
import type { Constitution } from '../governance/constitution.ts';
import { rule } from '../governance/constitution.ts';
import { defineCapability, type CapabilitySpec } from '../orchestratorClient/capabilityRegistry.ts';
import { claim, type Claim } from '../passport/passport.ts';

export const TOMORROW_LOCKED_DIMENSIONS = [
  'ecp_gate',
  'swap_only_mode',
  'bilateral_only_no_dco',
  'operator_disinterested',
  'no_price_formation',
] as const;

/** Starter constitution; the live one is compiled from Tomorrow's ratified NL policy. */
export function tomorrowConstitution(version = 1): Constitution {
  return {
    product: 'tomorrow',
    version,
    // money movement + novation always escalate (§1a); plus Tomorrow's settlement go-live
    alwaysEscalate: ['money_move', 'live_money_move', 'capital_draw', 'novate', 'settlement_instruction'],
    rules: [
      rule.denyActionType('no-ccp-novation', 'novate_to_ccp'),
      rule.denyActionType('no-mutualized-pool', 'create_guarantee_fund'),
      rule.notionalCap('fabric-run-cap', 250_000_000, 120),
      rule.allowUnder('ioi-publish', 'publish_ioi', 250_000_000, 40),
    ],
  };
}

/** Capabilities Tomorrow publishes for the rest of the portfolio to instantiate. */
export function tomorrowCapabilities(baseUrl = ''): CapabilitySpec[] {
  return [
    defineCapability({
      name: 'price_swap',
      owner: 'tomorrow',
      version: '1.0.0',
      description: 'Analytic swap/option pricer (IRS/CDS/TRS/cap/floor/probability option)',
      input: { productType: 'string', notional: 'number', tenorYears: 'number' },
      output: { pv: 'number', dv01: 'number' },
      tags: ['pricing', 'derivatives', 'risk'],
      endpoint: `${baseUrl}/api/otc/price`,
    }),
    defineCapability({
      name: 'parametric_displacement',
      owner: 'tomorrow',
      version: '1.0.0',
      description: 'Risk Studio: turn any risk into a parametric bilateral swap + premium-vs-synthetic verdict',
      input: { riskType: 'string', exposureUsd: 'number', region: 'string' },
      output: { structure: 'object', savingsUsd: 'number', replaceable: 'string' },
      tags: ['insurance', 'parametric', 'risk-studio'],
      endpoint: `${baseUrl}/api/risk/studio/displace`,
    }),
    defineCapability({
      name: 'war_room_pipeline',
      owner: 'tomorrow',
      version: '1.0.0',
      description: 'Email/clause/obligation/negotiation ingestion + redline analysis pipeline',
      input: { roomId: 'string', artifact: 'object' },
      output: { clauseEdits: 'array', digest: 'object' },
      tags: ['legal', 'negotiation', 'war-room'],
      endpoint: `${baseUrl}/api/firm/rooms/war-room/ingest`,
    }),
    defineCapability({
      name: 'fabric_run',
      owner: 'tomorrow',
      version: '1.0.0',
      description: 'PTRRS multilateral risk-optimization run (neutrality-proved, consent-gated)',
      input: { participants: 'array', positions: 'array' },
      output: { legs: 'array', neutralityProof: 'object' },
      tags: ['risk', 'netting', 'ptrrs'],
      endpoint: `${baseUrl}/api/otc/fabric/run`,
    }),
  ];
}

/** Tomorrow issues a credit-quality claim (composite 0..1) for the shared passport. */
export function tomorrowCreditClaim(compositeQuality: number, ttlDays = 90): Claim {
  return claim('credit_quality', 'tomorrow', Math.max(0, Math.min(1, compositeQuality)), ttlDays);
}

/** Tomorrow issues an ECP-eligibility claim once intake passes the ECP gate. */
export function tomorrowEcpClaim(ttlDays = 730): Claim {
  return claim('ecp_eligible', 'tomorrow', 1, ttlDays);
}
