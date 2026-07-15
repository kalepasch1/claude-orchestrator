import {requireConnectorUser} from '../../utils/connectorFabric'
import {advancedContext} from '../../utils/hivemindAdvanced'
export default defineEventHandler(async event=>advancedContext(await requireConnectorUser(event)))
