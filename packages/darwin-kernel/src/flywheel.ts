/**
 * The cross-product flywheel (opportunities #3 + #5 + #7 + #12).
 *
 * Given a subject's verified passports from one or more products, plus the consent
 * grants they've made, this composes:
 *   - `underwritingPrefill`: the data Tomorrow's Risk Studio / hedging needs,
 *     assembled from existing claims so a new product underwrites in milliseconds
 *     with ZERO new data collection (this is what makes "Risk Studio under every
 *     audience" actually shippable).
 *   - `crossSell`: which product to route the subject to next, consent-aware.
 *
 * Pure. Consent is enforced: a claim only contributes if the subject consented to
 * the source→target share for that scope.
 */
import type { ProductId } from './types.ts';
import { verifyPassport, type Passport, type Claim, type ClaimKind } from './passport/passport.ts';
import {
  consentAllows,
  suggestRoutes,
  type ConsentGrant,
  type RouteSuggestion,
  type RouteRule,
} from './identity/graph.ts';

export interface FlywheelInput {
  subject: string;
  /** the product asking (the target of any cross-product read) */
  asking: ProductId;
  /** all passports held about this subject (each issued by some product) */
  passports: Passport[];
  /** consent grants the subject has made */
  consent: ConsentGrant[];
  /** products the subject is already active on (to skip in cross-sell) */
  alreadyOn: ProductId[];
  asOf?: Date;
  routeRules?: RouteRule[];
}

export interface UnderwritingPrefill {
  /** consented, live claims usable by the asking product */
  usableClaims: { kind: ClaimKind; value: number; issuer: ProductId }[];
  kycVerified: boolean;
  ecpEligible: boolean;
  sanctionsClear: boolean;
  geoAllowed: boolean;
  /** 0..1 composite financial strength if a financial_profile/credit claim is usable */
  financialStrength: number | null;
  /** true when enough is present to skip a fresh KYC+financial intake */
  canInstantUnderwrite: boolean;
  reasons: string[];
}

export interface FlywheelResult {
  prefill: UnderwritingPrefill;
  crossSell: RouteSuggestion[];
}

/** A claim is usable by `asking` if it was issued by `asking` itself, OR the
 *  subject consented to share that scope from the issuer to `asking`. */
function claimUsable(
  claim: Claim,
  asking: ProductId,
  subject: string,
  consent: ConsentGrant[],
  asOf: Date,
): boolean {
  if (claim.issuer === asking) return true;
  return consentAllows(consent, {
    subject,
    from: claim.issuer,
    to: asking,
    scope: claim.kind,
    asOf,
  });
}

export function runFlywheel(input: FlywheelInput): FlywheelResult {
  const asOf = input.asOf ?? new Date();
  const usable: { kind: ClaimKind; value: number; issuer: ProductId }[] = [];
  const reasons: string[] = [];

  for (const passport of input.passports) {
    const v = verifyPassport(passport, asOf);
    if (!v.valid) {
      reasons.push(`passport ${passport.id.slice(0, 12)} skipped: ${v.reason}`);
      continue;
    }
    for (const c of v.liveClaims) {
      if (claimUsable(c, input.asking, input.subject, input.consent, asOf)) {
        usable.push({ kind: c.kind, value: c.value, issuer: c.issuer });
      } else {
        reasons.push(`claim ${c.kind} from ${c.issuer} blocked: no consent to ${input.asking}`);
      }
    }
  }

  const has = (k: ClaimKind, min = 0) => usable.some((c) => c.kind === k && c.value >= min);
  const financialClaim =
    usable.find((c) => c.kind === 'financial_profile') ??
    usable.find((c) => c.kind === 'credit_quality');

  const kycVerified = has('kyc_verified');
  const sanctionsClear = has('sanctions_clear');
  const geoAllowed = has('geo_allowed');
  const financialStrength = financialClaim ? financialClaim.value : null;

  // Instant underwrite when identity is proven AND we have a financial signal.
  const canInstantUnderwrite = kycVerified && financialStrength !== null;
  if (canInstantUnderwrite) {
    reasons.push('instant underwrite: KYC + financial signal present, no new intake required');
  }

  const prefill: UnderwritingPrefill = {
    usableClaims: usable,
    kycVerified,
    ecpEligible: has('ecp_eligible'),
    sanctionsClear,
    geoAllowed,
    financialStrength,
    canInstantUnderwrite,
    reasons,
  };

  const crossSell = suggestRoutes({
    liveClaimKinds: usable.map((c) => ({ kind: c.kind, value: c.value })),
    alreadyOn: input.alreadyOn,
    rules: input.routeRules,
  });

  return { prefill, crossSell };
}
