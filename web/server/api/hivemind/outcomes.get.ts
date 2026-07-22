import { requireConnectorUser } from '../../utils/connectorFabric'
import { outcomeCockpit } from '../../utils/hivemindControlPlane'

export default defineEventHandler(async event => outcomeCockpit(await requireConnectorUser(event)))
