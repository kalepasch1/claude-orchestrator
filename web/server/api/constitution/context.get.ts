import { requireConnectorUser } from '../../utils/connectorFabric'
import { executionContext } from '../../utils/executionConstitution'
export default defineEventHandler(async event => executionContext(await requireConnectorUser(event)))
