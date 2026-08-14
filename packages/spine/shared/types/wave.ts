/**
 * The wave domain entity.
 *
 * `contracts/wave.ts` exposes `WaveState` — the point-in-time view a caller
 * reads. This is the stored record behind it: the declared spec, the attempt
 * history and the settled output that the next wave consumes. Keeping the two
 * apart is what makes compounding work, because wave N reads N-1's *output*,
 * and output is entity state, not part of the read contract.
 *
 * Declaration-only.
 */
import type { EpochMillis, WaveId } from "../contracts/common.ts";
import type { WaveSpec } from "../contracts/compound.ts";
import type { WaveState, WaveStatus } from "../contracts/wave.ts";

/**
 * A wave as the platform stores it.
 *
 * Extends `WaveState` so it satisfies every read the contract exposes, and adds
 * only what the contract deliberately withholds.
 */
export interface Wave extends WaveState {
  /** The spec this wave was created from. Immutable for the wave's life. */
  readonly spec: WaveSpec;
  /**
   * One record per attempt, oldest first. Retries append; nothing is
   * overwritten, so a wave that eventually settled still shows what failed.
   */
  readonly attempts: readonly WaveAttempt[];
  /**
   * What this wave produced, available only once `status` is `"settled"`.
   * This is the compounding seam: the next wave's input.
   */
  readonly output?: WaveOutput;
  /** Why the wave reached `failed` or was `skipped`. Absent otherwise. */
  readonly terminalReason?: string;
}

/** One execution attempt. Immutable once written. */
export interface WaveAttempt {
  /** 1-based, matching `WaveState.attempt`. */
  readonly attempt: number;
  readonly status: WaveStatus;
  readonly startedAt: EpochMillis;
  readonly endedAt?: EpochMillis;
  /** Present when this attempt did not settle. */
  readonly failureReason?: string;
  /** True when the platform re-triggered without caller action. */
  readonly retried: boolean;
}

/**
 * A settled wave's product.
 *
 * `artifacts` is a map rather than a blob so a downstream wave can depend on
 * one named output without reading — or breaking on — the rest.
 */
export interface WaveOutput {
  readonly waveId: WaveId;
  readonly producedAt: EpochMillis;
  readonly artifacts: Readonly<Record<string, WaveArtifact>>;
}

/**
 * One named product of a wave.
 *
 * Carries a `digest` because compounding depends on knowing whether an upstream
 * output actually changed: without it, every downstream wave has to re-run on
 * every trigger.
 */
export interface WaveArtifact {
  /** Where the artifact lives — a repo path, ref, or URI. Never inline content. */
  readonly location: string;
  /** Content hash, so a consumer can tell a real change from a re-run. */
  readonly digest: string;
  readonly sizeBytes?: number;
  readonly mediaType?: string;
}

/**
 * Legal wave transitions, as data. Terminal statuses map to `never` so an
 * implementation cannot declare a way out of one.
 */
export type WaveTransitions = {
  readonly pending: "running" | "skipped" | "failed";
  readonly running: "settled" | "failed";
  readonly settled: never;
  readonly failed: never;
  readonly skipped: never;
};

/** Statuses from which no transition is legal. */
export type TerminalWaveStatus = Extract<
  WaveStatus,
  "settled" | "failed" | "skipped"
>;

/** Statuses a wave can still leave. */
export type ActiveWaveStatus = Exclude<WaveStatus, TerminalWaveStatus>;
