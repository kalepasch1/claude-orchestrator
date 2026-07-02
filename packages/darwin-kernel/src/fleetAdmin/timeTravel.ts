/**
 * Time-travel debugging — because every decision has a signed receipt and the twin can
 * replay any config, you can rewind to any past window and replay it under any law, then
 * attribute a drift to the exact change (amendment / promotion) that caused it and roll just
 * that back. Full auditability becomes full reversibility. Pure + zero-dep.
 */
import { governFleetAction, type FleetVerdict } from './govern.ts';
import { dryRunChange, type PlaneConfigSnapshot, type TwinResult } from './twin.ts';
import type { AdminAction } from './types.ts';
import type { Decision } from '../types.ts';

export interface ReplaySummary {
  actionId: string;
  at: string;
  decision: Decision;
  tier: FleetVerdict['tier'];
}

/** Replay every action in [fromIso, toIso) under a given plane config. */
export function replayWindow(
  actions: AdminAction[],
  window: { fromIso: string; toIso: string },
  config: PlaneConfigSnapshot = {},
): { summaries: ReplaySummary[]; autonomyRate: number } {
  const from = Date.parse(window.fromIso);
  const to = Date.parse(window.toIso);
  const inWindow = actions.filter((a) => {
    const t = Date.parse(a.at);
    return t >= from && t < to;
  });
  const summaries = inWindow.map((a) => {
    const v = governFleetAction({ action: a, constitution: config.constitution, policies: config.policies });
    return { actionId: a.id, at: a.at, decision: v.decision, tier: v.tier };
  });
  const auto = summaries.filter((s) => s.decision === 'allow' && s.tier === 'auto').length;
  const denom = summaries.filter((s) => s.decision !== 'deny').length;
  return { summaries, autonomyRate: denom ? Math.round((auto / denom) * 100) / 100 : 0 };
}

export interface ChangeImpact {
  label: string;
  changed: number;
  regressions: number;
  twin: TwinResult;
}

/**
 * Attribute drift: given the baseline law and a set of candidate changes (each an amendment
 * or promotion applied at some point), rank which one flipped the most decisions over the
 * window — the prime suspect for an observed drift. The top item is what to roll back.
 */
export function attributeDrift(
  actions: AdminAction[],
  before: PlaneConfigSnapshot,
  candidates: { label: string; after: PlaneConfigSnapshot }[],
  outcomes?: Record<string, 'approve' | 'modify' | 'reject'>,
): ChangeImpact[] {
  return candidates
    .map((c) => {
      const twin = dryRunChange({ actions, before, after: c.after, outcomes });
      return { label: c.label, changed: twin.changed, regressions: twin.regressions, twin };
    })
    .sort((a, b) => b.regressions - a.regressions || b.changed - a.changed);
}
