import { createHash, createHmac, timingSafeEqual } from 'node:crypto'

const TARGET = 'orchestrator'
const sha = (value: string) => createHash('sha256').update(value).digest('hex')

export default defineEventHandler(async (event) => {
  const apiKey = process.env.VIGIL_RECEIVER_API_KEY
  const signingSecret = process.env.VIGIL_RECEIVER_SIGNING_SECRET
  if (!apiKey || !signingSecret) throw createError({ statusCode: 503, statusMessage: 'VIGIL receiver is not configured' })
  const authorization = getHeader(event, 'authorization') || ''
  if (authorization !== `Bearer ${apiKey}`) throw createError({ statusCode: 401, statusMessage: 'Invalid VIGIL credential' })
  const raw = await readRawBody(event)
  if (!raw) throw createError({ statusCode: 400, statusMessage: 'Missing sync envelope' })
  const supplied = (getHeader(event, 'x-vigil-signature') || '').replace(/^sha256=/, '')
  const expected = createHmac('sha256', signingSecret).update(raw).digest('hex')
  const validSignature = supplied.length === expected.length && timingSafeEqual(Buffer.from(supplied), Buffer.from(expected))
  if (!validSignature) throw createError({ statusCode: 401, statusMessage: 'Invalid VIGIL signature' })
  const envelope = JSON.parse(raw)
  if (envelope.version !== '2026-07-15' || envelope.target !== TARGET || !envelope.eventId || !envelope.idempotencyKey || !envelope.payloadDigest) {
    throw createError({ statusCode: 422, statusMessage: 'Invalid VIGIL envelope' })
  }
  return {
    accepted: true,
    receiver: TARGET,
    eventId: envelope.eventId,
    idempotencyKey: envelope.idempotencyKey,
    classification: envelope.classification,
    receiptDigest: sha(`${TARGET}:${envelope.eventId}:${envelope.payloadDigest}`),
    receivedAt: new Date().toISOString(),
  }
})
