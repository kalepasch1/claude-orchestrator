/**
 * The stored form of a platform event.
 *
 * `contracts/event.ts` defines the event union that crosses the boundary. This
 * adds only what persistence needs and the wire deliberately does not carry:
 * when the platform applied the event, and whether it did.
 *
 * The union itself is NOT restated here. Re-declaring it would create a second
 * definition to keep in step, and the point of the contract layer is that there
 * is exactly one.
 *
 * Declaration-only.
 */
import type { EpochMillis, EventId } from "../contracts/common.ts";
import type { PlatformEvent, PlatformEventKind } from "../contracts/event.ts";

/**
 * One entry in a compound's append-only event log.
 *
 * `event` is the wire event verbatim, so the log replays exactly what was
 * delivered. Everything else is what the platform observed about handling it.
 */
export interface StoredEvent {
  readonly eventId: EventId;
  /** The delivered event, unmodified. */
  readonly event: PlatformEvent;
  /** When the platform durably recorded it — distinct from `occurredAt`. */
  readonly recordedAt: EpochMillis;
  /**
   * False when the event was a duplicate or arrived out of order and changed no
   * state. Recorded either way: a rejected delivery is evidence, and dropping
   * it would hide a producer that is replaying or racing.
   */
  readonly applied: boolean;
  /** Why an unapplied event was not applied. Absent when `applied` is true. */
  readonly rejectionReason?: EventRejectionReason;
}

/**
 * Why the platform declined to apply a delivered event.
 *
 * These mirror the failure modes `ProcessEvent` documents, kept as a closed set
 * so a log consumer can branch on them exhaustively.
 */
export type EventRejectionReason =
  | "duplicate"
  | "out_of_order"
  | "terminal_status"
  | "unknown_compound";

/**
 * Position in a compound's event log.
 *
 * Delivery is at-least-once, so a consumer resumes from a cursor rather than
 * from a timestamp: `occurredAt` can tie, `sequence` cannot.
 */
export interface EventCursor {
  /** Last sequence the consumer has fully handled. Zero before the first event. */
  readonly sequence: number;
  readonly eventId?: EventId;
}

/** Narrow the stored event union by wire event kind. */
export type StoredEventOfKind<K extends PlatformEventKind> = StoredEvent & {
  readonly event: Extract<PlatformEvent, { readonly kind: K }>;
};
