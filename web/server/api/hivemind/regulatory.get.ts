import { requireConnectorUser } from '../../utils/connectorFabric'
import { regulatoryCockpit } from '../../utils/regulatoryCapability'

export default defineEventHandler(async event => regulatoryCockpit(await requireConnectorUser(event)))
