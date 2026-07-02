/**
 * Promotion dossier — the one-tap decision packet the plane hands you for each autonomy
 * promotion offer. Composes three signals so you never widen autonomy on a hunch:
 *   1. VALUE  — approvals saved + dollars of latency-risk avoided (reverse auction)
 *   2. SAFETY — measured false-positive rate from replaying it on the whole history
 *   3. BLAST  — the correlated portfolio exposure that would flow through one auto path
 *
 * A promotion is only recommended when it's valuable AND proven-safe AND not a
 * concentrated blast. Pure + zero-dep.
 */
import type { AdminDomain, AutonomyTier } from './types.ts';
import type { LedgerEntry } from './ledger.ts';
import type { ResolvedCase } from './precedent.ts';
import { quantifyPromotion, type PromotionValue, type AuctionConfig, DEFAULT_AUCTION_CONFIG } from './promotionValue.ts';
import { replayPromotion, type ReplayResult, type ReplayConfig, DEFAULT_REPLAY_CONFIG } from './replay.ts';
import { simulateBlast, type BlastAssessment, type ExposureRecord, type BlastConfig, DEFAULT_BLAST_CONFIG } from './blastSimulator.ts';

export interface PromotionDossier {
  domain: AdminDomain;
  actionType: string;
  recommendTier: AutonomyTier;
  value: PromotionValue;
  replay: ReplayResult;
  blast: BlastAssessment;
  /** the plane's overall call, combining all three signals */
  verdict: 'recommend' | 'hold';
  headline: string;
}

/** Build the full dossier for one earned promotion offer. Returns null if not yet earned. */
export function promotionDossier(
  entry: LedgerEntry,
  history: ResolvedCase[],
  exposure: ExposureRecord[],
  ceilingOf: (d: AdminDomain) => AutonomyTier,
  cfg: { auction?: AuctionConfig; replay?: ReplayConfig; blast?: BlastConfig } = {},
): PromotionDossier | null {
  const value = quantifyPromotion(entry, ceilingOf, cfg.auction ?? DEFAULT_AUCTION_CONFIG);
  if (!value) return null;

  const replay = replayPromotion(
    { domain: entry.domain, actionType: entry.actionType, proposedTier: value.recommendTier },
    history,
    cfg.replay ?? DEFAULT_REPLAY_CONFIG,
  );
  const blast = simulateBlast(
    { domain: entry.domain, actionType: entry.actionType },
    exposure,
    cfg.blast ?? DEFAULT_BLAST_CONFIG,
  );

  const safe = replay.recommendation === 'safe_to_promote';
  const blastOk = blast.recommendation !== 'high_blast';
  const verdict: PromotionDossier['verdict'] = safe && blastOk ? 'recommend' : 'hold';

  const headline =
    verdict === 'recommend'
      ? `Promote '${entry.actionType}' → ${value.recommendTier}: ${value.approvalsSaved} decisions/window, ~$${value.dollarsAtRiskAvoided} risk avoided, ${(replay.falsePositiveRate * 100).toFixed(1)}% replayed error, ${blast.recommendation}.`
      : `Hold '${entry.actionType}': ${!safe ? replay.reason : blast.reason}.`;

  return { domain: entry.domain, actionType: entry.actionType, recommendTier: value.recommendTier, value, replay, blast, verdict, headline };
}
