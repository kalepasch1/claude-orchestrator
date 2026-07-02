/**
 * Causal treatment-effect estimation — move from "did this correlate" to "what did promoting X
 * actually CAUSE." Using the promotion as a natural experiment, a difference-in-differences on
 * the receipt log (treated action-type vs. untreated controls, before vs. after the promotion)
 * yields an estimated causal effect on a metric (regret rate, cost, latency). Every promotion
 * reports a real treatment effect, so decisions become econometrically grounded. Pure + zero-dep.
 */
export interface Observation {
  /** the metric of interest (e.g. regret rate, cost per decision) — lower usually better */
  metric: number;
  treated: boolean; // the promoted action-type
  period: 'pre' | 'post'; // relative to the promotion date
}

export interface DiDResult {
  /** difference-in-differences estimate: (postT-preT) - (postC-preC). Negative = promotion reduced the metric. */
  estimate: number;
  cells: { preTreated: number; postTreated: number; preControl: number; postControl: number };
  counts: { preTreated: number; postTreated: number; preControl: number; postControl: number };
  interpretation: string;
}

function mean(xs: number[]): number { return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0; }

/** Difference-in-differences over the four cells. */
export function differenceInDifferences(obs: Observation[]): DiDResult {
  const cell = (t: boolean, p: 'pre' | 'post') => obs.filter((o) => o.treated === t && o.period === p).map((o) => o.metric);
  const preT = cell(true, 'pre'), postT = cell(true, 'post'), preC = cell(false, 'pre'), postC = cell(false, 'post');
  const cells = { preTreated: mean(preT), postTreated: mean(postT), preControl: mean(preC), postControl: mean(postC) };
  const estimate = Math.round(((cells.postTreated - cells.preTreated) - (cells.postControl - cells.preControl)) * 1000) / 1000;

  const interpretation =
    estimate < 0
      ? `promotion CAUSED a ${Math.abs(estimate)} reduction in the metric vs. controls (net of the common trend)`
      : estimate > 0
        ? `promotion is associated with a ${estimate} INCREASE vs. controls — investigate before expanding`
        : 'no measurable causal effect vs. controls';

  return {
    estimate,
    cells,
    counts: { preTreated: preT.length, postTreated: postT.length, preControl: preC.length, postControl: postC.length },
    interpretation,
  };
}
