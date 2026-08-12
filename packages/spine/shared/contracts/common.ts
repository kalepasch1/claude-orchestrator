/**
 * Primitives shared by every spine contract.
 *
 * Declaration-only. Nothing in `shared/contracts` may carry a runtime value:
 * these files exist so a caller and an implementer can agree on a shape before
 * either one is written, which is what makes the spine composable across waves.
 */

/** Opaque identifier for a compound. Branded so a raw string cannot be passed by accident. */
export type CompoundId = string & { readonly __brand: "CompoundId" };

/** Opaque identifier for a single wave inside a compound. */
export type WaveId = string & { readonly __brand: "WaveId" };

/** Opaque identifier for one platform event. */
export type EventId = string & { readonly __brand: "EventId" };

/** Milliseconds since the Unix epoch. Contracts never carry `Date` across a boundary. */
export type EpochMillis = number;

/**
 * Lifecycle a compound moves through. `settled` and `failed` are terminal:
 * an implementation must reject any transition out of them.
 */
export type CompoundStatus =
  | "draft"
  | "queued"
  | "running"
  | "settled"
  | "failed";

/**
 * The minimum a caller needs to address a compound without owning the full
 * domain entity. The rich `Compound` entity lives in `shared/types` and is
 * layered on top of this reference; contracts intentionally depend only on
 * the reference so the operation surface stays stable while the entity grows.
 */
export interface CompoundRef {
  readonly id: CompoundId;
  readonly status: CompoundStatus;
}

/**
 * Uniform result envelope. Contracts return this rather than throwing so that
 * a failed operation is part of the type and cannot be silently ignored.
 */
export type Result<T, E = ContractError> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly error: E };

/** Machine-readable failure. `retryable` tells a caller whether to back off or give up. */
export interface ContractError {
  readonly code: ContractErrorCode;
  readonly message: string;
  readonly retryable: boolean;
  /** Free-form diagnostic payload. Never load-bearing for control flow. */
  readonly details?: Readonly<Record<string, unknown>>;
}

export type ContractErrorCode =
  | "invalid_input"
  | "not_found"
  | "conflict"
  | "precondition_failed"
  | "rate_limited"
  | "internal";

/**
 * Caller-supplied idempotency envelope. Every mutating contract takes one so a
 * retry after a timeout cannot double-apply.
 */
export interface Idempotent {
  /** Stable per logical attempt. Two calls with the same key must be one effect. */
  readonly idempotencyKey: string;
}
