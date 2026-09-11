import {requireConnectorUser} from '../../utils/connectorFabric'
import {governanceUXContext} from '../../utils/hivemindGovernance'
export default defineEventHandler(async event=>governanceUXContext(await requireConnectorUser(event)))
