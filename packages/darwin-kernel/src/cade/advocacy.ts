/**
 * The Advocacy Guild — delivery layer, FIREWALLED from substance.
 *
 * The determination is decided reviewer-blind first. Only then does this layer
 * adapt PACKAGING (tone, structure, citation emphasis, hedging) for the modeled
 * reviewer. A semantic-diff guard confirms the meaning did not drift — packaging
 * must never change the substance. This is also the UPL/ethics guard: the system
 * optimizes strategy + packaging; a human professional remains the authorized voice.
 */
import { cosine } from './vectors.ts';
import type { Determination, Embedder, ReviewerModel } from './types.ts';

export interface DeliveryPackage {
  /** Reviewer-adapted rendering of the SAME determination. */
  rendered: string;
  /** Cosine similarity between original and rendered meaning embeddings. */
  semanticFidelity: number;
  /** True iff fidelity ≥ threshold — packaging preserved substance. */
  substancePreserved: boolean;
  /** Confidence-conditioned hedging applied because the determination was thin. */
  hedged: boolean;
}

export interface PackageDeps {
  embedder: Embedder;
  /** Product-supplied restyler: substance in, reviewer-adapted prose out. */
  restyle: (substance: string, reviewer: ReviewerModel | undefined, hedge: boolean) => string;
}

export function packageForReviewer(
  det: Determination,
  deps: PackageDeps,
  fidelityThreshold = 0.82,
): DeliveryPackage {
  const reviewer = det.proof.record.reviewerModel;
  const hedged = det.confidence < 0.7;
  const rendered = deps.restyle(det.position, reviewer, hedged);
  const semanticFidelity = cosine(deps.embedder.embed(det.position), deps.embedder.embed(rendered));
  return {
    rendered,
    semanticFidelity,
    substancePreserved: semanticFidelity >= fidelityThreshold,
    hedged,
  };
}
