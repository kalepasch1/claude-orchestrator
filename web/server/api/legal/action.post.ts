import { requireConnectorUser } from '../../utils/connectorFabric'
import { executeLegalAction } from '../../utils/legalContractWorkspace'
export default defineEventHandler(async event=>executeLegalAction(await requireConnectorUser(event),await readBody(event)))
