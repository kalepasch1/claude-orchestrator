/**
 * Guess-rate limiter for the scoped proof endpoint.
 *
 * Share tokens carry 192 bits of entropy, so blind enumeration is already
 * infeasible; this exists to make *targeted* probing (a leaked partial link, a
 * scripted sweep) visibly pointless and to keep an unauthenticated endpoint
 * from being used as a free database-load generator.
 *
 * Keyed by client address only — never by token value, which is a credential
 * and is deliberately never stored, logged or used as a map key anywhere.
 *
 * The window is per serverless instance rather than global. That is a real
 * limitation (a spread-out attacker gets more attempts than the nominal cap),
 * and it is acceptable precisely because entropy, not this limiter, is what
 * makes guessing impossible. Treat this as a courtesy brake, not the control.
 */

const WINDOW_MS = 60_000
const MAX_PER_WINDOW = 30
/** Bound on memory so a spoofed-header flood cannot grow the map without limit. */
const MAX_TRACKED_CLIENTS = 5_000

const attempts = new Map<string, number[]>()

export type RateLimitDecision = {
  allowed: boolean
  remaining: number
  retryAfterSeconds: number
}

export function consumeProofLookup(
  clientKey: string,
  now: number = Date.now(),
  limit: number = MAX_PER_WINDOW,
  windowMs: number = WINDOW_MS,
): RateLimitDecision {
  const key = clientKey || 'unknown'
  const cutoff = now - windowMs

  if (attempts.size > MAX_TRACKED_CLIENTS) attempts.clear()

  const recent = (attempts.get(key) ?? []).filter((at) => at > cutoff)

  if (recent.length >= limit) {
    attempts.set(key, recent)
    const retryAfterMs = Math.max(0, (recent[0] ?? now) + windowMs - now)
    return { allowed: false, remaining: 0, retryAfterSeconds: Math.ceil(retryAfterMs / 1000) || 1 }
  }

  recent.push(now)
  attempts.set(key, recent)
  return { allowed: true, remaining: limit - recent.length, retryAfterSeconds: 0 }
}

/** Test hook. */
export function resetProofRateLimit(): void {
  attempts.clear()
}

/**
 * Best-effort client identity for rate limiting. Proxy headers are spoofable,
 * which is why exceeding the limit only slows a caller down and never grants or
 * denies access on its own.
 */
export function proofClientKey(headers: {
  forwardedFor?: string | null
  realIp?: string | null
  remoteAddress?: string | null
}): string {
  const forwarded = (headers.forwardedFor ?? '').split(',')[0]?.trim()
  return forwarded || (headers.realIp ?? '').trim() || (headers.remoteAddress ?? '').trim() || 'unknown'
}
