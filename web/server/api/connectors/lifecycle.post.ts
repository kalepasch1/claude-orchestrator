import { inspectConnectorLifecycle, requireConnectorUser } from '../../utils/connectorFabric'
export default defineEventHandler(async event => ({ accounts: await inspectConnectorLifecycle((await requireConnectorUser(event)).id), checked_at: new Date().toISOString() }))
