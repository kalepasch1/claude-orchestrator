/**
 * Event processing contract.
 *
 * Every observable state change on the platform is an event. Events are the
 * only supported way to learn that a wave finished, so this contract — not a
 * polling loop — is what a consumer builds against.
 *
 * Declaration-only: signatures, no implementations.
 */
import type {
  CompoundId,
  EpochMillis,
  EventId,
  Idempotent,
  Result,
  WaveId,
} from "./common.ts";
import type { WaveStatus } from "./wave.ts";

/** Discriminant for the platform event union. */
export type PlatformEventKind =
  | "compound.created"
  | "compound.cancelled"
  | "wave.triggered"
  | "wave.settled"
  | "wave.failed";

/** Fields present on every event regardless of kind. */
export interface PlatformEventBase {
  readonly eventId: EventId;
  readonly kind: PlatformEventKind;
  readonly compoundId: CompoundId;
  readonly occurredAt: EpochMillis;
  /**
   * Monotonically increasing per compound. A consumer uses it to detect gaps
   * and to order events that share an `occurredAt`.
   */
  readonly sequence: number;
}

export interface CompoundCreatedEvent extends PlatformEventBase {
  readonly kind: "compound.created";
  readonly name: string;
  readonly waveCount: number;
}

export interface CompoundCancelledEvent extends PlatformEventBase {
  readonly kind: "compound.cancelled";
  readonly reason: string;
}

export interface WaveTriggeredEvent extends PlatformEventBase {
  readonly kind: "wave.triggered";
  readonly waveId: WaveId;
  readonly waveName: string;
  readonly attempt: number;
  /** True when the trigger bypassed its `dependsOn` preconditions. */
  readonly forced: boolean;
}

export interface WaveSettledEvent extends PlatformEventBase {
  readonly kind: "wave.settled";
  readonly waveId: WaveId;
  readonly waveName: string;
  readonly durationMs: number;
}

export interface WaveFailedEvent extends PlatformEventBase {
  readonly kind: "wave.failed";
  readonly waveId: WaveId;
  readonly waveName: string;
  readonly attempt: number;
  readonly reason: string;
  /** True when the platform will re-trigger without caller action. */
  readonly willRetry: boolean;
}

/** Every event the platform emits. Exhaustive — switch on `kind`. */
export type PlatformEvent =
  | CompoundCreatedEvent
  | CompoundCancelledEvent
  | WaveTriggeredEvent
  | WaveSettledEvent
  | WaveFailedEvent;

/** Outcome of handing one event to the platform. */
export interface ProcessEventOutput {
  readonly eventId: EventId;
  /** False when the event was a duplicate and no state changed. */
  readonly applied: boolean;
  /** Resulting wave status, when the event concerned a wave. */
  readonly waveStatus?: WaveStatus;
}

/**
 * Ingest one event and apply its state transition.
 *
 * Contract:
 *  - is idempotent on `eventId`; a replayed event returns `applied: false`;
 *  - returns `conflict` when `sequence` is behind what has already been
 *    applied for that compound (out-of-order delivery);
 *  - returns `precondition_failed` for a transition out of a terminal status;
 *  - must not emit further events synchronously — a consumer that fans out
 *    does so from its own handler.
 */
export type ProcessEvent = (
  input: Idempotent & { readonly event: PlatformEvent },
) => Promise<Result<ProcessEventOutput>>;

/**
 * Subscribe to a compound's events. Returns an unsubscribe function.
 * Delivery is at-least-once, so a handler must be idempotent.
 */
export type SubscribeToEvents = (
  compoundId: CompoundId,
  handler: (event: PlatformEvent) => void | Promise<void>,
) => Promise<Result<() => void>>;
