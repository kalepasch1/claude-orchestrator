/**
 * Portfolio blast simulator — the one thing a per-app tool structurally cannot compute.
 * Because ONE control plane touches every app, it can model the CORRELATED downside of
 * auto-promoting an action-type: how much daily exposure concentrates through a single
 * code path, how many apps/subjects are in that blast radius, and the worst-case
 * simultaneous-failure cost. Price the single-blast-radius risk BEFORE widening autonomy.
 * Pure + zero-dep.
 */
import type { AdminDomain } from './types.ts';

/** A historical occurrence of an action-type, used to size exposure. */
export interface ExposureRecord {
  product: string;
  amountUsd?: number;
  at: string; // ISO
}

export interface BlastAssessment {
  domain: AdminDomain;
  actionType: string;
  /** distinct apps that would run this action-type unattended */
  appsAffected: number;
  /** modelled average daily $ flowing through this one auto path */
  dailyExposureUsd: number;
  /** the largest single-day $ seen historically (worst realized day) */
  worstDayUsd: number;
  /** share of exposure concentrated in the single biggest app (0..1) */
  concentration: number;
  /** count of actions/day (volume through the path) */
  dailyVolume: number;
  recommendation: 'low_blast' | 'concentrated_blast' | 'high_blast';
  reason: string;
}

export interface BlastConfig {
  /** daily exposure above this = high blast */
  highDailyUsd: number;
  /** concentration above this in one app = concentrated */
  concentratedShare: number;
}

export const DEFAULT_BLAST_CONFIG: BlastConfig = { highDailyUsd: 5000, concentratedShare: 0.75 };

function dayKey(iso: string): string {
  return iso.slice(0, 10);
}

/** Assess the correlated blast radius of auto-running (domain, actionType) portfolio-wide. */
export function simulateBlast(
  params: { domain: AdminDomain; actionType: string },
  records: ExposureRecord[],
  cfg: BlastConfig = DEFAULT_BLAST_CONFIG,
): BlastAssessment {
  const base = { domain: params.domain, actionType: params.actionType };
  if (records.length === 0) {
    return { ...base, appsAffected: 0, dailyExposureUsd: 0, worstDayUsd: 0, concentration: 0, dailyVolume: 0, recommendation: 'low_blast', reason: 'no_history' };
  }

  const byDay = new Map<string, number>();
  const byApp = new Map<string, number>();
  const days = new Set<string>();
  let total = 0;
  for (const r of records) {
    const amt = r.amountUsd ?? 0;
    total += amt;
    const dk = dayKey(r.at);
    days.add(dk);
    byDay.set(dk, (byDay.get(dk) ?? 0) + amt);
    byApp.set(r.product, (byApp.get(r.product) ?? 0) + amt);
  }
  const dayCount = Math.max(1, days.size);
  const dailyExposureUsd = Math.round(total / dayCount);
  const worstDayUsd = Math.round(Math.max(...byDay.values(), 0));
  const topApp = Math.max(...byApp.values(), 0);
  const concentration = total > 0 ? Math.round((topApp / total) * 100) / 100 : 0;
  const dailyVolume = Math.round((records.length / dayCount) * 10) / 10;

  let recommendation: BlastAssessment['recommendation'];
  let reason: string;
  if (dailyExposureUsd >= cfg.highDailyUsd) {
    recommendation = 'high_blast';
    reason = `~$${dailyExposureUsd}/day would flow through one auto path (worst day $${worstDayUsd})`;
  } else if (concentration >= cfg.concentratedShare) {
    recommendation = 'concentrated_blast';
    reason = `${Math.round(concentration * 100)}% of exposure concentrates in one app`;
  } else {
    recommendation = 'low_blast';
    reason = `~$${dailyExposureUsd}/day across ${byApp.size} apps, no single point dominant`;
  }

  return { ...base, appsAffected: byApp.size, dailyExposureUsd, worstDayUsd, concentration, dailyVolume, recommendation, reason };
}
