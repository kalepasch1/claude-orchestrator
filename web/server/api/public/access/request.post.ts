import { readBody } from 'h3'
import { limitPublicAdmission } from '~/server/utils/accessAdmission'
import { serviceClient } from '~/server/utils/fleetSupabase'

export default defineEventHandler(async event => {
  limitPublicAdmission(event, 6)
  const body = await readBody<any>(event)
  const email = String(body?.email || '').trim().toLowerCase()
  const explanation = String(body?.explanation || '').trim()
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) throw createError({ statusCode: 400, message: 'Enter a valid work email.' })
  if (explanation.length < 80 || explanation.length > 3000) throw createError({ statusCode: 400, message: 'Explain what you are building and why Madeus is a fit in at least 80 characters.' })
  const { data, error } = await serviceClient().from('orchestrator_access_requests').insert({ email, explanation }).select('id,status,created_at').single()
  if (error) throw createError({ statusCode: 503, message: 'The exemption request could not be recorded.' })
  return { request: data, message: 'Request received. Membership remains closed until an operator approves it.' }
})
