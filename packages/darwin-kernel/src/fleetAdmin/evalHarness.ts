/**
 * Eval harness — measure the plane against a labeled golden set BEFORE trusting it. Scores two
 * things against held-out human outcomes: (1) the GATE's auto-vs-human calls, where a
 * false-positive = the plane auto-ran something the human would NOT have clean-approved (the
 * dangerous error), and (2) the learned decision model's approve predictions. Reports the
 * confusion matrix + precision/recall/F1/accuracy so promotion is evidence-based. Pure + zero-dep.
 */
import type { AutonomyTier } from './types.ts';
import type { ResolvedCase } from './precedent.ts';
import { predictApprove, type DecisionModel } from './decisionModel.ts';

export interface BinaryScore {
  tp: number; fp: number; fn: number; tn: number;
  precision: number; recall: number; f1: number; accuracy: number;
  n: number;
}

/** Score binary predictions vs. actuals. `predicted`/`actual` are the POSITIVE class. */
export function scoreBinary(rows: { predicted: boolean; actual: boolean }[]): BinaryScore {
  let tp = 0, fp = 0, fn = 0, tn = 0;
  for (const r of rows) {
    if (r.predicted && r.actual) tp++;
    else if (r.predicted && !r.actual) fp++;
    else if (!r.predicted && r.actual) fn++;
    else tn++;
  }
  const precision = tp + fp ? tp / (tp + fp) : 0;
  const recall = tp + fn ? tp / (tp + fn) : 0;
  const f1 = precision + recall ? (2 * precision * recall) / (precision + recall) : 0;
  const n = rows.length;
  return {
    tp, fp, fn, tn,
    precision: Math.round(precision * 1000) / 1000,
    recall: Math.round(recall * 1000) / 1000,
    f1: Math.round(f1 * 1000) / 1000,
    accuracy: n ? Math.round(((tp + tn) / n) * 1000) / 1000 : 0,
    n,
  };
}

/**
 * Evaluate the GATE: positive prediction = "would auto-run"; positive label = "human
 * clean-approved". `fp` here is the safety-critical metric — auto-runs the human wouldn't have.
 */
export function evalGate(cases: { tier: AutonomyTier; decisionAllow: boolean; outcome: ResolvedCase['outcome'] }[]): BinaryScore & { falseAutoRuns: number } {
  const rows = cases.map((c) => ({ predicted: c.decisionAllow && c.tier === 'auto', actual: c.outcome === 'approve' }));
  const score = scoreBinary(rows);
  return { ...score, falseAutoRuns: score.fp };
}

/** Evaluate the learned decision model on held-out cases at a probability threshold. */
export function evalDecisionModel(model: DecisionModel, cases: ResolvedCase[], threshold = 0.5): BinaryScore {
  const rows = cases.map((c) => ({ predicted: predictApprove(model, c) >= threshold, actual: c.outcome === 'approve' }));
  return scoreBinary(rows);
}

/** Deterministic train/test split (every k-th case to test) for held-out evaluation. */
export function splitHoldout<T>(items: T[], testEvery = 5): { train: T[]; test: T[] } {
  const train: T[] = [], test: T[] = [];
  items.forEach((it, i) => ((i % testEvery === 0 ? test : train).push(it)));
  return { train, test };
}
