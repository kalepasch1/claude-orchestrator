/**
 * Nitro server middleware — Supabase auth gate for all /api/ routes.
 *
 * Extracts the access token from:
 *   1. `sb-access-token` cookie (explicit)
 *   2. `Authorization: Bearer <token>` header
 *   3. Nuxt Supabase module cookie (`sb-<ref>-auth-token` JSON with .access_token)
 *
 * Validates via supabase.auth.getUser(token) using the service role client,
 * then accepts either a legacy operator email or an active organization membership.
 *
 * Sets event.context.user = { id, email } on success.
 */
import { createClient } from '@supabase/supabase-js'
import { createError, getCookie, getHeader, parseCookies, defineEventHandler } from 'h3'

const ACCESS_COOKIE = 'sb-access-token'
const PUBLIC_ACCESS_PATHS = new Set([
  '/api/public/access/verify',
  '/api/public/access/request',
  '/api/public/access/claim',
  '/api/public/access/status',
  '/api/public/portfolio-simulation',
  // Machine-to-machine delivery hooks authenticate their raw body with an
  // HMAC in the route; requiring a Supabase user token would make them inert.
  '/api/webhooks/github',
  '/api/webhooks/vercel',
  // VIGIL receiver performs bearer-key and HMAC verification in-handler.
  '/api/integrations/vigil',
])

const DEFAULT_OPS_EMAILS = 'kalepasch@gmail.com,kale@smrter.us,kale@heretomorrow.us'

function getAllowedEmails(): Set<string> {
  const raw = process.env.OPS_EMAILS || DEFAULT_OPS_EMAILS
  return new Set(
    raw
      .split(',')
      .map((e) => e.trim().toLowerCase())
      .filter(Boolean),
  )
}

function getAccessToken(event: any): string | null {
  // 1. Explicit sb-access-token cookie
  const cookie = getCookie(event, ACCESS_COOKIE)
  if (cookie) return cookie

  // 2. Authorization: Bearer header
  const auth = getHeader(event, 'authorization')
  if (auth?.startsWith('Bearer ')) return auth.slice(7)

  // 3. Nuxt Supabase module cookie: sb-<project-ref>-auth-token (JSON with .access_token)
  const cookies = parseCookies(event)
  for (const [name, value] of Object.entries(cookies)) {
    if (/^sb-[a-z0-9]+-auth-token$/.test(name) && value) {
      try {
        const parsed = JSON.parse(value as string)
        if (parsed?.access_token) return parsed.access_token
      } catch {
        // Not valid JSON — skip
      }
    }
  }

  return null
}

export default defineEventHandler(async (event) => {
  const path = event.path || event.node.req.url || ''
  const pathname = path.split('?')[0]

  // Only protect /api/ routes
  if (!path.startsWith('/api/')) return
  if (PUBLIC_ACCESS_PATHS.has(pathname)) return

  // Vercel cron requests are server-to-server and do not have a Supabase
  // session. Limit this exception to the single scheduled analytics sync and
  // require Vercel's CRON_SECRET header; all interactive callers still take
  // the normal Supabase authorization path below.
  const cronSecret = process.env.CRON_SECRET
  const authorization = getHeader(event, 'authorization')
  if (
    pathname === '/api/fleet/analytics' &&
    cronSecret &&
    authorization === `Bearer ${cronSecret}`
  ) {
    event.context.cron = true
    return
  }

  const token = getAccessToken(event)
  if (!token) {
    throw createError({
      statusCode: 401,
      statusMessage: 'Unauthorized',
      message: 'Missing access token',
    })
  }

  const supabaseUrl = process.env.SUPABASE_URL
  const serviceKey = process.env.SUPABASE_SERVICE_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY
  if (!supabaseUrl || !serviceKey) {
    throw createError({
      statusCode: 500,
      statusMessage: 'Internal Server Error',
      message: 'Supabase configuration missing',
    })
  }

  const supabase = createClient(supabaseUrl, serviceKey)
  const { data, error } = await supabase.auth.getUser(token)

  if (error || !data?.user) {
    throw createError({
      statusCode: 401,
      statusMessage: 'Unauthorized',
      message: 'Invalid or expired token',
    })
  }

  const email = data.user.email?.toLowerCase()
  if (!email) {
    throw createError({
      statusCode: 403,
      statusMessage: 'Forbidden',
      message: 'No email associated with account',
    })
  }

  const allowed = getAllowedEmails()
  if (!allowed.has(email)) {
    const { data: membership, error: membershipError } = await supabase.from('orchestrator_org_memberships').select('user_id').eq('user_id', data.user.id).eq('status', 'active').limit(1).maybeSingle()
    if (membershipError || !membership) throw createError({ statusCode: 403, statusMessage: 'Forbidden', message: 'Active Madeus membership required' })
  }

  event.context.user = { id: data.user.id, email }
})
