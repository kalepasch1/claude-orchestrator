/**
 * Closed-loop self-promotion — the nightly cycle that actually moves the answered-from-plane
 * rate on its own. It assembles every earned promotion into an evidence-backed dossier
 * (value + replayed safety + blast), keeps only the ones that are recommended AND have zero
 * replayed regressions, and hands Bear a SINGLE "accept all safe promotions" batch. You stop
 * hunting for what to automate; the system brings you the vetted set. Pure + zero-dep.
 */
import type { AdminDomain, AutonomyTier } from './types.ts';
import type { LedgerEntry } from './ledger.ts';
import type { ResolvedCase } from './precedent.ts';
import type { ExposureRecord } from './blastSimulator.ts';
import { promotionDossier, type PromotionDossier } from './dossier.ts';

export interface SelfPromotionBatch {
  /** promotions that are valuable, replay-safe, and low-blast — safe to accept together */
  recommended: PromotionDossier[];
  /** earned offers that were held (why is in each dossier) */
  held: PromotionDossier[];
  totalApprovalsSaved: number;
  totalDollarsSaved: number;
  /** aggregate replayed divergences across the recommended set (0 = clean) */
  aggregateRegressions: number;
  safeToAcceptAll: boolean;
  summary: string;
}

/**
 * Assemble the batch. `exposureFor` supplies the historical $ records per action-type so
 * the blast simulator can size each promotion's portfolio exposure.
 */
export function assembleSelfPromotionBatch(params: {
  entries: LedgerEntry[];
  history: ResolvedCase[];
  exposureFor: (domain: AdminDomain, actionType: string) => ExposureRecord[];
  ceilingOf: (d: AdminDomain) => AutonomyTier;
}): SelfPromotionBatch {
  const dossiers: PromotionDossier[] = [];
  for (const entry of params.entries) {
    const d = promotionDossier(entry, params.history, params.exposureFor(entry.domain, entry.actionType), params.ceilingOf);
    if (d) dossiers.push(d);
  }

  const recommended = dossiers.filter((d) => d.verdict === 'recommend');
  const held = dossiers.filter((d) => d.verdict === 'hold');
  const totalApprovalsSaved = recommended.reduce((s, d) => s + d.value.approvalsSaved, 0);
  const totalDollarsSaved = recommended.reduce((s, d) => s + d.value.dollarsAtRiskAvoided, 0);
  const aggregateRegressions = recommended.reduce((s, d) => s + d.replay.divergences, 0);
  const safeToAcceptAll = recommended.length > 0 && aggregateRegressions === 0;

  return {
    recommended: recommended.sort((a, b) => b.value.dollarsAtRiskAvoided - a.value.dollarsAtRiskAvoided),
    held,
    totalApprovalsSaved,
    totalDollarsSaved,
    aggregateRegressions,
    safeToAcceptAll,
    summary:
      recommended.length === 0
        ? 'No promotions earned yet — nothing to accept.'
        : `${recommended.length} safe promotion(s) ready: ~${totalApprovalsSaved} decisions/period would auto-run, ` +
          `~$${totalDollarsSaved} risk avoided, ${aggregateRegressions} replayed regressions. ` +
          (safeToAcceptAll ? 'One tap accepts all.' : '⚠ review — some replayed regressions present.'),
  };
}
