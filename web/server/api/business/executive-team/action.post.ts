import{requireConnectorUser}from'../../../utils/connectorFabric'
import{executeExecutiveTeamAction}from'../../../utils/virtualExecutiveTeam'
export default defineEventHandler(async event=>executeExecutiveTeamAction(await requireConnectorUser(event),await readBody(event)))
