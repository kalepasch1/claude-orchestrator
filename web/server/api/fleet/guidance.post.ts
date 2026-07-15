import { guideAction } from '@darwin/kernel/fleetAdmin'
import { serviceClient } from '../../utils/fleetSupabase'
import { exposureFor } from '../../utils/fleetReads'
import { requireConnectorUser } from '../../utils/connectorFabric'
export default defineEventHandler(async (event) => { await requireConnectorUser(event); const body = await readBody<any>(event); if (!body?.product || !body?.domain || !body?.actionType || !body?.intent) throw createError({ statusCode: 400, message: 'product_domain_actionType_intent_required' }); const exposure = await exposureFor(serviceClient(), body.domain, body.actionType); return guideAction(body, exposure) })
