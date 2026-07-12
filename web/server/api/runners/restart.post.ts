// POST /api/runners/restart  { host: string }
// Inserts a controls row requesting a runner restart for the given host.
// Pattern matches other fleet control endpoints (controls table, scope/target/action).
import { createClient } from '@supabase/supabase-js'

export default defineEventHandler(async (event) => {
  const body = (await readBody(event)) as { host?: string }
  if (!body?.host || typeof body.host !== 'string') {
    throw createError({ statusCode: 400, message: 'host is required' })
  }

  const url = process.env.SUPABASE_URL || process.env.NUXT_SUPABASE_URL || ''
  const key = process.env.SUPABASE_SERVICE_KEY || process.env.NUXT_SUPABASE_SERVICE_KEY || ''
  if (!url || !key) {
    throw createError({ statusCode: 500, message: 'supabase not configured' })
  }

  const sb = createClient(url, key)
  const { error } = await sb.from('controls').insert({
    scope: 'runner',
    target: body.host,
    action: 'restart',
    value: JSON.stringify({ requested_at: new Date().toISOString() }),
  })

  if (error) {
    throw createError({ statusCode: 500, message: error.message })
  }

  return { ok: true, host: body.host }
})
