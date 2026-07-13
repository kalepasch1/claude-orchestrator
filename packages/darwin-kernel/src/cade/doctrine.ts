/**
 * Self-closing dispute → doctrine loop: mine realized determination outcomes for
 * PATTERNS that keep getting overturned, and emit ranked proposals (roster/prompt/
 * doctrine changes) for the improvement queue. Pure; the queueing is the app's job.
 */

export interface DeterminationOutcome {
  /** a coarse pattern key: issue kind, doctrine area, roster class, etc. */
  pattern: string;
  overturned: boolean;
}

export interface DoctrineProposal {
  pattern: string;
  count: number;
  overturnRate: number;
  /** rank = overturnRate × count (impact-weighted). */
  score: number;
  action: 'review_roster_or_prompt';
}

/**
 * Group outcomes by pattern; surface patterns that fail often enough (>= minCount and
 * >= failRate) as ranked proposals for the self-improvement miner.
 */
export function mineDoctrineUpdates(
  outcomes: DeterminationOutcome[],
  opts: { minCount?: number; failRate?: number } = {},
): DoctrineProposal[] {
  const minCount = opts.minCount ?? 3;
  const failRate = opts.failRate ?? 0.5;
  const agg = new Map<string, { count: number; overturns: number }>();
  for (const o of outcomes) {
    const a = agg.get(o.pattern) ?? { count: 0, overturns: 0 };
    a.count++;
    if (o.overturned) a.overturns++;
    agg.set(o.pattern, a);
  }
  const proposals: DoctrineProposal[] = [];
  for (const [pattern, a] of agg) {
    const rate = a.count > 0 ? a.overturns / a.count : 0;
    if (a.count >= minCount && rate >= failRate) {
      proposals.push({
        pattern,
        count: a.count,
        overturnRate: rate,
        score: rate * a.count,
        action: 'review_roster_or_prompt',
      });
    }
  }
  return proposals.sort((x, y) => y.score - x.score);
}
