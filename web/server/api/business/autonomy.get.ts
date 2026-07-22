import {requireConnectorUser} from '../../utils/connectorFabric'
import {autonomyDashboard} from '../../utils/autonomousBusinessFabric'
export default defineEventHandler(async event=>autonomyDashboard(await requireConnectorUser(event)))
