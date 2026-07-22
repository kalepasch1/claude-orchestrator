import { requireConnectorUser } from '../../utils/connectorFabric'
import { legalWorkspace } from '../../utils/legalContractWorkspace'
export default defineEventHandler(async event=>legalWorkspace(await requireConnectorUser(event)))
