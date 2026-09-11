import { requireConnectorUser } from '../../utils/connectorFabric'
import { declareGovernanceConflict, recordExecutionProof, runUserAutopilot } from '../../utils/hivemindControlPlane'

export default defineEventHandler(async event => {
  const user = await requireConnectorUser(event)
  const body = await readBody<any>(event)
  if (body?.action === 'refresh') return runUserAutopilot(user, 'operator')
  if (body?.action === 'execution_proof') return recordExecutionProof(user, body)
  if (body?.action === 'conflict') return declareGovernanceConflict(user, body)
  throw createError({ statusCode: 400, message: 'unknown_hivemind_outcome_action' })
})
