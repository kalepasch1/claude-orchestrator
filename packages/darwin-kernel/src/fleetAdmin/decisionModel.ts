/**
 * Admin-decision foundation model — the large, signed, labeled decision corpus is the moat;
 * this turns it into a learned policy. A small logistic model (deterministic training, zero
 * deps) over hashed action features replaces the feature-heuristics behind precedent / approver
 * / counterfactual predictions, and is itself servable as a capability other orgs consume.
 * Trained from the resolved-decision log; predicts P(a human clean-approves this action).
 */
import type { AdminAction, AdminDomain, Reversibility, BlastRadius } from './types.ts';
import type { ResolvedCase } from './precedent.ts';

const DIM = 12;

function h(s: string, mod: number): number {
  let x = 2166136261;
  for (let i = 0; i < s.length; i++) { x ^= s.charCodeAt(i); x = Math.imul(x, 16777619); }
  return Math.abs(x) % mod;
}
function amtBucket(v?: number): number {
  const a = v ?? 0;
  return a <= 0 ? 0 : a <= 50 ? 0.25 : a <= 500 ? 0.5 : a <= 5000 ? 0.75 : 1;
}
const REV: Record<Reversibility, number> = { reversible: 0, hard_to_reverse: 0.5, irreversible: 1 };
const BLAST: Record<BlastRadius, number> = { single: 0, small: 0.33, large: 0.66, fleet: 1 };

/** Feature vector for an action shape. Fixed dim so weights are stable + servable. */
export function featurize(a: { domain: AdminDomain; type: string; amountUsd?: number; reversibility: Reversibility; blastRadius: BlastRadius }): number[] {
  const x = new Array<number>(DIM).fill(0);
  x[0] = 1; // bias
  x[1] = amtBucket(a.amountUsd);
  x[2] = REV[a.reversibility];
  x[3] = BLAST[a.blastRadius];
  x[4 + h(a.domain, 2)] = 1; // 2 domain buckets → x[4..5]
  x[6 + h(a.type, 6)] = 1; // 6 verb buckets → x[6..11]
  return x;
}

export interface DecisionModel {
  weights: number[];
  epochs: number;
  samples: number;
}

function sigmoid(z: number): number { return 1 / (1 + Math.exp(-z)); }
function dot(a: number[], b: number[]): number { let s = 0; for (let i = 0; i < a.length; i++) s += a[i]! * b[i]!; return s; }

export interface TrainSample { features: number[]; label: number }

/** Deterministic logistic-regression fit (fixed epochs, L2). */
export function trainDecisionModel(samples: TrainSample[], epochs = 300, lr = 0.1, l2 = 0.001): DecisionModel {
  const w = new Array<number>(DIM).fill(0);
  for (let e = 0; e < epochs; e++) {
    for (const s of samples) {
      const p = sigmoid(dot(w, s.features));
      const err = p - s.label;
      for (let i = 0; i < DIM; i++) w[i] = w[i]! - lr * (err * s.features[i]! + l2 * w[i]!);
    }
  }
  return { weights: w, epochs, samples: samples.length };
}

/** Build training samples from the resolved-decision log (approve = 1, edit/reject = 0). */
export function samplesFromResolved(cases: ResolvedCase[]): TrainSample[] {
  return cases.map((c) => ({ features: featurize(c), label: c.outcome === 'approve' ? 1 : 0 }));
}

/** Predict P(clean-approve) for an action under a trained model. */
export function predictApprove(model: DecisionModel, a: Pick<AdminAction, 'domain' | 'type' | 'amountUsd' | 'reversibility' | 'blastRadius'>): number {
  return Math.round(sigmoid(dot(model.weights, featurize(a))) * 1000) / 1000;
}
