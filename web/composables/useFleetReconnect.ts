// useFleetReconnect — reconnection policy for the fleet realtime subscription.
//
// SLICE 2 of "real-time sync between web and runner": reconnection + error handling
// on the client. Deliberately scoped to the client policy so it is independently
// mergeable; the server-side heartbeat/stale-connection sweep is a separate slice and
// is listed at the bottom of this file so it stays discoverable.
//
// The transport is a Supabase Realtime channel, not a raw WebSocket, so "the connection
// dropped" arrives as a subscribe-callback status (CHANNEL_ERROR / TIMED_OUT / CLOSED)
// rather than an onclose event. What was missing was any response to those statuses at
// all: `connected` flipped to false and the page then sat there showing stale task rows
// with no indication that it had stopped receiving updates, which is worse than an
// obvious disconnect because it looks like a quiet fleet.
//
// The policy is a plain object with no Vue or Supabase imports so it can be tested with
// fake timers and no socket.

/** Statuses the Supabase subscribe callback reports. */
export type ChannelStatus =
  | 'SUBSCRIBED'
  | 'CHANNEL_ERROR'
  | 'TIMED_OUT'
  | 'CLOSED'
  | string

/** Statuses that mean the subscription is no longer delivering messages. */
const DEAD_STATUSES = new Set(['CHANNEL_ERROR', 'TIMED_OUT', 'CLOSED'])

export function isDeadStatus(status: ChannelStatus): boolean {
  return DEAD_STATUSES.has(String(status || '').toUpperCase())
}

export interface BackoffOptions {
  /** Delay before the first retry, in ms. */
  baseMs?: number
  /** Ceiling for any single delay, in ms. */
  maxMs?: number
  /** Multiplier applied per attempt. */
  factor?: number
  /**
   * Fraction of the delay to randomise, 0..1. Jitter matters here because every open
   * dashboard tab loses the channel at the same instant when the realtime service
   * blips, and without it they all retry in lockstep.
   */
  jitter?: number
  /** Give up after this many consecutive failures. */
  maxAttempts?: number
}

export const RECONNECT_DEFAULTS: Required<BackoffOptions> = {
  baseMs: 1000,
  maxMs: 30000,
  factor: 2,
  jitter: 0.2,
  maxAttempts: 8,
}

/**
 * Delay before retry number `attempt` (1-based). Pure and deterministic when
 * `random` is supplied, which is what makes the schedule assertable in a test.
 *
 * Never returns NaN or a negative number: a bad option value falls back to the
 * default rather than scheduling a timer that fires immediately in a tight loop.
 */
export function nextBackoffDelay(
  attempt: number,
  options: BackoffOptions = {},
  random: () => number = Math.random,
): number {
  const opts = { ...RECONNECT_DEFAULTS, ...options }
  const num = (value: number, fallback: number) =>
    typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : fallback

  const baseMs = num(opts.baseMs, RECONNECT_DEFAULTS.baseMs)
  const maxMs = num(opts.maxMs, RECONNECT_DEFAULTS.maxMs)
  const factor = num(opts.factor, RECONNECT_DEFAULTS.factor) || RECONNECT_DEFAULTS.factor
  const jitter = Math.min(1, num(opts.jitter, RECONNECT_DEFAULTS.jitter))

  const n = Math.max(1, Math.floor(Number(attempt) || 1))
  const raw = baseMs * Math.pow(factor, n - 1)
  const capped = Math.min(raw, maxMs)

  // Floor of 1ms everywhere, jitter or not: a 0ms retry is a busy loop, not a retry.
  if (jitter <= 0) return Math.max(1, Math.round(capped))
  // Symmetric jitter around the capped delay, clamped so it can never exceed maxMs
  // and never collapses to 0 (a 0ms retry is a busy loop, not a retry).
  const spread = capped * jitter
  const jittered = capped - spread + random() * spread * 2
  return Math.round(Math.max(1, Math.min(maxMs, jittered)))
}

export interface ReconnectPolicy {
  /** Consecutive failures since the last successful subscribe. */
  readonly attempts: number
  /** True once maxAttempts consecutive failures have been recorded. */
  readonly exhausted: boolean
  /**
   * Record a failure and return the delay to wait before retrying, or null when
   * the attempt budget is spent and the caller should stop.
   */
  fail(): number | null
  /** Record a successful subscribe: clears the attempt count. */
  succeed(): void
  /** Forget all history (used on teardown). */
  reset(): void
}

export function createReconnectPolicy(
  options: BackoffOptions = {},
  random: () => number = Math.random,
): ReconnectPolicy {
  const opts = { ...RECONNECT_DEFAULTS, ...options }
  const maxAttempts = Math.max(0, Math.floor(Number(opts.maxAttempts) || 0))
  let attempts = 0

  return {
    get attempts() {
      return attempts
    },
    get exhausted() {
      return attempts >= maxAttempts
    },
    fail() {
      if (attempts >= maxAttempts) return null
      attempts += 1
      return nextBackoffDelay(attempts, opts, random)
    },
    succeed() {
      attempts = 0
    },
    reset() {
      attempts = 0
    },
  }
}

/**
 * The message a client sends after reconnecting to catch up on anything it missed
 * while disconnected. Named by the spec; kept here so both sides import one constant
 * instead of two string literals that can drift.
 */
export const REQUEST_INITIAL_STATE = 'request-initial-state' as const

export interface RequestInitialStateMessage {
  type: typeof REQUEST_INITIAL_STATE
  /**
   * ISO timestamp of the last event this client actually saw. The server (or, here,
   * the catch-up query) only has to replay changes newer than this, so a reconnect
   * after a two-second blip does not refetch the whole task table.
   */
  since: string | null
  /** How many reconnect attempts it took, for diagnosis in the event log. */
  attempts: number
}

export function buildRequestInitialState(
  since: string | null,
  attempts = 0,
): RequestInitialStateMessage {
  return { type: REQUEST_INITIAL_STATE, since: since ?? null, attempts }
}

// NEXT SLICES (not in this patch, kept discoverable rather than widening it):
//  * server heartbeat/ping-pong + stale-connection cleanup, with a test that
//    simulates a disconnect and asserts the server drops the client;
//  * wiring `request-initial-state` to an actual catch-up query against tasks
//    (`updated_at > since`) so the re-sync replays missed rows rather than only
//    announcing that it wants them.
