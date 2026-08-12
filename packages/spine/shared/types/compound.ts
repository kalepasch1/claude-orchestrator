/**
 * Core domain entity for the compounding code-generation platform.
 *
 * Layering: `shared/contracts` owns the *operations* and the thin `CompoundRef`
 * that operations pass around; this file owns the *entity* — the full record a
 * store persists and a reader inspects. The split is deliberate. The contract
 * surface must stay stable while the entity grows fields, so contracts depend
 * on the reference and never on `Compound` itself.
 */
import type {
  CompoundId,
  CompoundRef,
  CompoundStatus,
  EpochMillis,
} from "../contracts/common.ts";
import type { WaveSpec } from "../contracts/compound.ts";
import type { WaveState } from "../contracts/wave.ts";

/**
 * Represents a compound event — a named, ordered series of waves whose output
 * compounds: wave N may read the settled output of wave N-1. This is the whole
 * persisted record, including execution state.
 */
export interface Compound {
  readonly id: CompoundId;
  /** Human-readable name, unique within `owner`. */
  readonly name: string;
  /** Owning project/repo slug, e.g. "beethoven". */
  readonly owner: string;
  /** Current lifecycle position. `settled` and `failed` are terminal. */
  readonly status: CompoundStatus;

  /** Declarative plan, in declaration order. Immutable after creation. */
  readonly waves: readonly WaveSpec[];
  /**
   * Live execution state, one entry per spec, in the same order. Empty until
   * the first `triggerWave`; a spec with no state has simply not started.
   */
  readonly waveStates: readonly WaveState[];

  /** Highest event `sequence` applied to this compound. Detects gaps/replays. */
  readonly sequence: number;

  readonly createdAt: EpochMillis;
  readonly updatedAt: EpochMillis;
  /** Set only once a terminal status is reached. */
  readonly settledAt?: EpochMillis;
  /** Present when `status` is `"failed"` or the compound was cancelled. */
  readonly failureReason?: string;

  /** Free-form labels for routing and reporting. Never load-bearing. */
  readonly labels?: Readonly<Record<string, string>>;
}

/** The subset of `Compound` that is safe to hand to a contract operation. */
export type CompoundReference = CompoundRef;

/** True when a compound can no longer change state. */
export type TerminalCompoundStatus = Extract<CompoundStatus, "settled" | "failed">;

/**
 * A compound that has reached a terminal status. Narrowing to this type
 * guarantees `settledAt` is populated, so readers need no optional check.
 */
export interface SettledCompound extends Compound {
  readonly status: TerminalCompoundStatus;
  readonly settledAt: EpochMillis;
}

/**
 * Shape a store returns for list/index views: identity and progress without
 * the full wave plan, so a listing does not pay for every spec.
 */
export interface CompoundSummary {
  readonly id: CompoundId;
  readonly name: string;
  readonly owner: string;
  readonly status: CompoundStatus;
  readonly waveCount: number;
  readonly settledWaveCount: number;
  readonly updatedAt: EpochMillis;
}
