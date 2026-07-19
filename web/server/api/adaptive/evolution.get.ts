import { requireConnectorUser } from '../../utils/connectorFabric'
import { evolutionContext } from '../../utils/capabilityEvolution'
export default defineEventHandler(async event => evolutionContext(await requireConnectorUser(event)))
