// Growth OS event emitter (TypeScript / JS apps).
// Drop into any product (Nuxt/Node). Fire-and-forget; never blocks or breaks the app.
//
// Usage:
//   import { growth } from '~/growth-os/emit'
//   growth('apparently').track('signup', { channel: 'organic', segment: 'apparently/licensing/dfs-startup' })
//   growth('apparently').track('revenue', { value: 5000, segment: 'apparently/licensing/nj', dedupKey: order.id })
//
// PRIVACY: pass a raw user id via `actorId` and it is hashed locally before it ever leaves the app.
// Never send emails/names. Payload is metadata only.

import { createHash } from 'node:crypto'

const ORCH_URL = process.env.ORCH_SUPABASE_URL || process.env.GROWTH_OS_URL || ''
const ORCH_ANON = process.env.ORCH_SUPABASE_ANON_KEY || process.env.GROWTH_OS_ANON || ''
const SALT = process.env.GROWTH_ACTOR_SALT || 'rotate-me'

type TrackOpts = {
  segment?: string
  channel?: 'organic' | 'paid' | 'referral' | 'content' | 'outbound' | 'direct' | string
  source?: string
  value?: number
  actorId?: string          // raw id — hashed locally, never transmitted
  props?: Record<string, unknown>
  dedupKey?: string
}

function hashActor(app: string, id?: string): string | null {
  if (!id) return null
  return createHash('sha256').update(`${app}:${id}:${SALT}`).digest('hex')
}

export function growth(app: string) {
  return {
    async track(eventType: string, opts: TrackOpts = {}): Promise<void> {
      if (!ORCH_URL || !ORCH_ANON) return // no-op if unconfigured — never break the app
      try {
        await fetch(`${ORCH_URL}/rest/v1/rpc/emit_growth_event`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            apikey: ORCH_ANON,
            Authorization: `Bearer ${ORCH_ANON}`,
          },
          body: JSON.stringify({
            p_app: app,
            p_event_type: eventType,
            p_segment: opts.segment ?? null,
            p_channel: opts.channel ?? null,
            p_source: opts.source ?? null,
            p_actor_hash: hashActor(app, opts.actorId),
            p_value: opts.value ?? 0,
            p_props: opts.props ?? {},
            p_dedup_key: opts.dedupKey ?? null,
          }),
          // keepalive so it survives page unload; short timeout via AbortSignal
          keepalive: true,
          signal: AbortSignal.timeout(2500),
        })
      } catch {
        /* swallow — growth telemetry must never affect product UX */
      }
    },
  }
}
