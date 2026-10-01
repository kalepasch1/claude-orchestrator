import { createHash, timingSafeEqual } from 'node:crypto'

/**
 * THE FLEET RELAY FAILS CLOSED (owner decision, 2026-10-01).
 *
 * /api/_fleet-relay used to gate on FLEET_RELAY_KEY only "when configured":
 * with the variable unset, any caller could use it as a transport to the
 * allowlisted Supabase projects. Now a request is admitted only when the key
 * IS configured AND the caller's x-fleet-relay-key matches it. Both sides are
 * hashed first so the comparison is constant-time and length-independent.
 */
export function fleetRelayKeyMatches (provided: unknown, required: string | undefined = process.env.FLEET_RELAY_KEY): boolean {
  if (typeof required !== 'string' || required.trim().length === 0) return false
  if (typeof provided !== 'string' || provided.length === 0) return false
  const a = createHash('sha256').update(provided).digest()
  const b = createHash('sha256').update(required).digest()
  return timingSafeEqual(a, b)
}
