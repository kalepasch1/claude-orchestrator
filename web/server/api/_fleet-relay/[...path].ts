/**
 * Supabase transport relay for the runner fleet, hosted on madeus.cc.
 *
 * WHY THIS EXISTS (2026-08-04). The operator's LAN blocks the Cloudflare/Vercel IP ranges
 * that serve `*.supabase.co` AND `*.vercel.app`, while custom domains (madeus.cc,
 * apparently.cc, heretomorrow.co) and raw Postgres ports resolve to different IPs and stay
 * reachable. A first relay deployed on a `*.vercel.app` hostname therefore inherited exactly
 * the block it was meant to route around, and the fleet's DB transport flapped at ~30%
 * reachability — every runner heartbeat, task claim and state write rides on it.
 *
 * madeus.cc is the fleet's own console and already carries a custom domain, so the fleet's
 * control-plane transport lives here rather than on a hostname the operator's network drops.
 *
 * SECURITY MODEL — this relay holds NO credentials of its own:
 *   - callers must present their own `apikey`/`Authorization`; Supabase enforces them,
 *   - targets are restricted to a fixed allowlist of this account's project refs, so it
 *     cannot be used as an open proxy,
 *   - a shared secret (`x-fleet-relay-key` vs FLEET_RELAY_KEY) gates use when configured.
 * It is a transport, not an authority.
 */
import {
  defineEventHandler, getRequestHeader, readRawBody, setResponseStatus,
  setResponseHeader, getQuery,
} from 'h3'

const ALLOWED_REFS = new Set([
  'eatfwdzfurujcuwlhdgj', // claude-orchestrator (fleet control plane)
  'oosolxvlfyifkhjohdzq', // apparently
  'edetxpcoaiqlqrwyzltw', // tomorrow
  'jygxrfpswgpmtspfoawy', // pareto-2080
  'whhfugddqehxxbmwutsw', // hisanta
  'qlzsnuspiypyejaqcdad', // racefeed
  'cwmeqqtvmjbapjsefbfq', // apparently-law
  'tsefmbiprirwcgqefemb', // illuminati
  'hjortulytchuaptnuciz', // vigil
  'rpsnzlyhnvswqoyhzwrb', // prediction-markets-institute
  'xnzrxkjixouzcizjemjg', // darwn
  'kyxsarhgjyhfujcgbogc', // lifeparty
  'olaxnyrzoptjcntrrjgn', // smarter
  'dpkkpkysaqnjvhhnphio', // smarter-mpc-trustee-a
  'bdmspfysrelrxfvkpbws', // smarter-mpc-trustee-b
])
const DEFAULT_REF = 'eatfwdzfurujcuwlhdgj'

const FORWARD_REQ_HEADERS = [
  'apikey', 'authorization', 'content-type', 'prefer', 'range', 'range-unit',
  'accept', 'accept-profile', 'content-profile', 'x-client-info', 'x-upsert',
]
const FORWARD_RES_HEADERS = [
  'content-type', 'content-range', 'preference-applied', 'range-unit',
  'x-total-count', 'location', 'sb-gateway-version',
]

export default defineEventHandler(async (event) => {
  const requiredKey = process.env.FLEET_RELAY_KEY
  if (requiredKey && getRequestHeader(event, 'x-fleet-relay-key') !== requiredKey) {
    setResponseStatus(event, 403)
    return { error: 'relay key required' }
  }

  const ref = (getRequestHeader(event, 'x-supabase-ref') || DEFAULT_REF).trim()
  if (!ALLOWED_REFS.has(ref)) {
    setResponseStatus(event, 403)
    return { error: 'ref not allowed' }
  }

  // Everything after /api/_fleet-relay/ is the upstream Supabase path (e.g. rest/v1/tasks).
  const segments = String(event.context.params?.path || '')
  if (!segments || segments === 'healthz') {
    return { ok: true, relay: 'madeus-fleet-relay', ref }
  }

  const query = getQuery(event)
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) {
    if (Array.isArray(v)) v.forEach((one) => qs.append(k, String(one)))
    else if (v !== undefined && v !== null) qs.append(k, String(v))
  }
  const target = `https://${ref}.supabase.co/${segments}${qs.toString() ? `?${qs}` : ''}`

  const headers: Record<string, string> = {}
  for (const h of FORWARD_REQ_HEADERS) {
    const v = getRequestHeader(event, h)
    if (v) headers[h] = v
  }

  const init: RequestInit = { method: event.method, headers, redirect: 'manual' }
  if (event.method !== 'GET' && event.method !== 'HEAD') {
    const raw = await readRawBody(event, false)
    if (raw && (raw as Buffer).length) init.body = raw as any
  }

  try {
    const upstream = await fetch(target, init)
    setResponseStatus(event, upstream.status)
    for (const h of FORWARD_RES_HEADERS) {
      const v = upstream.headers.get(h)
      if (v) setResponseHeader(event, h, v)
    }
    return Buffer.from(await upstream.arrayBuffer())
  } catch (err: any) {
    setResponseStatus(event, 502)
    return { error: 'relay failure', detail: String(err?.message || err) }
  }
})
