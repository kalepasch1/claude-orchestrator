/**
 * Galop wiring — horse-racing social betting.
 *
 * Adoption: on KYC/geo pass, mint a passport with kyc_verified + geo_allowed +
 * sanctions_clear claims (TTL = re-verify cadence). That passport is what makes a
 * Galop user one click into Pareto/Tomorrow. The server-authoritative settlement
 * pattern is published as a reusable "provably fair outcome" capability.
 */
import type { Constitution } from '../governance/constitution.ts';
import { rule } from '../governance/constitution.ts';
import { defineCapability, type CapabilitySpec } from '../orchestratorClient/capabilityRegistry.ts';
import { claim, type Claim } from '../passport/passport.ts';

export const GALOP_LOCKED_DIMENSIONS = [
  'server_authoritative_settlement', // winner unreadable pre-pick
  'kyc_geo_gated_real_money',
  'no_consumer_odds_data_to_operators', // antitrust firewall
] as const;

export function galopConstitution(version = 1): Constitution {
  return {
    product: 'galop',
    version,
    alwaysEscalate: ['cash_out', 'operator_payout', 'commingle_pool'],
    rules: [
      rule.denyActionType('no-pre-lock-reveal', 'reveal_winner_pre_lock'),
      rule.allowUnder('submit-pick', 'submit_pick', Number.MAX_SAFE_INTEGER, 30),
      rule.allowUnder('claim-daily', 'claim_daily', 1_000, 40),
    ],
  };
}

export function galopCapabilities(baseUrl = ''): CapabilitySpec[] {
  return [
    defineCapability({
      name: 'kyc_geo_gate',
      owner: 'galop',
      version: '1.0.0',
      description: 'KYC + geolocation + sanctions gate via the provider seam (Jumio/Geocomply)',
      input: { userId: 'string', region: 'string' },
      output: { kyc: 'boolean', geoAllowed: 'boolean', sanctionsClear: 'boolean' },
      tags: ['compliance', 'kyc', 'geo'],
      endpoint: `${baseUrl}/api/compliance/gate`,
    }),
    defineCapability({
      name: 'provably_fair_settlement',
      owner: 'galop',
      version: '1.0.0',
      description: 'Server-authoritative outcome settlement (result unreadable pre-commit) — reusable for any payout/loot/odds',
      input: { eventId: 'string', officialResult: 'object' },
      output: { settlements: 'array', proof: 'object' },
      tags: ['settlement', 'integrity', 'provably-fair'],
      endpoint: `${baseUrl}/api/rf/resolve`,
    }),
  ];
}

/** The big one: KYC/geo pass → a portable passport bundle reused across the portfolio. */
export function galopKycClaims(
  opts: { geoRegion?: string; sanctionsClear?: boolean } = {},
  ttlDays = 180,
): Claim[] {
  const out: Claim[] = [claim('kyc_verified', 'galop', 1, ttlDays)];
  if (opts.geoRegion) out.push(claim('geo_allowed', 'galop', 1, ttlDays, { region: opts.geoRegion }));
  if (opts.sanctionsClear) out.push(claim('sanctions_clear', 'galop', 1, ttlDays));
  return out;
}
