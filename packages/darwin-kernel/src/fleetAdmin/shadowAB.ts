/**
 * Continuous constitution A/B in production shadow — the twin + rule market run OFFLINE; this
 * runs them LIVE. A challenger constitution shadow-scores against the same real traffic as the
 * reigning champion; when it wins by a margin over enough decisions, it's recommended for
 * promotion (human-confirmed). The law improves continuously from production, not backtests.
 * Pure + zero-dep.
 */
import type { Constitution } from '../governance/constitution.ts';
import { scoreFaction, type FactionScore } from './ruleMarket.ts';
import type { AdminAction } from './types.ts';
import type { ResolvedCase } from './precedent.ts';

export interface ShadowABConfig {
  minSample: number;
  /** challenger must beat champion fitness by at least this margin to be promoted */
  promoteMargin: number;
}
export const DEFAULT_SHADOW_AB_CONFIG: ShadowABConfig = { minSample: 30, promoteMargin: 1 };

export interface ShadowABResult {
  champion: FactionScore;
  challenger: FactionScore;
  sampleSize: number;
  recommendation: 'promote_challenger' | 'keep_champion' | 'insufficient_sample';
  reason: string;
}

/**
 * Shadow-run both constitutions over the live decision stream (actions + realized outcomes)
 * and decide whether to promote the challenger.
 */
export function runShadowAB(params: {
  champion: { name: string; constitution: Constitution };
  challenger: { name: string; constitution: Constitution };
  history: AdminAction[];
  outcomes: Record<string, ResolvedCase['outcome']>;
  cfg?: ShadowABConfig;
}): ShadowABResult {
  const cfg = params.cfg ?? DEFAULT_SHADOW_AB_CONFIG;
  const champion = scoreFaction(params.champion, params.history, params.outcomes);
  const challenger = scoreFaction(params.challenger, params.history, params.outcomes);
  const sampleSize = Object.keys(params.outcomes).length;

  let recommendation: ShadowABResult['recommendation'];
  let reason: string;
  if (sampleSize < cfg.minSample) {
    recommendation = 'insufficient_sample';
    reason = `only ${sampleSize} resolved decisions (<${cfg.minSample})`;
  } else if (challenger.fitness - champion.fitness >= cfg.promoteMargin && challenger.regressions <= champion.regressions) {
    recommendation = 'promote_challenger';
    reason = `challenger fitness ${challenger.fitness} beats champion ${champion.fitness} by ≥${cfg.promoteMargin} with no more regressions`;
  } else {
    recommendation = 'keep_champion';
    reason = `challenger did not clear the promote margin (Δ ${Math.round((challenger.fitness - champion.fitness) * 100) / 100})`;
  }
  return { champion, challenger, sampleSize, recommendation, reason };
}
