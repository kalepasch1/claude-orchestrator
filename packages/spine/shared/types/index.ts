/**
 * Domain entity surface of the compounding code-generation platform spine.
 *
 * `shared/contracts` is what a *caller* depends on: the operations and the thin
 * references they pass. This barrel is what an *implementer* depends on: the
 * stored entities behind those references.
 *
 * The split is load-bearing in one direction only — `types` imports from
 * `contracts`, never the reverse — so the entity layer can grow without
 * changing a single contract signature. A consumer that only calls operations
 * should import `@spine/contracts` and not this module.
 *
 * Declaration-only: importing it pulls in no runtime code.
 */
export type * from "./compound.ts";
export type * from "./wave.ts";
export type * from "./event.ts";

import type { Compound } from "./compound.ts";
import type { Wave } from "./wave.ts";
import type { StoredEvent } from "./event.ts";

/**
 * Everything the platform persists for one compound, in one shape.
 *
 * This is the aggregate boundary: a compound, its waves and its event log are
 * written and read together, because applying an event has to update wave state
 * and the compound's `appliedSequence` atomically or the sequence check stops
 * being able to detect gaps.
 */
export interface CompoundAggregate {
  readonly compound: Compound;
  /** In declaration order, matching `Compound.waves`. */
  readonly waves: readonly Wave[];
  /** Ascending by `sequence`. Append-only. */
  readonly events: readonly StoredEvent[];
}
