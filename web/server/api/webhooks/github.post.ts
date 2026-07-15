import { readRawBody, getHeader, createError } from 'h3'
import { serviceClient } from '../../utils/fleetSupabase'
import { verifyHmac } from '../../utils/webhookAuth'

export default defineEventHandler(async (event) => {
  const raw = await readRawBody(event, 'utf8') || ''
  const secret = process.env.GITHUB_WEBHOOK_SECRET || ''
  if (!verifyHmac(raw, getHeader(event, 'x-hub-signature-256'), secret, 'sha256='))
    throw createError({ statusCode: 401, message: 'invalid_webhook_signature' })
  const payload = JSON.parse(raw); const eventId = getHeader(event, 'x-github-delivery')
  if (!eventId) throw createError({ statusCode: 400, message: 'missing_delivery_id' })
  const { error } = await serviceClient().from('delivery_events').upsert({
    provider: 'github', event_id: eventId, event_type: getHeader(event, 'x-github-event') || 'unknown', payload,
  }, { onConflict: 'provider,event_id', ignoreDuplicates: true })
  if (error) throw createError({ statusCode: 500, message: error.message })
  return { accepted: true, eventId }
})
