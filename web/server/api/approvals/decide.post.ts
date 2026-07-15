import { serviceClient } from '../../utils/fleetSupabase'

type DecisionStatus = 'approved' | 'denied'

export default defineEventHandler(async (event) => {
  const body = await readBody<{ id?: string; status?: DecisionStatus; approver?: string }>(event)
  const id = body?.id
  const status = body?.status
  const approver = String(body?.approver || 'dashboard').trim() || 'dashboard'
  if (!id || !['approved', 'denied'].includes(String(status))) {
    throw createError({ statusCode: 400, message: 'id and approved/denied status are required' })
  }

  const sb = serviceClient()
  const { data: card, error: readError } = await sb
    .from('approvals')
    .select('*')
    .eq('id', id)
    .maybeSingle()
  if (readError) throw createError({ statusCode: 500, message: readError.message })
  if (!card) throw createError({ statusCode: 404, message: 'approval not found' })

  const now = new Date().toISOString()
  let patch: Record<string, any>
  if (status === 'approved' && Number(card.approvals_required || 1) >= 2) {
    if (!card.decided_by) {
      patch = { decided_by: approver }
    } else if (card.decided_by === approver) {
      throw createError({ statusCode: 409, message: 'a different approver is required for the second approval' })
    } else {
      patch = { status: 'approved', second_approver: approver, decided_at: now }
    }
  } else {
    patch = { status, decided_at: now, decided_by: approver }
  }

  const { data, error } = await sb
    .from('approvals')
    .update(patch)
    .eq('id', id)
    .select('*')
    .maybeSingle()
  if (error) throw createError({ statusCode: 500, message: error.message })
  return { ok: true, approval: data }
})
