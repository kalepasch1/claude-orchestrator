import{organizationContext,requireOrgAdmin}from'../../../utils/adaptiveFabric'
import{requireConnectorUser}from'../../../utils/connectorFabric'
import{createNetworkTreasuryPlan}from'../../../utils/providerNetworkExecutionStore'
export default defineEventHandler(async event=>{const user=await requireConnectorUser(event),context=await organizationContext(user);requireOrgAdmin(context);const body=await readBody<any>(event);if(body.positions&&!Array.isArray(body.positions))throw createError({statusCode:422,message:'positions_array_required'});return await createNetworkTreasuryPlan(context.membership.organization_id,user.id,body)})
