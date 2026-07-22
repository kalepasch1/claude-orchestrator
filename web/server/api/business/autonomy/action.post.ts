import {requireConnectorUser} from '../../../utils/connectorFabric'
import {executeAutonomyAction} from '../../../utils/autonomousBusinessFabric'
export default defineEventHandler(async event=>executeAutonomyAction(await requireConnectorUser(event),await readBody(event)))
