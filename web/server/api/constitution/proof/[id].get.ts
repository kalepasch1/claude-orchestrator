import { verifyDecisionProof } from '@darwin/kernel/fleetAdmin'
import { organizationContext } from '../../../utils/adaptiveFabric'
import { requireConnectorUser } from '../../../utils/connectorFabric'
import { serviceClient } from '../../../utils/fleetSupabase'

export default defineEventHandler(async event => {
  const user = await requireConnectorUser(event)
  const id = getRouterParam(event, 'id')
  const context = await organizationContext(user)
  const { data } = await serviceClient().from('execution_proof_envelopes').select('*').eq('id', id).eq('organization_id', context.membership.organization_id).maybeSingle()
  if (!data) throw createError({ statusCode: 404, message: 'proof_passport_not_found' })
  const verification = verifyDecisionProof(data.proof)
  return {
    passport: {
      id: data.id,
      action_type: data.action_type,
      intent: data.intent,
      status: data.status,
      prediction: data.prediction,
      permissions: data.permissions,
      rollback_plan: data.rollback_plan,
      realized_outcome: data.realized_outcome,
      digest: data.proof_digest,
      created_at: data.created_at,
    },
    verification,
    receipt: data.proof?.receipt,
  }
})
