/**
 * Wave triggering contract.
 *
 * Triggering is the only way work starts. It is deliberately fire-and-observe:
 * the call returns as soon as the wave is accepted, and progress is reported
 * through the event stream (`./event.ts`) rather than by blocking the caller.
 *
 * Declaration-only: signatures, no implementations.
 */
import type {
  CompoundId,
  EpochMillis,
  Idempotent,
  Result,
  WaveId,
} from "./common.ts";

/** Lifecycle of a single wave. `settled`, `failed` and `skipped` are terminal. */
export type WaveStatus =
  | "pending"
  | "running"
  | "settled"
  | "failed"
  | "skipped";

/** What the caller must supply to start a wave. */
export interface TriggerWaveInput extends Idempotent {
  readonly compoundId: CompoundId;
  /** Wave name as declared in the compound's `WaveSpec`. */
  readonly waveName: string;
  /**
   * Bypass the `dependsOn` precondition check. Reserved for operator recovery;
   * an implementation must record it in the emitted event.
   */
  readonly force?: boolean;
}

/** Acknowledgement that a wave was accepted for execution. */
export interface TriggerWaveOutput {
  readonly waveId: WaveId;
  readonly compoundId: CompoundId;
  /** Always `"pending"` or `"running"` — never terminal at accept time. */
  readonly status: WaveStatus;
  readonly acceptedAt: EpochMillis;
  /** True when the same idempotency key already started this wave. */
  readonly deduplicated: boolean;
}

/**
 * Start one wave of a compound.
 *
 * Contract:
 *  - is idempotent on `idempotencyKey`; a retry returns the original `waveId`;
 *  - returns `precondition_failed` when a `dependsOn` wave has not settled and
 *    `force` is not set;
 *  - returns `conflict` when the wave is already running or terminal;
 *  - returns `not_found` for an unknown compound or wave name;
 *  - does NOT wait for completion — observe `WaveSettled` on the event stream.
 */
export type TriggerWave = (
  input: TriggerWaveInput,
) => Promise<Result<TriggerWaveOutput>>;

/** Point-in-time view of a wave. Pure read, no side effects. */
export interface WaveState {
  readonly waveId: WaveId;
  readonly compoundId: CompoundId;
  readonly name: string;
  readonly status: WaveStatus;
  readonly attempt: number;
  readonly startedAt?: EpochMillis;
  readonly settledAt?: EpochMillis;
}

/** Read one wave's current state. */
export type GetWave = (waveId: WaveId) => Promise<Result<WaveState>>;

/** Read every wave of a compound, in declaration order. */
export type ListWaves = (
  compoundId: CompoundId,
) => Promise<Result<readonly WaveState[]>>;
