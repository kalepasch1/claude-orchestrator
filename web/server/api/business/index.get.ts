import { requireConnectorUser } from '../../utils/connectorFabric'
import { businessDashboard } from '../../utils/businessOperatingSystem'
export default defineEventHandler(async event => businessDashboard(await requireConnectorUser(event)))
