/**
 * The compound domain entity.
 *
 * `shared/contracts/common.ts` deliberately exposes only `CompoundRef` — id and
 * status — and says of the rich entity: "the rich `Compound` entity lives in
 * `shared/types` and is layered on top of this reference". That layer was
 * referenced but never written, so anything needing the whole compound had to
 * re-declare it. This is that layer.
 *
 * The direction of the dependency matters and only goes one way: `types`
 * imports from `contracts`, never the reverse. That is what lets the operation
 * surface stay stable while the entity grows — adding a field here cannot
 * change a contract signature.
 *
 * Declaration-only, like `contracts`. Nothing in this directory may carry a
 * runtime value.
 */
import type {
  CompoundId,
  CompoundRef,
  CompoundStatus,
  EpochMillis,
} from "../contracts/common.ts";
import type { WaveSpec } from "../contracts/compound.ts";

/**
 * A compound as the platform stores it.
 *
 * Extends `CompoundRef` rather than restating it, so a `Compound` is accepted
 * anywhere a reference is expected and the two cannot drift apart.
 */
export interface Compound extends CompoundRef {
  readonly name: string;
  /** Owning project/repo slug, e.g. "beethoven". */
  readonly owner: string;
  /**
   * The wave series as declared at creation, in order. Immutable for the life
   * of the compound: re-planning means a new compound, so that a settled
   * compound's record still describes what actually ran.
   */
  readonly waves: readonly WaveSpec[];
  readonly labels: Readonly<Record<string, string>>;
  readonly createdAt: EpochMillis;
  /** Last status or progress change. Equals `createdAt` before the first wave. */
  readonly updatedAt: EpochMillis;
  /** Set only for a terminal status, and never cleared once set. */
  readonly terminalAt?: EpochMillis;
  /**
   * Highest event sequence applied to this compound. Callers compare against
   * `PlatformEventBase.sequence` to detect gaps; the platform uses it to reject
   * out-of-order delivery.
   */
  readonly appliedSequence: number;
  /** Why the compound reached `failed` or was cancelled. Absent otherwise. */
  readonly terminalReason?: string;
}

/** Rolled-up wave counts. Derived state — never a source of truth. */
export interface CompoundProgress {
  readonly compoundId: CompoundId;
  readonly total: number;
  readonly pending: number;
  readonly running: number;
  readonly settled: number;
  readonly failed: number;
  readonly skipped: number;
}

/**
 * Statuses from which no transition is legal.
 *
 * A type, not an array: `contracts/common.ts` documents `settled` and `failed`
 * as terminal, and expressing that as a type means a transition table that
 * forgets one fails to compile instead of being caught at runtime.
 */
export type TerminalCompoundStatus = Extract<CompoundStatus, "settled" | "failed">;

/** Statuses a compound can still leave. */
export type ActiveCompoundStatus = Exclude<CompoundStatus, TerminalCompoundStatus>;

/**
 * Legal compound transitions, as data.
 *
 * Terminal statuses map to `never`, so an implementation that tries to declare
 * a transition out of one cannot typecheck. This is the entity-layer statement
 * of the rule the contracts enforce with `precondition_failed`.
 */
export type CompoundTransitions = {
  readonly draft: "queued" | "failed";
  readonly queued: "running" | "failed";
  readonly running: "settled" | "failed";
  readonly settled: never;
  readonly failed: never;
};
