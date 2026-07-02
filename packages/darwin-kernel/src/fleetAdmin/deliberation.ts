/**
 * CADE pre-pass for human-tier cards — before Bear sees a hard decision, a mini
 * conclave argues it: an advocate (make the case), an adversary/red-team (break it),
 * and a reviewer/tribunal (forecast the decision-maker). The card then carries the
 * strongest case AND the strongest objection, so the human decision is faster + better.
 *
 * Structurally CADE-shaped (advocate / adversary / reviewer roles) and it ties into
 * CADE's real vector math (hashEmbedder + cosine) to measure genuine dissent between
 * the viewpoints. Deterministic + zero-dep — no fabricated model calls; a product can
 * escalate to the full `runDetermination` with injected personas when materiality is high.
 */
import { hashEmbedder, cosine } from '../cade/vectors.ts';
import type { AdminAction } from './types.ts';
import type { PrecedentAdvice } from './precedent.ts';

export interface Viewpoint {
  role: 'advocate' | 'adversary' | 'reviewer';
  position: string;
  confidence: number; // 0..1
}

export interface Deliberation {
  recommendation: 'approve' | 'reject' | 'needs_more_info';
  strongestCase: string;
  strongestObjection: string;
  /** 0..1 — how far apart the viewpoints are (real cosine dissent). 1 = fully split. */
  dissent: number;
  viewpoints: Viewpoint[];
}

function advocate(a: AdminAction): Viewpoint {
  const case_ = a.ifNotDone
    ? `Do it: ${a.intent}. Not doing it means: ${a.ifNotDone}.`
    : `Do it: ${a.intent}.`;
  // The agent's own confidence is the advocate's confidence.
  return { role: 'advocate', position: case_, confidence: Math.max(0, Math.min(1, a.confidence)) };
}

function adversary(a: AdminAction, precedent?: PrecedentAdvice): Viewpoint {
  const objections: string[] = [];
  if (a.reversibility !== 'reversible') objections.push(`this is ${a.reversibility} — a wrong call is costly to undo`);
  if (a.blastRadius === 'large' || a.blastRadius === 'fleet') objections.push(`blast radius is ${a.blastRadius}`);
  if ((a.amountUsd ?? 0) > 0) objections.push(`$${a.amountUsd} moves on this`);
  if (precedent && precedent.sampleSize >= 5 && precedent.cleanRate < 0.6)
    objections.push(`similar past cases were often edited/rejected (${Math.round(precedent.cleanRate * 100)}% clean)`);
  if (precedent && precedent.sampleSize < 5) objections.push('little precedent — we are guessing');
  const position = objections.length
    ? `Hold: ${objections.join('; ')}.`
    : `Weak grounds to object, but verify the params match intent before running.`;
  // Adversary confidence scales with how many real risks it found.
  return { role: 'adversary', position, confidence: Math.min(1, 0.3 + objections.length * 0.2) };
}

function reviewer(a: AdminAction, precedent?: PrecedentAdvice): Viewpoint {
  // Forecasts what the decision-maker (Bear) will likely do, from the structural signal.
  const leansApprove = a.reversibility === 'reversible' && (a.amountUsd ?? 0) <= 50 && (precedent?.cleanRate ?? 0) >= 0.6;
  const position = leansApprove
    ? 'A reasonable approver likely approves — reversible, small, and precedent-backed.'
    : 'A careful approver likely scrutinizes — irreversibility, money, or thin precedent warrant a look.';
  return { role: 'reviewer', position, confidence: leansApprove ? 0.7 : 0.55 };
}

/** Run the pre-pass. Attach the result to the approval card before it reaches Bear. */
export function deliberate(action: AdminAction, precedent?: PrecedentAdvice): Deliberation {
  const vps = [advocate(action), adversary(action, precedent), reviewer(action, precedent)];
  const embed = hashEmbedder(64);
  const vecs = vps.map((v) => embed.embed(v.position));
  // Dissent = 1 - mean pairwise cosine similarity (real CADE vector math).
  let sims = 0;
  let pairs = 0;
  for (let i = 0; i < vecs.length; i++)
    for (let j = i + 1; j < vecs.length; j++) {
      sims += cosine(vecs[i]!, vecs[j]!);
      pairs++;
    }
  const dissent = pairs ? Math.max(0, Math.min(1, 1 - sims / pairs)) : 0;

  const adv = vps.find((v) => v.role === 'adversary')!;
  const advo = vps.find((v) => v.role === 'advocate')!;
  const rev = vps.find((v) => v.role === 'reviewer')!;

  // Synthesis: reject if the adversary is more confident than the advocate; else lean
  // to the reviewer's forecast. Never auto-approve here — this only informs the human.
  let recommendation: Deliberation['recommendation'];
  if (adv.confidence >= advo.confidence) recommendation = 'reject';
  else if (rev.confidence >= 0.7) recommendation = 'approve';
  else recommendation = 'needs_more_info';

  return {
    recommendation,
    strongestCase: advo.position,
    strongestObjection: adv.position,
    dissent: Math.round(dissent * 100) / 100,
    viewpoints: vps,
  };
}
