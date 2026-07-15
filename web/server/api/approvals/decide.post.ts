import { serviceClient } from '../../utils/fleetSupabase'
import { deriveDecisionBrief } from '../../../utils/decisionBrief'

type DecisionStatus = 'approved' | 'denied'

export default defineEventHandler(async (event) => {
  const body = await readBody<{ id?: string; status?: DecisionStatus; approver?: string; authorizationBoundaryAcknowledged?: boolean }>(event)
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

  const brief = deriveDecisionBrief(card)
  if (status === 'approved' && brief.material && body.authorizationBoundaryAcknowledged !== true) {
    throw createError({
      statusCode: 428,
      message: 'Material approval requires explicit acknowledgement that authorization is not execution or completion.',
    })
  }

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
  if (data && data.status !== 'pending' && ['legal', 'material'].includes(String(card.kind)) && card.slug) {
    const { data: businessRun } = await sb.from('business_action_runs').select('id,action').eq('id', card.slug).maybeSingle()
    if (businessRun) {
      const next = data.status === 'approved' ? 'approved' : 'cancelled'
      const transitioned = await sb.from('business_action_runs').update({ state: next, updated_at: now, outcome: { approval_id: data.id, decision: data.status, decided_at: now, authorization_is_not_execution: true } }).eq('id', businessRun.id)
      if (transitioned.error) throw createError({ statusCode: 500, message: 'business_action_transition_failed' })
      if (data.status === 'approved') {
        await sb.from('governed_business_documents').update({ status: 'approved', approval_evidence: { approval_id: data.id, decided_at: now, authorization_is_not_signature: true }, updated_at: now }).eq('action_run_id', businessRun.id).in('status', ['legal_review', 'approval_required'])
        await sb.from('workforce_lifecycle_cases').update({ status: 'onboarding', updated_at: now }).eq('action_run_id', businessRun.id).eq('status', 'preboarding')
        await sb.from('business_opportunities').update({ state: 'review', updated_at: now }).eq('action_run_id', businessRun.id).eq('state', 'evidence_required')
      }
    } else {
      const { data: contract } = await sb.from('legal_contracts').select('id,current_version,approval_id').eq('id', card.slug).maybeSingle()
      if (contract && contract.approval_id === data.id) {
        const lifecycle = data.status === 'approved' ? 'approved' : 'cancelled'
        const transition = await sb.from('legal_contracts').update({ lifecycle, updated_at: now }).eq('id', contract.id).eq('approval_id', data.id)
        if (transition.error) throw createError({ statusCode: 500, message: 'legal_contract_transition_failed' })
        await sb.from('legal_contract_reviews').insert({ contract_id: contract.id, version: contract.current_version, reviewer_type: 'counsel', status: data.status === 'approved' ? 'accepted' : 'changes_requested', score: data.status === 'approved' ? 1 : 0, findings: [], evidence: { approval_id: data.id, decided_at: now, approver, authorization_is_not_signature_or_delivery: true }, reviewer_id: null })
      }
    }
  }
  return { ok: true, approval: data }
})
