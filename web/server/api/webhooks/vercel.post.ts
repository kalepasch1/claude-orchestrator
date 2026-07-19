import { readRawBody, getHeader, createError } from 'h3'
import { serviceClient } from '../../utils/fleetSupabase'
import { verifyHmac } from '../../utils/webhookAuth'

export default defineEventHandler(async (event) => {
  const raw = await readRawBody(event, 'utf8') || ''; const secret = process.env.VERCEL_WEBHOOK_SECRET || ''
  if (!verifyHmac(raw, getHeader(event, 'x-vercel-signature'), secret))
    throw createError({ statusCode: 401, message: 'invalid_webhook_signature' })
  const payload = JSON.parse(raw); const eventId = String(payload.id || payload.createdAt || '')
  if (!eventId) throw createError({ statusCode: 400, message: 'missing_event_id' })
  const { error } = await serviceClient().from('delivery_events').upsert({
    provider: 'vercel', event_id: eventId, event_type: payload.type || 'deployment', payload,
  }, { onConflict: 'provider,event_id', ignoreDuplicates: true })
  if (error) throw createError({ statusCode: 500, message: error.message })
  return { accepted: true, eventId }
})
