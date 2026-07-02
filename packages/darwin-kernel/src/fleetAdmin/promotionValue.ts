/**
 * Reverse-auction on autonomy — the plane proposes its OWN promotions with money
 * attached. Instead of "this is safe to auto," it says "auto-handling this would have
 * saved N approvals and $X in error/latency over the window — promote?" Autonomy
 * expansion becomes a quantified, one-tap business decision, not a vibe.
 *
 * Pure + zero-dep. Built on the flywheel ledger; a promotion is still human-confirmed.
 */
import type { AdminDomain, AutonomyTier } from './types.ts';
import type { LedgerEntry } from './ledger.ts';

export interface PromotionValue {
  domain: AdminDomain;
  actionType: string;
  recommendTier: AutonomyTier;
  /** clean human approvals that could have run unattended over the window */
  approvalsSaved: number;
  /** approver minutes reclaimed (approvalsSaved × perDecisionMinutes) */
  minutesReclaimed: number;
  /** modelled error/latency cost avoided by removing the human wait, in USD */
  dollarsAtRiskAvoided: number;
  agreementRate: number;
  streak: number;
  recommendation: string;
}

export interface AuctionConfig {
  minStreak: number;
  minAgreement: number;
  perDecisionMinutes: number;
  /** $ value of a reclaimed approver-hour (opportunity cost) */
  hourlyValueUsd: number;
  /** $ risk per hour an action waits in queue, per domain (latency cost of NOT auto-running) */
  latencyRiskPerHourUsd: Record<AdminDomain, number>;
  /** typical hours an escalated action waits for a human */
  avgWaitHours: number;
}

export const DEFAULT_AUCTION_CONFIG: AuctionConfig = {
  minStreak: 20,
  minAgreement: 0.95,
  perDecisionMinutes: 3,
  hourlyValueUsd: 200,
  latencyRiskPerHourUsd: { users_access: 2, billing: 8, trust_safety: 5, infra: 12 },
  avgWaitHours: 4,
};

/**
 * Quantify a promotion for one ledger entry. Returns null if the entry hasn't earned
 * an offer yet (short streak / low agreement / already promoted).
 */
export function quantifyPromotion(
  entry: LedgerEntry,
  ceilingOf: (d: AdminDomain) => AutonomyTier,
  cfg: AuctionConfig = DEFAULT_AUCTION_CONFIG,
): PromotionValue | null {
  if (entry.promotedAt) return null;
  const agreement = entry.total ? entry.cleanApprovals / entry.total : 0;
  if (entry.streak < cfg.minStreak || agreement < cfg.minAgreement) return null;

  const ceiling = ceilingOf(entry.domain);
  const recommendTier: AutonomyTier = ceiling === 'auto' ? 'auto' : 'co_pilot';

  const approvalsSaved = entry.cleanApprovals;
  const minutesReclaimed = approvalsSaved * cfg.perDecisionMinutes;
  const latencyRisk = cfg.latencyRiskPerHourUsd[entry.domain] ?? 5;
  const dollarsAtRiskAvoided = Math.round(approvalsSaved * cfg.avgWaitHours * latencyRisk);

  return {
    domain: entry.domain,
    actionType: entry.actionType,
    recommendTier,
    approvalsSaved,
    minutesReclaimed,
    dollarsAtRiskAvoided,
    agreementRate: Math.round(agreement * 100) / 100,
    streak: entry.streak,
    recommendation:
      `Promote '${entry.actionType}' → ${recommendTier}: would have run ${approvalsSaved} decisions unattended ` +
      `(~${Math.round(minutesReclaimed)} min reclaimed, ~$${dollarsAtRiskAvoided} latency risk avoided) at ` +
      `${Math.round(agreement * 100)}% agreement.`,
  };
}

/** Rank all promotion offers by modelled value (dollars first, then volume). */
export function auctionBoard(
  entries: LedgerEntry[],
  ceilingOf: (d: AdminDomain) => AutonomyTier,
  cfg: AuctionConfig = DEFAULT_AUCTION_CONFIG,
): PromotionValue[] {
  return entries
    .map((e) => quantifyPromotion(e, ceilingOf, cfg))
    .filter((x): x is PromotionValue => x !== null)
    .sort((a, b) => b.dollarsAtRiskAvoided - a.dollarsAtRiskAvoided || b.approvalsSaved - a.approvalsSaved);
}
