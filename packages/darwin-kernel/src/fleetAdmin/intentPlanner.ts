/**
 * Learned intent planner — makes intent-level autonomy OPEN-ENDED. Instead of hand-templates
 * only, a novel goal ("make this regulator relationship warmer") is composed into a step plan
 * by retrieving the nearest past SUCCESSFUL intents and reusing their steps, falling back to a
 * template when there's no close match. The composed plan is still governed as one decision by
 * `governIntent`, so open-ended does not mean unbounded. Pure + zero-dep (a product can inject
 * embeddings; here we retrieve by token overlap, which is deterministic + testable).
 */
import type { AdminAction } from './types.ts';
import { planIntent, type IntentPlan } from './intent.ts';

/** A past intent that worked — the training signal for the planner. */
export interface PlanExemplar {
  goal: string;
  steps: AdminAction[];
  /** how well it worked (0..1) — successful exemplars are preferred */
  success: number;
}

export interface ComposedPlan {
  plan: IntentPlan;
  source: 'exemplar' | 'template';
  confidence: number;
  matchedGoal?: string;
}

function tokens(s: string): Set<string> {
  return new Set(s.toLowerCase().split(/[^a-z0-9]+/).filter((t) => t.length > 2));
}
function jaccard(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 || b.size === 0) return 0;
  let inter = 0;
  for (const t of a) if (b.has(t)) inter++;
  return inter / (a.size + b.size - inter);
}

/**
 * Compose a plan for a goal. If a past successful exemplar is similar enough, reuse its steps
 * (re-targeted to this subject/product); otherwise fall back to the deterministic template.
 */
export function composeIntentPlan(params: {
  goal: string;
  subjectId?: string;
  product: AdminAction['product'];
  amountUsd?: number;
  exemplars?: PlanExemplar[];
  at?: string;
  minSimilarity?: number;
}): ComposedPlan {
  const at = params.at ?? new Date().toISOString();
  const minSim = params.minSimilarity ?? 0.34;
  const goalTokens = tokens(params.goal);

  let best: { ex: PlanExemplar; sim: number } | null = null;
  for (const ex of params.exemplars ?? []) {
    const sim = jaccard(goalTokens, tokens(ex.goal)) * (0.5 + 0.5 * Math.max(0, Math.min(1, ex.success)));
    if (!best || sim > best.sim) best = { ex, sim };
  }

  if (best && best.sim >= minSim) {
    const steps: AdminAction[] = best.ex.steps.map((s, i) => ({
      ...s,
      id: `${params.goal}:${s.type}:${params.subjectId ?? 'global'}:${i}`,
      product: params.product,
      subjectId: params.subjectId,
      at,
    }));
    return {
      plan: { intentId: `intent_${params.goal}_${params.subjectId ?? 'global'}`, goal: params.goal, subjectId: params.subjectId, product: params.product, steps },
      source: 'exemplar',
      confidence: Math.round(best.sim * 100) / 100,
      matchedGoal: best.ex.goal,
    };
  }

  return { plan: planIntent({ goal: params.goal, subjectId: params.subjectId, product: params.product, amountUsd: params.amountUsd, at }), source: 'template', confidence: 0 };
}
