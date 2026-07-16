import { requireConnectorUser } from '../../utils/connectorFabric'
import {
  createRegulatoryRelationship,
  ingestUserRegulatorySource,
  requestRegulatoryAssistance,
  runRegulatoryAutopilot,
  updateRegulatoryProfile,
} from '../../utils/regulatoryCapability'
import { organizationContext, requireOrgAdmin } from '../../utils/adaptiveFabric'

export default defineEventHandler(async event => {
  const user = await requireConnectorUser(event)
  const body = await readBody<any>(event)
  if (body?.action === 'scan') {
    const context = await organizationContext(user)
    return runRegulatoryAutopilot(context.membership.organization_id, 'operator')
  }
  if (body?.action === 'assess') return ingestUserRegulatorySource(user, body)
  if (body?.action === 'assist') return requestRegulatoryAssistance(user, body)
  if (body?.action === 'configure') {
    const context = await organizationContext(user); requireOrgAdmin(context)
    return updateRegulatoryProfile(user, body)
  }
  if (body?.action === 'relationship') {
    const context = await organizationContext(user); requireOrgAdmin(context)
    return createRegulatoryRelationship(user, body)
  }
  throw createError({ statusCode: 400, message: 'unknown_regulatory_action' })
})
