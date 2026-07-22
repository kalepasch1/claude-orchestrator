import { requireConnectorUser } from '../../utils/connectorFabric'
import { executeBusinessAction } from '../../utils/businessOperatingSystem'
export default defineEventHandler(async event => executeBusinessAction(await requireConnectorUser(event), await readBody(event)))
