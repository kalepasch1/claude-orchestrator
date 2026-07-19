import { requireConnectorUser } from '../../utils/connectorFabric'
import { adaptiveContext } from '../../utils/adaptiveFabric'
export default defineEventHandler(async event => adaptiveContext(await requireConnectorUser(event)))
