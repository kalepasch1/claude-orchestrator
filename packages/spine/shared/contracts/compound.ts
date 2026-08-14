/**
 * Compound creation contract.
 *
 * A *compound* is the unit of compounding work on the platform: a named series
 * of waves whose output feeds the next wave's input. Creating one only
 * registers the series and its policy — it does not start any wave. Starting is
 * `triggerWave`, deliberately a separate operation so a compound can be
 * reviewed before it runs.
 *
 * Declaration-only: signatures, no implementations.
 */
import type {
  CompoundId,
  CompoundRef,
  CompoundStatus,
  EpochMillis,
  Idempotent,
  Result,
} from "./common.ts";

/** What the caller must supply to register a compound. */
export interface CreateCompoundInput extends Idempotent {
  /** Human-readable name, unique within an owner. */
  readonly name: string;
  /** Owning project/repo slug, e.g. "beethoven". */
  readonly owner: string;
  /**
   * Ordered wave specifications. Order is meaningful: wave N may read the
   * settled output of wave N-1. An empty list is invalid.
   */
  readonly waves: readonly WaveSpec[];
  /** Optional free-form labels for routing and reporting. Never load-bearing. */
  readonly labels?: Readonly<Record<string, string>>;
}

/** Declarative description of one wave. Contains no execution state. */
export interface WaveSpec {
  /** Unique within its compound. */
  readonly name: string;
  /**
   * Names of waves in the same compound that must settle before this one may
   * be triggered. Must be acyclic; an implementation rejects cycles as
   * `invalid_input`.
   */
  readonly dependsOn?: readonly string[];
  /** Hard ceiling on wall-clock runtime. Exceeding it fails the wave. */
  readonly timeoutMs?: number;
  /** How many times the platform may re-trigger the wave after failure. */
  readonly maxAttempts?: number;
}

/** What the caller gets back once the compound is registered. */
export interface CreateCompoundOutput {
  readonly compound: CompoundRef;
  readonly createdAt: EpochMillis;
  /**
   * True when an existing compound was returned because the idempotency key
   * had already been used. The caller should treat this as success, not a
   * conflict.
   */
  readonly deduplicated: boolean;
}

/**
 * Register a new compound.
 *
 * Contract:
 *  - never starts a wave; the returned status is always `"draft"`;
 *  - is idempotent on `idempotencyKey`;
 *  - rejects an empty or cyclic wave list with `invalid_input`;
 *  - rejects a duplicate (owner, name) with `conflict`.
 */
export type CreateCompound = (
  input: CreateCompoundInput,
) => Promise<Result<CreateCompoundOutput>>;

/** Read a compound's current reference by id. Pure read, no side effects. */
export type GetCompound = (
  id: CompoundId,
) => Promise<Result<CompoundRef>>;

/**
 * Move a compound to a terminal status ahead of schedule. Only valid from a
 * non-terminal status; from `settled`/`failed` it returns `precondition_failed`.
 */
export type CancelCompound = (
  input: Idempotent & { readonly id: CompoundId; readonly reason: string },
) => Promise<Result<{ readonly id: CompoundId; readonly status: CompoundStatus }>>;
