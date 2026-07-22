import{requireConnectorUser}from'../../utils/connectorFabric'
import{executiveTeamDashboard}from'../../utils/virtualExecutiveTeam'
export default defineEventHandler(async event=>executiveTeamDashboard(await requireConnectorUser(event)))
