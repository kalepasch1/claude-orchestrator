/**
 * Regret ledger — closes the loop on AUTO-runs. An auto decision has no human outcome to
 * learn from, so today the flywheel only learns from what you reject. This captures lightweight
 * post-hoc signals — a reversed charge, a reopened ticket, a rollback, a complaint — as implicit
 * REGRET on past auto decisions, and folds them back into precedent + replay + the red-team.
 * The plane learns from its unattended mistakes, not just its supervised ones. Pure + zero-dep.
 */
import type { AdminAction, AdminDomain } from './types.ts';
import type { ResolvedCase } from './precedent.ts';

export interface RegretSignal {
  actionId: string;
  kind: 'reversed_charge' | 'reopened_ticket' | 'rollback' | 'complaint' | 'manual_undo';
  at: string;
}

/** An auto-run action, minimally described (from fleet_admin_actions where tier='auto'). */
export interface AutoRunRecord {
  id: string;
  domain: AdminDomain;
  type: string;
  amountUsd?: number;
  reversibility: AdminAction['reversibility'];
  blastRadius: AdminAction['blastRadius'];
  at: string;
}

/** Map regret signals to the auto actions they impugn → implicit 'reject' outcomes by id. */
export function regretAsOutcomes(signals: RegretSignal[]): Record<string, 'reject'> {
  const out: Record<string, 'reject'> = {};
  for (const s of signals) out[s.actionId] = 'reject';
  return out;
}

/**
 * Fold regret into the resolved-decision history used by precedent + replay: each regretted
 * auto action becomes a 'reject' ResolvedCase, so the same shape auto-runs less next time.
 */
export function regretToResolvedCases(autos: AutoRunRecord[], signals: RegretSignal[]): ResolvedCase[] {
  const regretted = new Set(signals.map((s) => s.actionId));
  return autos
    .filter((a) => regretted.has(a.id))
    .map((a) => ({ domain: a.domain, type: a.type, amountUsd: a.amountUsd, reversibility: a.reversibility, blastRadius: a.blastRadius, outcome: 'reject' as const, at: a.at }));
}

export interface RegretReport {
  byType: { domain: AdminDomain; actionType: string; autoRuns: number; regrets: number; regretRate: number }[];
  totalAutoRuns: number;
  totalRegrets: number;
  overallRegretRate: number;
}

/** Per action-type regret rate among auto-runs — the KPI that should trend to zero. */
export function regretReport(autos: AutoRunRecord[], signals: RegretSignal[]): RegretReport {
  const regretted = new Set(signals.map((s) => s.actionId));
  const groups = new Map<string, { domain: AdminDomain; type: string; autoRuns: number; regrets: number }>();
  for (const a of autos) {
    const k = `${a.domain}::${a.type}`;
    const g = groups.get(k) ?? { domain: a.domain, type: a.type, autoRuns: 0, regrets: 0 };
    g.autoRuns += 1;
    if (regretted.has(a.id)) g.regrets += 1;
    groups.set(k, g);
  }
  const byType = [...groups.values()]
    .map((g) => ({ domain: g.domain, actionType: g.type, autoRuns: g.autoRuns, regrets: g.regrets, regretRate: g.autoRuns ? Math.round((g.regrets / g.autoRuns) * 1000) / 1000 : 0 }))
    .sort((a, b) => b.regretRate - a.regretRate);
  const totalAutoRuns = autos.length;
  const totalRegrets = autos.filter((a) => regretted.has(a.id)).length;
  return { byType, totalAutoRuns, totalRegrets, overallRegretRate: totalAutoRuns ? Math.round((totalRegrets / totalAutoRuns) * 1000) / 1000 : 0 };
}
