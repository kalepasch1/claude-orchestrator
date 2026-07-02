/**
 * Approver-preference model — the plane learns BEAR, not just "what was decided." From
 * his decision history it learns per-type approval rates, which domains he always
 * scrutinizes, his active hours, and his common edits — then predicts his likely call,
 * orders the queue to his real attention budget, and pre-fills the edit he usually makes.
 * The difference between a queue you clear and a queue that clears itself with your taste
 * baked in. Pure + zero-dep.
 */
import type { AdminDomain } from './types.ts';

export interface ApproverDecisionRecord {
  domain: AdminDomain;
  actionType: string;
  outcome: 'approve' | 'modify' | 'reject';
  at: string; // ISO
  /** if the outcome was 'modify', the params the human changed to */
  modifiedParams?: Record<string, unknown>;
}

export interface TypeStat {
  actionType: string;
  domain: AdminDomain;
  total: number;
  approveRate: number;
  modifyRate: number;
  rejectRate: number;
  /** the most common modification the human applies to this type, if any */
  commonEdit?: Record<string, unknown>;
}

export interface ApproverProfile {
  types: Record<string, TypeStat>; // key `${domain}::${type}`
  /** domains the human approves < 50% of the time — they want eyes on these */
  scrutinizedDomains: AdminDomain[];
  /** local-hour histogram (0..23) of when the human actually decides */
  activeHours: number[];
  totalDecisions: number;
}

function keyOf(d: AdminDomain, t: string): string {
  return `${d}::${t}`;
}

function modeOf(objs: Record<string, unknown>[]): Record<string, unknown> | undefined {
  if (objs.length === 0) return undefined;
  const counts = new Map<string, { obj: Record<string, unknown>; n: number }>();
  for (const o of objs) {
    const k = JSON.stringify(o);
    const e = counts.get(k) ?? { obj: o, n: 0 };
    e.n++;
    counts.set(k, e);
  }
  return [...counts.values()].sort((a, b) => b.n - a.n)[0]?.obj;
}

export function buildApproverProfile(records: ApproverDecisionRecord[]): ApproverProfile {
  const byType = new Map<string, ApproverDecisionRecord[]>();
  const byDomain = new Map<AdminDomain, ApproverDecisionRecord[]>();
  const activeHours = new Array<number>(24).fill(0);

  for (const r of records) {
    const tk = keyOf(r.domain, r.actionType);
    (byType.get(tk) ?? byType.set(tk, []).get(tk)!).push(r);
    (byDomain.get(r.domain) ?? byDomain.set(r.domain, []).get(r.domain)!).push(r);
    const h = new Date(r.at).getHours();
    if (Number.isFinite(h)) activeHours[h] = (activeHours[h] ?? 0) + 1;
  }

  const types: Record<string, TypeStat> = {};
  for (const [k, rs] of byType) {
    const total = rs.length;
    const c = (o: string) => rs.filter((r) => r.outcome === o).length;
    types[k] = {
      actionType: rs[0]!.actionType,
      domain: rs[0]!.domain,
      total,
      approveRate: Math.round((c('approve') / total) * 100) / 100,
      modifyRate: Math.round((c('modify') / total) * 100) / 100,
      rejectRate: Math.round((c('reject') / total) * 100) / 100,
      commonEdit: modeOf(rs.filter((r) => r.outcome === 'modify' && r.modifiedParams).map((r) => r.modifiedParams!)),
    };
  }

  const scrutinizedDomains: AdminDomain[] = [];
  for (const [d, rs] of byDomain) {
    const approve = rs.filter((r) => r.outcome === 'approve').length / rs.length;
    if (approve < 0.5) scrutinizedDomains.push(d);
  }

  return { types, scrutinizedDomains, activeHours, totalDecisions: records.length };
}

export interface DecisionPrediction {
  likely: 'approve' | 'modify' | 'reject' | 'uncertain';
  confidence: number;
  basis: string;
}

/** Predict how Bear will likely decide a card of this (domain, type). */
export function predictDecision(profile: ApproverProfile, domain: AdminDomain, actionType: string): DecisionPrediction {
  const stat = profile.types[keyOf(domain, actionType)];
  if (!stat || stat.total < 3) return { likely: 'uncertain', confidence: 0, basis: 'insufficient_history' };
  const entries: [DecisionPrediction['likely'], number][] = [
    ['approve', stat.approveRate],
    ['modify', stat.modifyRate],
    ['reject', stat.rejectRate],
  ];
  entries.sort((a, b) => b[1] - a[1]);
  const [likely, rate] = entries[0]!;
  return { likely, confidence: rate, basis: `${Math.round(rate * 100)}% of ${stat.total} past ${actionType} decisions` };
}

/** Suggest the edit Bear usually makes to this type (pre-fill the modify path). */
export function prefillEdit(profile: ApproverProfile, domain: AdminDomain, actionType: string): Record<string, unknown> | undefined {
  return profile.types[keyOf(domain, actionType)]?.commonEdit;
}

export interface QueueItem {
  domain: AdminDomain;
  actionType: string;
  priority: number;
}

/**
 * Order the queue to Bear's attention: things he scrutinizes (low predicted approve
 * rate) or that are high priority float up; things he reliably rubber-stamps sink (they
 * are promotion candidates anyway). Returns items with an attention score.
 */
export function orderQueueForApprover<T extends QueueItem>(profile: ApproverProfile, items: T[]): (T & { attention: number })[] {
  return items
    .map((it) => {
      const pred = predictDecision(profile, it.domain, it.actionType);
      // High attention when he is NOT likely to simply approve, or the stakes are high.
      const notRubberStamp = pred.likely === 'uncertain' ? 0.6 : 1 - (pred.likely === 'approve' ? pred.confidence : 0);
      const scrutiny = profile.scrutinizedDomains.includes(it.domain) ? 0.3 : 0;
      const attention = Math.round(Math.min(1, notRubberStamp * 0.6 + scrutiny + (it.priority / 100) * 0.4) * 100) / 100;
      return { ...it, attention };
    })
    .sort((a, b) => b.attention - a.attention || b.priority - a.priority);
}
